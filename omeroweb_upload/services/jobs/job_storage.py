"""
Job storage and management for upload workflows.
"""
import os
import json
import time
import random
import logging
import re
import portalocker
from pathlib import Path

logger = logging.getLogger(__name__)

# Constants from original file
INT_SANITIZER = re.compile(r"[^0-9]")
UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"
DEFAULT_UPLOAD_BATCH_FILES = 5


def get_job_path(job_id: str, jobs_root: Path) -> Path:
    """Get filesystem path for job file."""
    return jobs_root / f"{job_id}.json"


def get_env_int(env_key: str, default: int, min_value: int, max_value: int) -> int:
    """Get integer from environment with bounds checking.

    IMPORTANT: env vars must be OPTIONAL. Missing/invalid values should fall back to defaults.
    """
    raw = os.environ.get(env_key, "")
    if raw:
        raw = INT_SANITIZER.sub("", str(raw))
    try:
        value = int(raw) if raw else default
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def normalize_job_batch_size(value, default: int) -> int:
    """Normalize batch size to valid range."""
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(10, normalized))


def resolve_job_batch_size(job_dict) -> int:
    """Resolve batch size for job from dict or environment."""
    default_batch_size = get_env_int(
        UPLOAD_BATCH_FILES_ENV,
        DEFAULT_UPLOAD_BATCH_FILES,
        1,
        10,
    )
    return normalize_job_batch_size(job_dict.get("job_batch_size"), default_batch_size)


def has_pending_uploads(job_dict) -> bool:
    """Check if job has pending upload entries."""
    return any(entry.get("status") == "pending" for entry in job_dict.get("files", []))


def get_compatibility_pending_entries(job_dict):
    """Get entries awaiting compatibility check."""
    return [
        entry
        for entry in job_dict.get("files", [])
        if (
            entry.get("status") == "uploaded"
            and not entry.get("compatibility")
            and not entry.get("compatibility_skip")
        )
    ]


def should_start_compatibility_check(job_dict) -> bool:
    """Determine if compatibility check should start."""
    if not job_dict or job_dict.get("compatibility_thread_active"):
        return False
    if job_dict.get("compatibility_confirmed"):
        return False
    pending_entries = get_compatibility_pending_entries(job_dict)
    if not pending_entries:
        return False
    batch_size = resolve_job_batch_size(job_dict)
    return len(pending_entries) >= batch_size or not has_pending_uploads(job_dict)


def refresh_job_status(job_dict):
    """Update job status based on current state."""
    if has_pending_uploads(job_dict):
        job_dict["status"] = "uploading"
        return job_dict

    # SEM-EDX: if nothing requires compatibility (e.g. only .txt files, or all skipped),
    # do NOT get stuck in "checking". Mark as compatible once uploads are complete.
    if job_dict.get("special_upload") == "sem_edx_spectra":
        pending_entries = get_compatibility_pending_entries(job_dict)
        if not pending_entries and job_dict.get("compatibility_status") not in ("compatible", "incompatible", "error"):
            job_dict["compatibility_status"] = "compatible"

    compatibility_status = job_dict.get("compatibility_status")
    if compatibility_status == "incompatible":
        job_dict["status"] = "awaiting_confirmation"
    elif compatibility_status == "error":
        # Compatibility check errors should NOT block the import.
        # The actual import will surface real errors.
        logger.warning(
            "Compatibility check had errors for job %s – proceeding to import anyway",
            job_dict.get("job_id", "?"),
        )
        job_dict["status"] = "ready"
    elif compatibility_status == "compatible":
        job_dict["status"] = "ready"
    else:
        job_dict["status"] = "checking"
    return job_dict


def load_job(job_id: str, jobs_root: Path):
    """Load job data from filesystem."""
    path = get_job_path(job_id, jobs_root)
    if not path.exists():
        return None
    try:
        with portalocker.Lock(path, "r", timeout=1) as handle:
            return json.load(handle)
    except (portalocker.exceptions.LockException, OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to lock or read job file %s: %s", path, exc)
    try:
        with path.open("r") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read job file %s without lock: %s", path, exc)
    return None


def save_job(job_dict, jobs_root: Path, retries: int = 5, timeout: float = 2.0):
    """Save job data to filesystem with retry logic."""
    path = get_job_path(job_dict["job_id"], jobs_root)
    job_dict["updated"] = time.time()
    for attempt in range(retries):
        if attempt:
            time.sleep(random.uniform(0.05, 0.2))
        try:
            with portalocker.Lock(path, "w", timeout=timeout) as handle:
                json.dump(job_dict, handle)
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except (portalocker.exceptions.LockException, OSError) as exc:
            logger.warning(
                "Unable to lock job file %s for writing (attempt %s/%s): %s",
                path,
                attempt + 1,
                retries,
                exc,
            )
    logger.error("Failed to lock job file %s for writing after %s attempts.", path, retries)
    return False


def robust_update_job(job_id: str, update_fn, jobs_root: Path, retries: int = 5, timeout: float = 2.0):
    """Atomically update job with function."""
    path = get_job_path(job_id, jobs_root)
    for attempt in range(retries):
        if attempt:
            time.sleep(random.uniform(0.05, 0.2))
        try:
            with portalocker.Lock(path, "r+", timeout=timeout) as handle:
                job_dict = json.load(handle)
                job_dict = update_fn(job_dict)
                handle.seek(0)
                handle.truncate()
                json.dump(job_dict, handle)
                handle.flush()
                os.fsync(handle.fileno())
            return job_dict
        except json.JSONDecodeError as exc:
            logger.error("Job file %s is corrupt: %s", path, exc)
            return None
        except (portalocker.exceptions.LockException, OSError) as exc:
            logger.warning(
                "Unable to lock job file %s for update (attempt %s/%s): %s",
                path,
                attempt + 1,
                retries,
                exc,
            )
    logger.error("Failed to lock job file %s for update after %s attempts.", path, retries)
    return None


def safe_job_id(value: str) -> bool:
    """Validate job ID format."""
    import re
    JOB_ID_SANITIZER = re.compile(r"^[0-9a-fA-F]{32}$")
    return bool(value and JOB_ID_SANITIZER.match(value))


def append_job_message(job: dict, message: str):
    """Append message to job log."""
    messages = job.get("messages", [])
    messages.append({"timestamp": time.time(), "text": message})
    job["messages"] = messages


def append_job_error(job: dict, message: str):
    """Append error to job log."""
    errors = job.get("errors", [])
    errors.append({"timestamp": time.time(), "text": message})
    job["errors"] = errors

def _compatibility_pending_entries(job_dict):
    return [
        entry
        for entry in job_dict.get("files", [])
        if (
            entry.get("status") == "uploaded"
            and not entry.get("compatibility")
            and not entry.get("compatibility_skip")
        )
    ]
