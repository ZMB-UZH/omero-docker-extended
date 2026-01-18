"""
Compatibility layer - wraps refactored services to maintain original function signatures.
This allows views to call functions without passing jobs_root parameter.
"""
from .jobs.job_storage import (
    get_job_path as _get_job_path_internal,
    load_job as _load_job_internal,
    save_job as _save_job_internal,
    robust_update_job as _robust_update_job_internal,
    get_env_int,
    normalize_job_batch_size,
    resolve_job_batch_size,
    has_pending_uploads,
    get_compatibility_pending_entries,
    should_start_compatibility_check,
    refresh_job_status,
    safe_job_id,
    append_job_message,
    append_job_error,
    _compatibility_pending_entries
)
from ..utils.file_helpers import get_jobs_root
from ..utils.omero_helpers import (
    _current_user_id,
    _get_owner_username,
    _has_read_write_permissions
)
from .omero.dataset_service import _iter_accessible_projects
from .upload_management.workflow_service import (
    _normalize_sem_edx_associations,
    _build_sem_edx_associations_from_entries
)


# Wrapper functions that inject jobs_root parameter
def _job_path(job_id: str):
    """Get job path without needing to pass jobs_root."""
    return _get_job_path_internal(job_id, get_jobs_root())


def _load_job(job_id: str):
    """Load job without needing to pass jobs_root."""
    return _load_job_internal(job_id, get_jobs_root())


def _save_job(job_dict, retries: int = 5, timeout: float = 2.0):
    """Save job without needing to pass jobs_root."""
    return _save_job_internal(job_dict, get_jobs_root(), retries, timeout)


def _robust_update_job(job_id: str, update_fn, retries: int = 5, timeout: float = 2.0):
    """Update job without needing to pass jobs_root."""
    return _robust_update_job_internal(job_id, update_fn, get_jobs_root(), retries, timeout)


# Re-export with underscore aliases
__all__ = [
    '_job_path',
    '_load_job',
    '_save_job',
    '_robust_update_job',
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
    '_compatibility_pending_entries',
    '_current_user_id',
    '_get_owner_username',
    '_has_read_write_permissions',
    '_iter_accessible_projects',
    '_normalize_sem_edx_associations',
    '_build_sem_edx_associations_from_entries',
]
