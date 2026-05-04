from __future__ import annotations

import json
from types import SimpleNamespace

from omeroweb_import.views import core_functions


class _ImageId:
    """Represent image identifier."""

    def __init__(self, value):
        """Initialize the instance.

        Inputs: `value`. Output: None.
        """
        self._value = value

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value


class _ImageRow:
    """Represent image row."""

    def __init__(self, image_id):
        """Initialize the instance.

        Inputs: `image_id`. Output: None.
        """
        self._image_id = image_id

    def getId(self):
        """Return the fake OMERO identifier.

        Inputs: none. Output: `_ImageId` result.
        """
        return _ImageId(self._image_id)


class _UnlockedLock:
    """Represent unlocked lock."""

    def __enter__(self):
        """Enter the context manager.

        Inputs: none. Output: `self`.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Exit the context manager.

        Inputs: `exc_type`, `exc`, `tb`. Output: bool.
        """
        return False


class _FailingLock:
    """Represent failing lock."""

    def __enter__(self):
        """Enter the context manager.

        Inputs: none. Output: None. Raises on invalid or unavailable state.
        """
        raise core_functions.portalocker.exceptions.LockException("busy")

    def __exit__(self, exc_type, exc, tb):
        """Exit the context manager.

        Inputs: `exc_type`, `exc`, `tb`. Output: bool.
        """
        return False


def test_timeout_expired_handles_invalid_negative_and_elapsed_values(monkeypatch):
    """Verify timeout expired handles invalid negative and elapsed values.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(core_functions.time, "time", lambda: 15.0)
    assert core_functions._timeout_expired(10.0, "bad") is False
    assert core_functions._timeout_expired(10.0, -1) is False
    assert core_functions._timeout_expired(10.0, 6) is False
    assert core_functions._timeout_expired(10.0, 5) is True


def test_job_storage_helpers_cover_missing_corrupt_and_lock_failure_paths(
    tmp_path, monkeypatch
):
    """Verify job storage helpers cover missing corrupt and lock failure paths.

    Inputs: `tmp_path`, `monkeypatch`. Output: `_FailingLock` result.
    """
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    job_id = "c" * 32

    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "JOB_LOCK_RETRIES", 1, raising=False)
    monkeypatch.setattr(core_functions.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        core_functions.portalocker, "Lock", lambda *args, **kwargs: _UnlockedLock()
    )

    assert core_functions._load_job(job_id) is None

    job_path = jobs_root / f"{job_id}.json"
    job_path.write_text("{", encoding="utf-8")
    assert core_functions._load_job(job_id) is None

    job_path.write_text(
        json.dumps({"job_id": job_id, "status": "ready"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        core_functions.portalocker, "Lock", lambda *args, **kwargs: _FailingLock()
    )
    monkeypatch.setattr(
        core_functions,
        "_read_job_file",
        lambda current_job_id: (_ for _ in ()).throw(OSError("stale file")),
    )
    assert core_functions._load_job(job_id) is None

    lock_calls = []

    def failing_lock(*args, **kwargs):
        """Failing lock.

        Inputs: `*args`, `**kwargs`. Output: `_FailingLock` result.
        """
        lock_calls.append((args, kwargs))
        return _FailingLock()

    monkeypatch.setattr(core_functions.portalocker, "Lock", failing_lock)
    assert core_functions._save_job({"job_id": job_id}) is False
    assert lock_calls

    monkeypatch.setattr(
        core_functions.portalocker, "Lock", lambda *args, **kwargs: _UnlockedLock()
    )
    assert core_functions._robust_update_job(job_id, lambda current: current) is None

    job_path.write_text("{", encoding="utf-8")
    assert core_functions._robust_update_job(job_id, lambda current: current) is None

    job_path.write_text(
        json.dumps({"job_id": job_id, "status": "ready"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        core_functions.portalocker, "Lock", lambda *args, **kwargs: _FailingLock()
    )
    assert core_functions._robust_update_job(job_id, lambda current: current) is None

    monkeypatch.setattr(
        core_functions,
        "_job_path",
        lambda current_job_id: (_ for _ in ()).throw(PermissionError("denied")),
    )
    monkeypatch.setattr(
        core_functions,
        "_job_lock_path",
        lambda current_job_id: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert core_functions._load_job(job_id) is None
    assert core_functions._save_job({"job_id": job_id}) is False
    assert core_functions._robust_update_job(job_id, lambda current: current) is None


def test_batch_find_images_by_name_covers_dataset_global_and_failure_paths(monkeypatch):
    """Verify batch find images by name covers dataset global and failure paths.

    Inputs: `monkeypatch`. Output: computed value.
    """

    class _Params:
        """Represent params."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.values = {}

        def addLong(self, key, value):
            """Add long.

            Inputs: `key`, `value`. Output: `self`.
            """
            self.values[key] = value
            return self

        def addList(self, key, value):
            """Add list.

            Inputs: `key`, `value`. Output: `self`.
            """
            self.values[key] = list(value)
            return self

    monkeypatch.setattr(
        core_functions.omero,
        "sys",
        SimpleNamespace(ParametersI=_Params),
        raising=False,
    )

    queries = []
    wrappers = {
        11: SimpleNamespace(getName=lambda: "alpha.tif"),
        12: SimpleNamespace(getName=lambda: "beta.tif"),
    }

    def find_all_by_query(query, params, opts):
        """Find all by query.

        Inputs: `query`, `params`, `opts`. Output: list.
        """
        queries.append((query, dict(params.values)))
        return [_ImageRow(11), _ImageRow(12)]

    conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: SimpleNamespace(findAllByQuery=find_all_by_query),
        getObject=lambda model, image_id: wrappers.get(image_id),
    )

    assert core_functions._batch_find_images_by_name(conn, []) == {}

    scoped = core_functions._batch_find_images_by_name(
        conn,
        ["alpha.tif", "beta.tif", "missing.tif"],
        dataset_id=9,
    )
    assert sorted(scoped) == ["alpha.tif", "beta.tif"]
    assert "JOIN FETCH i.datasetLinks" in queries[0][0]
    assert "i.name IN (:names)" in queries[0][0]
    assert queries[0][1]["did"] == 9
    assert queries[0][1]["names"] == ["alpha.tif", "beta.tif", "missing.tif"]

    queries.clear()
    unscoped = core_functions._batch_find_images_by_name(
        conn,
        ["alpha.tif", "beta.tif"],
    )
    assert sorted(unscoped) == ["alpha.tif", "beta.tif"]
    assert "JOIN FETCH i.datasetLinks" not in queries[0][0]
    assert "i.name IN (:names)" in queries[0][0]
    assert queries[0][1]["names"] == ["alpha.tif", "beta.tif"]

    failing_conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: SimpleNamespace(
            findAllByQuery=lambda query, params, opts: (_ for _ in ()).throw(
                RuntimeError("query failed")
            )
        ),
        getObject=lambda model, image_id: None,
    )
    assert (
        core_functions._batch_find_images_by_name(
            failing_conn,
            ["alpha.tif"],
            dataset_id=9,
        )
        == {}
    )

    timeout_checks = []
    monkeypatch.setattr(
        core_functions,
        "_timeout_expired",
        lambda start_time, timeout_seconds: (
            timeout_checks.append((start_time, timeout_seconds)) or True
        ),
    )
    timed = core_functions._batch_find_images_by_name(
        conn,
        ["alpha.tif"],
        timeout_seconds=1,
    )
    assert sorted(timed) == ["alpha.tif", "beta.tif"]
    assert timeout_checks and timeout_checks[-1][1] == 1
