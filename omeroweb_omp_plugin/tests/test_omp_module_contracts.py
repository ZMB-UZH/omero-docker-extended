from __future__ import annotations

from pathlib import Path

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
            return next(self._exists)

        def open(self, *_args, **_kwargs):
            raise AssertionError("path should not be opened when the job disappears")

    job_path = _DisappearingPath()
    lock_path = Path("/tmp/fake.lock")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _Lock)
    monkeypatch.setattr(
        job_storage,
        "_validated_job_path",
        lambda job_id, suffix: job_path if suffix == ".json" else lock_path,
    )

    assert job_storage.load_job("a" * 32) is None
