import json
import logging
import os
import portalocker
import re
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from threading import local

from ...constants import JOBS_DIR

logger = logging.getLogger(__name__)
_JOB_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_HELD_JOB_LOCKS = local()


def _validate_job_id(job_id):
    """Validate job ID.

    Inputs: `job_id`. Output: `uuid.UUID(hex=job_id.lower()).hex`. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("Invalid job id.")
    return uuid.UUID(hex=job_id.lower()).hex


def _jobs_root() -> Path:
    """Jobs root.

    Inputs: none. Output: `Path`.
    """
    return Path(JOBS_DIR)


def _validated_job_path(job_id, suffix: str) -> Path:
    """Validated job path.

    Inputs: `job_id`, `suffix`. Output: `Path`.
    """
    return _jobs_root() / f"{_validate_job_id(job_id)}{suffix}"


def get_job_path(job_id):
    """Return job path.

    Inputs: `job_id`. Output: `str` result.
    """
    return str(_validated_job_path(job_id, ".json"))


def get_job_lock_path(job_id):
    """Return job lock path.

    Inputs: `job_id`. Output: `str` result.
    """
    return str(_validated_job_path(job_id, ".lock"))


def _held_job_locks() -> Counter[str]:
    """Held job locks.

    Inputs: none. Output: `Counter[str]`.
    """
    locks = getattr(_HELD_JOB_LOCKS, "locks", None)
    if locks is None:
        locks = Counter()
        _HELD_JOB_LOCKS.locks = locks
    return locks


@contextmanager
def mark_job_lock_held(job_id):
    """Mark the current thread as owning a job lock for nested saves.

    Inputs: `job_id`. Output: yielded values.
    """
    try:
        lock_key = str(_validated_job_path(job_id, ".lock"))
    except ValueError:
        yield
        return
    held_locks = _held_job_locks()
    held_locks[lock_key] += 1
    try:
        yield
    finally:
        held_locks[lock_key] -= 1
        if held_locks[lock_key] <= 0:
            del held_locks[lock_key]


def load_job(job_id):
    """Load job.

    Inputs: `job_id`. Output: `json.load` result or None.
    """
    try:
        path = _validated_job_path(job_id, ".json")
        lock_path = _validated_job_path(job_id, ".lock")
    except ValueError:
        return None
    if not path.exists():
        return None
    with portalocker.Lock(lock_path, "a+", timeout=1):
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)


def save_job(job_dict):
    """Save job data to filesystem.

    Inputs: `job_dict`. Output: None.
    """
    path = _validated_job_path(job_dict["job_id"], ".json")
    lock_path = _validated_job_path(job_dict["job_id"], ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    if _held_job_locks().get(str(lock_path), 0) > 0:
        _write_job_file(path, job_dict)
        return

    with portalocker.Lock(lock_path, "a+", timeout=1):
        _write_job_file(path, job_dict)


def _write_job_file(path, job_dict):
    """Write job file.

    Inputs: `path`, `job_dict`. Output: None.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            json.dump(job_dict, handle)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
