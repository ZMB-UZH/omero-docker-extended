"""
Job storage and retrieval using file-based persistence.
"""

import os
import json
import logging
import portalocker
import re

from ...constants import JOBS_DIR

logger = logging.getLogger(__name__)
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _validate_job_id(job_id):
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("Invalid job id.")
    return job_id


def get_job_path(job_id):
    """Get filesystem path for job JSON file."""
    return os.path.join(JOBS_DIR, f"{_validate_job_id(job_id)}.json")


def get_job_lock_path(job_id):
    """Get filesystem path for job lock file."""
    return os.path.join(JOBS_DIR, f"{_validate_job_id(job_id)}.lock")


def load_job(job_id):
    """Load job data from filesystem."""
    try:
        path = get_job_path(job_id)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    with portalocker.Lock(path, "r", timeout=1) as f:
        return json.load(f)


def save_job(job_dict):
    """Save job data to filesystem."""
    path = get_job_path(job_dict["job_id"])
    with portalocker.Lock(path, "w", timeout=1) as f:
        json.dump(job_dict, f)
