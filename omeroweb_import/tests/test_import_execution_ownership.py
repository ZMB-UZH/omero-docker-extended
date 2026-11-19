"""Regression tests for import dispatch and its durable execution boundary."""

from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import uuid

import portalocker
import pytest

from omeroweb_import.strings import errors


@pytest.fixture
def job_store(monkeypatch, tmp_path):
    """Create a ready job in an isolated directory.

    Inputs: pytest path and patch fixtures. Output: importer module and job ID.
    """
    from omeroweb_import.views import core_functions

    job_id = uuid.uuid4().hex
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: tmp_path)
    assert core_functions._save_job(
        {"job_id": job_id, "status": "ready", "import_thread_started": False}
    )
    return core_functions, job_id


def test_simultaneous_requests_execute_one_import(job_store, monkeypatch):
    """Both requests see the same ready snapshot; only one runs the import.

    Inputs: isolated job store and patches. Output: verifies one durable completion.
    """
    core, job_id = job_store
    both_read = threading.Barrier(2, timeout=10)
    release = threading.Event()
    dispatched = []
    workers = []
    original_load = core._load_job

    def read_for_dispatch(current_id):
        """Wait until both dispatchers have read the ready snapshot.

        Inputs: job ID. Output: snapshot read before either dispatcher proceeds.
        """
        snapshot = original_load(current_id)
        both_read.wait()
        return snapshot

    def make_worker(**kwargs):
        """Keep references so the test can join every launched worker.

        Inputs: thread options. Output: real thread with those options.
        """
        worker = threading.Thread(**kwargs)
        workers.append(worker)
        return worker

    def process(current_id):
        """Complete the job after both dispatchers have returned.

        Inputs: job ID. Output: none; records the invocation and saves progress.
        """
        dispatched.append(current_id)
        assert release.wait(10)
        assert core._update_job(
            current_id, lambda job: {**job, "status": "done", "imported_bytes": 123}
        )

    monkeypatch.setattr(core, "_load_job", read_for_dispatch)
    monkeypatch.setattr(core, "threading", SimpleNamespace(Thread=make_worker))
    monkeypatch.setattr(core, "_process_import_job", process)
    try:
        with ThreadPoolExecutor(2) as executor:
            requests = [
                executor.submit(core._start_import_thread, job_id) for _ in range(2)
            ]
            for request in requests:
                request.result(timeout=15)
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=10)
            assert not worker.is_alive()

    assert dispatched == [job_id]
    assert original_load(job_id)["status"] == "done"
    assert original_load(job_id)["imported_bytes"] == 123


