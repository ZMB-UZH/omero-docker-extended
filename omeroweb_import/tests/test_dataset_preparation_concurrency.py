"""Destination preparation must not roll back background import progress."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace
import uuid

import pytest

from omeroweb_import.strings import errors
from omeroweb_import.views import core_functions as core, index_view


@pytest.fixture
def stored_job(monkeypatch, tmp_path):
    """Persist a checking job in an isolated job store.

    Inputs: pytest patch and temporary directory. Output: saved job dictionary.
    """
    monkeypatch.setattr(core, "_get_jobs_root", lambda: tmp_path)
    job = {
        "job_id": uuid.uuid4().hex,
        "status": "checking",
        "compatibility_status": "checking",
        "compatibility_thread_active": True,
        "dataset_map": {},
        "files": [{"relative_path": "folder/image.tif", "status": "uploaded"}],
    }
    assert core._save_job(job)
    return job


@pytest.mark.parametrize("worker_status", ["ready", "importing", "error"])
def test_destination_write_preserves_concurrent_worker_progress(
    monkeypatch, stored_job, worker_status
):
    """Interleave destination creation with a committed worker transition.

    Inputs: isolated job and worker status. Output: preserved progress and targets.
    """
    entered = threading.Event()
    proceed = threading.Event()
    job_id = stored_job["job_id"]
    stale_request_job = core._load_job(job_id)

    def create_dataset(conn, name, dataset_map, project_id=None):
        """Block destination creation until the worker has saved its progress.

        Inputs: connection and destination map. Output: deterministic dataset ID.
        """
        entered.set()
        assert proceed.wait(10), "test did not release the destination request"
        dataset_map[name] = 21
        return 21

    def finish_worker(current):
        """Commit worker results while destination creation remains blocked.

        Inputs: locked job. Output: job with completed compatibility and progress.
        """
        current.update(
            status=worker_status,
            compatibility_status="compatible",
            compatibility_thread_active=False,
            imported_bytes=123,
            import_thread_started=worker_status == "importing",
            messages=["worker progress"],
            errors=["worker failure"] if worker_status == "error" else [],
        )
        current["files"][0]["compatibility"] = "compatible"
        current["dataset_map"]["another-target"] = 82
        return current

    monkeypatch.setattr(core, "_get_or_create_dataset", create_dataset)
    with ThreadPoolExecutor(max_workers=1) as executor:
        request = executor.submit(
            core._prepare_request_job_import_datasets,
            job_id,
            stale_request_job,
            object(),
        )
        try:
            assert entered.wait(10), "destination request did not start"
            completed = core._update_job(job_id, finish_worker)
            assert completed["status"] == worker_status
        finally:
            proceed.set()
        prepared, error = request.result(timeout=10)

    persisted = core._load_job(job_id)
    assert error is None
    assert prepared == persisted
    for key in (
        "status",
        "compatibility_status",
        "compatibility_thread_active",
        "import_thread_started",
        "imported_bytes",
        "files",
        "messages",
        "errors",
    ):
        assert persisted[key] == completed[key], key
    assert persisted["dataset_map"] == {"folder": 21, "another-target": 82}


def test_destination_write_keeps_already_committed_targets(monkeypatch, stored_job):
    """Keep committed targets when a request carries stale destination values.

    Inputs: isolated saved job. Output: exact committed target values survive.
    """
    job_id = stored_job["job_id"]
    stale = core._load_job(job_id)
    stale["dataset_map"] = {"folder": 21}
    stale["orphan_dataset_name"] = "stale-orphan"

    def commit_targets(current):
        """Persist newer destinations than those held by the request.

        Inputs: locked job. Output: job containing the committed target map.
        """
        current["dataset_map"] = {"folder": 42, "other-folder": 43}
        current["orphan_dataset_name"] = "committed-orphan"
        return current

    core._update_job(job_id, commit_targets)
    prepared, error = core._prepare_request_job_import_datasets(job_id, stale, object())
    assert error is None
    assert prepared["dataset_map"] == {"folder": 42, "other-folder": 43}
    assert prepared["orphan_dataset_name"] == "committed-orphan"


def test_destination_write_fails_when_job_no_longer_exists(stored_job):
    """Reject destination persistence after the job has been removed.

    Inputs: isolated saved job. Output: error without recreating the deleted job.
    """
    job_id = stored_job["job_id"]
    stale = core._load_job(job_id)
    stale["dataset_map"] = {"folder": 21}
    core._job_path(job_id).unlink()
    prepared, error = core._prepare_request_job_import_datasets(job_id, stale, object())
    assert prepared is None
    assert error == errors.unable_update_upload_job_state()
    assert core._load_job(job_id) is None


@pytest.mark.parametrize("current_status", ["ready", "importing", "done", "error"])
def test_stale_confirmation_does_not_restart_an_advanced_job(
    monkeypatch, tmp_path, stored_job, current_status
):
    """Replay a delayed confirmation after another request advances the job.

    Inputs: isolated job and advanced status. Output: unchanged state, no restart.
    """
    job_id = stored_job["job_id"]
    stale = core._load_job(job_id)
    stale["status"] = "awaiting_confirmation"
    stale["import_thread_started"] = False

    def advance(current):
        """Advance persisted state beyond the request's confirmation snapshot.

        Inputs: locked job. Output: confirmed job carrying recorded progress.
        """
        current.update(
            status=current_status,
            compatibility_confirmed=True,
            compatibility_thread_active=False,
            import_thread_started=True,
            imported_bytes=123,
        )
        return current

    advanced = core._update_job(job_id, advance)
    monkeypatch.setattr(index_view, "_get_upload_root", lambda: tmp_path / "uploads")
    monkeypatch.setattr(index_view, "_load_owned_job", lambda *args: (stale, None))

    def unexpected_preparation(*args):
        """Reject any repeat preparation or import launch from stale confirmation.

        Inputs: intercepted call arguments. Output: explicit regression failure.
        """
        pytest.fail("a stale confirmation must not restart destination preparation")

    monkeypatch.setattr(
        index_view, "_prepare_ready_job_for_import_start", unexpected_preparation
    )
    monkeypatch.setattr(index_view, "_start_import_thread", unexpected_preparation)
    response = index_view.confirm_import(
        SimpleNamespace(method="POST", user=SimpleNamespace(username="fixture-user")),
        job_id=job_id,
        conn=object(),
    )
    assert response.status_code == 200
    assert json.loads(response.content) == {"ok": True, "status": current_status}
    assert core._load_job(job_id) == advanced
