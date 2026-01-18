"""
Job storage and retrieval using file-based persistence.
"""
import os
import json
import logging
import portalocker

from ...constants import JOBS_DIR

logger = logging.getLogger(__name__)


def get_job_path(job_id):
    """Get filesystem path for job JSON file."""
    return os.path.join(JOBS_DIR, f"{job_id}.json")


def get_job_lock_path(job_id):
    """Get filesystem path for job lock file."""
    return os.path.join(JOBS_DIR, f"{job_id}.lock")


def load_job(job_id):
    """Load job data from filesystem."""
    path = get_job_path(job_id)
    if not os.path.exists(path):
        return None
    with portalocker.Lock(path, "r", timeout=1) as f:
        return json.load(f)


def save_job(job_dict):
    """Save job data to filesystem."""
    path = get_job_path(job_dict["job_id"])
    with portalocker.Lock(path, "w", timeout=1) as f:
        json.dump(job_dict, f)
