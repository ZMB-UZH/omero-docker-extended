import json
import logging
import portalocker
import re
import tempfile
import uuid
from pathlib import Path

from ...constants import JOBS_DIR

logger = logging.getLogger(__name__)
_JOB_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _validate_job_id(job_id):
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("Invalid job id.")
    return uuid.UUID(hex=job_id.lower()).hex


def _jobs_root() -> Path:
    return Path(JOBS_DIR)


def _validated_job_path(job_id, suffix: str) -> Path:
    return _jobs_root() / f"{_validate_job_id(job_id)}{suffix}"


def get_job_path(job_id):
    """Get filesystem path for job JSON file."""
    return str(_validated_job_path(job_id, ".json"))


def get_job_lock_path(job_id):
    """Get filesystem path for job lock file."""
    return str(_validated_job_path(job_id, ".lock"))


def load_job(job_id):
    """Load job data from filesystem."""
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
    """Save job data to filesystem."""
    path = _validated_job_path(job_dict["job_id"], ".json")
    lock_path = _validated_job_path(job_dict["job_id"], ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with portalocker.Lock(lock_path, "a+", timeout=1):
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
            tmp_path.replace(path)
            tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
