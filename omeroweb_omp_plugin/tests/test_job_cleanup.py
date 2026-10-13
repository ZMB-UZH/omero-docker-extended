"""Behavioral checks for legacy file cleanup, confined to disposable directories."""

import logging
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from omeroweb_omp_plugin.services import job_cleanup as cleanup


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """Inputs: temporary directory. Output: explicit cleanup root and stable clock."""
    root = tmp_path / "storage.json" / "jobs"
    root.mkdir(parents=True)
    monkeypatch.setattr(cleanup, "JOBS_DIR", str(root))
    monkeypatch.setattr(cleanup.time, "time", lambda: 100000.0)
    monkeypatch.setattr(cleanup, "_cleanup_state", {"last_cleanup_time": 0.0})
    return root


def aged_file(path, age):
    """Inputs: path and age. Output: real fixture file with controlled timestamps."""
    path.write_bytes(b"keep original bytes")
    os.utime(path, (100000 - age, 100000 - age))
    return path


def test_cleanup_removes_only_expired_job_and_its_local_lock(jobs, caplog):
    """Inputs: mixed ages and JSON-named parent. Output: precise, directory-local deletion."""
    caplog.set_level(logging.INFO)
    old = aged_file(jobs / "expired.json", cleanup.JOB_MAX_AGE_SECONDS + 1)
    lock = aged_file(jobs / "expired.lock", cleanup.JOB_MAX_AGE_SECONDS + 1)
    unrelated = jobs.parent.parent / "storage.lock" / "jobs"
    unrelated.mkdir(parents=True)
    foreign_lock = aged_file(
        unrelated / "expired.lock", cleanup.JOB_MAX_AGE_SECONDS + 1
    )
    no_lock = aged_file(jobs / "no-lock.json", cleanup.JOB_MAX_AGE_SECONDS + 1)
    retained = [
        aged_file(jobs / "recent.json", 1),
        aged_file(jobs / "boundary.json", cleanup.JOB_MAX_AGE_SECONDS),
        aged_file(jobs / "not-a-job.txt", cleanup.JOB_MAX_AGE_SECONDS + 1),
        aged_file(jobs / "active.lock", cleanup.JOB_MAX_AGE_SECONDS + 1),
        foreign_lock,
    ]
    cleanup.cleanup_old_jobs()
    assert all(not path.exists() for path in (old, lock, no_lock))
    assert all(path.read_bytes() == b"keep original bytes" for path in retained)
    assert "Cleaned up 2 old job file(s)" in caplog.text


def test_cleanup_throttle_and_missing_directory_do_not_enumerate(jobs, monkeypatch):
    """Inputs: recent cleanup and absent storage. Output: no directory enumeration."""
    listing = Mock(side_effect=AssertionError("Unexpected directory access"))
    monkeypatch.setattr(cleanup.os, "listdir", listing)
    cleanup._cleanup_state["last_cleanup_time"] = (
        100000 - cleanup.JOB_CLEANUP_INTERVAL + 1
    )
    cleanup.cleanup_old_jobs()
    cleanup._cleanup_state["last_cleanup_time"] = 0
    monkeypatch.setattr(cleanup, "JOBS_DIR", str(jobs / "absent"))
    cleanup.cleanup_old_jobs()
    listing.assert_not_called()


def test_cleanup_keeps_lock_failure_bounded_and_sanitized(jobs, monkeypatch, caplog):
    """Inputs: lock removal failure. Output: job cleanup succeeds and logs stay single-line."""
    caplog.set_level(logging.DEBUG)
    job = aged_file(jobs / "expired.json", cleanup.JOB_MAX_AGE_SECONDS + 1)
    lock = aged_file(jobs / "expired.lock", cleanup.JOB_MAX_AGE_SECONDS + 1)
    remove = os.remove

    def fail_lock(path):
        """Inputs: cleanup path. Output: injected lock failure or actual file deletion."""
        if Path(path) == lock:
            raise OSError("failure\nforged-log-entry")
        return remove(path)

    monkeypatch.setattr(cleanup.os, "remove", fail_lock)
    cleanup.cleanup_old_jobs()
    assert not job.exists()
    assert lock.exists()
    message = next(
        record.getMessage() for record in caplog.records if "lock cleanup" in record.msg
    )
    assert "\n" not in message and "\\n" in message


def test_cleanup_reports_per_file_error_and_continues(jobs, caplog):
    """Inputs: JSON-named directory and valid old job. Output: error retained, other job removed."""
    invalid = jobs / "directory.json"
    invalid.mkdir()
    os.utime(invalid, (0, 0))
    old = aged_file(jobs / "old.json", cleanup.JOB_MAX_AGE_SECONDS + 1)
    cleanup.cleanup_old_jobs()
    assert invalid.is_dir()
    assert not old.exists()
    assert "Encountered 1 error(s)" in caplog.text


def test_cleanup_reports_unreadable_inventory(jobs, monkeypatch, caplog):
    """Inputs: inaccessible directory listing. Output: sanitized error without deleting files."""
    retained = aged_file(jobs / "old.json", cleanup.JOB_MAX_AGE_SECONDS + 1)
    monkeypatch.setattr(
        cleanup.os, "listdir", Mock(side_effect=OSError("denied\nprivate"))
    )
    cleanup.cleanup_old_jobs()
    assert retained.exists()
    message = next(
        record.getMessage()
        for record in caplog.records
        if "Job cleanup failed" in record.msg
    )
    assert "\n" not in message and "\\n" in message
