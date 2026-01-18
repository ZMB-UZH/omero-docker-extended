"""
Compatibility layer - wraps refactored services to maintain original function signatures.
This allows views to call functions without passing jobs_root parameter.
"""
from .jobs.job_storage import (
    get_job_path as _get_job_path,
    load_job as _load_job,
    save_job as _save_job,
    robust_update_job as _robust_update_job,
    get_env_int,
    normalize_job_batch_size,
    resolve_job_batch_size,
    has_pending_uploads,
    get_compatibility_pending_entries,
    should_start_compatibility_check,
    refresh_job_status,
    safe_job_id,
    append_job_message,
    append_job_error
)
from ..utils.file_helpers import get_jobs_root


# Wrapper functions that inject jobs_root parameter
def get_job_path(job_id: str):
    """Get job path without needing to pass jobs_root."""
    return _get_job_path(job_id, get_jobs_root())


def load_job(job_id: str):
    """Load job without needing to pass jobs_root."""
    return _load_job(job_id, get_jobs_root())


def save_job(job_dict, retries: int = 5, timeout: float = 2.0):
    """Save job without needing to pass jobs_root."""
    return _save_job(job_dict, get_jobs_root(), retries, timeout)


def robust_update_job(job_id: str, update_fn, retries: int = 5, timeout: float = 2.0):
    """Update job without needing to pass jobs_root."""
    return _robust_update_job(job_id, update_fn, get_jobs_root(), retries, timeout)


# Re-export functions that don't need wrapping
__all__ = [
    'get_job_path',
    'load_job',
    'save_job',
    'robust_update_job',
    'get_env_int',
    'normalize_job_batch_size',
    'resolve_job_batch_size',
    'has_pending_uploads',
    'get_compatibility_pending_entries',
    'should_start_compatibility_check',
    'refresh_job_status',
    'safe_job_id',
    'append_job_message',
    'append_job_error',
]
