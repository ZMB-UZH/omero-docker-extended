from __future__ import annotations

import json
import multiprocessing
import time

import pytest

from omeroweb_import.services.jobs import job_storage


def _job_id() -> str:
    """Return the job ID.

    Inputs: none. Output: `str`.
    """
    return "a" * 32


@pytest.mark.parametrize("operation", ["save", "update"])
@pytest.mark.parametrize("failure", ["serialization", "file_sync", "replace"])
def test_failed_write_preserves_previous_job(tmp_path, monkeypatch, operation, failure):
    """Keep the last committed record when a replacement cannot complete.

    Inputs: disposable job and injected failure. Output: old bytes remain intact
    and no partial temporary record remains visible.
    """
    payload = {"job_id": _job_id(), "status": "ready"}
    path = job_storage.get_job_path(_job_id(), tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")
    original = path.read_bytes()
    changed = {**payload, "status": "changed"}
    if failure == "serialization":
        changed["invalid"] = object()
    else:

        def fail(*_args, **_kwargs):
            """Raise a deterministic pre-commit I/O failure.

            Inputs: filesystem arguments. Output: raises OSError before commit.
            """
            raise OSError("injected write failure")

        monkeypatch.setattr(
            job_storage.os, "fsync" if failure == "file_sync" else "replace", fail
        )

    def write():
        """Execute the selected storage API with one attempt.

        Inputs: enclosing payload and operation. Output: storage result or error.
        """
        if operation == "save":
            return job_storage.save_job(changed, tmp_path, retries=1)
        return job_storage.robust_update_job(
            _job_id(), lambda _job: changed, tmp_path, retries=1
        )

    if failure == "serialization":
        with pytest.raises(TypeError):
            write()
    else:
        result = write()
        assert result is (False if operation == "save" else None)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_temporary_cleanup_preserves_original_error(
    tmp_path, monkeypatch, caplog
):
    """Report cleanup failure without masking serialization failure or losing state.

    Inputs: failed serialization and temporary-file removal. Output: the previous
    record remains intact and the cleanup diagnostic cannot inject log lines.
    """
    payload = {"job_id": _job_id(), "status": "ready"}
    saved = job_storage.save_job(payload, tmp_path)
    assert saved is True
    path = job_storage.get_job_path(_job_id(), tmp_path)
    original = path.read_bytes()

    def fail_unlink(_path, **_kwargs):
        """Simulate a filesystem cleanup error with an unsafe log delimiter.

        Inputs: temporary path and unlink options. Output: raises OSError.
        """
        raise OSError("cleanup failed\ninjected line")

    monkeypatch.setattr(job_storage.Path, "unlink", fail_unlink)
    with pytest.raises(TypeError):
        job_storage.save_job({**payload, "invalid": object()}, tmp_path)
    assert path.read_bytes() == original
    assert len(caplog.records) == 1
    assert "Unable to remove uncommitted job file" in caplog.records[0].getMessage()
    assert "\n" not in caplog.records[0].getMessage()


def _increment_job(jobs_root, barrier):
    """Increment a disposable record from an independent process.

    Inputs: jobs directory and start barrier. Output: twelve persisted increments.
    """
    barrier.wait(timeout=15)
    for _ in range(12):
        updated = job_storage.robust_update_job(
            _job_id(), lambda job: {**job, "count": job["count"] + 1}, jobs_root
        )
        assert updated is not None


def test_atomic_updates_across_processes_keep_readers_consistent(tmp_path):
    """Serialize independent writers while readers see complete records.

    Inputs: isolated filesystem and spawned processes. Output: every increment
    persists, reads never observe partial JSON, and the final mode is private.
    """
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    saved = job_storage.save_job({"job_id": _job_id(), "count": 0}, tmp_path)
    assert saved is True
    processes = [
        context.Process(target=_increment_job, args=(tmp_path, barrier))
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    try:
        barrier.wait(timeout=15)
        deadline = time.monotonic() + 30
        while any(process.is_alive() for process in processes):
            assert time.monotonic() < deadline
            record = job_storage.load_job(_job_id(), tmp_path)
            assert record is not None
            assert 0 <= record["count"] <= 36
            time.sleep(0.005)
    finally:
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    assert [process.exitcode for process in processes] == [0, 0, 0]
    assert job_storage.load_job(_job_id(), tmp_path)["count"] == 36
    path = job_storage.get_job_path(_job_id(), tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("operation", ["save", "update"])
def test_post_commit_sync_failure_is_not_retried(tmp_path, monkeypatch, operation):
    """Report an uncertain durability result without replaying a committed update.

    Inputs: temporary record and injected sync failure. Output: one committed
    change and an exception, with no automatic retry after replacement.
    """
    payload = {"job_id": _job_id(), "count": 0}
    saved = job_storage.save_job(payload, tmp_path)
    assert saved is True
    real_fsync = job_storage.os.fsync
    calls = []

    def fail_directory_sync(fd):
        """Allow file synchronization and fail only directory synchronization.

        Inputs: open descriptor. Output: fsync result or a directory-only error.
        """
        import stat

        if stat.S_ISDIR(job_storage.os.fstat(fd).st_mode):
            raise OSError("directory synchronization failed")
        return real_fsync(fd)

    def update(job):
        """Record invocation count so retries cannot go unnoticed.

        Inputs: current job. Output: a copy with the counter incremented.
        """
        calls.append(True)
        return {**job, "count": job["count"] + 1}

    monkeypatch.setattr(job_storage.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="directory synchronization failed"):
        if operation == "save":
            job_storage.save_job({**payload, "count": 1}, tmp_path)
        else:
            job_storage.robust_update_job(_job_id(), update, tmp_path)
    path = job_storage.get_job_path(_job_id(), tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["count"] == 1
    assert len(calls) == (1 if operation == "update" else 0)


@pytest.mark.parametrize("value", [None, 3, b"a" * 32, "a" * 32 + "\n"])
def test_job_ids_require_an_exact_string_match(value):
    """Reject non-string identifiers and trailing line separators.

    Inputs: malformed identifier. Output: validation rejects the exact value.
    """
    assert job_storage.safe_job_id(value) is False


def test_job_storage_batch_and_compatibility_helpers_cover_threshold_and_status_logic(
    monkeypatch,
):
    """Verify job storage batch and compatibility helpers cover threshold and status logic.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job storage batch and compatibility helpers cover threshold and status logic.
    """
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
    """Verify job storage file access helpers cover lock fallback retry and corrupt updates.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `real_lock` result. Raises: LockException for the exercised failure path.
    """
    payload = {"job_id": _job_id(), "status": "ready"}
    path = tmp_path / f"{_job_id()}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    real_lock = job_storage.portalocker.Lock

    assert job_storage.safe_job_id(_job_id()) is True
    assert job_storage.safe_job_id("not-a-job-id") is False
    assert job_storage.get_job_path(_job_id(), tmp_path) == path

    class _RaisingLock:
        """Test double for raising lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `_RaisingLock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None. Raises: LockException when validation or the called operation fails.
            """
            raise job_storage.portalocker.exceptions.LockException("busy")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _RaisingLock)
    assert job_storage.load_job(_job_id(), tmp_path) == payload
    assert job_storage.load_job("../escape", tmp_path) is None

    attempts = {"count": 0}

    def flaky_lock(*args, **kwargs):
        """Return the flaky lock.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `real_lock` result. Raises: LockException when validation or external operations
        fail.
        """
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
    assert attempts["count"] >= 2

    class _AlwaysFailLock:
        """Test double for always fail lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `_AlwaysFailLock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None. Raises: LockException when validation or the called operation fails.
            """
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
    """Verify job storage append helpers store timestamped messages.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job storage append helpers store timestamped messages.
    """
    monkeypatch.setattr(job_storage.time, "time", lambda: 123.5)
    job = {}

    job_storage.append_job_message(job, "hello")
    job_storage.append_job_error(job, "boom")

    assert job["messages"] == [{"timestamp": 123.5, "text": "hello"}]
    assert job["errors"] == [{"timestamp": 123.5, "text": "boom"}]


def test_job_storage_remaining_edges_cover_empty_paths_and_failed_update_retries(
    tmp_path,
    monkeypatch,
):
    """Verify job storage remaining edges cover empty paths and failed update retries.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None after assertions pass. Raises: LockException when validation or
    external operations fail.
    """
    monkeypatch.setenv("EDGE_BATCH_SIZE", "not-a-number")
    assert job_storage.get_env_int("EDGE_BATCH_SIZE", 4, 1, 10) == 4
    assert job_storage.should_start_compatibility_check({"files": []}) is False
    assert job_storage.load_job(_job_id(), tmp_path) is None

    path = tmp_path / f"{_job_id()}.json"
    path.write_text(json.dumps({"job_id": _job_id(), "status": "checking"}))

    class _AlwaysFailLock:
        """Test double for always fail lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `_AlwaysFailLock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None. Raises: LockException when validation or the called operation fails.
            """
            raise job_storage.portalocker.exceptions.LockException("busy")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _AlwaysFailLock)
    monkeypatch.setattr(job_storage.time, "sleep", lambda _value: None)
    monkeypatch.setattr(job_storage.random, "uniform", lambda _start, _end: 0.0)

    assert (
        job_storage.robust_update_job(
            _job_id(),
            lambda job: {**job, "status": "ready"},
            tmp_path,
            retries=2,
            timeout=0.1,
        )
        is None
    )


def test_job_storage_load_job_covers_locked_success_and_failed_fallback_reads(
    tmp_path,
    monkeypatch,
):
    """Verify job storage load job covers locked success and failed fallback reads.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None after assertions pass. Raises: LockException when validation or
    external operations fail.
    """
    payload = {"job_id": _job_id(), "status": "ready"}
    path = tmp_path / f"{_job_id()}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert job_storage.load_job(_job_id(), tmp_path) == payload

    class _FailingLock:
        """Test double for failing lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `_FailingLock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None. Raises: LockException when validation or the called operation fails.
            """
            raise job_storage.portalocker.exceptions.LockException("busy")

    monkeypatch.setattr(job_storage.portalocker, "Lock", _FailingLock)
    monkeypatch.setattr(
        job_storage.Path,
        "open",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("open failed")),
    )
    assert job_storage.load_job(_job_id(), tmp_path) is None
