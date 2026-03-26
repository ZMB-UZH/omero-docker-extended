from __future__ import annotations

import json

from omeroweb_import.services.jobs import job_storage


def _job_id() -> str:
    return "a" * 32


def test_job_storage_batch_and_compatibility_helpers_cover_threshold_and_status_logic(
    monkeypatch,
):
    monkeypatch.setenv(job_storage.UPLOAD_BATCH_FILES_ENV, "2")
    job = {
        "files": [
            {"status": "uploaded"},
            {"status": "uploaded"},
            {"status": "pending"},
            {"status": "uploaded", "compatibility": "compatible"},
            {"status": "uploaded", "compatibility_skip": True},
        ]
    }

    assert job_storage.get_env_int("MISSING_BATCH_SIZE", 5, 1, 10) == 5
    assert job_storage.normalize_job_batch_size("9", default=3) == 9
    assert job_storage.normalize_job_batch_size("nope", default=3) == 3
    assert job_storage.resolve_job_batch_size({"job_batch_size": "0"}) == 1
    assert job_storage.resolve_job_batch_size({"job_batch_size": "99"}) == 10
    assert [
        entry["status"] for entry in job_storage.get_compatibility_pending_entries(job)
    ] == [
        "uploaded",
        "uploaded",
    ]
    assert job_storage._compatibility_pending_entries(
        job
    ) == job_storage.get_compatibility_pending_entries(job)
    assert job_storage.has_pending_uploads(job) is True
    assert job_storage.should_start_compatibility_check(job) is True

    job["compatibility_thread_active"] = True
    assert job_storage.should_start_compatibility_check(job) is False
    job.pop("compatibility_thread_active")
    job["compatibility_confirmed"] = True
    assert job_storage.should_start_compatibility_check(job) is False
    job["compatibility_confirmed"] = False
    job["files"][2]["status"] = "uploaded"
    assert job_storage.has_pending_uploads(job) is False
    assert job_storage.should_start_compatibility_check(job) is True

    assert (
        job_storage.refresh_job_status({"files": [{"status": "pending"}]})["status"]
        == "uploading"
    )
    sem_edx = job_storage.refresh_job_status(
        {
            "files": [{"status": "uploaded", "compatibility_skip": True}],
            "special_upload": "sem_edx_spectra",
        }
    )
    assert sem_edx["compatibility_status"] == "compatible"
    assert sem_edx["status"] == "ready"
    assert (
        job_storage.refresh_job_status(
            {"files": [], "compatibility_status": "incompatible"}
        )["status"]
        == "awaiting_confirmation"
    )
    assert (
        job_storage.refresh_job_status(
            {"files": [], "compatibility_status": "error", "job_id": _job_id()}
        )["status"]
        == "ready"
    )
    assert (
        job_storage.refresh_job_status(
            {"files": [], "compatibility_status": "compatible"}
        )["status"]
        == "ready"
    )
    assert job_storage.refresh_job_status({"files": []})["status"] == "checking"


def test_job_storage_file_access_helpers_cover_lock_fallback_retry_and_corrupt_updates(
    tmp_path,
    monkeypatch,
):
    payload = {"job_id": _job_id(), "status": "ready"}
    path = tmp_path / f"{_job_id()}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    real_lock = job_storage.portalocker.Lock

    assert job_storage.safe_job_id(_job_id()) is True
    assert job_storage.safe_job_id("not-a-job-id") is False
    assert job_storage.get_job_path(_job_id(), tmp_path) == path

    class _RaisingLock:
        def __init__(self, *_args, **_kwargs):
            raise job_storage.portalocker.exceptions.LockException("busy")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _RaisingLock)
    assert job_storage.load_job(_job_id(), tmp_path) == payload
    assert job_storage.load_job("../escape", tmp_path) is None

    attempts = {"count": 0}

    def flaky_lock(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise job_storage.portalocker.exceptions.LockException("busy")
        return real_lock(*args, **kwargs)

    monkeypatch.setattr(job_storage.portalocker, "Lock", flaky_lock)
    monkeypatch.setattr(job_storage.time, "sleep", lambda _value: None)
    monkeypatch.setattr(job_storage.random, "uniform", lambda _start, _end: 0.0)
    assert job_storage.save_job(payload, tmp_path, retries=2, timeout=0.1) is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "ready"
    assert isinstance(saved["updated"], float)
    assert attempts["count"] == 2

    class _AlwaysFailLock:
        def __init__(self, *_args, **_kwargs):
            raise job_storage.portalocker.exceptions.LockException("busy")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _AlwaysFailLock)
    assert job_storage.save_job(payload, tmp_path, retries=2, timeout=0.1) is False

    path.write_text(
        json.dumps({"job_id": _job_id(), "status": "checking"}), encoding="utf-8"
    )
    monkeypatch.setattr(job_storage.portalocker, "Lock", real_lock)
    updated = job_storage.robust_update_job(
        _job_id(),
        lambda job: {**job, "status": "ready", "messages": ["done"]},
        tmp_path,
        retries=1,
        timeout=0.1,
    )
    assert updated["status"] == "ready"
    assert json.loads(path.read_text(encoding="utf-8"))["messages"] == ["done"]

    corrupt_id = "b" * 32
    corrupt_path = tmp_path / f"{corrupt_id}.json"
    corrupt_path.write_text("{bad-json", encoding="utf-8")
    assert (
        job_storage.robust_update_job(
            corrupt_id, lambda job: job, tmp_path, retries=1, timeout=0.1
        )
        is None
    )
    assert job_storage.robust_update_job("../escape", lambda job: job, tmp_path) is None


def test_job_storage_append_helpers_store_timestamped_messages(monkeypatch):
    monkeypatch.setattr(job_storage.time, "time", lambda: 123.5)
    job = {}

    job_storage.append_job_message(job, "hello")
    job_storage.append_job_error(job, "boom")

    assert job["messages"] == [{"timestamp": 123.5, "text": "hello"}]
    assert job["errors"] == [{"timestamp": 123.5, "text": "boom"}]
