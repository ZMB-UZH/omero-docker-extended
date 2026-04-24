from __future__ import annotations

from iter_test_helpers import next_or_fail

from pathlib import Path
from threading import Thread

import pytest

from omeroweb_omp_plugin import apps, urls
from omeroweb_omp_plugin.services import ai_providers
from omeroweb_omp_plugin.services.jobs import job_storage


def test_ai_provider_options_return_copy():
    options = ai_providers.list_ai_provider_options()
    options.append({"value": "new", "label": "New"})

    assert all(option["value"] != "new" for option in ai_providers.AI_PROVIDER_OPTIONS)


def test_job_storage_validates_and_roundtrips_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(job_storage, "JOBS_DIR", str(tmp_path))
    job_id = "d" * 32
    uppercase_job_id = job_id.upper()
    job = {"job_id": uppercase_job_id, "status": "queued"}

    assert job_storage.get_job_path(uppercase_job_id).endswith(f"{job_id}.json")
    assert job_storage.get_job_lock_path(uppercase_job_id).endswith(f"{job_id}.lock")
    job_storage.save_job(job)
    assert job_storage.load_job(uppercase_job_id) == job
    assert job_storage.load_job(job_id) == job
    assert job_storage.load_job("invalid") is None


def test_job_storage_fsyncs_before_atomic_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(job_storage, "JOBS_DIR", str(tmp_path))
    fsynced_fds = []
    monkeypatch.setattr(job_storage.os, "fsync", fsynced_fds.append)

    job_storage.save_job({"job_id": "3" * 32, "status": "queued"})

    assert len(fsynced_fds) == 1


def test_job_storage_saves_when_caller_already_holds_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(job_storage, "JOBS_DIR", str(tmp_path))
    job_id = "1" * 32
    job = {"job_id": job_id, "status": "queued"}
    job_storage.save_job(job)

    lock_path = job_storage.get_job_lock_path(job_id)
    with job_storage.portalocker.Lock(lock_path, "a+", timeout=1):
        job["status"] = "running"
        with job_storage.mark_job_lock_held(job_id):
            job_storage.save_job(job)

    assert job_storage.load_job(job_id) == {"job_id": job_id, "status": "running"}


def test_job_storage_held_lock_marker_is_thread_local(tmp_path, monkeypatch):
    monkeypatch.setattr(job_storage, "JOBS_DIR", str(tmp_path))
    job_id = "2" * 32
    lock_key = job_storage.get_job_lock_path(job_id)
    visible_counts = []

    def collect_marker_count():
        visible_counts.append(job_storage._held_job_locks().get(lock_key, 0))

    with job_storage.mark_job_lock_held(job_id):
        thread = Thread(target=collect_marker_count)
        thread.start()
        thread.join()
        assert job_storage._held_job_locks().get(lock_key, 0) == 1

    assert visible_counts == [0]
    assert job_storage._held_job_locks().get(lock_key, 0) == 0


def test_omp_module_contracts_cover_ready_hook_and_named_routes(monkeypatch):
    configured = []
    monkeypatch.setattr(
        apps, "configure_omero_gateway_logging", lambda: configured.append(True)
    )

    config = apps.OMPPluginConfig(apps.OMPPluginConfig.name, apps)
    config.ready()

    assert configured == [True]
    route_names = [pattern.name for pattern in urls.urlpatterns]
    assert "omeroweb_omp_plugin_index" in route_names
    assert "omeroweb_omp_plugin_start_job" in route_names
    assert "omeroweb_omp_plugin_save_ai_credentials" in route_names
    assert "omeroweb_omp_plugin_help" in route_names


def test_omp_job_storage_edge_paths_cover_missing_files_and_tmp_cleanup(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(job_storage, "JOBS_DIR", str(tmp_path))

    missing_job_id = "e" * 32
    assert job_storage.load_job(missing_job_id) is None

    class _Lock:
        def __init__(self, *_args, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(job_storage.portalocker, "Lock", _Lock)
    assert job_storage.load_job(missing_job_id) is None

    created = {}

    class _TempFile:
        def __init__(self, path: Path):
            self.name = str(path)
            self._handle = path.open("w", encoding="utf-8")

        def write(self, data):
            return self._handle.write(data)

        def flush(self):
            return self._handle.flush()

        def fileno(self):
            return self._handle.fileno()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self._handle.close()
            return False

    def _named_tempfile(*_args, **_kwargs):
        path = tmp_path / ".edge.json.tmp"
        created["path"] = path
        return _TempFile(path)

    monkeypatch.setattr(job_storage.tempfile, "NamedTemporaryFile", _named_tempfile)
    monkeypatch.setattr(
        job_storage.Path,
        "replace",
        lambda self, other: (_ for _ in ()).throw(RuntimeError("replace failed")),
    )

    with pytest.raises(RuntimeError, match="replace failed"):
        job_storage.save_job({"job_id": "f" * 32, "status": "queued"})

    assert created["path"].exists() is False


def test_omp_job_storage_load_job_returns_none_if_file_disappears_after_lock(
    monkeypatch,
):
    class _Lock:
        def __init__(self, *_args, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _DisappearingPath:
        def __init__(self):
            self._exists = iter((True, False))

        def exists(self):
            return next_or_fail(self._exists)

        @staticmethod
        def open(*_args, **_kwargs):
            raise AssertionError("path should not be opened when the job disappears")

    job_path = _DisappearingPath()
    lock_path = Path("fake.lock")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _Lock)
    monkeypatch.setattr(
        job_storage,
        "_validated_job_path",
        lambda job_id, suffix: job_path if suffix == ".json" else lock_path,
    )

    assert job_storage.load_job("a" * 32) is None