def test_attempt_setup_failure_releases_the_execution_lock(job_store, monkeypatch):
    """A failed dispatch setup must leave a ready job eligible for retry.

    Inputs: isolated job store and randomness fault. Output: verifies that
    the real execution lock can be reacquired without changing job state.
    """
    core, job_id = job_store

    def unavailable():
        """Model the OS failing to supply randomness for a new attempt.

        Inputs: none. Output: raises an OSError before an attempt is recorded.
        """
        raise OSError("attempt identifier unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(core.uuid, "uuid4", unavailable)
        with pytest.raises(OSError, match="attempt identifier unavailable"):
            core._start_import_thread(job_id)

    assert core._load_job(job_id)["status"] == "ready"
    ownership = core._try_import_execution_lock(job_id)
    assert ownership is not None
    ownership.close()


def _exit_while_holding_lock(path, acquired, release):
    """Model abrupt worker exit without releasing the execution lock in Python.

    Inputs: lock path and process events. Output: exits with the lock still held.
    """
    with Path(path).open("r+b") as handle:
        portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        acquired.set()
        if release.wait(15):
            os._exit(0)


class _InlineThread:
    """Run a worker synchronously so the test can inspect its persisted result."""

    def __init__(self, *, target, args, daemon):
        """Capture a worker invocation without allocating a thread.

        Inputs: target, arguments, and thread-compatible daemon flag. Output: none.
        """
        self.target = target
        self.args = args

    def start(self):
        """Run the captured invocation in the caller.

        Inputs: stored target and arguments. Output: none after the target returns.
        """
        self.target(*self.args)


@pytest.mark.parametrize("phase", ["claimed", "executing"])
def test_poll_recovers_job_after_owning_process_exits(
    job_store, tmp_path, monkeypatch, phase
):
    """Poll an active then exited worker, without replaying ambiguous effects.

    Inputs: job store, staged file, worker phase and patches. Output: verifies recovery.
    """
    from omeroweb_import.views import index_view

    core, job_id = job_store
    original_attempt = uuid.uuid4().hex
    status = "ready" if phase == "claimed" else "importing"
    staged = tmp_path / "staged.tif"
    staged.write_bytes(b"retained input")
    assert core._update_job(
        job_id,
        lambda job: {
            **job,
            "status": status,
            "import_thread_started": True,
            "import_worker_phase": phase,
            "import_worker_attempt": original_attempt,
            "imported_bytes": 17 if phase == "executing" else 0,
        },
    )
    ownership = core._try_import_execution_lock(job_id)
    assert ownership is not None
    ownership.close()
    lock_path = tmp_path / f".{job_id}.import.lock"
    assert lock_path.stat().st_mode & 0o777 == 0o600

    calls = []

    def complete(current_id):
        """Record a recovery that invoked the importer.

        Inputs: job ID. Output: none; marks the fixture complete in the job store.
        """
        calls.append(current_id)
        assert core._update_job(current_id, lambda job: {**job, "status": "done"})

    monkeypatch.setattr(core, "_process_import_job", complete)
    monkeypatch.setattr(
        core,
        "_mark_failed_job_for_deferred_cleanup",
        lambda *_: pytest.fail("interrupted data was scheduled for cleanup"),
    )
    monkeypatch.setattr(core, "threading", SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(
        index_view, "_load_owned_job", lambda *args: (core._load_job(job_id), None)
    )
    request = SimpleNamespace(method="GET", user=SimpleNamespace(username="test-user"))
    context = multiprocessing.get_context("spawn")
    acquired, release = context.Event(), context.Event()
    process = context.Process(
        target=_exit_while_holding_lock, args=(lock_path, acquired, release)
    )
    process.start()
    try:
        assert acquired.wait(10)
        response = index_view.job_status(request, job_id=job_id, conn=None)
        assert json.loads(response.content)["status"] == status
        assert calls == []
    finally:
        release.set()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0

    response = index_view.job_status(request, job_id=job_id, conn=None)
    persisted = core._load_job(job_id)
    if phase == "claimed":
        assert calls == [job_id]
        assert persisted["status"] == "done"
        assert persisted["import_worker_attempt"] != original_attempt
    else:
        assert calls == []
        assert persisted["status"] == "error"
        assert persisted["import_worker_phase"] == "interrupted"
        assert persisted["reconciliation_required"] is True
        assert persisted["imported_bytes"] == 17
        assert persisted["errors"] == [errors.import_execution_interrupted()]
        assert staged.read_bytes() == b"retained input"
    assert json.loads(response.content)["status"] == persisted["status"]


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_nonregular_execution_lock_does_not_dispatch(
    job_store, tmp_path, monkeypatch, kind
):
    """Reject a non-regular lock without blocking or touching other files.

    Inputs: isolated job store and unexpected file type. Output: verifies no dispatch.
    """
    core, job_id = job_store
    target = tmp_path / "untouched"
    target.write_bytes(b"unchanged")
    entry = tmp_path / f".{job_id}.import.lock"
    if kind == "symlink":
        entry.symlink_to(target)
    else:
        os.mkfifo(entry)
    monkeypatch.setattr(
        core, "_process_import_job", lambda *_: pytest.fail("an import was dispatched")
    )
    core._start_import_thread(job_id)
    assert core._load_job(job_id)["import_thread_started"] is False
    assert target.read_bytes() == b"unchanged"


def test_claim_rechecks_a_job_that_completed_after_the_initial_read(
    job_store, monkeypatch
):
    """An old ready snapshot must not revive a terminal job.

    Inputs: job store and lock hook. Output: verifies completion survives dispatch.
    """
    core, job_id = job_store
    original_lock = core._try_import_execution_lock

    def lock_after_completion(current_id):
        """Finalize the job before the dispatcher obtains its lock.

        Inputs: job ID. Output: production lock acquisition result.
        """
        assert core._update_job(current_id, lambda job: {**job, "status": "done"})
        return original_lock(current_id)

    monkeypatch.setattr(core, "_try_import_execution_lock", lock_after_completion)
    monkeypatch.setattr(
        core, "_process_import_job", lambda *_: pytest.fail("a finished job restarted")
    )
    core._start_import_thread(job_id)
    current = core._load_job(job_id)
    assert current["status"] == "done"
    assert "import_worker_attempt" not in current


def test_unconfirmed_claim_durability_does_not_start_the_worker(job_store, monkeypatch):
    """Recover a saved claim only after a later, verified transaction.

    Inputs: job store and a transient sync failure. Output: verifies exactly one run.
    """
    core, job_id = job_store
    original_sync = core._fsync_jobs_directory
    outcomes = iter([False, True])

    def sync_jobs_directory():
        """Fail the first directory sync and perform later syncs normally.

        Inputs: queued outcomes. Output: none; raises OSError for the first attempt.
        """
        if not next(outcomes, True):
            raise OSError("test directory synchronization failure")
        original_sync()

    executions = []

    def complete(current_id):
        """Record execution after the retry confirms its own claim.

        Inputs: job ID. Output: none; persists the fixture's terminal state.
        """
        executions.append(current_id)
        assert core._update_job(current_id, lambda job: {**job, "status": "done"})

    monkeypatch.setattr(core, "_fsync_jobs_directory", sync_jobs_directory)
    monkeypatch.setattr(core, "threading", SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(core, "_process_import_job", complete)
    core._start_import_thread(job_id)
    uncertain = core._load_job(job_id)
    assert uncertain["import_worker_phase"] == "claimed"
    assert executions == []

    core._start_import_thread(job_id)
    committed = core._load_job(job_id)
    assert committed["status"] == "done"
    assert committed["import_worker_attempt"] != uncertain["import_worker_attempt"]
    assert executions == [job_id]
