"""
Core helper functions for upload views.
All non-view functions extracted here to reduce index_view.py size.
"""

import errno
import os
import json
import logging
import random
import re
import secrets
import stat
import string
import subprocess
import shutil
import threading
import time
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import omero

import portalocker

from concurrent.futures import ThreadPoolExecutor, as_completed

from pathlib import Path, PurePosixPath
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from omero.gateway import BlitzGateway
from omero.model import DatasetI, ProjectDatasetLinkI, ProjectI
from omero.rtypes import rstring
from omeroweb.decorators import login_required
from typing import Optional
from ..constants import (
    MAX_UPLOAD_BATCH_BYTES,
    MAX_UPLOAD_BATCH_GB,
    OMERO_CLI,
    OMERO_IMPORT_SCAN_DEPTH,
)
from ..services.ome_zarr_support import (
    OME_ZARR_IMPORT_KIND_IMAGE,
    inspect_ome_zarr_image,
    normalize_native_ome_zarr_copy,
)
from ..strings import errors, messages
from ..utils.file_helpers import resolve_upload_root, resolve_jobs_root
from omero_plugin_common.tmp_utils import get_plugin_tmp_dir
from omero_plugin_common.env_utils import get_bool_env, ENV_FILE_OMEROWEB
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info
from omero_plugin_common.tmp_cleanup import (
    safe_mark_path_for_deferred_cleanup,
    safe_remove_job_data,
)
from .utils import current_username, json_error, load_json_body

__all__ = [
    "BlitzGateway",
    "DatasetI",
    "DEFAULT_UPLOAD_BATCH_FILES",
    "DEFAULT_UPLOAD_CONCURRENCY",
    "INT_SANITIZER",
    "JOB_ID_SANITIZER",
    "JOB_SERVICE_GROUP_ENV",
    "JOB_SERVICE_AUTH_ENV",
    "JOB_SERVICE_SECURE_ENV",
    "JOB_SERVICE_USER_ENV",
    "JsonResponse",
    "MAX_IMPORT_LOG_LINES",
    "MAX_UPLOAD_BATCH_BYTES",
    "MAX_UPLOAD_BATCH_GB",
    "OMERO_CLI",
    "OMERO_IMPORT_SCAN_DEPTH",
    "ORPHAN_DATASET_PREFIX",
    "ORPHAN_SUFFIX_ALPHANUM",
    "ORPHAN_SUFFIX_LENGTH",
    "Optional",
    "Path",
    "ProjectDatasetLinkI",
    "ProjectI",
    "PurePosixPath",
    "SPECIAL_METHODS_DISABLED_ENV",
    "SEM_EDX_FILEANNOTATION_NS",
    "ThreadPoolExecutor",
    "UPLOAD_BATCH_FILES_ENV",
    "UPLOAD_CONCURRENCY_ENV",
    "_CLI_ID_PATTERN",
    "_IMPORT_OBJECT_PATTERN",
    "_DIRS_INITIALIZED",
    "_IMPORT_LOCKS",
    "_IMPORT_LOCKS_GUARD",
    "_JOBS_ROOT_CACHE",
    "_UPLOAD_ROOT_CACHE",
    "_append_job_error",
    "_append_job_message",
    "_append_txt_attachment_message",
    "_apply_upload_updates",
    "_append_upload_chunks_to_staged_path",
    "_attach_txt_to_image_service",
    "_batch_find_images_by_name",
    "_build_staged_relative_path",
    "_build_omero_cli_command",
    "_build_sem_edx_associations_from_entries",
    "_check_import_compatibility",
    "_classify_compatibility_output",
    "_collect_project_payload",
    "_compatibility_pending_entries",
    "_current_user_id",
    "_dataset_name_for_path",
    "_ensure_dir",
    "_ensure_dir_with_permissions",
    "_ensure_parent_dir",
    "_extract_import_candidates",
    "_find_image_by_name",
    "_find_project_dataset",
    "_generate_orphan_dataset_name",
    "_get_env_bool",
    "_get_env_int",
    "_get_failed_import_retention_seconds",
    "_get_id",
    "_get_import_lock",
    "_get_job_service_credentials",
    "_get_jobs_root",
    "_get_or_create_dataset",
    "_get_owner_id",
    "_get_owner_username",
    "_get_session_key",
    "_get_text",
    "_get_upload_root",
    "_has_import_candidates_in_output",
    "_has_pending_uploads",
    "_has_read_write_permissions",
    "_import_file",
    "_import_job_entry",
    "_initialize_directories",
    "_is_owned_by_user",
    "_iter_accessible_projects",
    "_job_path",
    "_link_dataset_to_project",
    "_load_job",
    "_mark_failed_job_for_deferred_cleanup",
    "_normalize_job_batch_size",
    "_normalize_upload_relative_path",
    "_normalize_sem_edx_associations",
    "_normalize_sem_edx_settings",
    "_open_service_connection",
    "_open_session_connection",
    "_parse_cli_id",
    "_planned_import_units_for_request",
    "_prepare_job_import_datasets",
    "_prepare_uploaded_job_for_request_path_import",
    "_process_import_job",
    "_reconnect_session",
    "_refresh_job_status",
    "_resolve_root_relative_path",
    "_resolve_job_batch_size",
    "_resolve_jobs_root",
    "_resolve_omero_host_port",
    "_resolve_staged_target_path",
    "_resolve_upload_root",
    "_replace_staged_upload_file",
    "_reset_staged_upload_file",
    "_robust_update_job",
    "_run_compatibility_check",
    "_run_omero_cli",
    "_safe_job_id",
    "_safe_relative_path",
    "_save_job",
    "_staged_upload_size",
    "_native_zarr_import_enabled",
    "_special_methods_enabled",
    "_should_auto_skip_import",
    "_should_start_compatibility_check",
    "_should_start_import_plan_build",
    "_start_compatibility_check_thread",
    "_start_import_thread",
    "_update_job",
    "_validate_session",
    "_validate_staged_target_path",
    "_verify_import",
    "as_completed",
    "current_username",
    "errors",
    "json",
    "json_error",
    "load_json_body",
    "logger",
    "logging",
    "login_required",
    "messages",
    "omero",
    "os",
    "portalocker",
    "random",
    "re",
    "render",
    "reverse",
    "rstring",
    "secrets",
    "settings",
    "stat",
    "string",
    "subprocess",
    "threading",
    "time",
    "uuid",
]

logger = logging.getLogger(__name__)

_IMPORT_LOCKS = {}
_IMPORT_LOCKS_GUARD = threading.Lock()

UPLOAD_CONCURRENCY_ENV = "OMERO_WEB_UPLOAD_CONCURRENCY"
DEFAULT_UPLOAD_CONCURRENCY = 3
UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"
DEFAULT_UPLOAD_BATCH_FILES = 5
SPECIAL_METHODS_DISABLED_ENV = "OMERO_WEB_UPLOAD_DISABLE_SPECIAL_METHODS"
NATIVE_ZARR_IMPORT_ENABLED_ENV = "OMERO_WEB_UPLOAD_ALTERNATIVE_ZARR_IMPORT"
MAX_IMPORT_LOG_LINES = 1000
MAX_UPLOAD_PATH_COMPONENT_BYTES = 255
MAX_UPLOAD_RELATIVE_PATH_BYTES = 2048
MAX_UPLOAD_STAGED_TARGET_BYTES = 4096
INT_SANITIZER = re.compile(r"[^0-9]")
JOB_ID_SANITIZER = re.compile(r"^[0-9a-fA-F]{32}$")
JOB_LOCK_RETRIES = 12
JOB_LOCK_TIMEOUT_SECONDS = 2.0
JOB_LOCK_RETRY_SLEEP_MIN_SECONDS = 0.05
JOB_LOCK_RETRY_SLEEP_MAX_SECONDS = 0.2
ORPHAN_DATASET_PREFIX = "Orphaned_images_base_path_import"
ORPHAN_SUFFIX_LENGTH = 6
ORPHAN_SUFFIX_ALPHANUM = string.ascii_uppercase + string.digits

# --------------------------------------------------------------------------
# JOB SERVICE ACCOUNT (for async background jobs across plugins)
#
# IMPORTANT:
# - NEVER use the end-user OMERO.web session for background jobs.
# - Background jobs MUST login with a service user to avoid logging the user out.
# - The service user is created automatically by the OMERO.server startup script.
# --------------------------------------------------------------------------
JOB_SERVICE_USERNAME_DEFAULT = "job-service"

# Prefer shared names across ALL plugins/containers.
# Keep backward-compat: also accept the old OMERO_WEB_* names.
JOB_SERVICE_USER_ENV = "OMERO_JOB_SERVICE_USERNAME"
JOB_SERVICE_USER_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_USERNAME"

JOB_SERVICE_AUTH_ENV = "OMERO_JOB_SERVICE_PASS"
JOB_SERVICE_AUTH_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_PASS"

JOB_SERVICE_GROUP_ENV = "OMERO_JOB_SERVICE_GROUP"
JOB_SERVICE_GROUP_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_GROUP"

# Allow forcing secure/insecure Ice connection from environment.
# Defaults to True (ssl) if unset.
JOB_SERVICE_SECURE_ENV = "OMERO_JOB_SERVICE_SECURE"
JOB_SERVICE_SECURE_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_SECURE"

# Namespace used for SEM-EDX spectra TXT attachments (FileAnnotation.ns)
SEM_EDX_FILEANNOTATION_NS = "sem_edx.spectra"

# --------------------------------------------------------------------------
# AUTO-SKIP: OS / application junk-file detection
#
# Only genuine operating-system artefacts, thumbnail caches, and filesystem
# debris are skipped.  Everything else -- including all XML variants -- is
# forwarded to OMERO and Bio-Formats so the server decides what it can import.
# --------------------------------------------------------------------------
_ALWAYS_SKIP_FILENAMES = frozenset(
    {
        # Windows
        "thumbs.db",  # thumbnail cache
        "desktop.ini",  # folder display settings
        "ehthumbs.db",  # Explorer thumbnail cache (legacy)
        "ehthumbs_vista.db",  # Explorer thumbnail cache (Vista)
        "$recycle.bin",  # recycle-bin sentinel
        "ntuser.dat",  # user profile registry hive
        "ntuser.dat.log",  # user profile registry log
        "ntuser.ini",  # user profile settings
        "iconcache.db",  # icon cache
        # macOS
        ".ds_store",  # Finder folder metadata
        ".apdisk",  # Apple disk image metadata
        ".volumeicon.icns",  # custom volume icon
        ".fseventsd",  # filesystem-events daemon
        ".spotlight-v100",  # Spotlight index
        ".temporaryitems",  # temporary items folder
        ".trashes",  # per-volume trash
        # Linux
        ".directory",  # KDE/Dolphin folder settings
        ".trash-1000",  # common user-trash sentinel
        # Cross-platform applications
        ".picasa.ini",  # Google Picasa metadata
        ".picasaoriginals",  # Google Picasa originals folder
        ".bridgecache",  # Adobe Bridge cache
        ".bridgecachet",  # Adobe Bridge cache thumbnail
        ".bridgesort",  # Adobe Bridge sort order
        ".adobe",  # Adobe application data
    }
)

# Directories whose *contents* should never be imported.
# If any path component matches (case-insensitive) the file is skipped.
_ALWAYS_SKIP_DIRS = frozenset(
    {
        "lost+found",  # Linux filesystem recovery directory
        "$recycle.bin",  # Windows recycle bin
        "system volume information",  # Windows system folder
        ".trashes",  # macOS per-volume trash
        ".spotlight-v100",  # macOS Spotlight index
        ".fseventsd",  # macOS filesystem events
        ".temporaryitems",  # macOS temporary items
    }
)
SEM_EDX_SETTINGS_DEFAULTS = {
    "create_tables": True,
    "create_figures_attachments": True,
    "create_figures_images": True,
}

# Cache for directory paths (initialized once per application lifecycle)
_UPLOAD_ROOT_CACHE = None
_JOBS_ROOT_CACHE = None
_DIRS_INITIALIZED = False


# --------------------------------------------------------------------------
# PATHS + JOB STORAGE
# --------------------------------------------------------------------------


def _resolve_upload_root() -> Path:
    return resolve_upload_root()


def _resolve_jobs_root() -> Path:
    return resolve_jobs_root()


def _ensure_parent_dir(path: Path) -> bool:
    parent = path.parent
    if parent.exists():
        return True
    try:
        parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        logger.info("Created parent directory: %s with permissions 0o755", parent)
        return True
    except OSError as exc:
        logger.error("Unable to create parent directory %s: %s", parent, exc)
        return False


def _initialize_directories():
    """
    Initialize upload directories once per application lifecycle.

    This function:
    - Ensures parent directories exist with 0o755 (accessible for traversal)
    - Creates target directories with 0o700 (secure)
    - Only runs once, subsequent calls return immediately

    Called automatically by _get_upload_root() and _get_jobs_root()
    """
    global _DIRS_INITIALIZED

    if _DIRS_INITIALIZED:
        return  # Already initialized, skip

    upload_root = _resolve_upload_root()
    jobs_root = _resolve_jobs_root()

    if not _ensure_parent_dir(upload_root) or not _ensure_parent_dir(jobs_root):
        return

    # Create upload directory with 0o700
    _ensure_dir_with_permissions(upload_root, 0o700)

    # Create jobs directory with 0o700
    _ensure_dir_with_permissions(jobs_root, 0o700)

    # Mark as initialized so we don't check again
    _DIRS_INITIALIZED = True
    logger.info("Upload directories initialized successfully")


def _get_upload_root() -> Path:
    """
    Get the upload root directory.

    Uses cached path after first initialization to avoid repeated filesystem checks.
    """
    global _UPLOAD_ROOT_CACHE

    # Use cached path if available
    if _UPLOAD_ROOT_CACHE is None:
        _initialize_directories()
        _UPLOAD_ROOT_CACHE = _resolve_upload_root()

    return _UPLOAD_ROOT_CACHE


def _get_jobs_root() -> Path:
    """
    Get the jobs directory.

    Uses cached path after first initialization to avoid repeated filesystem checks.
    """
    global _JOBS_ROOT_CACHE

    # Use cached path if available
    if _JOBS_ROOT_CACHE is None:
        _initialize_directories()
        _JOBS_ROOT_CACHE = _resolve_jobs_root()

    return _JOBS_ROOT_CACHE


def _ensure_dir(path: Path) -> bool:
    """
    Ensure directory exists. Used for subdirectories within upload/jobs roots.
    Does NOT set permissions (uses defaults).
    """
    try:
        managed_path = _resolve_managed_directory_path(path)
        managed_path.mkdir(parents=True, exist_ok=True)
        return True
    except (OSError, ValueError) as exc:
        logger.warning(
            "Unable to create directory %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(exc),
        )
        return False


def _ensure_dir_with_permissions(path: Path, mode: int) -> bool:
    """
    Ensure directory exists with strict permissions.

    - Creates target directory with specified mode if it doesn't exist
    - If directory exists, verifies and fixes permissions if necessary
    - NEVER deletes any files or directories
    - Does NOT create parent directories (caller's responsibility)

    Args:
        path: Directory path to ensure
        mode: Octal permissions for the target directory (e.g., 0o700 for rwx------)

    Returns:
        True if directory exists/created successfully, False otherwise
    """
    try:
        if not path.exists():
            # Create target directory with specified secure permissions
            # Parent directory must already exist
            try:
                path.mkdir(mode=mode, exist_ok=True)
                logger.info(
                    "Created directory: %s with permissions %s",
                    sanitize_log_value(path),
                    oct(mode),
                )
            except OSError as target_exc:
                logger.error(
                    "Unable to create target directory %s: %s",
                    sanitize_log_value(path),
                    sanitize_log_value(target_exc),
                )
                return False

            return True
        else:
            # Directory exists - check and fix permissions if necessary
            # NEVER delete any files
            try:
                current_perms = stat.S_IMODE(path.stat().st_mode)
                if current_perms != mode:
                    path.chmod(mode)
                    logger.warning(
                        "Fixed permissions for existing directory: %s (was %s, now %s)",
                        sanitize_log_value(path),
                        oct(current_perms),
                        oct(mode),
                    )
            except OSError as perm_exc:
                logger.warning(
                    "Could not verify/fix permissions for %s: %s",
                    sanitize_log_value(path),
                    sanitize_log_value(perm_exc),
                )
            return True
    except OSError as exc:
        logger.error(
            "Unable to create/verify directory %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(exc),
        )
        return False


def _job_path(job_id: str) -> Path:
    return _resolve_managed_child_parts(
        _get_jobs_root(),
        (f"{_validated_job_id(job_id)}.json",),
    )


def _get_env_int(env_key: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.environ.get(env_key, "")
    if raw:
        raw = INT_SANITIZER.sub("", str(raw))
    try:
        value = int(raw) if raw else default
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _get_env_bool(env_key: str, default: bool = False) -> bool:
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _get_import_timeout_seconds() -> int:
    return _get_env_int(
        IMPORT_TIMEOUT_SECONDS_ENV,
        IMPORT_TIMEOUT_SECONDS_DEFAULT,
        60,
        24 * 60 * 60,
    )


def _special_methods_enabled() -> bool:
    return not _get_env_bool(SPECIAL_METHODS_DISABLED_ENV)


def _native_zarr_import_enabled() -> bool:
    return get_bool_env(NATIVE_ZARR_IMPORT_ENABLED_ENV, env_file=ENV_FILE_OMEROWEB)


def _normalize_job_batch_size(value, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(10, normalized))


def _normalize_sem_edx_settings(raw_settings):
    if not isinstance(raw_settings, dict):
        return dict(SEM_EDX_SETTINGS_DEFAULTS)

    normalized = dict(SEM_EDX_SETTINGS_DEFAULTS)
    for key in normalized:
        if key in raw_settings:
            normalized[key] = bool(raw_settings[key])
    return normalized


def _resolve_job_batch_size(job_dict) -> int:
    default_batch_size = _get_env_int(
        UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10
    )
    return _normalize_job_batch_size(job_dict.get("job_batch_size"), default_batch_size)


def _has_pending_uploads(job_dict) -> bool:
    return any(entry.get("status") == "pending" for entry in job_dict.get("files", []))


def _compatibility_pending_entries(job_dict):
    if not job_dict.get("compatibility_enabled", True):
        return []
    return [
        entry
        for entry in job_dict.get("files", [])
        if (
            entry.get("status") == "uploaded"
            and not entry.get("compatibility")
            and not entry.get("compatibility_skip")
        )
    ]


def _should_start_compatibility_check(job_dict) -> bool:
    if not job_dict or job_dict.get("compatibility_thread_active"):
        return False
    if job_dict.get("compatibility_confirmed"):
        return False
    if _has_pending_uploads(job_dict):
        return False
    pending_entries = _compatibility_pending_entries(job_dict)
    if not pending_entries:
        return False
    return True


def _should_start_import_plan_build(job_dict) -> bool:
    if not job_dict or job_dict.get("compatibility_enabled", True):
        return False
    if job_dict.get("compatibility_thread_active"):
        return False
    if job_dict.get("status") in ("done", "error", "importing"):
        return False
    if _has_pending_uploads(job_dict):
        return False
    if _planned_import_units_for_request(job_dict):
        return False
    return any(
        isinstance(entry, dict)
        and entry.get("status") == "uploaded"
        and not entry.get("import_skip")
        for entry in (job_dict.get("files") or [])
    )


def _refresh_job_status(job_dict):
    if _has_pending_uploads(job_dict):
        job_dict["status"] = "uploading"
        return job_dict

    if job_dict.get("compatibility_thread_active"):
        job_dict["status"] = "checking"
        return job_dict

    # If nothing requires compatibility (all files skipped or already decided),
    # do NOT get stuck in "checking" once uploads are complete.
    pending_entries = _compatibility_pending_entries(job_dict)
    if not pending_entries and job_dict.get("compatibility_status") not in (
        "compatible",
        "incompatible",
        "error",
    ):
        job_dict["compatibility_status"] = "compatible"

    compatibility_status = job_dict.get("compatibility_status")
    if compatibility_status == "incompatible":
        job_dict["status"] = "awaiting_confirmation"
    elif compatibility_status == "error":
        # Compatibility check errors (CLI crash, timeout, etc.) should NOT block the
        # import.  The actual import will surface real errors.  Blocking here caused
        # the Import plugin to freeze when the frontend had compatibility checking
        # disabled (no-one would ever send the confirmation request).
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


def _load_job(job_id: str):
    if not _safe_job_id(job_id):
        logger.warning(
            "Upload job id rejected as invalid: %s",
            sanitize_log_value(job_id),
        )
        return None
    path = _job_path(job_id)
    lock_path = _job_lock_path(job_id)
    if not path.exists():
        return None
    last_lock_error = None
    for attempt in range(JOB_LOCK_RETRIES):
        if attempt:
            time.sleep(
                random.uniform(  # nosec B311
                    JOB_LOCK_RETRY_SLEEP_MIN_SECONDS, JOB_LOCK_RETRY_SLEEP_MAX_SECONDS
                )
            )
        try:
            with portalocker.Lock(lock_path, "a+", timeout=JOB_LOCK_TIMEOUT_SECONDS):
                if not path.exists():
                    return None
                return _read_job_file(job_id)
        except json.JSONDecodeError as exc:
            logger.error(
                "Job file %s is corrupt: %s",
                sanitize_log_value(path),
                sanitize_log_value(exc),
            )
            return None
        except (portalocker.exceptions.LockException, OSError) as exc:
            last_lock_error = exc
            logger.debug(
                "Unable to lock job file %s for read (attempt %s/%s): %s",
                sanitize_log_value(path),
                attempt + 1,
                JOB_LOCK_RETRIES,
                sanitize_log_value(exc),
            )
    if last_lock_error is None:
        return None
    try:
        return _read_job_file(job_id)
    except json.JSONDecodeError as exc:
        logger.error(
            "Job file %s is corrupt after lock contention: %s",
            sanitize_log_value(path),
            sanitize_log_value(exc),
        )
    except OSError as exc:
        logger.warning(
            "Unable to read job file %s after lock contention: %s (last lock error: %s)",
            sanitize_log_value(path),
            sanitize_log_value(exc),
            sanitize_log_value(last_lock_error),
        )
    return None


def _save_job(
    job_dict, retries: int = JOB_LOCK_RETRIES, timeout: float = JOB_LOCK_TIMEOUT_SECONDS
):
    job_id = job_dict.get("job_id")
    if not _safe_job_id(job_id):
        logger.warning(
            "Refusing to save upload job with invalid id: %s",
            sanitize_log_value(job_id),
        )
        return False
    path = _job_path(job_id)
    lock_path = _job_lock_path(job_id)
    job_dict["updated"] = time.time()
    for attempt in range(retries):
        if attempt:
            time.sleep(
                random.uniform(  # nosec B311
                    JOB_LOCK_RETRY_SLEEP_MIN_SECONDS, JOB_LOCK_RETRY_SLEEP_MAX_SECONDS
                )
            )
        try:
            with portalocker.Lock(lock_path, "a+", timeout=timeout):
                _write_job_file(job_id, job_dict)
            return True
        except (portalocker.exceptions.LockException, OSError) as exc:
            logger.warning(
                "Unable to lock job file %s for writing (attempt %s/%s): %s",
                sanitize_log_value(path),
                attempt + 1,
                retries,
                sanitize_log_value(exc),
            )
    logger.error(
        "Failed to lock job file %s for writing after %s attempts.",
        sanitize_log_value(path),
        retries,
    )
    return False


def _robust_update_job(
    job_id: str,
    update_fn,
    retries: int = JOB_LOCK_RETRIES,
    timeout: float = JOB_LOCK_TIMEOUT_SECONDS,
):
    if not _safe_job_id(job_id):
        logger.warning(
            "Refusing to update upload job with invalid id: %s",
            sanitize_log_value(job_id),
        )
        return None
    path = _job_path(job_id)
    lock_path = _job_lock_path(job_id)
    for attempt in range(retries):
        if attempt:
            time.sleep(
                random.uniform(  # nosec B311
                    JOB_LOCK_RETRY_SLEEP_MIN_SECONDS, JOB_LOCK_RETRY_SLEEP_MAX_SECONDS
                )
            )
        try:
            with portalocker.Lock(lock_path, "a+", timeout=timeout):
                if not path.exists():
                    logger.warning(
                        "Job file %s not found for update.", sanitize_log_value(path)
                    )
                    return None
                job_dict = _read_job_file(job_id)
                job_dict = update_fn(job_dict)
                _write_job_file(job_id, job_dict)
            return job_dict
        except json.JSONDecodeError as exc:
            logger.error(
                "Job file %s is corrupt: %s",
                sanitize_log_value(path),
                sanitize_log_value(exc),
            )
            return None
        except (portalocker.exceptions.LockException, OSError) as exc:
            logger.warning(
                "Unable to lock job file %s for update (attempt %s/%s): %s",
                sanitize_log_value(path),
                attempt + 1,
                retries,
                sanitize_log_value(exc),
            )
    logger.error(
        "Failed to lock job file %s for update after %s attempts.",
        sanitize_log_value(path),
        retries,
    )
    return None


def _safe_relative_path(raw_name: str):
    if not raw_name or not isinstance(raw_name, str):
        return None
    raw = raw_name.replace("\\", "/")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        return None
    parts = []
    for part in candidate.parts:
        if part in ("", ".", ".."):
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _validate_relative_path_lengths(rel_path: str):
    if len(os.fsencode(rel_path)) > MAX_UPLOAD_RELATIVE_PATH_BYTES:
        return errors.file_path_too_long(rel_path, MAX_UPLOAD_RELATIVE_PATH_BYTES)
    for part in PurePosixPath(rel_path).parts:
        if len(os.fsencode(part)) > MAX_UPLOAD_PATH_COMPONENT_BYTES:
            return errors.filename_too_long(part, MAX_UPLOAD_PATH_COMPONENT_BYTES)
    return None


def _normalize_upload_relative_path(raw_name: str):
    rel_path = _safe_relative_path(raw_name)
    if rel_path is None:
        return None, errors.invalid_filename(raw_name)
    length_error = _validate_relative_path_lengths(rel_path)
    if length_error:
        return None, length_error
    return rel_path, None


def _resolve_root_relative_path(
    root: Path, relative_path: str, *, max_bytes: int = None
):
    try:
        return _resolve_managed_child_path(
            root, relative_path, max_bytes=max_bytes
        ), None
    except OSError:
        return None, errors.invalid_filename(relative_path)
    except ValueError as exc:
        return None, _managed_path_error_message(exc, relative_path)


def _resolve_staged_target_path(upload_root: Path, staged_path: str):
    return _resolve_root_relative_path(
        upload_root,
        staged_path,
        max_bytes=MAX_UPLOAD_STAGED_TARGET_BYTES,
    )


def _validate_staged_target_path(upload_root: Path, staged_path: str):
    _, error = _resolve_staged_target_path(upload_root, staged_path)
    return error


def _append_upload_chunks_to_staged_path(upload_root: Path, staged_path: str, upload):
    normalized_path, normalize_error = _normalize_upload_relative_path(staged_path)
    if normalize_error:
        return None, None, normalize_error

    bytes_written = 0
    try:
        relative_parts = PurePosixPath(normalized_path).parts
        parent_path, file_name, root_real_path, display_path = _managed_parent_directory_path(
            Path(upload_root),
            relative_parts,
            max_bytes=MAX_UPLOAD_STAGED_TARGET_BYTES,
            create_parents=True,
        )
        with os.fdopen(
            _open_managed_upload_file(
                parent_path,
                root_real_path,
                file_name,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                display_path,
            ),
            "ab",
        ) as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
                bytes_written += len(chunk)
        file_path = _managed_child_path(
            parent_path,
            root_real_path,
            file_name,
            display_path,
        )
        stat_result = _managed_path_lstat(file_path, display_path)
        saved_size = stat_result.st_size if stat_result is not None else 0
    except ValueError as exc:
        return None, None, _managed_path_error_message(exc, normalized_path)
    except OSError as exc:
        return None, None, exc
    return bytes_written, saved_size, None


def _reset_staged_upload_file(upload_root: Path, staged_path: str):
    normalized_path, normalize_error = _normalize_upload_relative_path(staged_path)
    if normalize_error:
        return normalize_error

    try:
        relative_parts = PurePosixPath(normalized_path).parts
        parent_path, file_name, root_real_path, display_path = _managed_parent_directory_path(
            Path(upload_root),
            relative_parts,
            max_bytes=MAX_UPLOAD_STAGED_TARGET_BYTES,
            create_parents=True,
        )
        file_path = _managed_child_path(
            parent_path,
            root_real_path,
            file_name,
            display_path,
        )
        stat_result = _managed_path_lstat(file_path, display_path)
        if stat_result is not None:
            try:
                os.unlink(file_path)
            except FileNotFoundError:
                # Another request may have already removed the staged leaf.
                pass
    except ValueError as exc:
        return _managed_path_error_message(exc, normalized_path)
    except OSError as exc:
        return exc
    return None


def _staged_upload_size(upload_root: Path, staged_path: str):
    normalized_path, normalize_error = _normalize_upload_relative_path(staged_path)
    if normalize_error:
        return None, normalize_error

    try:
        relative_parts = PurePosixPath(normalized_path).parts
        parent_path, file_name, root_real_path, display_path = _managed_parent_directory_path(
            Path(upload_root),
            relative_parts,
            max_bytes=MAX_UPLOAD_STAGED_TARGET_BYTES,
            create_parents=True,
        )
        file_path = _managed_child_path(
            parent_path,
            root_real_path,
            file_name,
            display_path,
        )
        stat_result = _managed_path_lstat(file_path, display_path)
        return (stat_result.st_size if stat_result is not None else 0), None
    except ValueError as exc:
        return None, _managed_path_error_message(exc, normalized_path)
    except OSError as exc:
        return None, exc


def _replace_staged_upload_file(upload_root: Path, staged_path: str, upload):
    normalized_path, normalize_error = _normalize_upload_relative_path(staged_path)
    if normalize_error:
        return None, normalize_error

    try:
        relative_parts = PurePosixPath(normalized_path).parts
        parent_path, file_name, root_real_path, display_path = _managed_parent_directory_path(
            Path(upload_root),
            relative_parts,
            max_bytes=MAX_UPLOAD_STAGED_TARGET_BYTES,
            create_parents=True,
        )
        with os.fdopen(
            _open_managed_upload_file(
                parent_path,
                root_real_path,
                file_name,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                display_path,
            ),
            "wb",
        ) as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
    except ValueError as exc:
        return None, _managed_path_error_message(exc, normalized_path)
    except OSError as exc:
        return None, exc
    size, size_error = _staged_upload_size(upload_root, normalized_path)
    if size_error is not None:
        return None, size_error
    return size, None


def _build_staged_relative_path(relative_path: str) -> str:
    return PurePosixPath("_staged", relative_path).as_posix()


def _should_auto_skip_import(relative_path: str) -> bool:
    """
    Detect files that should never be imported into OMERO.

    Only OS-level junk files (thumbnail caches, desktop metadata, recycle bins,
    lost+found, etc.) are skipped.  Every other file -- including all XML
    variants -- is forwarded to OMERO so the server and Bio-Formats decide
    whether it can be imported.

    Returns True when the file should be marked ``import_skip=True``.
    """
    if not relative_path:
        return False

    parts = PurePosixPath(relative_path)
    filename = parts.name
    filename_lower = filename.lower()

    # 1. Known OS / application junk files (exact filename match)
    if filename_lower in _ALWAYS_SKIP_FILENAMES:
        return True

    # 2. macOS resource-fork files (._*)
    if filename.startswith("._"):
        return True

    # 3. Files inside OS junk directories (e.g. lost+found, $RECYCLE.BIN)
    for part in parts.parent.parts:
        if part.lower() in _ALWAYS_SKIP_DIRS:
            return True

    return False


def _normalize_sem_edx_associations(raw_associations, normalized_entries):
    if not isinstance(raw_associations, dict):
        return {}

    # ACCEPT BOTH relative_path AND staged_path
    available_paths = {}

    for entry in normalized_entries:
        rel = entry.get("relative_path")
        if rel:
            available_paths[rel] = entry

        staged = entry.get("staged_path")
        if staged:
            available_paths[staged] = entry

    normalized = {}

    for image_path, txt_paths in raw_associations.items():
        image_rel = _safe_relative_path(image_path or "")
        if not image_rel:
            continue
        if image_rel.lower().endswith(".txt"):
            continue
        if image_rel not in available_paths:
            continue
        if not isinstance(txt_paths, list):
            continue

        cleaned_txt = []

        for txt_path in txt_paths:
            txt_rel = _safe_relative_path(txt_path or "")
            if not txt_rel:
                continue
            if not txt_rel.lower().endswith(".txt"):
                continue
            if txt_rel not in available_paths:
                continue
            if txt_rel not in cleaned_txt:
                cleaned_txt.append(txt_rel)

        if cleaned_txt:
            normalized[image_rel] = cleaned_txt

    return normalized


def _build_sem_edx_associations_from_entries(entries):
    """Server-side fallback to derive SEM-EDX TXT->image associations.

    The UI normally submits sem_edx_associations, but if that payload is missing/empty
    (e.g. browser/localStorage issues, UI state bugs), we can deterministically derive
    associations from the uploaded file list:

    - Group by directory (based on relative_path)
    - Choose ONE non-.txt file per directory as the target image (lexicographically)
    - Attach ALL .txt files in that directory to that image

    This keeps behaviour predictable and ensures TXT attachment is at least attempted.
    """

    if not isinstance(entries, list) or not entries:
        return {}

    grouped = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("relative_path")
        if not rel or not isinstance(rel, str):
            continue
        rel_norm = _safe_relative_path(rel)
        if not rel_norm:
            continue
        parent = str(PurePosixPath(rel_norm).parent)
        if parent == ".":
            parent = ""
        bucket = grouped.setdefault(parent, {"images": [], "txt": []})
        if rel_norm.lower().endswith(".txt"):
            bucket["txt"].append(rel_norm)
        else:
            bucket["images"].append(rel_norm)

    associations = {}
    for bucket in grouped.values():
        if not bucket["images"] or not bucket["txt"]:
            continue
        image_rel = sorted(bucket["images"])[0]
        txt_rels = sorted(set(bucket["txt"]))
        if txt_rels:
            associations[image_rel] = txt_rels

    return associations


def _get_text(value_obj):
    if value_obj is None:
        return ""
    try:
        if hasattr(value_obj, "getValue"):
            value = value_obj.getValue()
            if value is not None:
                return value
        saw_value_attr = False
        for attr_name in ("val", "_val"):
            if hasattr(value_obj, attr_name):
                saw_value_attr = True
                value = getattr(value_obj, attr_name)
                if value is not None:
                    return value
        if saw_value_attr:
            return ""
        return str(value_obj)
    except Exception:
        return str(value_obj)


def _external_info_text(external_info, attribute_name: str, getter_name: str) -> str:
    if external_info is None:
        return ""

    value = _get_text(getattr(external_info, attribute_name, None)).strip()
    if value:
        return value

    getter = getattr(external_info, getter_name, None)
    if callable(getter):
        try:
            return _get_text(getter()).strip()
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)
    return value


def _query_image_external_info(conn, image_id: int) -> tuple[str, str]:
    if conn is None:
        return "", ""

    try:
        qs = conn.getQueryService()
        params = omero.sys.ParametersI()
        params.addId(int(image_id))
        rows = qs.projection(
            "SELECT i.details.externalInfo.lsid, i.details.externalInfo.entityType "
            "FROM Image i WHERE i.id = :id",
            params,
            conn.SERVICE_OPTS,
        )
    except Exception:
        return "", ""

    if not rows:
        return "", ""

    row = rows[0]
    lsid = _get_text(row[0] if len(row) > 0 else None).strip()
    entity_type = _get_text(row[1] if len(row) > 1 else None).strip()
    return lsid, entity_type


@lru_cache(maxsize=None)
def _units_length_for_name(unit_name: str):
    from omero.model.enums import UnitsLength

    raw_name = str(unit_name or "").strip()
    if not raw_name:
        return UnitsLength.PIXEL

    alias = _units_length_symbol_aliases().get(raw_name.replace("μ", "µ"))
    if alias is not None:
        return alias

    normalized_name = _normalize_units_length_name(raw_name)
    return _units_length_by_normalized_name().get(normalized_name, UnitsLength.PIXEL)


def _normalize_units_length_name(unit_name: str) -> str:
    normalized_name = str(unit_name or "").strip().replace("μ", "µ").lower()
    normalized_name = normalized_name.replace("-", "").replace("_", "").replace(" ", "")
    normalized_name = normalized_name.replace("metres", "meters").replace(
        "metre", "meter"
    )
    if normalized_name.endswith("s"):
        normalized_name = normalized_name[:-1]
    return normalized_name


@lru_cache(maxsize=1)
def _units_length_by_normalized_name():
    from omero.model.enums import UnitsLength

    return {
        _normalize_units_length_name(unit.name): unit
        for unit in sorted(
            UnitsLength._enumerators.values(),
            key=lambda enum_value: getattr(enum_value, "name", str(enum_value)),
        )
    }


@lru_cache(maxsize=1)
def _units_length_symbol_aliases():
    units = _units_length_by_normalized_name()
    alias_map = {}

    si_prefix_symbols = {
        "yotta": "Y",
        "zetta": "Z",
        "exa": "E",
        "peta": "P",
        "tera": "T",
        "giga": "G",
        "mega": "M",
        "kilo": "k",
        "hecto": "h",
        "deca": "da",
        "": "",
        "deci": "d",
        "centi": "c",
        "milli": "m",
        "micro": "u",
        "nano": "n",
        "pico": "p",
        "femto": "f",
        "atto": "a",
        "zepto": "z",
        "yocto": "y",
    }
    for prefix_name, symbol in si_prefix_symbols.items():
        unit = units.get(f"{prefix_name}meter")
        if unit is not None:
            alias_map[f"{symbol}m" if symbol else "m"] = unit
    if "um" in alias_map:
        alias_map["µm"] = alias_map["um"]
        alias_map["μm"] = alias_map["um"]

    fixed_symbol_aliases = {
        "angstrom": ("Å", "Å"),
        "astronomicalunit": ("au",),
        "lightyear": ("ly",),
        "parsec": ("pc",),
        "thou": ("thou",),
        "inch": ("in",),
        "foot": ("ft",),
        "yard": ("yd",),
        "mile": ("mi",),
        "point": ("pt",),
        "pixel": ("px",),
    }
    for unit_name, symbols in fixed_symbol_aliases.items():
        unit = units.get(unit_name)
        if unit is None:
            continue
        for symbol in symbols:
            alias_map[symbol] = unit
    return alias_map


def _native_zarr_length_from_value_unit(value_unit):
    if not isinstance(value_unit, (list, tuple)) or not value_unit:
        return None

    try:
        numeric_value = float(value_unit[0])
    except (TypeError, ValueError):
        return None

    from omero.model import LengthI

    unit_name = ""
    if len(value_unit) > 1 and value_unit[1]:
        unit_name = str(value_unit[1]).strip()
    return LengthI(numeric_value, _units_length_for_name(unit_name))


def _native_zarr_length_signature(length) -> Optional[tuple[float, str]]:
    if length is None:
        return None

    try:
        value = float(length.getValue())
    except Exception:
        raw_value = getattr(length, "val", None)
        if raw_value is None:
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None

    unit_name = ""
    try:
        unit = length.getUnit()
        if unit is not None:
            unit_name = str(getattr(unit, "name", None) or unit).strip().lower()
    except Exception:
        logger.debug("Suppressed exception in cleanup", exc_info=True)
    return round(value, 9), unit_name


def _native_zarr_image_relative_path_from_lsid(
    managed_zarr: Path, lsid: str
) -> Optional[str]:
    root_path = Path(managed_zarr).resolve(strict=False)
    lsid_text = str(lsid or "").strip()
    if not lsid_text:
        raise ValueError("empty externalInfo.lsid")

    lsid_path = Path(lsid_text.split("?", 1)[0]).resolve(strict=False)
    if lsid_path == root_path:
        return None

    relative_path = lsid_path.relative_to(root_path)
    relative_text = relative_path.as_posix().strip()
    return relative_text or None


def _runtime_native_zarr_physical_sizes(
    managed_zarr: Path,
    image_relative_path: Optional[str],
) -> tuple[dict[str, object], Optional[str]]:
    target_path = managed_zarr
    if image_relative_path:
        target_path = managed_zarr / image_relative_path

    inspection = inspect_ome_zarr_image(target_path)
    if not inspection.recognized:
        return (
            {},
            "ome-zarr did not recognize the imported store as a readable OME-Zarr image.",
        )
    if inspection.support_error:
        return {}, inspection.support_error

    normalized_sizes = {}
    for axis_name, raw_value in inspection.physical_sizes.items():
        try:
            length_value = _native_zarr_length_from_value_unit(raw_value)
        except Exception as exc:
            return (
                {},
                f"Failed to normalize native Zarr pixel size for axis {axis_name}: {exc}",
            )
        if length_value is not None:
            normalized_sizes[axis_name] = length_value
    return normalized_sizes, None


def _finalize_imported_zarr_image_metadata(
    username: str,
    host: str,
    port: int,
    image_ids: list[str],
    *,
    managed_zarr: Path,
    group_id: Optional[int] = None,
    group_name: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Reconcile source-derived metadata onto Images created by native Zarr import.

    ``omero-cli-zarr`` creates pure NGFF images through the OMERO API. The
    installed runtime does not persist physical pixel sizes on that path even
    though it parses them from the Zarr metadata. Use the managed-store LSID to
    resolve the imported image back to its source group, parse metadata with the
    installed runtime parser, and save canonical pixel sizes onto OMERO's
    ``Pixels`` object before declaring the import successful.
    """
    if not username:
        return False, [
            "Missing importing username for native Zarr metadata finalization."
        ]

    unique_ids = []
    seen_ids = set()
    for image_id in image_ids:
        text_id = str(image_id).strip()
        if not text_id or text_id in seen_ids:
            continue
        seen_ids.add(text_id)
        unique_ids.append(text_id)
    if not unique_ids:
        return False, [
            "No imported Image IDs were available for native Zarr metadata finalization."
        ]

    admin_conn = None
    conn = None
    errors_found = []
    try:
        admin_conn = _open_admin_connection(host, port)
        if admin_conn is None:
            return False, [
                "Failed to open an admin connection for native Zarr metadata finalization."
            ]
        conn = admin_conn.suConn(username)
        if conn is None:
            return False, [
                "Failed to open the importing user's session for native Zarr metadata finalization."
            ]
        if group_id is not None:
            conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
        elif group_name:
            conn.SERVICE_OPTS.setOmeroGroup(group_name)

        update_service = conn.getUpdateService()
        for image_id in unique_ids:
            try:
                image = conn.getObject("Image", int(image_id))
            except Exception as exc:
                errors_found.append(
                    f"Image:{image_id} lookup failed during metadata finalization: {exc}"
                )
                continue
            if image is None:
                errors_found.append(
                    f"Image:{image_id} could not be loaded during native Zarr metadata finalization."
                )
                continue

            lsid, _entity_type = _query_image_external_info(conn, int(image_id))
            if not lsid:
                errors_found.append(
                    f"Image:{image_id} is missing externalInfo.lsid during native Zarr metadata finalization."
                )
                continue

            try:
                image_relative_path = _native_zarr_image_relative_path_from_lsid(
                    managed_zarr, lsid
                )
            except Exception:
                errors_found.append(
                    f"Image:{image_id} resolved to unexpected externalInfo.lsid {lsid!r}."
                )
                continue

            expected_sizes, metadata_error = _runtime_native_zarr_physical_sizes(
                managed_zarr,
                image_relative_path,
            )
            if metadata_error:
                errors_found.append(
                    f"Image:{image_id} metadata finalization failed: {metadata_error}"
                )
                continue
            if not expected_sizes:
                continue

            try:
                pixels = image.getPrimaryPixels()
            except Exception as exc:
                errors_found.append(
                    f"Image:{image_id} primary Pixels lookup failed during metadata finalization: {exc}"
                )
                continue
            pixels_obj = getattr(pixels, "_obj", None)
            if pixels_obj is None:
                errors_found.append(
                    f"Image:{image_id} primary Pixels object was unavailable during metadata finalization."
                )
                continue

            changed = False
            setter_error = None
            for axis_name, expected_length in expected_sizes.items():
                getter = getattr(pixels, f"getPhysicalSize{axis_name.upper()}", None)
                current_length = getter() if callable(getter) else None
                if _native_zarr_length_signature(
                    current_length
                ) == _native_zarr_length_signature(expected_length):
                    continue
                setter = getattr(
                    pixels_obj, f"setPhysicalSize{axis_name.upper()}", None
                )
                if not callable(setter):
                    setter_error = axis_name.upper()
                    break
                setter(expected_length)
                changed = True
            if setter_error:
                errors_found.append(
                    f"Image:{image_id} Pixels object is missing a physical-size setter for axis {setter_error}."
                )
                continue
            if changed:
                try:
                    update_service.saveAndReturnObject(pixels_obj)
                except Exception as exc:
                    errors_found.append(
                        f"Image:{image_id} physical pixel-size save failed during metadata finalization: {exc}"
                    )
                    continue

            try:
                refreshed_image = conn.getObject("Image", int(image_id))
            except Exception as exc:
                errors_found.append(
                    f"Image:{image_id} reload failed after native Zarr metadata finalization: {exc}"
                )
                continue
            if refreshed_image is None:
                errors_found.append(
                    f"Image:{image_id} could not be reloaded after native Zarr metadata finalization."
                )
                continue
            try:
                refreshed_pixels = refreshed_image.getPrimaryPixels()
            except Exception as exc:
                errors_found.append(
                    f"Image:{image_id} primary Pixels reload failed after native Zarr metadata finalization: {exc}"
                )
                continue
            for axis_name, expected_length in expected_sizes.items():
                getter = getattr(
                    refreshed_pixels, f"getPhysicalSize{axis_name.upper()}", None
                )
                actual_length = getter() if callable(getter) else None
                if _native_zarr_length_signature(
                    actual_length
                ) != _native_zarr_length_signature(expected_length):
                    errors_found.append(
                        f"Image:{image_id} physicalSize{axis_name.upper()} did not persist from native Zarr metadata."
                    )
                    break

        return len(errors_found) == 0, errors_found
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
        if admin_conn:
            try:
                admin_conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)


def _get_id(obj):
    try:
        return obj._obj.id.val
    except Exception as exc:
        logger.debug("Falling back to getId() for object %r: %s", obj, exc)
    try:
        gid = obj.getId()
        return gid.getValue() if hasattr(gid, "getValue") else gid
    except (AttributeError, Exception):
        return None


def _get_owner_id(obj):
    if obj is None:
        return None
    try:
        details = obj.getDetails()
        owner = details.getOwner() if details else None
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception as exc:
        logger.debug("Could not resolve owner via details for object %r: %s", obj, exc)
    try:
        owner = obj.getOwner()
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception as exc:
        logger.debug(
            "Could not resolve owner via getOwner() for object %r: %s", obj, exc
        )
    return None


def _current_user_id(conn):
    try:
        user = conn.getUser()
        if user is not None:
            uid = user.getId()
            return uid.getValue() if hasattr(uid, "getValue") else uid
    except Exception:
        return None
    return None


def _is_owned_by_user(obj, user_id):
    if obj is None or user_id is None:
        return False
    owner_id = _get_owner_id(obj)
    if owner_id is None:
        return False
    try:
        return int(owner_id) == int(user_id)
    except Exception:
        return False


def _get_owner_username(obj):
    if obj is None:
        return ""
    owner = None
    try:
        details = obj.getDetails()
        owner = details.getOwner() if details else None
    except Exception:
        owner = None
    if owner is None:
        try:
            owner = obj.getOwner()
        except Exception:
            owner = None
    if owner is None:
        return ""
    for attr in ("getOmeName", "getName", "getFirstName"):
        try:
            if hasattr(owner, attr):
                value = _get_text(getattr(owner, attr)())
                if value:
                    return value
        except Exception:
            logger.debug("Failed to get owner name via %s", attr)
            continue
    owner_id = _get_id(owner)
    return str(owner_id) if owner_id is not None else ""


def _has_read_write_permissions(obj):
    if obj is None:
        return False
    for attr in ("canEdit", "canWrite"):
        checker = getattr(obj, attr, None)
        if callable(checker):
            try:
                if checker():
                    return True
            except Exception:
                logger.debug("Permission check via %s failed", attr)
                continue
    try:
        details = obj.getDetails()
        permissions = details.getPermissions() if details else None
        if permissions:
            return bool(permissions.isRead() and permissions.isWrite())
    except Exception:
        return False
    return False


def _iter_accessible_projects(conn):
    if conn is None:
        return

    # Save current group context
    current_group = None
    try:
        current_group = conn.SERVICE_OPTS.getOmeroGroup()
    except Exception as exc:
        logger.debug("Failed to read current OMERO group context: %s", exc)

    try:
        # Set group context to -1 to query across all groups
        conn.SERVICE_OPTS.setOmeroGroup("-1")

        # Try to get projects with cross-group querying enabled
        try:
            for proj in conn.getObjects("Project"):
                yield proj
            return
        except Exception as e:
            logger.warning(
                "Failed to query projects across all groups with SERVICE_OPTS: %s", e
            )

        # Fallback: try with opts parameter
        try:
            for proj in conn.getObjects("Project", opts={"group": "-1"}):
                yield proj
            return
        except Exception as e:
            logger.warning("Failed to query projects with opts group=-1: %s", e)

    finally:
        # Restore original group context
        if current_group is not None:
            try:
                conn.SERVICE_OPTS.setOmeroGroup(current_group)
            except Exception as exc:
                logger.warning(
                    "Failed to restore OMERO group context to %s: %s",
                    current_group,
                    exc,
                )

    # Final fallback: try without cross-group querying
    try:
        for proj in conn.getObjects("Project"):
            yield proj
        return
    except Exception as e:
        logger.warning("Failed to query projects in current group: %s", e)

    # Last resort: use listProjects
    try:
        for proj in conn.listProjects():
            yield proj
    except Exception as e:
        logger.warning("Failed to list projects: %s", e)
        return


def _collect_project_payload(conn, user_id):
    owned_projects = []
    collab_projects = []
    try:
        for proj in _iter_accessible_projects(conn):
            pid = _get_id(proj)
            pname = _get_text(proj.getName())
            if pid is None:
                continue
            entry = {"id": str(pid), "name": pname}
            if _is_owned_by_user(proj, user_id):
                owned_projects.append(entry)
            elif _has_read_write_permissions(proj):
                owner_name = _get_owner_username(proj) or "Unknown user"
                collab_projects.append({**entry, "owner": owner_name})
    except Exception as exc:
        logger.exception("Error listing projects: %s", exc)
    return {"owned": owned_projects, "collab": collab_projects}


def _dataset_name_for_path(relative_path: str, orphan_dataset_name: str = None):
    parts = PurePosixPath(relative_path).parts
    if len(parts) <= 1:
        return orphan_dataset_name
    return "\\".join(parts[:-1])


DIRECTORY_PACKAGE_EXTENSIONS = (".zarr",)


def _directory_package_root_for_relative_path(relative_path: str) -> Optional[str]:
    parts = PurePosixPath(relative_path).parts
    if not parts:
        return None

    for index, part in enumerate(parts):
        lower_part = part.lower()
        if any(
            lower_part.endswith(extension) for extension in DIRECTORY_PACKAGE_EXTENSIONS
        ):
            return PurePosixPath(*parts[: index + 1]).as_posix()
    return None


def _dataset_name_for_upload_relative_path(
    relative_path: str, orphan_dataset_name: str = None
):
    package_root = _directory_package_root_for_relative_path(relative_path)
    if package_root:
        return "\\".join(PurePosixPath(package_root).parts)
    return _dataset_name_for_path(relative_path, orphan_dataset_name)


def _logical_unit_is_directory_package_root(entry: dict) -> bool:
    dataset_relative_path = (
        entry.get("dataset_relative_path") or entry.get("relative_path") or ""
    )
    if not dataset_relative_path or entry.get("relative_path") != dataset_relative_path:
        return False

    root_parts = PurePosixPath(dataset_relative_path).parts
    if not root_parts:
        return False

    covered_relative_paths = entry.get("covered_relative_paths") or []
    if len(covered_relative_paths) <= 1:
        return False

    for covered_relative_path in covered_relative_paths:
        covered_parts = PurePosixPath(covered_relative_path).parts
        if covered_parts[: len(root_parts)] == root_parts and len(covered_parts) > len(
            root_parts
        ):
            return True
    return False


def _dataset_name_for_import_entry(entry: dict, orphan_dataset_name: str = None):
    dataset_relative_path = (
        entry.get("dataset_relative_path") or entry.get("relative_path") or ""
    )
    if not dataset_relative_path:
        return orphan_dataset_name
    if _logical_unit_is_directory_package_root(entry):
        return "\\".join(PurePosixPath(dataset_relative_path).parts)
    return _dataset_name_for_path(dataset_relative_path, orphan_dataset_name)


def _generate_orphan_dataset_name():
    suffix = "".join(
        secrets.choice(ORPHAN_SUFFIX_ALPHANUM) for _ in range(ORPHAN_SUFFIX_LENGTH)
    )
    return f"{ORPHAN_DATASET_PREFIX}_{suffix}"


def _find_project_dataset(conn, project_id: int, name: str):
    if not project_id or not name:
        return None
    try:
        project = conn.getObject("Project", int(project_id))
    except Exception:
        project = None
    if project is None:
        return None
    try:
        for dataset in project.listChildren():
            if _get_text(dataset.getName()) == name:
                return _get_id(dataset)
    except Exception as exc:
        logger.warning("Unable to list datasets for project %s: %s", project_id, exc)
    return None


def _link_dataset_to_project(conn, dataset_id: int, project_id: int):
    if not dataset_id or not project_id:
        return False
    try:
        link = ProjectDatasetLinkI()
        link.setParent(ProjectI(int(project_id), False))
        link.setChild(DatasetI(int(dataset_id), False))
        conn.getUpdateService().saveAndReturnObject(link)
        return True
    except Exception as exc:
        logger.warning(
            "Failed to link dataset %s to project %s: %s", dataset_id, project_id, exc
        )
        return False


# --------------------------------------------------------------------------
# OMERO IMPORT HELPERS
# --------------------------------------------------------------------------


def _resolve_omero_host_port(conn):
    host = getattr(conn, "host", None) or getattr(conn, "_host", None)
    port = getattr(conn, "port", None) or getattr(conn, "_port", None)

    if not host:
        host = getattr(settings, "OMERO_HOST", None)
    if not port:
        port = getattr(settings, "OMERO_PORT", None)

    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None

    return host, port


def _get_session_key(conn):
    if callable(getattr(conn, "getSessionId", None)):
        try:
            return conn.getSessionId()
        except Exception:
            return None
    for attr in ("_sessionUuid", "_session"):
        val = getattr(conn, attr, None)
        if val:
            return val
    return None


def _get_or_create_dataset(conn, name: str, dataset_map: dict, project_id: int = None):
    if not name:
        return None
    if name in dataset_map:
        return dataset_map[name]

    if project_id:
        existing_id = _find_project_dataset(conn, project_id, name)
        if existing_id:
            dataset_map[name] = existing_id
            return existing_id

    existing = None
    try:
        existing = next(conn.getObjects("Dataset", attributes={"name": name}), None)
    except Exception:
        existing = None

    if existing is not None:
        dataset_id = _get_id(existing)
        if dataset_id is None and hasattr(existing, "getId"):
            dataset_id = existing.getId().getValue()
        dataset_map[name] = dataset_id
        if project_id and dataset_id:
            _link_dataset_to_project(conn, dataset_id, project_id)
        return dataset_id

    try:
        dataset = DatasetI()
        dataset.setName(rstring(name))
        dataset = conn.getUpdateService().saveAndReturnObject(dataset)
        dataset_id = dataset.getId().getValue()
        if project_id:
            _link_dataset_to_project(conn, dataset_id, project_id)
    except Exception as exc:
        logger.warning("Failed to create dataset %s: %s", name, exc)
        return None

    dataset_map[name] = dataset_id
    return dataset_id


def _plan_job_dataset_targets(job_dict: dict, entries_to_import: list[dict]):
    orphan_dataset_name = job_dict.get("orphan_dataset_name")
    if any(
        _dataset_name_for_import_entry(entry) is None for entry in entries_to_import
    ):
        orphan_dataset_name = orphan_dataset_name or _generate_orphan_dataset_name()

    dataset_names = []
    for entry in entries_to_import:
        dataset_name = _dataset_name_for_import_entry(entry, orphan_dataset_name)
        if dataset_name:
            dataset_names.append(dataset_name)

    return orphan_dataset_name, sorted(set(dataset_names))


def _serialize_import_unit_plan(unit: dict):
    covered_relative_paths = [
        relative_path
        for relative_path in (unit.get("covered_relative_paths") or [])
        if isinstance(relative_path, str) and relative_path
    ]
    relative_path = (unit.get("relative_path") or "").strip()
    dataset_relative_path = (unit.get("dataset_relative_path") or relative_path).strip()
    if not relative_path or not dataset_relative_path or not covered_relative_paths:
        return None

    serialized = {
        "covered_relative_paths": covered_relative_paths,
        "dataset_relative_path": dataset_relative_path,
        "relative_path": relative_path,
    }
    group_header_name = (unit.get("group_header_name") or "").strip()
    if group_header_name:
        serialized["group_header_name"] = group_header_name
    return serialized


def _planned_import_units_for_request(job_dict: dict):
    raw_units = job_dict.get("planned_import_units") or []
    if not isinstance(raw_units, list):
        return []

    active_relative_paths = {
        (entry.get("relative_path") or "").strip()
        for entry in (job_dict.get("files") or [])
        if isinstance(entry, dict)
        and not entry.get("import_skip")
        and (entry.get("relative_path") or "").strip()
    }
    if not active_relative_paths:
        return []

    planned_units = []
    seen_units = set()
    for raw_unit in raw_units:
        if not isinstance(raw_unit, dict):
            continue
        serialized = _serialize_import_unit_plan(raw_unit)
        if serialized is None:
            continue
        covered_relative_paths = serialized["covered_relative_paths"]
        if any(
            relative_path not in active_relative_paths
            for relative_path in covered_relative_paths
        ):
            continue
        unit_key = (
            serialized["relative_path"],
            serialized["dataset_relative_path"],
            tuple(covered_relative_paths),
            serialized.get("group_header_name", ""),
        )
        if unit_key in seen_units:
            continue
        seen_units.add(unit_key)
        planned_units.append(serialized)

    return planned_units


def _plan_request_job_dataset_targets(job_dict: dict):
    planned_units = _planned_import_units_for_request(job_dict)
    if planned_units:
        orphan_dataset_name = job_dict.get("orphan_dataset_name")
        if any(_dataset_name_for_import_entry(unit) is None for unit in planned_units):
            orphan_dataset_name = orphan_dataset_name or _generate_orphan_dataset_name()

        dataset_names = []
        for unit in planned_units:
            dataset_name = _dataset_name_for_import_entry(unit, orphan_dataset_name)
            if dataset_name:
                dataset_names.append(dataset_name)

        return orphan_dataset_name, sorted(set(dataset_names))

    orphan_dataset_name = job_dict.get("orphan_dataset_name")
    entries = job_dict.get("files") or []
    requires_orphan_dataset = False

    for entry in entries:
        if not isinstance(entry, dict) or entry.get("import_skip"):
            continue
        relative_path = (entry.get("relative_path") or "").strip()
        if not relative_path:
            continue
        if (
            _dataset_name_for_upload_relative_path(relative_path, orphan_dataset_name)
            is None
        ):
            requires_orphan_dataset = True
            break

    if requires_orphan_dataset and not orphan_dataset_name:
        orphan_dataset_name = _generate_orphan_dataset_name()

    dataset_names = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("import_skip"):
            continue
        relative_path = (entry.get("relative_path") or "").strip()
        if not relative_path:
            continue
        dataset_name = _dataset_name_for_upload_relative_path(
            relative_path, orphan_dataset_name
        )
        if dataset_name:
            dataset_names.append(dataset_name)

    return orphan_dataset_name, sorted(set(dataset_names))


def _prepare_request_job_import_datasets(
    job_id: str, job_dict: dict, conn: Optional[BlitzGateway] = None
):
    generic_error = errors.unable_prepare_import_destination()
    if conn is None:
        return None, generic_error

    orphan_dataset_name, dataset_names = _plan_request_job_dataset_targets(job_dict)
    dataset_map = dict(job_dict.get("dataset_map") or {})
    missing_dataset_names = [name for name in dataset_names if name not in dataset_map]

    job_dict["orphan_dataset_name"] = orphan_dataset_name
    job_dict["dataset_map"] = dataset_map

    if missing_dataset_names:
        try:
            if job_dict.get("group_id") is not None and hasattr(conn, "SERVICE_OPTS"):
                try:
                    conn.SERVICE_OPTS.setOmeroGroup(str(int(job_dict["group_id"])))
                except Exception as exc:
                    logger.warning(
                        "Failed to scope request OMERO connection to group %s for job %s: %s",
                        sanitize_log_value(job_dict.get("group_id")),
                        sanitize_log_value(job_id),
                        sanitize_log_value(exc),
                    )

            for dataset_name in missing_dataset_names:
                dataset_id = _get_or_create_dataset(
                    conn,
                    dataset_name,
                    dataset_map,
                    project_id=job_dict.get("project_id"),
                )
                if dataset_id is None:
                    logger.warning(
                        "Failed to create dataset %s for job %s using the request OMERO connection.",
                        sanitize_log_value(dataset_name),
                        sanitize_log_value(job_id),
                    )
                    return None, generic_error
        except Exception as exc:
            logger.warning(
                "Failed to prepare request-path dataset targets for job %s: %s",
                sanitize_log_value(job_id),
                sanitize_log_value(exc),
            )
            return None, generic_error

    if not _save_job(job_dict):
        return None, errors.unable_update_upload_job_state()

    return job_dict, None


def _prepare_uploaded_job_for_request_path_import(
    job_id: str,
    job_dict: dict,
    conn: Optional[BlitzGateway] = None,
):
    if conn is None or _has_pending_uploads(job_dict):
        return job_dict, None

    if _should_start_compatibility_check(job_dict):
        _start_compatibility_check_thread(job_id)
        logger.info("Upload job %s checking compatibility.", sanitize_log_value(job_id))
        return _load_job(job_id) or job_dict, None

    if _should_start_import_plan_build(job_dict):
        _start_compatibility_check_thread(job_id)
        logger.info(
            "Upload job %s planning import units before request-path dataset preparation.",
            sanitize_log_value(job_id),
        )
        return _load_job(job_id) or job_dict, None

    if job_dict.get("status") not in ("checking", "awaiting_confirmation", "ready"):
        return job_dict, None

    if job_dict.get(
        "compatibility_thread_active"
    ) and not _planned_import_units_for_request(job_dict):
        return job_dict, None

    if (
        job_dict.get("compatibility_enabled", True)
        and job_dict.get("status") in ("checking", "awaiting_confirmation")
        and not _planned_import_units_for_request(job_dict)
    ):
        return job_dict, None

    prepared_job, prep_error = _prepare_request_job_import_datasets(
        job_id, job_dict, conn
    )
    if prep_error:
        return prepared_job or job_dict, prep_error

    return _load_job(job_id) or prepared_job or job_dict, None


def _ensure_job_dataset_targets(
    job_dict: dict, entries_to_import: list[dict], conn: Optional[BlitzGateway] = None
):
    orphan_dataset_name, dataset_names = _plan_job_dataset_targets(
        job_dict, entries_to_import
    )
    dataset_map = dict(job_dict.get("dataset_map") or {})
    missing_dataset_names = [name for name in dataset_names if name not in dataset_map]
    generic_error = errors.unable_prepare_import_destination()

    job_dict["orphan_dataset_name"] = orphan_dataset_name
    job_dict["dataset_map"] = dataset_map

    if not missing_dataset_names:
        return True, None

    if conn is not None:
        try:
            if job_dict.get("group_id") is not None and hasattr(conn, "SERVICE_OPTS"):
                try:
                    conn.SERVICE_OPTS.setOmeroGroup(str(int(job_dict["group_id"])))
                except Exception as exc:
                    logger.warning(
                        "Failed to scope request OMERO connection to group %s for job %s: %s",
                        sanitize_log_value(job_dict.get("group_id")),
                        sanitize_log_value(job_dict.get("job_id")),
                        sanitize_log_value(exc),
                    )

            for dataset_name in missing_dataset_names:
                dataset_id = _get_or_create_dataset(
                    conn,
                    dataset_name,
                    dataset_map,
                    project_id=job_dict.get("project_id"),
                )
                if dataset_id is None:
                    logger.warning(
                        "Failed to create dataset %s for job %s using the request OMERO connection.",
                        sanitize_log_value(dataset_name),
                        sanitize_log_value(job_dict.get("job_id")),
                    )
                    return False, generic_error
            return True, None
        except Exception as exc:
            logger.warning(
                "Failed to prepare dataset targets for job %s using the request OMERO connection: %s",
                sanitize_log_value(job_dict.get("job_id")),
                sanitize_log_value(exc),
            )
            return False, generic_error

    host = job_dict.get("host")
    port = job_dict.get("port")
    username = (job_dict.get("username") or "").strip()
    if not host or not port or not username:
        logger.warning(
            "Missing OMERO connection details for dataset preparation on job %s.",
            sanitize_log_value(job_dict.get("job_id")),
        )
        return False, generic_error

    service_conn = _open_service_connection(
        host, port, group_id=job_dict.get("group_id")
    )
    if not service_conn:
        logger.warning(
            "Unable to open OMERO service connection for dataset preparation on job %s.",
            sanitize_log_value(job_dict.get("job_id")),
        )
        return False, generic_error

    user_conn = None
    try:
        user_conn = _open_user_owned_background_connection(
            username,
            group_id=job_dict.get("group_id"),
            service_conn=service_conn,
            purpose=f"dataset preparation on job {job_dict.get('job_id') or '?'}",
        )
        if not user_conn:
            logger.warning(
                "Background dataset preparation for job %s cannot reuse the live OMERO.web session.",
                sanitize_log_value(job_dict.get("job_id")),
            )
            return False, generic_error

        for dataset_name in missing_dataset_names:
            dataset_id = _get_or_create_dataset(
                user_conn,
                dataset_name,
                dataset_map,
                project_id=job_dict.get("project_id"),
            )
            if dataset_id is None:
                logger.warning(
                    "Failed to create dataset %s for job %s using the service OMERO connection.",
                    sanitize_log_value(dataset_name),
                    sanitize_log_value(job_dict.get("job_id")),
                )
                return False, generic_error
        return True, None
    finally:
        if user_conn is not None:
            try:
                user_conn.close()
            except Exception as exc:
                logger.warning(
                    "Failed to close impersonated OMERO connection after dataset creation: %s",
                    exc,
                )
        try:
            service_conn.close()
        except Exception as exc:
            logger.warning(
                "Failed to close job-service connection after dataset creation: %s", exc
            )


def _prepare_job_import_datasets(
    job_id: str, job_dict: dict, conn: Optional[BlitzGateway] = None
):
    upload_root = _get_upload_root() / job_id
    if not upload_root.exists():
        error_message = errors.upload_folder_missing_on_server()

        def mark_error(current_job):
            current_job["status"] = "error"
            _append_job_error(current_job, error_message)
            current_job["updated"] = time.time()
            return current_job

        updated_job = _update_job(job_id, mark_error) or job_dict
        return updated_job, error_message

    entries_to_import = _build_import_units(job_dict, upload_root)
    datasets_ready, dataset_error = _ensure_job_dataset_targets(
        job_dict, entries_to_import, conn=conn
    )
    if not datasets_ready:
        error_message = dataset_error or errors.unable_prepare_import_destination()

        def mark_error(current_job):
            current_job["status"] = "error"
            _append_job_error(current_job, error_message)
            current_job["updated"] = time.time()
            return current_job

        updated_job = _update_job(job_id, mark_error) or job_dict
        return updated_job, error_message

    if not _save_job(job_dict):
        return None, errors.unable_update_upload_job_state()

    return job_dict, None


_CLI_ID_PATTERN = re.compile(
    r"(?P<type>OriginalFile|FileAnnotation|ImageAnnotationLink):(?P<id>\d+)"
)

# Patterns to detect successfully imported OMERO objects in CLI output.
# Different OMERO CLI commands report created objects using different formats
# such as ``Image:123`` or ``Created Image 123``.
_IMPORT_OBJECT_PATTERNS = (
    re.compile(r"\b(?:Image|Fileset|Plate|Screen|Dataset|OriginalFile):(\d+)\b"),
    re.compile(
        r"\bCreated (?:Image|Fileset|Plate|Screen|Dataset|OriginalFile)\s+(\d+)\b"
    ),
)
_IMPORT_OBJECT_PATTERN = _IMPORT_OBJECT_PATTERNS[0]


def _build_omero_cli_command(subcommand, session_key: str, host: str, port: int):
    cmd = [OMERO_CLI]
    if session_key:
        cmd.extend(["-k", session_key])
    if host:
        cmd.extend(["-s", host])
    if port:
        cmd.extend(["-p", str(port)])
    cmd.extend(subcommand)
    return cmd


IMPORT_TIMEOUT_SECONDS_DEFAULT = (
    24 * 60 * 60
)  # 24 hours per file import for large structured datasets
IMPORT_TIMEOUT_SECONDS_ENV = "OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS"
CLI_KEEPALIVE_SECONDS_DEFAULT = 30
CLI_KEEPALIVE_SECONDS_ENV = "OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS"
FAILED_IMPORT_RETENTION_SECONDS_DEFAULT = 48 * 60 * 60
FAILED_IMPORT_RETENTION_SECONDS_ENV = "OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS"
LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_DEFAULT = 2 * 60 * 60
LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_ENV = "OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS"
SCRIPT_START_TIMEOUT_SECONDS_DEFAULT = 180
SCRIPT_START_TIMEOUT_SECONDS_ENV = "OMERO_WEB_UPLOAD_SCRIPT_START_TIMEOUT_SECONDS"
SCRIPT_START_RETRY_SECONDS_DEFAULT = 5
SCRIPT_START_RETRY_SECONDS_ENV = "OMERO_WEB_UPLOAD_SCRIPT_START_RETRY_SECONDS"


def _get_cli_keepalive_seconds() -> int:
    return _get_env_int(
        CLI_KEEPALIVE_SECONDS_ENV,
        CLI_KEEPALIVE_SECONDS_DEFAULT,
        0,
        3600,
    )


def _get_local_import_scan_timeout_seconds() -> int:
    return _get_env_int(
        LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_ENV,
        LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_DEFAULT,
        30,
        24 * 60 * 60,
    )


def _get_script_start_timeout_seconds() -> int:
    return _get_env_int(
        SCRIPT_START_TIMEOUT_SECONDS_ENV,
        SCRIPT_START_TIMEOUT_SECONDS_DEFAULT,
        1,
        24 * 60 * 60,
    )


def _get_script_start_retry_seconds() -> int:
    return _get_env_int(
        SCRIPT_START_RETRY_SECONDS_ENV,
        SCRIPT_START_RETRY_SECONDS_DEFAULT,
        1,
        300,
    )


def _get_failed_import_retention_seconds() -> int:
    return _get_env_int(
        FAILED_IMPORT_RETENTION_SECONDS_ENV,
        FAILED_IMPORT_RETENTION_SECONDS_DEFAULT,
        60,
        30 * 24 * 60 * 60,
    )


def _sanitize_cli_output_for_logging(text: str) -> str:
    sanitized = sanitize_log_value(text)
    return re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "***",
        sanitized,
        flags=re.IGNORECASE,
    )


def _extract_imported_object_ids(output: str) -> list[str]:
    if not output:
        return []
    created_ids = []
    seen = set()
    for pattern in _IMPORT_OBJECT_PATTERNS:
        for match in pattern.finditer(output):
            object_id = match.group(1)
            if not object_id or object_id in seen:
                continue
            seen.add(object_id)
            created_ids.append(object_id)
    return created_ids


def _reports_no_processor_available(stdout: str, stderr: str) -> bool:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    lowered = combined.lower()
    return "noprocessoravailable" in lowered or "no processor available" in lowered


BACKGROUND_IMPORT_SESSION_TTL_SLACK_SECONDS = 10 * 60
BACKGROUND_IMPORT_SESSION_MIN_SECONDS = 60 * 60
BACKGROUND_IMPORT_SESSION_MAX_SECONDS = 7 * 24 * 60 * 60


def _get_background_import_session_timeout_seconds(
    timeout_hint_seconds: Optional[int] = None,
) -> int:
    base_seconds = (
        timeout_hint_seconds
        if timeout_hint_seconds is not None
        else _get_import_timeout_seconds()
    )
    requested = int(base_seconds) + BACKGROUND_IMPORT_SESSION_TTL_SLACK_SECONDS
    return max(
        BACKGROUND_IMPORT_SESSION_MIN_SECONDS,
        min(BACKGROUND_IMPORT_SESSION_MAX_SECONDS, requested),
    )


def _get_root_password() -> str:
    return (os.environ.get("ROOTPASS") or "").strip()


def _open_admin_connection(host: str, port: int) -> Optional[BlitzGateway]:
    root_pass = _get_root_password()
    if not root_pass:
        logger.error(
            "ROOTPASS is missing; cannot create independent background OMERO sessions."
        )
        return None

    _, _, _, secure = _get_job_service_credentials()
    conn = BlitzGateway("root", root_pass, host=host, port=int(port), secure=secure)
    try:
        if not conn.connect():
            last_err = None
            try:
                last_err = conn.getLastError()
            except Exception:
                last_err = None
            logger.error(
                "root connect() failed for background import sessions: host=%s port=%s tls=%s lastError=%r",
                sanitize_log_value(host),
                sanitize_log_value(port),
                "enabled" if secure else "disabled",
                last_err,
            )
            try:
                conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
            return None
        conn.SERVICE_OPTS.setOmeroGroup("-1")
        return conn
    except Exception as exc:
        logger.error(
            "root connect() raised for background import sessions: host=%s port=%s error=%s",
            sanitize_log_value(host),
            sanitize_log_value(port),
            sanitize_log_value(exc),
        )
        try:
            conn.close()
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)
        return None


def _resolve_group_name(
    conn: Optional[BlitzGateway],
    group_id: Optional[int],
    group_name: Optional[str] = None,
) -> Optional[str]:
    cached_name = (group_name or "").strip()
    if cached_name:
        return cached_name
    if conn is None or group_id is None:
        return None
    try:
        group = conn.getObject("ExperimenterGroup", int(group_id))
    except Exception as exc:
        logger.warning(
            "Failed to resolve group %s for background import session creation: %s",
            sanitize_log_value(group_id),
            sanitize_log_value(exc),
        )
        return None
    if group is None:
        return None
    try:
        return (group.getName() or "").strip() or None
    except Exception:
        return None


@contextmanager
def _background_import_session(
    username: str,
    host: str,
    port: int,
    *,
    group_id: Optional[int] = None,
    group_name: Optional[str] = None,
    timeout_hint_seconds: Optional[int] = None,
):
    admin_conn = _open_admin_connection(host, port)
    if admin_conn is None:
        yield None
        return

    session = None
    session_key = None
    try:
        resolved_group_name = _resolve_group_name(
            admin_conn, group_id, group_name=group_name
        )
        principal = omero.sys.Principal(
            (username or "").strip(),
            resolved_group_name or "",
            "User",
        )
        timeout_ms = (
            _get_background_import_session_timeout_seconds(timeout_hint_seconds) * 1000
        )
        session = admin_conn.c.sf.getSessionService().createSessionWithTimeouts(
            principal,
            timeout_ms,
            timeout_ms,
        )
        session_key = session.getUuid().getValue()
        yield session_key
    except Exception as exc:
        logger.error(
            "Failed to create independent background OMERO session for user %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        yield None
    finally:
        if session is not None:
            try:
                admin_conn.c.sf.getSessionService().closeSession(session)
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
        try:
            admin_conn.close()
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)


def _write_cli_ice_config(
    cli_home: Path, keepalive_seconds: int, base_config_path: str = ""
) -> Optional[Path]:
    if keepalive_seconds <= 0:
        return None

    config_lines = []
    if base_config_path:
        try:
            base_text = Path(base_config_path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Failed to read base ICE_CONFIG %s: %s", base_config_path, exc
            )
        else:
            stripped = base_text.rstrip()
            if stripped:
                config_lines.append(stripped)

    config_lines.append(f"omero.keep_alive={keepalive_seconds}")
    config_text = "\n".join(config_lines) + "\n"

    target_path = cli_home / "omero-cli-ice.config"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=cli_home,
        prefix="ice-config-",
        suffix=".tmp",
        delete=False,
    ) as tmp_file:
        tmp_file.write(config_text)
        tmp_name = tmp_file.name

    tmp_path = Path(tmp_name)
    tmp_path.chmod(0o600)
    tmp_path.replace(target_path)
    return target_path


def _classify_import_failure(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part).lower()
    if (
        "proxy keep alive failed" in combined
        or "exception while executing ping()" in combined
        or 'operation = "keepallalive"' in combined
    ):
        return errors.import_session_expired()
    if "no annotate access for parent directory" in combined:
        parent_match = re.search(
            r"no annotate access for parent directory:\s*(\d+)",
            stderr,
            re.IGNORECASE,
        )
        group_match = re.search(
            r"current group:\s*([^\r\n]+)",
            stderr,
            re.IGNORECASE,
        )
        parent_id = parent_match.group(1) if parent_match else None
        group_name = group_match.group(1).strip() if group_match else None
        return errors.import_parent_directory_not_writable(
            group_name=group_name,
            parent_id=parent_id,
        )
    return errors.import_failed()


def _run_omero_cli(cmd, timeout=None):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        env=_build_cli_env(),
    )


def _run_local_import_scan(path: Path, timeout: Optional[int] = None):
    if timeout is None:
        timeout = _get_local_import_scan_timeout_seconds()
    cmd = [
        OMERO_CLI,
        "import",
        "-f",
        "--depth",
        str(OMERO_IMPORT_SCAN_DEPTH),
        str(path),
    ]

    env = os.environ.copy()
    omerodir_path = (
        get_plugin_tmp_dir("compat-check") / f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    env["OMERODIR"] = str(omerodir_path)

    cli_home = _get_upload_root() / ".omero-cli-home"
    cli_cache = cli_home / ".cache"
    _ensure_dir_with_permissions(cli_home, 0o700)
    _ensure_dir_with_permissions(cli_cache, 0o700)

    env["HOME"] = str(cli_home)
    env["XDG_CACHE_HOME"] = str(cli_cache)

    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    finally:
        shutil.rmtree(omerodir_path, ignore_errors=True)


def _parse_cli_id(output: str, expected_type: str):
    for line in (output or "").splitlines():
        match = _CLI_ID_PATTERN.search(line.strip())
        if match and match.group("type") == expected_type:
            return int(match.group("id"))
    return None


def _read_proc_rchar(pid):
    """Read *rchar* (total bytes read via read syscalls) from ``/proc/{pid}/io``.

    Returns ``None`` when the file cannot be read (process exited, permissions,
    non-Linux OS, etc.).
    """
    try:
        with open(f"/proc/{pid}/io", "r") as fh:
            for line in fh:
                if line.startswith("rchar:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError, PermissionError):
        logger.debug("Suppressed exception reading process I/O stats", exc_info=True)
    return None


def _get_path_total_size(path: Path) -> int:
    """Return the total byte size of *path* (file or directory, recursive)."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        logger.debug("Suppressed exception in cleanup", exc_info=True)
    return total


def _build_cli_env():
    """Build the environment dict for OMERO CLI sub-processes.

    Factored out of ``_run_omero_cli`` so that ``_import_file`` can re-use it
    for both the blocking *subprocess.run* path and the streaming *Popen* path.
    """
    cli_env = os.environ.copy()
    cli_home = _get_upload_root() / ".omero-cli-home"
    cli_cache = cli_home / ".cache"
    _ensure_dir_with_permissions(cli_home, 0o700)
    _ensure_dir_with_permissions(cli_cache, 0o700)
    cli_env["HOME"] = str(cli_home)
    cli_env["XDG_CACHE_HOME"] = str(cli_cache)
    cli_ice_config = _write_cli_ice_config(
        cli_home,
        _get_cli_keepalive_seconds(),
        cli_env.get("ICE_CONFIG", ""),
    )
    if cli_ice_config is not None:
        cli_env["ICE_CONFIG"] = str(cli_ice_config)
    return cli_env


# How often (seconds) the import progress monitor updates the job file.
_IMPORT_PROGRESS_INTERVAL = 5


def _import_file(
    conn,
    session_key: str,
    host: str,
    port: int,
    path: Path,
    dataset_id=None,
    import_name: Optional[str] = None,
    progress_job=None,
):
    """Run ``omero import`` for *path*.

    When *progress_job* is a mutable job dict the function uses
    ``subprocess.Popen`` instead of ``subprocess.run`` and periodically writes
    an estimated ``import_progress_bytes`` value into the dict (and persists it
    to disk).  The estimate is derived from ``/proc/{pid}/io`` – the number of
    bytes the CLI process has read so far – giving a real, data-driven progress
    signal that the front-end can relay through the orange progress bar.

    Returns ``(success, stdout, stderr)`` – the same contract as before.
    """
    cmd = _build_omero_cli_command(["import"], session_key, host, port)
    cmd.extend(["--depth", str(OMERO_IMPORT_SCAN_DEPTH)])
    if dataset_id:
        cmd.extend(["-d", str(dataset_id)])
    if import_name:
        cmd.extend(["-n", str(import_name)])
    cmd.append(str(path))

    logger.info(
        "Import CLI: starting import for %s (dataset_id=%s)", path.name, dataset_id
    )
    import_start = time.time()

    # ------------------------------------------------------------------
    # Fast path: no progress tracking requested – keep the proven
    # subprocess.run() behaviour unchanged.
    # ------------------------------------------------------------------
    if progress_job is None:
        try:
            result = _run_omero_cli(cmd, timeout=_get_import_timeout_seconds())
        except subprocess.TimeoutExpired:
            logger.error(
                "Import CLI timed out after %ds for %s",
                _get_import_timeout_seconds(),
                path,
            )
            return (
                False,
                "",
                f"Import timed out after {_get_import_timeout_seconds()} seconds",
            )
        elapsed = time.time() - import_start
        success = result.returncode == 0
        logger.info(
            "Import CLI: finished for %s in %.1fs (success=%s, returncode=%d, "
            "stdout_lines=%d, stderr_lines=%d)",
            path.name,
            elapsed,
            success,
            result.returncode,
            len((result.stdout or "").splitlines()),
            len((result.stderr or "").splitlines()),
        )
        if not success:
            logger.warning(
                "Import CLI stderr for %s: %s",
                path.name,
                _sanitize_cli_output_for_logging((result.stderr or "").strip()[:500]),
            )
        return success, result.stdout, result.stderr

    # ------------------------------------------------------------------
    # Progress-tracking path: use Popen so we can monitor /proc/{pid}/io
    # while the CLI runs.
    # ------------------------------------------------------------------
    cli_env = _build_cli_env()
    file_size = _get_path_total_size(path)
    timeout_seconds = _get_import_timeout_seconds()
    imported_base = progress_job.get("imported_bytes", 0)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        env=cli_env,
    )

    # Drain stdout/stderr in background threads to prevent pipe deadlock.
    stdout_lines = []
    stderr_lines = []

    def _drain(pipe, dest):
        try:
            for line in pipe:
                dest.append(line)
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)

    t_out = threading.Thread(
        target=_drain, args=(proc.stdout, stdout_lines), daemon=True
    )
    t_err = threading.Thread(
        target=_drain, args=(proc.stderr, stderr_lines), daemon=True
    )
    t_out.start()
    t_err.start()

    baseline_rchar = _read_proc_rchar(proc.pid)
    last_save = 0.0  # force first save

    try:
        while proc.poll() is None:
            elapsed = time.time() - import_start
            if elapsed > timeout_seconds:
                proc.kill()
                logger.error(
                    "Import CLI timed out after %ds for %s", timeout_seconds, path
                )
                t_out.join(timeout=5)
                t_err.join(timeout=5)
                for pipe in (proc.stdout, proc.stderr):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except Exception:
                            logger.debug(
                                "Suppressed exception in cleanup", exc_info=True
                            )
                return (
                    False,
                    "".join(stdout_lines),
                    f"Import timed out after {timeout_seconds} seconds",
                )

            # Update progress from /proc I/O – lightweight read, max every
            # _IMPORT_PROGRESS_INTERVAL seconds.
            now = time.time()
            if now - last_save >= _IMPORT_PROGRESS_INTERVAL and file_size > 0:
                rchar = _read_proc_rchar(proc.pid)
                if rchar is not None and baseline_rchar is not None:
                    bytes_read = max(0, rchar - baseline_rchar)
                    capped = min(file_size, bytes_read)
                    progress_job["import_progress_bytes"] = imported_base + capped
                    try:
                        _save_job(progress_job)
                    except Exception:
                        logger.debug(
                            "Suppressed exception in cleanup", exc_info=True
                        )  # best-effort; don't derail the import
                    last_save = now

            time.sleep(2)
    except Exception:
        proc.kill()
        raise
    finally:
        t_out.join(timeout=10)
        t_err.join(timeout=10)
        # Close pipes to avoid ResourceWarning for unclosed file objects.
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    logger.debug("Suppressed exception in cleanup", exc_info=True)

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    elapsed = time.time() - import_start
    success = proc.returncode == 0

    logger.info(
        "Import CLI: finished for %s in %.1fs (success=%s, returncode=%d, "
        "stdout_lines=%d, stderr_lines=%d)",
        path.name,
        elapsed,
        success,
        proc.returncode,
        len(stdout.splitlines()),
        len(stderr.splitlines()),
    )
    if not success:
        logger.warning(
            "Import CLI stderr for %s: %s",
            path.name,
            _sanitize_cli_output_for_logging(stderr.strip()[:500]),
        )
    return success, stdout, stderr


def _validate_session(conn):
    """
    Validate that a BlitzGateway connection is still active.

    Returns:
        bool: True if session is valid, False otherwise
    """
    try:
        # Try to get the current event context - this will fail if session expired
        conn.getEventContext()
        return True
    except Exception as exc:
        logger.warning("Session validation failed: %s", exc)
        return False


def _reconnect_session(session_key: str, host: str, port: int, old_conn=None):
    """
    Create a new connection or reconnect using the session key.

    Args:
        session_key: OMERO session key
        host: OMERO server host
        port: OMERO server port
        old_conn: Previous connection to close (if any)

    Returns:
        BlitzGateway connection or None if failed
    """
    if old_conn:
        try:
            old_conn.close()
        except Exception as exc:
            logger.debug(
                "Failed to close stale OMERO connection before reconnect: %s", exc
            )

    try:
        client = omero.client(host=host, port=port)
        _join_detached_session(client, session_key)
        conn = BlitzGateway(client_obj=client)
        conn.SERVICE_OPTS.setOmeroGroup("-1")

        # Validate the new connection
        if not _validate_session(conn):
            logger.error("Newly created session is invalid")
            try:
                conn.close()
            except Exception as exc:
                logger.warning(
                    "Failed to close invalid OMERO session during reconnect: %s", exc
                )
            return None

        return conn
    except Exception as exc:
        logger.error("Failed to reconnect session: %s", exc)
        return None


def _open_session_connection(session_key: str, host: str, port: int):
    """
    Open a BlitzGateway connection using a session key.

    Args:
        session_key: OMERO session key
        host: OMERO server host
        port: OMERO server port

    Returns:
        BlitzGateway connection
    """
    client = omero.client(host=host, port=port)
    _join_detached_session(client, session_key)
    conn = BlitzGateway(client_obj=client)
    conn.SERVICE_OPTS.setOmeroGroup("-1")
    return conn


def _join_detached_session(client, session_key: str):
    """Join a live OMERO session without letting helper-client teardown destroy it."""
    session = client.joinSession(session_key)
    detach_on_destroy = getattr(session, "detachOnDestroy", None)
    if callable(detach_on_destroy):
        detach_on_destroy()
    return session


def _find_image_by_name(conn, file_name: str, dataset_id=None, timeout_seconds=30):
    """
    Find image by name using OMERO QueryService with limits and timeout.

    FIXED: This version uses database queries instead of iterating all images.
    Prevents hangs on large datasets (100-1000x faster).
    """
    if not file_name:
        return None

    import time

    start_time = time.time()

    try:
        qs = conn.getQueryService()

        # Try dataset-scoped search first (fastest)
        if dataset_id:
            try:
                query = """
                    SELECT i FROM Image i
                    JOIN FETCH i.datasetLinks dil
                    WHERE dil.parent.id = :did
                    AND i.name = :name
                """

                params = omero.sys.ParametersI()
                _params_add_long(params, "did", dataset_id)
                _params_add_string(params, "name", file_name)
                _params_page(params, 0, 100)  # Limit results

                images = qs.findAllByQuery(query, params, conn.SERVICE_OPTS)

                if images:
                    elapsed = time.time() - start_time
                    logger.debug(
                        "Found image '%s' in Dataset:%d in %.2fs",
                        file_name,
                        dataset_id,
                        elapsed,
                    )
                    return conn.getObject("Image", images[0].getId().getValue())
            except Exception as exc:
                logger.warning("Dataset search failed for '%s': %s", file_name, exc)

        # Global search as fallback
        try:
            query = "SELECT i FROM Image i WHERE i.name = :name"
            params = omero.sys.ParametersI()
            _params_add_string(params, "name", file_name)
            _params_page(params, 0, 100)

            images = qs.findAllByQuery(query, params, conn.SERVICE_OPTS)

            if images:
                elapsed = time.time() - start_time
                if len(images) > 1:
                    logger.warning(
                        "Found %d images named '%s' - using first",
                        len(images),
                        file_name,
                    )
                logger.debug("Found image '%s' globally in %.2fs", file_name, elapsed)
                return conn.getObject("Image", images[0].getId().getValue())
            else:
                logger.warning("Image '%s' not found", file_name)
                return None
        except Exception as exc:
            logger.error("Global search failed for '%s': %s", file_name, exc)
            return None
    except Exception:
        logger.exception("Unexpected error searching for '%s'", file_name)
        return None


def _params_add_string(params, key, value):
    add_string = getattr(params, "addString", None)
    if callable(add_string):
        add_string(key, value)
        return

    generic_add = getattr(params, "add", None)
    if callable(generic_add):
        rstring_factory = getattr(getattr(omero, "rtypes", None), "rstring", rstring)
        generic_add(key, rstring_factory(value))
        return

    values = getattr(params, "values", None)
    if isinstance(values, dict):
        values[key] = value
        return

    raise AttributeError(f"Unsupported OMERO parameter object for string key {key!r}")


def _params_add_long(params, key, value):
    add_long = getattr(params, "addLong", None)
    if callable(add_long):
        add_long(key, value)
        return

    generic_add = getattr(params, "add", None)
    if callable(generic_add):
        generic_add(key, value)
        return

    values = getattr(params, "values", None)
    if isinstance(values, dict):
        values[key] = value
        return

    raise AttributeError(f"Unsupported OMERO parameter object for integer key {key!r}")


def _params_add_string_list(params, key, values):
    normalized_values = [str(value) for value in values]

    add_list = getattr(params, "addList", None)
    if callable(add_list):
        add_list(key, normalized_values)
        return

    generic_add = getattr(params, "add", None)
    if callable(generic_add):
        generic_add(key, normalized_values)
        return

    param_values = getattr(params, "values", None)
    if isinstance(param_values, dict):
        param_values[key] = normalized_values
        return

    raise AttributeError(
        f"Unsupported OMERO parameter object for string-list key {key!r}"
    )


def _params_page(params, offset, size):
    page = getattr(params, "page", None)
    if callable(page):
        page(offset, size)


def _batch_find_images_by_name(conn, file_names, dataset_id=None, timeout_seconds=60):
    """
    Find multiple images in a single query - MUCH faster than individual lookups.

    Returns: dict mapping file_name -> Image wrapper object

    CRITICAL: This is the key to fixing SEM EDX performance.
    Instead of N queries (one per TXT file), we do 1 query for all images.
    """
    if not file_names:
        return {}

    import time

    start_time = time.time()
    results = {}

    try:
        qs = conn.getQueryService()

        params = omero.sys.ParametersI()
        _params_add_string_list(params, "names", file_names)

        if dataset_id:
            query = """
                SELECT i FROM Image i
                JOIN FETCH i.datasetLinks dil
                WHERE dil.parent.id = :did
                AND i.name IN (:names)
            """
            _params_add_long(params, "did", dataset_id)
        else:
            query = """
                SELECT i FROM Image i
                WHERE i.name IN (:names)
            """

        logger.info(
            "Batch searching for %d images (dataset_id=%s)", len(file_names), dataset_id
        )
        images = qs.findAllByQuery(query, params, conn.SERVICE_OPTS)

        for image_obj in images:
            img_wrapper = conn.getObject("Image", image_obj.getId().getValue())
            if img_wrapper:
                results[img_wrapper.getName()] = img_wrapper

        elapsed = time.time() - start_time
        logger.info(
            "Batch search found %d/%d images in %.2fs",
            len(results),
            len(file_names),
            elapsed,
        )

        missing = set(file_names) - set(results.keys())
        if missing:
            logger.warning("Missing %d images: %s", len(missing), list(missing)[:5])
    except Exception as exc:
        logger.error("Batch image search failed: %s", exc)

    return results


def _get_job_service_credentials():
    """Resolve service credentials from environment.

    This is intentionally NOT taken from the end-user's OMERO.web session.
    Using the user's session for background work can invalidate their login.
    """
    user = (os.environ.get(JOB_SERVICE_USER_ENV) or "").strip()
    if not user:
        user = (os.environ.get(JOB_SERVICE_USER_ENV_FALLBACK) or "").strip()
    if not user:
        user = JOB_SERVICE_USERNAME_DEFAULT

    passwd = (os.environ.get(JOB_SERVICE_AUTH_ENV) or "").strip()
    if not passwd:
        passwd = (os.environ.get(JOB_SERVICE_AUTH_ENV_FALLBACK) or "").strip()

    # Optional override: force a specific group id for job-service.
    # If empty, we'll use the job's group_id (recommended).
    group_override = (os.environ.get(JOB_SERVICE_GROUP_ENV) or "").strip()
    if not group_override:
        group_override = (os.environ.get(JOB_SERVICE_GROUP_ENV_FALLBACK) or "").strip()

    # Optional: allow forcing secure/insecure connection
    secure_raw = (os.environ.get(JOB_SERVICE_SECURE_ENV) or "").strip()
    if not secure_raw:
        secure_raw = (os.environ.get(JOB_SERVICE_SECURE_ENV_FALLBACK) or "").strip()

    secure = True
    if secure_raw:
        if secure_raw.lower() in ("0", "false", "no", "off"):
            secure = False

    return user, passwd, group_override, secure


def _create_dataset_via_admin_connection(
    username: str,
    host: str,
    port: int,
    name: str,
    group_id: Optional[int] = None,
    group_name: Optional[str] = None,
    project_id: Optional[int] = None,
) -> Optional[int]:
    """Create a Dataset using an independent admin impersonation path."""
    import omero.rtypes as rtypes
    from omero.model import DatasetI, ProjectDatasetLinkI, ProjectI

    admin_conn = _open_admin_connection(host, port)
    if admin_conn is None:
        return None

    conn = None
    try:
        conn = admin_conn.suConn(username)
        if conn is None:
            logger.warning(
                "Cannot switch to user %s for dataset creation via admin connection.",
                sanitize_log_value(username),
            )
            return None

        if group_id is not None:
            conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
        elif group_name:
            conn.SERVICE_OPTS.setOmeroGroup(group_name)

        ds = DatasetI()
        ds.setName(rtypes.rstring(name))
        ds = conn.getUpdateService().saveAndReturnObject(ds, conn.SERVICE_OPTS)
        ds_id = ds.getId().getValue()

        if project_id is not None:
            link = ProjectDatasetLinkI()
            link.setParent(ProjectI(int(project_id), False))
            link.setChild(DatasetI(ds_id, False))
            conn.getUpdateService().saveObject(link, conn.SERVICE_OPTS)

        logger.info(
            "Created dataset %s (id=%d) via independent admin-backed connection",
            sanitize_log_value(name),
            ds_id,
        )
        return ds_id
    except Exception as exc:
        logger.warning(
            "Dataset creation via admin connection failed: %s", sanitize_log_value(exc)
        )
        return None
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)
        try:
            admin_conn.close()
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)


def _open_service_connection(
    host: str, port: int, group_id: Optional[int] = None
) -> Optional[BlitzGateway]:
    """Login as service user for async background work (safe for user sessions)."""
    service_user, service_pass, group_override, secure = _get_job_service_credentials()

    if not service_pass:
        logger.error(
            "job-service authentication missing. Set %s in the omeroweb container environment.",
            JOB_SERVICE_AUTH_ENV,
        )
        return None

    conn = BlitzGateway(
        service_user, service_pass, host=host, port=int(port), secure=secure
    )

    try:
        try:
            ok = conn.connect()
        except Exception as exc:
            logger.error(
                "job-service connect() raised: host=%s port=%s tls=%s error_type=%s has_last_error=%s",
                sanitize_log_value(host),
                port,
                "enabled" if secure else "disabled",
                sanitize_log_value(type(exc).__name__),
                _connection_has_last_error(conn),
            )
            try:
                conn.close()
            except Exception as close_exc:
                logger.debug(
                    "Failed to close job-service connection after connect() exception: %s",
                    close_exc,
                )
            return None

        if not ok:
            logger.error(
                "job-service connect() failed: host=%s port=%s tls=%s has_last_error=%s",
                sanitize_log_value(host),
                port,
                "enabled" if secure else "disabled",
                _connection_has_last_error(conn),
            )
            try:
                conn.close()
            except Exception as close_exc:
                logger.debug(
                    "Failed to close job-service connection after failed connect(): %s",
                    close_exc,
                )
            return None

        # Prefer explicit override, else use job's group_id when provided.
        effective_group = None
        if group_override:
            try:
                effective_group = int(group_override)
            except Exception:
                logger.warning(
                    "Ignoring invalid %s override; falling back to the job group context.",
                    JOB_SERVICE_GROUP_ENV,
                )
        if effective_group is None and group_id is not None:
            effective_group = int(group_id)

        if effective_group is not None:
            try:
                conn.SERVICE_OPTS.setOmeroGroup(str(effective_group))
            except Exception as exc:
                logger.warning(
                    "Failed to set job-service group context to %s: %s",
                    effective_group,
                    exc,
                )

        return conn

    except Exception:
        try:
            conn.close()
        except Exception as close_exc:
            logger.debug(
                "Failed to close job-service connection during exception cleanup: %s",
                close_exc,
            )
        raise


def _connection_has_last_error(conn) -> bool:
    try:
        return bool(conn.getLastError())
    except Exception:
        return False


def _open_group_scoped_session_connection(
    session_key: str,
    host: str,
    port: int,
    group_id: Optional[int] = None,
):
    """Open the importing user's OMERO session and scope it to the target group."""
    if not session_key:
        return None

    conn = None
    try:
        conn = _open_session_connection(session_key, host, port)
        if conn is None:
            return None
        if group_id is not None:
            try:
                conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
            except Exception as exc:
                logger.warning(
                    "Failed to set session-scoped post-import group context to %s: %s",
                    sanitize_log_value(group_id),
                    sanitize_log_value(exc),
                )
        return conn
    except Exception:
        if conn is not None:
            try:
                conn.close()
            except Exception as close_exc:
                logger.warning(
                    "Failed to close session-scoped OMERO connection after exception: %s",
                    sanitize_log_value(close_exc),
                )
        raise


def _open_user_owned_background_connection(
    username: str,
    *,
    session_key: str = "",
    host: str = "",
    port: Optional[int] = None,
    group_id: Optional[int] = None,
    service_conn: Optional[BlitzGateway] = None,
    purpose: str = "background OMERO work",
):
    """Open a user-owned OMERO connection without reusing the live OMERO.web session."""
    if service_conn is None or not username:
        logger.warning(
            "No service connection available for %s as user %s. "
            "Live OMERO.web sessions are not reopened in background workers.",
            sanitize_log_value(purpose),
            sanitize_log_value(username),
        )
        return None

    try:
        conn = service_conn.suConn(username)
    except Exception as exc:
        logger.warning(
            "Service connection failed to switch to OMERO user %s for %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(purpose),
            sanitize_log_value(exc),
        )
        return None

    if not conn:
        logger.warning(
            "Service connection could not switch to OMERO user %s for %s.",
            sanitize_log_value(username),
            sanitize_log_value(purpose),
        )
        return None

    if group_id is not None:
        try:
            conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
        except Exception as exc:
            logger.warning(
                "Failed to set impersonated group context to %s for %s: %s",
                sanitize_log_value(group_id),
                sanitize_log_value(purpose),
                sanitize_log_value(exc),
            )

    return conn


def _logical_import_entry_display_name(entry: dict) -> str:
    rel_path = (entry.get("relative_path") or "").strip()
    if not rel_path:
        return ""
    return PurePosixPath(rel_path).name


def _logical_import_entry_group_header_name(entry: dict) -> str:
    explicit_group_header_name = (entry.get("group_header_name") or "").strip()
    if explicit_group_header_name:
        return explicit_group_header_name
    staged_path = (entry.get("staged_path") or "").strip()
    if not staged_path:
        return ""
    return PurePosixPath(staged_path).name


def _entry_requires_name_normalization(entry: dict, dataset_id: Optional[int]) -> bool:
    if not dataset_id:
        return False

    covered_relative_paths = entry.get("covered_relative_paths") or []
    if len(covered_relative_paths) <= 1:
        return False

    desired_name = _logical_import_entry_display_name(entry)
    group_header_name = _logical_import_entry_group_header_name(entry)
    return bool(
        desired_name and group_header_name and desired_name != group_header_name
    )


def _build_import_name_normalization_context(entry: dict, dataset_id: Optional[int]):
    if not _entry_requires_name_normalization(entry, dataset_id):
        return None

    desired_name = _logical_import_entry_display_name(entry)
    group_header_name = _logical_import_entry_group_header_name(entry)
    if not desired_name or not group_header_name:
        return None

    return {
        "desired_name": desired_name,
        "group_header_name": group_header_name,
    }


def _extract_imported_image_ids(import_stdout: str) -> list[int]:
    if not import_stdout:
        return []

    imported_ids = []
    seen_ids = set()
    for match in re.finditer(r"(?m)^\s*Image:(\d+)\s*$", import_stdout):
        image_id = int(match.group(1))
        if image_id in seen_ids:
            continue
        seen_ids.add(image_id)
        imported_ids.append(image_id)
    return imported_ids


def _image_name_requires_normalization(
    current_name: str, group_header_name: str
) -> bool:
    normalized_current = (current_name or "").strip()
    if not normalized_current:
        return True
    return normalized_current == (group_header_name or "").strip()


def _apply_import_name_normalization_context(
    entry: dict,
    context: Optional[dict],
    imported_image_ids: list[int],
    session_key: str,
    host: str,
    port: int,
    group_id: Optional[int],
) -> list[int]:
    if not context or not session_key:
        return []

    desired_name = (context.get("desired_name") or "").strip()
    group_header_name = (context.get("group_header_name") or "").strip()
    if not imported_image_ids or not desired_name or not group_header_name:
        return []

    conn = _open_group_scoped_session_connection(
        session_key,
        host,
        port,
        group_id=group_id,
    )
    if conn is None:
        return []

    try:
        images = []
        for image_id in imported_image_ids:
            image = conn.getObject("Image", image_id)
            if image is None:
                logger.warning(
                    "Imported image %s could not be reopened for post-import reconciliation.",
                    image_id,
                )
                continue
            images.append(image)

        renamed_ids = []
        if len(images) == 1:
            image = images[0]
            current_name = (image.getName() or "").strip()
            if (
                _image_name_requires_normalization(current_name, group_header_name)
                and current_name != desired_name
            ):
                image.setName(desired_name)
                image.save()
                image_id = _get_id(image)
                if image_id is not None:
                    renamed_ids.append(int(image_id))
            return renamed_ids

        for index, image in enumerate(images, start=1):
            current_name = (image.getName() or "").strip()
            if not _image_name_requires_normalization(current_name, group_header_name):
                continue
            target_name = f"{desired_name} [{index}]"
            if current_name == target_name:
                continue
            image.setName(target_name)
            image.save()
            image_id = _get_id(image)
            if image_id is not None:
                renamed_ids.append(int(image_id))

        return renamed_ids
    except Exception as exc:
        logger.warning(
            "Post-import name normalization failed for %s: %s",
            sanitize_log_value(entry.get("relative_path")),
            sanitize_log_value(exc),
        )
        return []
    finally:
        try:
            conn.close()
        except Exception as exc:
            logger.warning(
                "Failed to close session-scoped OMERO connection after normalization: %s",
                sanitize_log_value(exc),
            )


def _attach_txt_to_image_service(
    conn: BlitzGateway,
    image_id: int,
    txt_path: Path,
    username: str,
    create_tables: bool = True,
    plot_path: Optional[Path] = None,
    *,
    session_key: str = "",
    host: str = "",
    port: Optional[int] = None,
    group_id: Optional[int] = None,
):
    """Attach a TXT file to an Image using OMERO API (no CLI).

    Creates:
      - OriginalFile
      - FileAnnotation (ns=SEM_EDX_FILEANNOTATION_NS)
      - ImageAnnotationLink
      - OMERO Table with spectrum data
      - Optional PNG plot attachment (if plot_path provided)

    This is safe to run in background threads and does NOT touch the user's session.
    Prefer a detached end-user session when available so user-owned objects do
    not depend on job-service administrator privileges.
    """
    from omero.model import FileAnnotationI, OriginalFileI
    from omero.rtypes import rstring, rlong
    from omero.gateway import FileAnnotationWrapper
    from ..services.omero.sem_edx_parser import attach_sem_edx_tables

    def _attach_file(
        user_connection,
        image_obj,
        file_path: Path,
        mimetype: str,
    ):
        try:
            binary_data = file_path.read_bytes()
        except Exception as exc:
            raise RuntimeError(f"Unable to read file {file_path}: {exc}") from exc

        update_service = user_connection.getUpdateService()
        of = OriginalFileI()
        of.setName(rstring(file_path.name))
        of.setPath(rstring(f"sem_edx/img_{image_id}/"))
        of.setSize(rlong(len(binary_data)))
        of.setMimetype(rstring(mimetype))

        of = update_service.saveAndReturnObject(of)

        store = user_connection.c.sf.createRawFileStore()
        try:
            store.setFileId(of.getId().getValue())
            store.write(binary_data, 0, len(binary_data))
            save = getattr(store, "save", None)
            if callable(save):
                save()
        finally:
            try:
                store.close()
            except Exception as exc:
                logger.warning(
                    "Failed to close raw file store after attaching %s: %s",
                    file_path,
                    exc,
                )

        fa = FileAnnotationI()
        fa.setNs(rstring(SEM_EDX_FILEANNOTATION_NS))
        fa.setFile(of.proxy())

        fa = update_service.saveAndReturnObject(fa)
        image_obj.linkAnnotation(FileAnnotationWrapper(user_connection, fa))

    user_conn = _open_user_owned_background_connection(
        username,
        session_key=session_key,
        host=host,
        port=port,
        group_id=group_id,
        service_conn=conn,
        purpose=f"SEM-EDX attachment for Image:{image_id}",
    )
    if not user_conn:
        raise RuntimeError(f"Failed to create connection as user {username}")

    try:
        # Get the image in user's context
        image_obj = user_conn.getObject("Image", image_id)
        if not image_obj:
            raise RuntimeError(f"Image:{image_id} not found for user {username}")

        _attach_file(user_conn, image_obj, txt_path, "text/plain")

        # Parse the SEM EDX file and create OMERO Table with spectrum data
        try:
            table_id = attach_sem_edx_tables(
                user_conn, image_id, txt_path, persist_table=create_tables
            )
            if table_id:
                logger.info(
                    "Created OMERO Table for image %d from %s", image_id, txt_path.name
                )
        except Exception as exc:
            # Don't fail the entire attachment if table creation fails
            logger.error(
                "Failed to create OMERO Table for image %d from %s: %s",
                image_id,
                txt_path.name,
                exc,
            )
        if plot_path and plot_path.exists():
            try:
                _attach_file(user_conn, image_obj, plot_path, "image/png")
                logger.info(
                    "Attached SEM EDX spectrum plot %s to image %d",
                    plot_path.name,
                    image_id,
                )
            except Exception as exc:
                logger.error(
                    "Failed to attach SEM EDX plot %s to image %d: %s",
                    plot_path.name,
                    image_id,
                    exc,
                )
    finally:
        # Always close the user connection
        try:
            user_conn.close()
        except Exception as exc:
            logger.warning("Failed to close temporary user OMERO connection: %s", exc)


def _append_job_message(job: dict, message: str):
    if not message:
        return
    job.setdefault("messages", [])
    job["messages"].append(message)
    if len(job["messages"]) > MAX_IMPORT_LOG_LINES:
        job["messages"] = job["messages"][-MAX_IMPORT_LOG_LINES:]


def _append_job_error(job: dict, message: str):
    if not message:
        return
    job.setdefault("errors", [])
    job["errors"].append(message)
    if len(job["errors"]) > MAX_IMPORT_LOG_LINES:
        job["errors"] = job["errors"][-MAX_IMPORT_LOG_LINES:]


def _append_txt_attachment_message(
    job: dict, txt_name: str, image_name: str, success: bool
):
    label = "Txt attachment success" if success else "Txt attachment failure"
    _append_job_message(job, f"{label}: {txt_name} into {image_name}")


def _verify_import(conn, file_name: str, dataset_id=None):
    if dataset_id:
        try:
            dataset = conn.getObject("Dataset", dataset_id)
            if dataset is None:
                return False
            for image in dataset.listChildren():
                if getattr(image, "getName", None) and image.getName() == file_name:
                    return True
        except Exception:
            return False
        return False

    try:
        for image in conn.getObjects("Image", attributes={"name": file_name}):
            if getattr(image, "getName", None) and image.getName() == file_name:
                return True
    except Exception:
        return False
    return False


def _get_import_lock(username: str):
    key = username or "__default__"
    with _IMPORT_LOCKS_GUARD:
        lock = _IMPORT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _IMPORT_LOCKS[key] = lock
    return lock


def _safe_job_id(value: str) -> bool:
    return bool(value and isinstance(value, str) and JOB_ID_SANITIZER.match(value))


def _validated_job_id(value: str) -> str:
    if not _safe_job_id(value):
        raise ValueError("Invalid job id.")
    return uuid.UUID(hex=str(value).lower()).hex


def _job_lock_path(job_id: str) -> Path:
    return _resolve_managed_child_parts(
        _get_jobs_root(),
        (f".{_validated_job_id(job_id)}.lock",),
    )


_MANAGED_NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW", 0)
_MANAGED_DIRECTORY_CREATE_MODE = 0o700
_MANAGED_FILE_CREATE_MODE = 0o600
_MANAGED_COMPONENT_RE = re.compile(r"(?!\.{1,2}$)[^/\\\x00]+")


class _ManagedPathValidationError(ValueError):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


def _invalid_managed_path(display_path: str) -> _ManagedPathValidationError:
    return _ManagedPathValidationError(errors.invalid_filename(display_path))


def _managed_path_error_message(exc: Exception, fallback_path: str) -> str:
    message = getattr(exc, "public_message", "") or ""
    if (
        isinstance(exc, _ManagedPathValidationError)
        and (
            message.startswith("Invalid filename:")
            or message.startswith("Filename is too long")
            or message.startswith("File path is too long")
        )
    ):
        return message
    return errors.invalid_filename(fallback_path)


def _validate_managed_relative_parts(
    root: Path, relative_parts: tuple[str, ...], *, max_bytes: int = None
) -> tuple[Path, tuple[str, ...]]:
    if not relative_parts:
        raise _invalid_managed_path("")

    root_path = Path(root)
    current = root_path
    display_path = []
    normalized_parts = []

    for part in relative_parts:
        part_text = str(part or "")
        if (
            not part_text
            or part_text in {".", ".."}
            or "/" in part_text
            or "\\" in part_text
        ):
            raise _invalid_managed_path("/".join(relative_parts))
        display_path.append(part_text)
        normalized_parts.append(part_text)
        current = current / part_text
        if max_bytes is not None and len(os.fsencode(str(current))) > max_bytes:
            raise _ManagedPathValidationError(
                errors.file_path_too_long("/".join(display_path), max_bytes)
            )

    return root_path, tuple(normalized_parts)


def _managed_root_relative_parts(path: Path) -> tuple[Path, tuple[str, ...]]:
    candidate = Path(path)
    for root in (_get_upload_root(), _get_jobs_root()):
        root_path = Path(root)
        try:
            relative = candidate.relative_to(root_path)
        except ValueError:
            candidate_absolute = candidate.absolute()
            root_absolute = root_path.absolute()
            try:
                relative = candidate_absolute.relative_to(root_absolute)
            except ValueError:
                continue
        return root_path, relative.parts
    raise _ManagedPathValidationError("Directory is outside managed upload roots.")


def _validated_managed_component(component: str, display_path: str) -> str:
    component_text = str(component or "")
    if not _MANAGED_COMPONENT_RE.fullmatch(component_text):
        raise _invalid_managed_path(display_path)
    return component_text


def _managed_child_path(
    parent_path: Path,
    root_real_path: str,
    directory_name: str,
    display_path: str,
) -> Path:
    safe_name = _validated_managed_component(directory_name, display_path)
    candidate_path = os.path.realpath(os.path.join(os.fspath(parent_path), safe_name))
    if (
        candidate_path != root_real_path
        and not candidate_path.startswith(root_real_path + os.sep)
    ):
        raise _invalid_managed_path(display_path)
    return Path(candidate_path)


def _managed_path_lstat(path: Path, display_path: str):
    try:
        stat_result = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _invalid_managed_path(display_path) from exc
    if stat.S_ISLNK(stat_result.st_mode):
        raise _invalid_managed_path(display_path)
    return stat_result


def _managed_existing_directory_path(
    parent_path: Path,
    root_real_path: str,
    directory_name: str,
    display_path: str,
) -> Path:
    candidate_path = _managed_child_path(
        parent_path,
        root_real_path,
        directory_name,
        display_path,
    )
    stat_result = _managed_path_lstat(candidate_path, display_path)
    if stat_result is None:
        raise FileNotFoundError(os.fspath(candidate_path))
    if not stat.S_ISDIR(stat_result.st_mode):
        raise _invalid_managed_path(display_path)
    return candidate_path


def _create_managed_directory_path(
    parent_path: Path,
    root_real_path: str,
    directory_name: str,
    display_path: str,
) -> Path:
    safe_name = _validated_managed_component(directory_name, display_path)
    candidate_path = os.path.realpath(os.path.join(os.fspath(parent_path), safe_name))
    if (
        candidate_path != root_real_path
        and not candidate_path.startswith(root_real_path + os.sep)
    ):
        raise _invalid_managed_path(display_path)
    os.mkdir(candidate_path, _MANAGED_DIRECTORY_CREATE_MODE)
    created_path = Path(candidate_path)
    stat_result = _managed_path_lstat(created_path, display_path)
    if stat_result is None or not stat.S_ISDIR(stat_result.st_mode):
        raise _invalid_managed_path(display_path)
    return created_path


def _open_managed_upload_file(
    parent_path: Path,
    root_real_path: str,
    child_name: str,
    flags: int,
    display_path: str,
) -> int:
    safe_name = _validated_managed_component(child_name, display_path)
    candidate_path = os.path.realpath(os.path.join(os.fspath(parent_path), safe_name))
    if (
        candidate_path != root_real_path
        and not candidate_path.startswith(root_real_path + os.sep)
    ):
        raise _invalid_managed_path(display_path)
    _managed_path_lstat(Path(candidate_path), display_path)
    try:
        return os.open(candidate_path, flags | _MANAGED_NOFOLLOW_FLAG, _MANAGED_FILE_CREATE_MODE)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _invalid_managed_path(display_path) from exc
        raise


def _validate_existing_managed_path_segments(
    root_path: Path, normalized_parts: tuple[str, ...]
) -> None:
    root_real_path = os.path.realpath(os.fspath(root_path))
    current_path = Path(root_real_path)
    if not current_path.exists():
        return
    if not current_path.is_dir():
        raise FileNotFoundError(os.fspath(current_path))
    display_parts = []
    for directory_name in normalized_parts[:-1]:
        display_parts.append(directory_name)
        try:
            current_path = _managed_existing_directory_path(
                current_path,
                root_real_path,
                directory_name,
                "/".join(display_parts),
            )
        except FileNotFoundError:
            return
        except OSError as exc:
            raise _invalid_managed_path("/".join(display_parts)) from exc

    leaf_path = _managed_child_path(
        current_path,
        root_real_path,
        normalized_parts[-1],
        "/".join(normalized_parts),
    )
    _managed_path_lstat(leaf_path, "/".join(normalized_parts))


def _managed_parent_directory_path(
    root: Path,
    relative_parts: tuple[str, ...],
    *,
    max_bytes: int = None,
    create_parents: bool = False,
) -> tuple[Path, str, str, str]:
    root_path, normalized_parts = _validate_managed_relative_parts(
        root,
        relative_parts,
        max_bytes=max_bytes,
    )

    root_real_path = os.path.realpath(os.fspath(root_path))
    current_path = Path(root_real_path)
    if not current_path.is_dir():
        raise _invalid_managed_path("")
    display_parts = []

    for directory_name in normalized_parts[:-1]:
        display_parts.append(directory_name)
        display_path = "/".join(display_parts)
        try:
            current_path = _managed_existing_directory_path(
                current_path,
                root_real_path,
                directory_name,
                display_path,
            )
        except FileNotFoundError:
            if not create_parents:
                raise _invalid_managed_path(display_path)
            current_path = _create_managed_directory_path(
                current_path,
                root_real_path,
                directory_name,
                display_path,
            )
        except OSError as exc:
            raise _invalid_managed_path(display_path) from exc

    file_display_path = "/".join(normalized_parts)
    return current_path, normalized_parts[-1], root_real_path, file_display_path


def _resolve_managed_child_parts(
    root: Path, relative_parts: tuple[str, ...], *, max_bytes: int = None
) -> Path:
    root_path, normalized_parts = _validate_managed_relative_parts(
        root,
        relative_parts,
        max_bytes=max_bytes,
    )
    _validate_existing_managed_path_segments(root_path, normalized_parts)
    return root_path.joinpath(*normalized_parts)


def _resolve_managed_child_path(
    root: Path, relative_path: str, *, max_bytes: int = None
) -> Path:
    normalized_path, normalize_error = _normalize_upload_relative_path(relative_path)
    if normalize_error:
        raise _ManagedPathValidationError(normalize_error)

    return _resolve_managed_child_parts(
        root,
        PurePosixPath(normalized_path).parts,
        max_bytes=max_bytes,
    )


def _resolve_managed_directory_path(path: Path) -> Path:
    root_path, relative = _managed_root_relative_parts(Path(path))
    if not relative:
        return root_path
    if any(part in ("", ".", "..") for part in relative):
        raise _ManagedPathValidationError("Invalid managed directory path.")
    return _resolve_managed_child_parts(root_path, relative)


def _fsync_directory(path: Path):
    try:
        dir_fd = os.open(path, os.O_DIRECTORY)
    except (AttributeError, OSError):
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _fsync_jobs_directory():
    _fsync_directory(_get_jobs_root())


def _read_job_file(job_id: str):
    path = _job_path(job_id)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_job_file(job_id: str, job_dict):
    path = _job_path(job_id)
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
        os.replace(tmp_path, path)
        _fsync_jobs_directory()
        tmp_path = None
        return True
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                logger.debug("Suppressed exception in cleanup", exc_info=True)


def _apply_upload_updates(job_id: str, updates: list, errors: list):
    def apply_updates(job_dict):
        entries_by_id = {
            entry.get("upload_id"): entry for entry in job_dict.get("files", [])
        }
        for update in updates:
            entry = entries_by_id.get(update.get("upload_id"))
            if not entry:
                continue
            entry["status"] = update.get("status", entry.get("status"))
            if update.get("errors"):
                entry.setdefault("errors", []).extend(update["errors"])
        if errors:
            job_dict.setdefault("errors", []).extend(errors)
        uploaded_bytes = sum(
            entry.get("size", 0)
            for entry in job_dict.get("files", [])
            if entry.get("status") == "uploaded"
        )
        job_dict["uploaded_bytes"] = uploaded_bytes
        compatibility_pending = _compatibility_pending_entries(job_dict)
        if (
            compatibility_pending
            and job_dict.get("compatibility_status") != "incompatible"
        ):
            job_dict["compatibility_status"] = "checking"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    return _robust_update_job(job_id, apply_updates)


def _update_job(job_id: str, update_fn):
    return _robust_update_job(job_id, update_fn)


def _classify_compatibility_output(
    return_code: int,
    stdout: str,
    stderr: str,
    expected_file_path: Optional[Path] = None,
):
    """
    Classify OMERO import compatibility check output.

    Returns a tuple of (status, details) where status is one of:
    - "compatible": File can be imported
    - "incompatible": File format not supported
    - "error": Check failed due to an error

    CRITICAL: The -f flag ALWAYS returns exit code 0, even for incompatible files.
    Actual compatibility is determined by checking if import candidates exist in stdout.

    Stdout is checked FIRST because Java/Bio-Formats commonly writes warnings to stderr
    (log4j, reflection access, class loading) that would cause false "error" results if
    stderr were checked first.  Only treat stderr as a fatal error when stdout contains
    no usable information at all.
    """
    details = (stderr or stdout or "").strip()
    lowered = (stdout or "").strip().lower() + " " + (stderr or "").strip().lower()

    # 1. Check stdout for actual import candidates FIRST.
    #    If Bio-Formats found importable files, the file IS compatible regardless
    #    of any warnings/errors printed to stderr.
    has_candidates = _has_import_candidates_in_output(
        stdout or "",
        expected_file_path=expected_file_path,
    )
    if has_candidates:
        return "compatible", "File format supported by OMERO"

    # 2. Check for explicit incompatibility messages (in stdout OR stderr).
    incompatible_markers = [
        "unsupported",
        "unknown format",
        "no suitable reader",
        "cannot read",
        "not a supported",
        "cannot determine reader",
        "no reader found",
        "failed to determine reader",
    ]

    if any(marker in lowered for marker in incompatible_markers):
        return "incompatible", details

    # 3. No candidates found and no clear incompatibility message.
    #    Check stderr for fatal errors (missing file, CLI crash, etc.).
    if stderr and stderr.strip():
        stderr_lower = stderr.lower()
        fatal_indicators = [
            "no such file",
            "permission denied",
            "timeout",
        ]
        if any(indicator in stderr_lower for indicator in fatal_indicators):
            return "error", stderr.strip()

    # 4. Fallback: no candidates, no clear signal → incompatible.
    return "incompatible", details or "No importable files detected by Bio-Formats"


def _has_import_candidates_in_output(
    output: str,
    expected_file_path: Optional[Path] = None,
) -> bool:
    """
    Check if omero import -f output contains actual import candidates.

    The -f flag displays files grouped by import groups, separated by "#" comments.
    Real import candidates are non-empty, non-comment lines.

    Returns True if at least one import candidate is found.
    """
    if not output or not output.strip():
        return False

    candidates = _extract_import_candidates(output)
    if not candidates:
        return False

    if expected_file_path is None:
        return True

    try:
        expected_resolved = expected_file_path.resolve()
    except OSError:
        expected_resolved = expected_file_path
    expected_is_dir = expected_file_path.is_dir()

    for candidate in candidates:
        candidate_path = _parse_candidate_path_line(candidate)
        if candidate_path is None:
            continue
        try:
            resolved_candidate = candidate_path.resolve()
        except OSError:
            resolved_candidate = candidate_path
        if resolved_candidate == expected_resolved:
            return True
        if expected_is_dir:
            try:
                resolved_candidate.relative_to(expected_resolved)
            except ValueError:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
            else:
                return True

    for parsed_group in _parse_import_groups(output):
        group_path = parsed_group.get("group_path")
        if group_path is None:
            continue
        try:
            resolved_group = group_path.resolve()
        except OSError:
            resolved_group = group_path
        if resolved_group == expected_resolved:
            return True

    return False


def _extract_import_candidates(output: str):
    """
    Extract import candidates from OMERO import -f output.

    Returns a list of file paths that would be imported.
    This is used for additional validation after compatibility check.
    """
    if not output or not output.strip():
        return []

    candidates = []
    lines = output.strip().split("\n")

    skip_patterns = [
        "# group:",
        "to import",
        "file(s)",
        "group(s)",
        "call(s)",
        "parsed into",
        "setid",
        "reader:",
        "dry run",
        "would import",
    ]

    for line in lines:
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        # Skip metadata lines
        stripped_lower = stripped.lower()
        if any(pattern in stripped_lower for pattern in skip_patterns):
            continue

        parsed_candidate = _parse_candidate_path_line(stripped)
        if parsed_candidate is not None:
            candidates.append(str(parsed_candidate))

    return candidates


def _parse_candidate_path_line(line: str) -> Optional[Path]:
    """Parse an OMERO import candidate line into a concrete path.

    Returns ``None`` when the input does not look like a standalone path line.
    """
    raw = (line or "").strip()
    if not raw:
        return None

    unquoted = raw.strip('"').strip("'")
    if not unquoted:
        return None

    candidate = Path(unquoted)
    if not candidate.is_absolute():
        return None

    # Reject lines that include additional text and only keep concrete path entries.
    if str(candidate) != unquoted:
        return None

    return candidate


def _parse_import_groups(output: str):
    groups = []
    current_group = None

    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("# Group:"):
            group_header = stripped[len("# Group:") :].strip()
            group_path_text = group_header.split(" SPW:", 1)[0].strip()
            current_group = {
                "group_path": _parse_candidate_path_line(group_path_text),
                "members": [],
            }
            groups.append(current_group)
            continue

        if current_group is None or stripped.startswith("#"):
            continue

        member_path = _parse_candidate_path_line(stripped)
        if member_path is not None:
            current_group["members"].append(member_path)

    return groups


def _relative_path_within_root(relative_path: str, root_relative_path: str) -> bool:
    if not root_relative_path:
        return False
    return relative_path == root_relative_path or relative_path.startswith(
        f"{root_relative_path}/"
    )


def _common_relative_prefix(relative_paths: list[str]) -> str:
    if not relative_paths:
        return ""

    common_parts = list(PurePosixPath(relative_paths[0]).parts)
    for relative_path in relative_paths[1:]:
        parts = PurePosixPath(relative_path).parts
        max_len = min(len(common_parts), len(parts))
        match_len = 0
        while match_len < max_len and common_parts[match_len] == parts[match_len]:
            match_len += 1
        common_parts = common_parts[:match_len]
        if not common_parts:
            return ""

    return PurePosixPath(*common_parts).as_posix()


def _group_covers_all_active_paths_under_root(
    active_relative_paths: list[str],
    root_relative_path: str,
    covered_relative_paths: list[str],
) -> bool:
    if not root_relative_path or not covered_relative_paths:
        return False

    covered_relative_path_set = set(covered_relative_paths)
    found_any_active_path = False

    for active_relative_path in active_relative_paths:
        if not _relative_path_within_root(active_relative_path, root_relative_path):
            continue
        found_any_active_path = True
        if active_relative_path not in covered_relative_path_set:
            return False

    return found_any_active_path


def _looks_like_directory_package_root(
    active_relative_paths: list[str],
    root_relative_path: str,
    group_path_relative: str,
    covered_relative_paths: list[str],
) -> bool:
    if not root_relative_path or not covered_relative_paths:
        return False
    if group_path_relative and not _relative_path_within_root(
        group_path_relative, root_relative_path
    ):
        return False
    if not _group_covers_all_active_paths_under_root(
        active_relative_paths,
        root_relative_path,
        covered_relative_paths,
    ):
        return False

    root_name = PurePosixPath(root_relative_path).name
    root_parts = PurePosixPath(root_relative_path).parts
    direct_hidden_children = False
    distinct_first_children = set()
    has_nested_children = False

    for covered_relative_path in covered_relative_paths:
        covered_parts = PurePosixPath(covered_relative_path).parts
        if covered_parts[: len(root_parts)] != root_parts:
            continue
        suffix_parts = covered_parts[len(root_parts) :]
        if not suffix_parts:
            continue
        distinct_first_children.add(suffix_parts[0])
        if len(suffix_parts) == 1 and suffix_parts[0].startswith("."):
            direct_hidden_children = True
        if len(suffix_parts) > 1:
            has_nested_children = True

    if direct_hidden_children:
        return True

    if "." not in root_name.lstrip("."):
        return False

    if group_path_relative:
        root_depth = len(PurePosixPath(root_relative_path).parts)
        group_depth = len(PurePosixPath(group_path_relative).parts)
        if group_depth > root_depth + 1:
            return True

    return has_nested_children and len(distinct_first_children) > 1


def _collect_import_entries(job_dict, *, for_compatibility: bool = False):
    entries = []
    for index, entry in enumerate(job_dict.get("files", [])):
        rel_path = entry.get("relative_path")
        if not rel_path:
            continue
        if for_compatibility:
            if entry.get("status") != "uploaded":
                continue
            if entry.get("import_skip"):
                continue
            if entry.get("compatibility") or entry.get("compatibility_skip"):
                continue
        else:
            if entry.get("status") not in ("uploaded", "pending"):
                continue
            if entry.get("import_skip"):
                continue
        entries.append(
            {
                "index": index,
                "relative_path": rel_path,
                "staged_path": entry.get("staged_path")
                or _build_staged_relative_path(rel_path),
                "entry": entry,
            }
        )
    return entries


def _single_entry_import_unit(entry: dict):
    rel_path = entry["relative_path"]
    return {
        "cleanup_staged_paths": [entry["staged_path"]],
        "covered_indexes": [entry["index"]],
        "covered_relative_paths": [rel_path],
        "dataset_relative_path": rel_path,
        "index": entry["index"],
        "relative_path": rel_path,
        "staged_path": entry["staged_path"],
    }


def _probe_import_path(
    path: Path,
    staged_root: Path,
    active_relative_paths: list[str],
    cache: dict[str, dict],
):
    cache_key = str(path)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        staged_root_resolved = staged_root.resolve()
    except OSError:
        staged_root_resolved = staged_root
    try:
        result = _run_local_import_scan(path)
    except Exception as exc:
        logger.warning(
            "Import scan failed for %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(exc),
        )
        cached = {
            "coverage": set(),
            "groups": (),
            "returncode": -1,
            "stderr": str(exc),
            "stdout": "",
        }
        cache[cache_key] = cached
        return cached

    active_relative_path_set = set(active_relative_paths)
    groups = []
    coverage = set()

    for parsed_group in _parse_import_groups(result.stdout):
        group_path = parsed_group.get("group_path")
        member_paths = parsed_group.get("members") or []
        group_path_relative = None
        if group_path is not None:
            try:
                group_path_resolved = group_path.resolve()
            except OSError:
                group_path_resolved = group_path
            try:
                group_path_relative = group_path_resolved.relative_to(
                    staged_root_resolved
                ).as_posix()
            except ValueError:
                group_path_relative = None

        member_relative_paths = []
        for member_path in member_paths:
            try:
                member_resolved = member_path.resolve()
            except OSError:
                member_resolved = member_path
            try:
                member_relative_path = member_resolved.relative_to(
                    staged_root_resolved
                ).as_posix()
            except ValueError:
                continue
            if member_relative_path in active_relative_path_set:
                member_relative_paths.append(member_relative_path)

        if group_path_relative and group_path_relative in active_relative_path_set:
            member_relative_paths.append(group_path_relative)

        if not member_relative_paths:
            continue

        ordered_member_relative_paths = [
            relative_path
            for relative_path in active_relative_paths
            if relative_path in set(member_relative_paths)
        ]
        coverage.update(ordered_member_relative_paths)
        groups.append(
            {
                "covered_relative_paths": tuple(ordered_member_relative_paths),
                "group_path_relative": group_path_relative,
            }
        )

    cached = {
        "coverage": coverage,
        "groups": tuple(groups),
        "returncode": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout,
    }
    cache[cache_key] = cached
    return cached


def _build_import_units(
    job_dict, upload_root: Path, *, for_compatibility: bool = False
):
    active_entries = _collect_import_entries(
        job_dict, for_compatibility=for_compatibility
    )
    if not active_entries:
        return []

    active_relative_paths = [entry["relative_path"] for entry in active_entries]
    if len(set(active_relative_paths)) != len(active_relative_paths):
        logger.warning(
            "Duplicate relative paths detected in upload job during import planning; "
            "falling back to per-entry units."
        )
        return [_single_entry_import_unit(entry) for entry in active_entries]

    entry_by_relative_path = {entry["relative_path"]: entry for entry in active_entries}
    staged_root = upload_root / "_staged"
    probe_cache = {}

    covered_relative_paths = set()
    units = []

    for rel_path in active_relative_paths:
        if rel_path in covered_relative_paths:
            continue

        chosen_group = None
        current = PurePosixPath(rel_path).parent
        while current and str(current) != ".":
            dir_rel = current.as_posix()
            dir_path = staged_root / dir_rel
            if dir_path.exists() and dir_path.is_dir():
                probe = _probe_import_path(
                    dir_path, staged_root, active_relative_paths, probe_cache
                )
                matching_groups = [
                    group
                    for group in probe.get("groups", [])
                    if rel_path in group.get("covered_relative_paths", ())
                    and len(group.get("covered_relative_paths", ())) > 1
                ]
                if matching_groups:
                    chosen_group = sorted(
                        matching_groups,
                        key=lambda group: (
                            -len(group.get("covered_relative_paths", ())),
                            group.get("group_path_relative") or "",
                        ),
                    )[0]
                    break
            current = current.parent

        if chosen_group:
            group_coverage = [
                covered_rel_path
                for covered_rel_path in active_relative_paths
                if covered_rel_path in chosen_group["covered_relative_paths"]
                and covered_rel_path not in covered_relative_paths
            ]
            if group_coverage:
                common_root_relative_path = _common_relative_prefix(group_coverage)
                group_path_relative = (
                    chosen_group.get("group_path_relative") or group_coverage[0]
                )
                group_header_name = (
                    PurePosixPath(group_path_relative).name
                    if group_path_relative
                    else ""
                )
                if _looks_like_directory_package_root(
                    active_relative_paths,
                    common_root_relative_path,
                    group_path_relative,
                    group_coverage,
                ):
                    logical_relative_path = common_root_relative_path
                    dataset_relative_path = common_root_relative_path
                    staged_path = _build_staged_relative_path(common_root_relative_path)
                    cleanup_staged_paths = [staged_path]
                else:
                    logical_relative_path = group_path_relative
                    if group_path_relative in group_coverage:
                        dataset_relative_path = group_path_relative
                    else:
                        dataset_relative_path = group_coverage[0]
                    staged_path = _build_staged_relative_path(group_path_relative)
                    cleanup_staged_paths = [
                        entry_by_relative_path[covered_rel_path]["staged_path"]
                        for covered_rel_path in group_coverage
                    ]

                covered_relative_paths.update(group_coverage)
                unit = {
                    "cleanup_staged_paths": cleanup_staged_paths,
                    "covered_indexes": [
                        entry_by_relative_path[covered_rel_path]["index"]
                        for covered_rel_path in group_coverage
                    ],
                    "covered_relative_paths": group_coverage,
                    "dataset_relative_path": dataset_relative_path,
                    "index": entry_by_relative_path[group_coverage[0]]["index"],
                    "relative_path": logical_relative_path,
                    "staged_path": staged_path,
                }
                if (
                    group_header_name
                    and group_header_name != PurePosixPath(logical_relative_path).name
                ):
                    unit["group_header_name"] = group_header_name
                units.append(unit)
                continue

        # Fallback: if the probe found no group but this file belongs to a
        # known directory package (e.g. .zarr), group all uncovered files
        # under the same package root into one import unit.  This fires when
        # the OMERO CLI scan failed (timeout, OOM, crash) and prevents
        # individual zarr chunks from being imported as standalone files.
        #
        # Only activate when NO sibling under the same package root was
        # already covered by a probe group — if the probe did produce groups,
        # it intentionally excluded this file.
        package_root = _directory_package_root_for_relative_path(rel_path)
        if package_root:
            any_sibling_covered_by_probe = any(
                _directory_package_root_for_relative_path(covered_rp) == package_root
                for covered_rp in covered_relative_paths
            )
            if not any_sibling_covered_by_probe:
                package_entries = [
                    rp
                    for rp in active_relative_paths
                    if rp not in covered_relative_paths
                    and _directory_package_root_for_relative_path(rp) == package_root
                ]
                if package_entries:
                    logger.info(
                        "Probe-based grouping unavailable for directory package %s; "
                        "grouping %d file(s) by extension fallback.",
                        sanitize_log_value(package_root),
                        len(package_entries),
                    )
                    covered_relative_paths.update(package_entries)
                    staged_path = _build_staged_relative_path(package_root)
                    units.append(
                        {
                            "cleanup_staged_paths": [staged_path],
                            "covered_indexes": [
                                entry_by_relative_path[rp]["index"]
                                for rp in package_entries
                            ],
                            "covered_relative_paths": package_entries,
                            "dataset_relative_path": package_root,
                            "index": entry_by_relative_path[package_entries[0]][
                                "index"
                            ],
                            "relative_path": package_root,
                            "staged_path": staged_path,
                        }
                    )
                    continue

        entry = entry_by_relative_path[rel_path]
        covered_relative_paths.add(rel_path)
        units.append(_single_entry_import_unit(entry))

    all_entries = job_dict.get("files", [])
    for unit in units:
        covered_entries = [
            all_entries[entry_index]
            for entry_index in unit.get("covered_indexes", [])
            if isinstance(entry_index, int) and 0 <= entry_index < len(all_entries)
        ]
        _attach_import_routing_fields(unit, covered_entries)

    units.sort(key=lambda unit: unit["index"])
    return units


def _check_import_compatibility(
    session_key: str,
    host: str,
    port: int,
    file_path: Path,
    dataset_id: Optional[int],
    relative_path: str,
):
    """
    Check if a file can be imported into OMERO by analyzing it with Bio-Formats.

    CRITICAL FIXES:
    1. The -f flag ALWAYS returns exit code 0, regardless of compatibility
    2. Compatibility is determined by parsing stdout for import candidates
    3. Proper distinction between errors and incompatibility

    Uses 'omero import -f' which performs local file format analysis
    without requiring server connection or authentication.
    """
    if not file_path.exists():
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": f"Missing staged file: {file_path.name}",
            "details": f"Missing staged file: {file_path.name}",
        }

    native_plan = None
    native_plan_payload = None
    is_directory_zarr = file_path.is_dir() and any(
        file_path.name.lower().endswith(ext) for ext in DIRECTORY_PACKAGE_EXTENSIONS
    )
    if is_directory_zarr and _native_zarr_import_enabled():
        native_plan = _native_zarr_import_plan(file_path)
        native_plan_payload = _serialize_native_zarr_plan(native_plan)

    try:
        result = _run_local_import_scan(file_path)
    except subprocess.TimeoutExpired:
        timeout_seconds = _get_local_import_scan_timeout_seconds()
        response = {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": "Compatibility check timeout",
            "details": f"Compatibility check timeout after {timeout_seconds} seconds",
        }
        if is_directory_zarr:
            response["import_backend"] = _ZARR_IMPORT_BACKEND_BIOFORMATS
            if native_plan_payload is not None:
                response["native_zarr_plan"] = native_plan_payload
        return response
    except FileNotFoundError as exc:
        response = {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": str(exc),
            "details": f"OMERO CLI not found: {exc}",
        }
        if is_directory_zarr:
            response["import_backend"] = _ZARR_IMPORT_BACKEND_BIOFORMATS
            if native_plan_payload is not None:
                response["native_zarr_plan"] = native_plan_payload
        return response
    except Exception as exc:
        response = {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": str(exc),
            "details": f"Unexpected error during compatibility check: {exc}",
        }
        if is_directory_zarr:
            response["import_backend"] = _ZARR_IMPORT_BACKEND_BIOFORMATS
            if native_plan_payload is not None:
                response["native_zarr_plan"] = native_plan_payload
        return response

    # CRITICAL FIX: Classify based on stdout content, NOT return code
    status, details = _classify_compatibility_output(
        result.returncode,
        result.stdout,
        result.stderr,
        expected_file_path=file_path,
    )

    # Additional logging for debugging
    logger.debug(
        "Compatibility check for %s: status=%s, returncode=%d, stdout_lines=%d, stderr_lines=%d",
        relative_path,
        status,
        result.returncode,
        len((result.stdout or "").splitlines()),
        len((result.stderr or "").splitlines()),
    )

    if status == "compatible":
        response = {
            "status": status,
            "relative_path": relative_path,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "details": details or "Compatibility check completed.",
        }
        if is_directory_zarr:
            response["import_backend"] = _ZARR_IMPORT_BACKEND_BIOFORMATS
            if native_plan_payload is not None:
                response["native_zarr_plan"] = native_plan_payload
        return response

    if status == "incompatible" and is_directory_zarr:
        if native_plan and native_plan.kind:
            return {
                "status": "compatible",
                "relative_path": relative_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "details": native_plan.compatibility_details or details,
                "import_backend": _ZARR_IMPORT_BACKEND_NATIVE,
                "native_zarr_plan": native_plan_payload,
            }
        if native_plan and native_plan.recognized_zarr and native_plan.validation_error:
            return {
                "status": "error",
                "relative_path": relative_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "details": native_plan.validation_error,
                "import_backend": _ZARR_IMPORT_BACKEND_NATIVE,
                "native_zarr_plan": native_plan_payload,
            }

    response = {
        "status": status,
        "relative_path": relative_path,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "details": details or "Compatibility check completed.",
    }
    if is_directory_zarr:
        response["import_backend"] = _ZARR_IMPORT_BACKEND_BIOFORMATS
        if native_plan_payload is not None:
            response["native_zarr_plan"] = native_plan_payload
    return response


def _run_compatibility_check(job_id: str):
    try:
        _run_compatibility_check_inner(job_id)
    except Exception as exc:
        logger.error(
            "Compatibility check crashed for job %s: %s",
            sanitize_log_value(job_id),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )

        def reset_thread(job_dict):
            job_dict["compatibility_thread_active"] = False
            job_dict["compatibility_status"] = "error"
            _refresh_job_status(job_dict)
            job_dict["updated"] = time.time()
            return job_dict

        _update_job(job_id, reset_thread)


def _run_compatibility_check_inner(job_id: str):
    job = _load_job(job_id)
    if not job:
        return

    session_key = job.get("session_key")
    host = job.get("host")
    port = job.get("port")
    upload_root = _get_upload_root() / job_id
    planned_units = _build_import_units(job, upload_root, for_compatibility=True)
    if not planned_units:

        def mark_idle(job_dict):
            job_dict["planned_import_units"] = []
            job_dict["compatibility_thread_active"] = False
            has_uploaded = any(
                entry.get("status") == "uploaded" for entry in job_dict.get("files", [])
            )
            if has_uploaded:
                has_errors = any(
                    entry.get("compatibility") == "error"
                    for entry in job_dict.get("files", [])
                )
                if job_dict.get("incompatible_files"):
                    job_dict["compatibility_status"] = "incompatible"
                elif has_errors:
                    job_dict["compatibility_status"] = "error"
                else:
                    job_dict["compatibility_status"] = "compatible"
            else:
                if job_dict.get("compatibility_status") not in (
                    "incompatible",
                    "error",
                    "compatible",
                ):
                    job_dict["compatibility_status"] = "pending"
            _refresh_job_status(job_dict)
            job_dict["updated"] = time.time()
            return job_dict

        _update_job(job_id, mark_idle)
        return

    serialized_plans = [
        serialized
        for serialized in (_serialize_import_unit_plan(unit) for unit in planned_units)
        if serialized is not None
    ]

    def persist_plans(job_dict):
        job_dict["planned_import_units"] = serialized_plans
        job_dict["updated"] = time.time()
        return job_dict

    job = _update_job(job_id, persist_plans) or job

    if not job.get("compatibility_enabled", True):

        def mark_planning_ready(job_dict):
            job_dict["compatibility_thread_active"] = False
            if job_dict.get("compatibility_status") not in ("incompatible", "error"):
                job_dict["compatibility_status"] = "compatible"
            _refresh_job_status(job_dict)
            job_dict["updated"] = time.time()
            return job_dict

        _update_job(job_id, mark_planning_ready)
        return

    batch_size = _resolve_job_batch_size(job)
    units_to_check = planned_units[:batch_size]

    max_workers = min(4, len(units_to_check), os.cpu_count() or 2)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for unit in units_to_check:
            staged_path = unit.get("staged_path") or unit.get("relative_path")
            if not staged_path:
                continue
            file_path, staged_error = _resolve_staged_target_path(
                upload_root, staged_path
            )
            if staged_error:
                logger.warning(
                    "Compatibility check rejected staged path for job %s: relative_path=%s staged_path=%s error=%s",
                    job_id,
                    unit.get("relative_path"),
                    staged_path,
                    staged_error,
                )
                results.append(
                    {
                        "covered_indexes": unit.get("covered_indexes", []),
                        "covered_relative_paths": unit.get(
                            "covered_relative_paths", []
                        ),
                        "relative_path": unit.get("relative_path"),
                        "status": "error",
                        "details": staged_error,
                    }
                )
                continue
            dataset_name = _dataset_name_for_import_entry(
                unit, job.get("orphan_dataset_name")
            )
            dataset_id = (job.get("dataset_map") or {}).get(dataset_name)
            future = executor.submit(
                _check_import_compatibility,
                session_key,
                host,
                port,
                file_path,
                dataset_id,
                unit.get("relative_path"),
            )
            future_map[future] = unit
        for future in as_completed(future_map):
            unit = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.warning(
                    "Compatibility check failed for %s: %s",
                    unit.get("relative_path"),
                    exc,
                )
                result = {
                    "status": "error",
                    "stdout": "",
                    "stderr": str(exc),
                    "details": str(exc),
                }
            results.append(
                {
                    "covered_indexes": unit.get("covered_indexes", []),
                    "covered_relative_paths": unit.get("covered_relative_paths", []),
                    "relative_path": unit.get("relative_path"),
                    "status": result.get("status"),
                    "details": result.get("details", ""),
                    "import_backend": result.get("import_backend"),
                    "native_zarr_plan": result.get("native_zarr_plan"),
                }
            )

    new_incompatible = [
        rel_path
        for result in results
        if result.get("status") == "incompatible"
        for rel_path in result.get("covered_relative_paths", [])
        if isinstance(rel_path, str)
    ]

    def apply_results(job_dict):
        entries = job_dict.get("files", [])
        for result in results:
            covered_indexes = result.get("covered_indexes", [])
            status = result.get("status")
            for entry_index in covered_indexes:
                if entry_index is None or entry_index >= len(entries):
                    continue
                entry = entries[entry_index]
                if status == "compatible":
                    entry["compatibility"] = "compatible"
                elif status == "incompatible":
                    entry["compatibility"] = "incompatible"
                    entry.setdefault("compatibility_errors", []).append(
                        result.get("details") or "Import check failed."
                    )
                else:
                    entry["compatibility"] = "error"
                    entry.setdefault("compatibility_errors", []).append(
                        result.get("details") or "Compatibility check failed."
                    )
                entry["compatibility_details"] = result.get("details", "") or ""
                import_backend = result.get("import_backend")
                if import_backend:
                    entry["import_backend"] = import_backend
                else:
                    entry.pop("import_backend", None)
                native_zarr_plan = result.get("native_zarr_plan")
                if native_zarr_plan is not None:
                    entry["native_zarr_plan"] = native_zarr_plan
                else:
                    entry.pop("native_zarr_plan", None)

        existing_incompatible = set(job_dict.get("incompatible_files", []))
        existing_incompatible.update(filter(None, new_incompatible))
        job_dict["incompatible_files"] = sorted(existing_incompatible)

        pending_after = _compatibility_pending_entries(job_dict)
        has_errors = any(
            entry.get("compatibility") == "error" for entry in job_dict.get("files", [])
        )
        if job_dict["incompatible_files"]:
            job_dict["compatibility_status"] = "incompatible"
        elif pending_after:
            job_dict["compatibility_status"] = "checking"
        elif has_errors:
            job_dict["compatibility_status"] = "error"
        else:
            job_dict["compatibility_status"] = "compatible"
        job_dict["compatibility_thread_active"] = False
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    updated_job = _update_job(job_id, apply_results)
    if updated_job:
        if _should_start_compatibility_check(updated_job):
            _start_compatibility_check_thread(job_id)
            return


def _start_compatibility_check_thread(job_id: str):
    started = {"value": False}

    def mark_started(job_dict):
        if job_dict.get("compatibility_thread_active"):
            return job_dict
        job_dict["compatibility_thread_active"] = True
        if job_dict.get("compatibility_status") != "incompatible":
            job_dict["compatibility_status"] = "checking"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        started["value"] = True
        return job_dict

    job = _update_job(job_id, mark_started)
    if not job or not started["value"]:
        return
    worker = threading.Thread(
        target=_run_compatibility_check, args=(job_id,), daemon=True
    )
    worker.start()


@dataclass(frozen=True)
class _NativeZarrImportPlan:
    kind: Optional[str] = None
    recognized_zarr: bool = False
    validation_error: Optional[str] = None
    verify_lsid_prefix: bool = False
    compatibility_details: str = ""


_NATIVE_ZARR_KIND_OME_ZARR = OME_ZARR_IMPORT_KIND_IMAGE
_ZARR_IMPORT_BACKEND_BIOFORMATS = "bioformats"
_ZARR_IMPORT_BACKEND_NATIVE = "native_zarr"
_IMPORT_ROUTING_ENTRY_FIELDS = (
    "compatibility",
    "compatibility_details",
    "import_backend",
    "native_zarr_plan",
)


def _native_zarr_import_plan(zarr_path: Path) -> _NativeZarrImportPlan:
    inspection = inspect_ome_zarr_image(zarr_path)
    recognized_zarr = bool(getattr(inspection, "recognized", False))
    if not recognized_zarr:
        return _NativeZarrImportPlan()
    supported = bool(getattr(inspection, "supported", False))
    inspection_kind = getattr(inspection, "kind", None)
    if supported and not inspection_kind:
        inspection_kind = _NATIVE_ZARR_KIND_OME_ZARR
    return _NativeZarrImportPlan(
        kind=inspection_kind if supported else None,
        recognized_zarr=True,
        validation_error=getattr(inspection, "support_error", None),
        verify_lsid_prefix=bool(getattr(inspection, "verify_lsid_prefix", False)),
        compatibility_details=getattr(inspection, "compatibility_details", ""),
    )


def _serialize_native_zarr_plan(
    plan: Optional[_NativeZarrImportPlan],
) -> Optional[dict]:
    if not isinstance(plan, _NativeZarrImportPlan):
        return None
    if not (
        plan.kind
        or plan.recognized_zarr
        or plan.validation_error
        or plan.verify_lsid_prefix
        or plan.compatibility_details
    ):
        return None
    return {
        "kind": plan.kind,
        "recognized_zarr": bool(plan.recognized_zarr),
        "validation_error": plan.validation_error,
        "verify_lsid_prefix": bool(plan.verify_lsid_prefix),
        "compatibility_details": plan.compatibility_details,
    }


def _deserialize_native_zarr_plan(payload) -> _NativeZarrImportPlan:
    if isinstance(payload, _NativeZarrImportPlan):
        return payload
    if not isinstance(payload, dict):
        return _NativeZarrImportPlan()
    return _NativeZarrImportPlan(
        kind=payload.get("kind"),
        recognized_zarr=bool(payload.get("recognized_zarr", False)),
        validation_error=payload.get("validation_error"),
        verify_lsid_prefix=bool(payload.get("verify_lsid_prefix", False)),
        compatibility_details=payload.get("compatibility_details", "") or "",
    )


def _attach_import_routing_fields(unit: dict, covered_entries: list[dict]) -> None:
    if not covered_entries:
        return

    for field_name in _IMPORT_ROUTING_ENTRY_FIELDS:
        values = [
            entry.get(field_name) for entry in covered_entries if field_name in entry
        ]
        if not values:
            continue
        first_value = values[0]
        if all(value == first_value for value in values):
            unit[field_name] = first_value


ZARR_MANAGED_REPO_SCRIPT_NAME = "Manage_Zarr_ManagedRepository.py"
ZARR_SHARED_TRANSFER_SUBDIR = "managed-zarr-transfer"
ZARR_SHARED_TRANSFER_ROOT_MODE = 0o711
ZARR_SHARED_TRANSFER_TOKEN_MODE = 0o711
ZARR_SHARED_TRANSFER_DIR_MODE = 0o755
ZARR_SHARED_TRANSFER_FILE_MODE = 0o644


_SCRIPT_OUTPUT_PATTERN = re.compile(r"^\s*\*?\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$")


def _extract_script_outputs(text: str) -> dict[str, str]:
    outputs = {}
    for line in (text or "").splitlines():
        match = _SCRIPT_OUTPUT_PATTERN.match(line)
        if not match:
            continue
        key = (match.group(1) or "").strip()
        value = (match.group(2) or "").strip()
        if key:
            outputs[key] = value
    return outputs


def _shared_zarr_transfer_root() -> Path:
    root = get_plugin_tmp_dir(ZARR_SHARED_TRANSFER_SUBDIR)
    root.chmod(ZARR_SHARED_TRANSFER_ROOT_MODE)
    return root.resolve(strict=False)


def _normalize_shared_zarr_permissions(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    path.chmod(ZARR_SHARED_TRANSFER_DIR_MODE)
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        current_dir = Path(dirpath)
        if not current_dir.is_symlink():
            current_dir.chmod(ZARR_SHARED_TRANSFER_DIR_MODE)
        for name in dirnames:
            current_path = current_dir / name
            if current_path.is_symlink():
                continue
            current_path.chmod(ZARR_SHARED_TRANSFER_DIR_MODE)
        for name in filenames:
            current_path = current_dir / name
            if current_path.is_symlink():
                continue
            current_path.chmod(ZARR_SHARED_TRANSFER_FILE_MODE)


def _prepare_server_readable_zarr_source(
    file_path: Path,
) -> tuple[Optional[Path], Optional[Path], Optional[str]]:
    try:
        source = Path(file_path).resolve(strict=True)
    except OSError as exc:
        return None, None, f"Failed to resolve staged Zarr source: {exc}"

    if not source.is_dir():
        return None, None, f"Staged Zarr source is not a directory: {source}"

    transfer_root = _shared_zarr_transfer_root()
    transfer_parent = transfer_root / uuid.uuid4().hex
    try:
        transfer_parent.mkdir(mode=ZARR_SHARED_TRANSFER_TOKEN_MODE, exist_ok=False)
        transfer_parent.chmod(ZARR_SHARED_TRANSFER_TOKEN_MODE)
        shared_source = transfer_parent / source.name
        shutil.copytree(source, shared_source, symlinks=True)
        prepare_error = _prepare_native_zarr_copy(shared_source)
        if prepare_error:
            raise RuntimeError(prepare_error)
        _normalize_shared_zarr_permissions(shared_source)
        return shared_source, transfer_parent, None
    except Exception as exc:
        try:
            if transfer_parent.exists():
                shutil.rmtree(transfer_parent)
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)
        return None, None, f"Failed to prepare server-readable Zarr staging copy: {exc}"


def _cleanup_shared_zarr_transfer(path: Optional[Path]) -> None:
    if path is None:
        return
    transfer_root = _shared_zarr_transfer_root()
    target = Path(path).resolve(strict=False)
    try:
        target.relative_to(transfer_root)
    except ValueError:
        logger.warning(
            "Refusing to remove shared Zarr transfer path outside %s: %s",
            sanitize_log_value(transfer_root),
            sanitize_log_value(target),
        )
        return
    if target == transfer_root:
        logger.warning(
            "Refusing to remove shared Zarr transfer root directly: %s",
            sanitize_log_value(target),
        )
        return
    try:
        if target.exists():
            shutil.rmtree(target)
    except Exception as exc:
        logger.warning(
            "Failed to remove shared Zarr transfer path %s: %s",
            sanitize_log_value(target),
            sanitize_log_value(exc),
        )


def _iter_script_services(conn):
    if conn is None:
        return
    seen = set()
    for svc_getter in (
        lambda: conn.getScriptService(),
        lambda: conn.c.sf.getScriptService(),
    ):
        try:
            svc = svc_getter()
        except Exception:
            logger.debug("Skipping script service getter", exc_info=True)
            continue
        if svc is None or id(svc) in seen:
            continue
        seen.add(id(svc))
        yield svc


def _find_script_id_by_name(
    conn, script_name: str, *, preferred_path_fragment: Optional[str] = None
) -> Optional[int]:
    if conn is None or not script_name:
        return None

    best_sid = None
    best_preferred = False
    for svc in _iter_script_services(conn):
        try:
            scripts = svc.getScripts()
        except Exception:
            logger.debug("Failed to list scripts from service", exc_info=True)
            continue

        for script in scripts:
            try:
                name = str(
                    getattr(
                        getattr(script, "name", None),
                        "val",
                        getattr(script, "name", ""),
                    )
                    or ""
                )
                path = str(
                    getattr(
                        getattr(script, "path", None),
                        "val",
                        getattr(script, "path", ""),
                    )
                    or ""
                )
                sid = getattr(
                    getattr(script, "id", None), "val", getattr(script, "id", None)
                )
                sid = int(sid) if sid is not None else None
            except Exception:
                logger.debug("Skipping unparseable script entry", exc_info=True)
                continue

            if sid is None:
                continue

            basename = os.path.basename(name or path)
            if script_name not in {name, basename, path}:
                continue

            path_match = bool(
                preferred_path_fragment and preferred_path_fragment in path
            )
            if path_match and not best_preferred:
                best_sid = sid
                best_preferred = True
                continue
            if path_match == best_preferred and (best_sid is None or sid > best_sid):
                best_sid = sid

    return best_sid


def _run_zarr_managed_repo_script(
    action: str,
    host: str,
    port: int,
    *,
    username: str,
    group_name: str,
    source_path: Optional[Path] = None,
    managed_path: Optional[Path] = None,
) -> tuple[bool, dict[str, str], str]:
    admin_conn = _open_admin_connection(host, port)
    if admin_conn is None:
        return (
            False,
            {},
            "Unable to open an admin OMERO session for managed-repository Zarr staging.",
        )

    script_id = None
    try:
        script_id = _find_script_id_by_name(
            admin_conn,
            ZARR_MANAGED_REPO_SCRIPT_NAME,
            preferred_path_fragment="omero/import_scripts",
        )
    finally:
        try:
            admin_conn.close()
        except Exception:
            logger.debug("Suppressed exception in cleanup", exc_info=True)

    if script_id is None:
        return False, {}, f"OMERO script not found: {ZARR_MANAGED_REPO_SCRIPT_NAME}"

    root_pass = _get_root_password()
    if not root_pass:
        return (
            False,
            {},
            "ROOTPASS is missing; cannot launch the managed-repository Zarr helper.",
        )

    cmd = [OMERO_CLI, "-q"]
    if host:
        cmd.extend(["-s", host])
    if port:
        cmd.extend(["-p", str(port)])
    cmd.extend(["-u", "root", "script", "launch", str(int(script_id))])
    cmd.extend(
        [
            f"Action={action}",
            f"Group_Name={group_name}",
            f"Username={username}",
        ]
    )
    if source_path is not None:
        cmd.append(f"Source_Path={source_path}")
    if managed_path is not None:
        cmd.append(f"Managed_Path={managed_path}")

    env = _build_cli_env()
    env["OMERO_PASSWORD"] = root_pass
    helper_timeout = _get_import_timeout_seconds()
    retry_deadline = time.time() + _get_script_start_timeout_seconds()
    retry_sleep = _get_script_start_retry_seconds()

    while True:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=helper_timeout,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return False, {}, "Managed-repository Zarr helper timed out."
        except Exception as exc:
            return False, {}, str(exc)

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        combined = "\n".join(part for part in (stdout, stderr) if part)
        outputs = _extract_script_outputs(combined)
        if result.returncode == 0:
            return True, outputs, outputs.get("Message") or combined

        if (
            _reports_no_processor_available(stdout, stderr)
            and time.time() < retry_deadline
        ):
            time.sleep(retry_sleep)
            continue

        return (
            False,
            outputs,
            combined
            or f"Managed-repository Zarr helper failed with exit code {result.returncode}.",
        )


def _cleanup_managed_zarr_path(
    host: str,
    port: int,
    *,
    username: str,
    group_name: str,
    managed_path: Optional[Path],
) -> None:
    if managed_path is None:
        return
    success, _outputs, message = _run_zarr_managed_repo_script(
        "cleanup",
        host,
        port,
        username=username,
        group_name=group_name,
        managed_path=managed_path,
    )
    if not success:
        logger.warning(
            "Failed to clean staged managed-repository Zarr path %s: %s",
            sanitize_log_value(managed_path),
            _sanitize_cli_output_for_logging(message[:500]),
        )


def _import_zarr_via_cli(
    file_path: Path,
    session_key: str,
    host: str,
    port: int,
    dataset_id: Optional[int],
    import_name: Optional[str],
    rel_path: str,
    entry: dict,
    cleanup_staged_paths: list,
    covered_indexes: list,
    covered_relative_paths: list,
    group_id: Optional[int] = None,
    progress_job: Optional[dict] = None,
    username: Optional[str] = None,
    group_name: Optional[str] = None,
    native_plan: Optional[_NativeZarrImportPlan] = None,
) -> dict:
    """Import a Zarr image store using ``omero zarr import``.

    Stages the zarr into the OMERO managed repository via a server-side OMERO
    script, then runs ``omero zarr import`` against that final managed path.
    """
    if not username or not group_name:
        error_msg = (
            "Missing username or group name for managed-repository Zarr staging."
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    native_plan = native_plan or _native_zarr_import_plan(file_path)
    if not native_plan.kind:
        error_msg = (
            "Zarr source is not supported by the installed omero-cli-zarr runtime."
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }
    if native_plan.validation_error:
        error_msg = native_plan.validation_error
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    shared_source = None
    shared_transfer_parent = None
    prepare_error = None
    shared_source, shared_transfer_parent, prepare_error = (
        _prepare_server_readable_zarr_source(file_path)
    )
    if shared_source is None:
        error_msg = (
            prepare_error or "Failed to prepare a server-readable Zarr staging copy."
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    managed_zarr = None
    stage_message = None
    stage_outputs = {}
    try:
        try:
            stage_success, stage_outputs, stage_message = _run_zarr_managed_repo_script(
                "stage",
                host,
                port,
                username=username,
                group_name=group_name,
                source_path=shared_source,
            )
        except Exception as exc:
            stage_success = False
            stage_message = str(exc) or (
                "Failed to stage Zarr into the managed repository."
            )
            logger.error(
                "Managed-repository Zarr staging failed for %s: %s",
                sanitize_log_value(rel_path),
                sanitize_log_value(exc),
                exc_info=sanitized_exc_info(exc),
            )
        if stage_success:
            managed_path_raw = (stage_outputs.get("Managed_Path") or "").strip()
            if managed_path_raw:
                managed_zarr = Path(managed_path_raw)
    finally:
        try:
            _cleanup_shared_zarr_transfer(shared_transfer_parent)
        except Exception as exc:
            logger.warning(
                "Failed to clean shared Zarr transfer for %s: %s",
                sanitize_log_value(rel_path),
                sanitize_log_value(exc),
            )

    if managed_zarr is None:
        error_msg = stage_message or "Failed to stage Zarr into the managed repository."
        logger.error(
            "Failed to stage zarr %s into managed repository: %s",
            sanitize_log_value(rel_path),
            _sanitize_cli_output_for_logging(error_msg[:500]),
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    # --- Run omero zarr import ---------------------------------------------
    # Use an independent server-created user session, not the browser session
    # and not the shared job-service account, so ownership and target-dataset
    # permissions remain aligned with the importing user even if the browser
    # logs out mid-job.
    cmd = _build_omero_cli_command(["zarr", "import"], session_key, host, port)
    if dataset_id:
        cmd.extend(["--target", f"Dataset:{dataset_id}"])
    if import_name:
        cmd.extend(["--name", import_name])
    cmd.append(str(managed_zarr))

    env = _build_cli_env()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_get_import_timeout_seconds(),
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        success = result.returncode == 0

        logger.info(
            "omero zarr import for %s: returncode=%d stdout=%r stderr=%r",
            sanitize_log_value(rel_path),
            result.returncode,
            _sanitize_cli_output_for_logging(stdout.strip()[:500]),
            _sanitize_cli_output_for_logging(stderr.strip()[:500]),
        )
    except subprocess.TimeoutExpired:
        logger.error("omero zarr import timed out for %s", sanitize_log_value(rel_path))
        success = False
        stdout = ""
        stderr = f"Import timed out after {_get_import_timeout_seconds()} seconds"
    except Exception as exc:
        logger.error(
            "omero zarr import failed for %s: %s",
            sanitize_log_value(rel_path),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        success = False
        stdout = ""
        stderr = str(exc)

    # --- Detect created objects --------------------------------------------
    combined_output = stdout + "\n" + stderr
    imported_objects = _extract_imported_object_ids(combined_output)
    expected_lsid = None if native_plan.verify_lsid_prefix else str(managed_zarr)
    expected_lsid_prefix = str(managed_zarr) if native_plan.verify_lsid_prefix else None

    if username:
        api_objects = _verify_zarr_import_via_api(
            username,
            host,
            port,
            import_name,
            file_path.name,
            expected_lsid=expected_lsid,
            expected_lsid_prefix=expected_lsid_prefix,
            dataset_id=dataset_id,
            group_id=group_id,
            group_name=group_name,
        )
        if api_objects:
            imported_objects = api_objects
            logger.info(
                "OMERO API verification found native-zarr images for %s: %s",
                sanitize_log_value(rel_path),
                sanitize_log_value(imported_objects[:5]),
            )

    if not success and not imported_objects:
        error_msg = _classify_import_failure(stdout.strip(), stderr.strip())
        _cleanup_managed_zarr_path(
            host,
            port,
            username=username,
            group_name=group_name,
            managed_path=managed_zarr,
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    if not imported_objects:
        error_msg = errors.import_no_objects_created()
        _cleanup_managed_zarr_path(
            host,
            port,
            username=username,
            group_name=group_name,
            managed_path=managed_zarr,
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    metadata_ok, metadata_errors = _finalize_imported_zarr_image_metadata(
        username or "",
        host,
        port,
        imported_objects,
        managed_zarr=managed_zarr,
        group_id=group_id,
        group_name=group_name,
    )
    if not metadata_ok:
        _cleanup_imported_images(host, port, imported_objects)
        _cleanup_managed_zarr_path(
            host,
            port,
            username=username,
            group_name=group_name,
            managed_path=managed_zarr,
        )
        error_msg = "Native Zarr import failed metadata finalization: " + "; ".join(
            str(error) for error in metadata_errors[:3]
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    render_ok, render_errors = _verify_imported_zarr_images_renderable(
        username or "",
        host,
        port,
        imported_objects,
        expected_lsid=expected_lsid,
        expected_lsid_prefix=expected_lsid_prefix,
        group_id=group_id,
        group_name=group_name,
    )
    if not render_ok:
        _cleanup_imported_images(host, port, imported_objects)
        _cleanup_managed_zarr_path(
            host,
            port,
            username=username,
            group_name=group_name,
            managed_path=managed_zarr,
        )
        error_msg = (
            "Native Zarr import failed post-import render verification: "
            + "; ".join(str(error) for error in render_errors[:3])
        )
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    return {
        "cleanup_staged_paths": cleanup_staged_paths,
        "covered_indexes": covered_indexes,
        "covered_relative_paths": covered_relative_paths,
        "index": entry.get("index"),
        "status": "imported",
        "rel_path": rel_path,
        "file_path": managed_zarr,
    }


def _validate_native_ome_ngff_zarr(zarr_path: Path) -> Optional[str]:
    """Return an error string when *zarr_path* is not a safe native
    ``omero zarr import`` candidate, else ``None``.

    The authoritative interpretation comes from ``ome-zarr`` itself.
    """
    return _native_zarr_import_plan(zarr_path).validation_error


def _prepare_native_zarr_copy(zarr_path: Path) -> Optional[str]:
    """Validate an ephemeral copy for native Zarr import.

    The copy is safe to mutate because it is discarded after the managed
    repository handoff, but supported OME-NGFF layouts must remain faithful to
    the source contract. The current OMERO stack renders staged raw
    multiscale NGFF correctly; mutating those stores before native import can
    break thumbnail generation.
    """
    plan = _native_zarr_import_plan(zarr_path)
    if not plan.kind:
        return plan.validation_error or (
            "Zarr source is not supported by the installed omero-cli-zarr runtime."
        )
    if plan.validation_error:
        return plan.validation_error

    return normalize_native_ome_zarr_copy(zarr_path)


def _verify_zarr_import_via_api(
    username: str,
    host: str,
    port: int,
    import_name: Optional[str],
    file_name: str,
    *,
    expected_lsid: Optional[str] = None,
    expected_lsid_prefix: Optional[str] = None,
    dataset_id: Optional[int] = None,
    group_id: Optional[int] = None,
    group_name: Optional[str] = None,
) -> list[str]:
    """Return imported Image IDs for a native Zarr import.

    Prefer an ``externalInfo.lsid`` match so duplicate image names do not cause
    false positives. Fall back to the legacy name-based lookup only when an
    expected native Zarr LSID match is unavailable.
    """
    if not username:
        return []
    admin_conn = None
    conn = None
    try:
        admin_conn = _open_admin_connection(host, port)
        if admin_conn is None:
            return []
        conn = admin_conn.suConn(username)
        if not conn:
            return []
        if group_id is not None:
            conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
        elif group_name:
            conn.SERVICE_OPTS.setOmeroGroup(group_name)

        qs = conn.getQueryService()
        if expected_lsid or expected_lsid_prefix:
            params = omero.sys.ParametersI()
            query_parts = ["SELECT i.id FROM Image i"]
            where_parts = []
            if dataset_id is not None:
                query_parts.append("JOIN i.datasetLinks dl")
                params.addId(int(dataset_id))
                where_parts.insert(0, "dl.parent.id = :id")
            if expected_lsid:
                params.add("lsid", omero.rtypes.rstring(str(expected_lsid)))
                where_parts.append("i.details.externalInfo.lsid = :lsid")
            elif expected_lsid_prefix:
                prefix_value = str(expected_lsid_prefix).rstrip("/") + "/%"
                params.add("lsid_prefix", omero.rtypes.rstring(prefix_value))
                where_parts.append("i.details.externalInfo.lsid like :lsid_prefix")
            query_parts.append("WHERE " + " AND ".join(where_parts))
            rows = qs.projection(" ".join(query_parts), params, conn.SERVICE_OPTS)
            exact_ids = [str(row[0].val) for row in rows] if rows else []
            if exact_ids:
                return exact_ids

        if dataset_id is not None:
            return _verify_import_via_api(
                username,
                host,
                port,
                int(dataset_id),
                import_name,
                file_name,
                group_id=group_id,
                group_name=group_name,
            )
        return []
    except Exception as exc:
        logger.debug(
            "Native Zarr API verification failed for %s: %s",
            sanitize_log_value(expected_lsid or expected_lsid_prefix or file_name),
            sanitize_log_value(exc),
        )
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
        if admin_conn:
            try:
                admin_conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)


def _verify_imported_zarr_images_renderable(
    username: str,
    host: str,
    port: int,
    image_ids: list[str],
    *,
    expected_lsid: Optional[str] = None,
    expected_lsid_prefix: Optional[str] = None,
    group_id: Optional[int] = None,
    group_name: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Exercise OMERO's thumbnail/render path for newly imported Zarr images."""
    if not username:
        return False, [
            "Missing importing username for post-import render verification."
        ]

    unique_ids = []
    seen_ids = set()
    for image_id in image_ids:
        text_id = str(image_id).strip()
        if not text_id or text_id in seen_ids:
            continue
        seen_ids.add(text_id)
        unique_ids.append(text_id)
    if not unique_ids:
        return False, ["No imported Image IDs were available for render verification."]

    admin_conn = None
    conn = None
    errors_found = []
    try:
        admin_conn = _open_admin_connection(host, port)
        if admin_conn is None:
            return False, [
                "Failed to open an admin connection for render verification."
            ]
        conn = admin_conn.suConn(username)
        if conn is None:
            return False, [
                "Failed to open the importing user's session for render verification."
            ]
        if group_id is not None:
            conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
        elif group_name:
            conn.SERVICE_OPTS.setOmeroGroup(group_name)

        for image_id in unique_ids:
            try:
                image = conn.getObject("Image", int(image_id))
            except Exception as exc:
                errors_found.append(f"Image:{image_id} lookup failed: {exc}")
                continue
            if image is None:
                errors_found.append(
                    f"Image:{image_id} could not be loaded after import."
                )
                continue

            sizes = (
                int(image.getSizeX() or 0),
                int(image.getSizeY() or 0),
                int(image.getSizeZ() or 0),
                int(image.getSizeC() or 0),
                int(image.getSizeT() or 0),
            )
            if any(size <= 0 for size in sizes):
                errors_found.append(
                    "Image:%s has invalid dimensions after import: x=%d y=%d z=%d c=%d t=%d"
                    % ((image_id,) + sizes)
                )
                continue

            details = getattr(getattr(image, "_obj", None), "details", None)
            external_info = getattr(details, "externalInfo", None)
            if external_info is None:
                errors_found.append(
                    f"Image:{image_id} is missing externalInfo after native Zarr import."
                )
                continue
            lsid, _entity_type = _query_image_external_info(conn, int(image_id))
            if not lsid:
                lsid = _external_info_text(external_info, "lsid", "getLsid")
            if expected_lsid and lsid != str(expected_lsid):
                errors_found.append(
                    f"Image:{image_id} resolved to unexpected externalInfo.lsid {lsid!r}."
                )
                continue
            if expected_lsid_prefix:
                expected_prefix = str(expected_lsid_prefix).rstrip("/")
                if not lsid.startswith(expected_prefix + "/"):
                    errors_found.append(
                        f"Image:{image_id} resolved to unexpected externalInfo.lsid {lsid!r}."
                    )
                    continue

            for thumb_size in ((96, 96), (256, 256)):
                try:
                    thumbnail = image.getThumbnail(size=thumb_size, direct=True)
                except Exception as exc:
                    errors_found.append(
                        f"Image:{image_id} thumbnail {thumb_size[0]}x{thumb_size[1]} failed: {exc}"
                    )
                    break
                if not thumbnail:
                    errors_found.append(
                        f"Image:{image_id} thumbnail {thumb_size[0]}x{thumb_size[1]} returned no data."
                    )
                    break

        return len(errors_found) == 0, errors_found
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
        if admin_conn:
            try:
                admin_conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)


def _cleanup_imported_images(host: str, port: int, image_ids: list[str]) -> None:
    """Best-effort cleanup for images created by a failed native Zarr import."""
    cleaned_ids = []
    for image_id in image_ids:
        try:
            cleaned_ids.append(int(str(image_id)))
        except (TypeError, ValueError):
            continue
    if not cleaned_ids:
        return

    admin_conn = None
    try:
        admin_conn = _open_admin_connection(host, port)
        if admin_conn is None:
            return
        admin_conn.SERVICE_OPTS.setOmeroGroup("-1")
        admin_conn.deleteObjects("Image", cleaned_ids, wait=True)
    except Exception as exc:
        logger.warning(
            "Failed to delete imported native-Zarr images %s: %s",
            sanitize_log_value(cleaned_ids),
            sanitize_log_value(exc),
        )
    finally:
        if admin_conn:
            try:
                admin_conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)


def _verify_import_via_api(
    username: str,
    host: str,
    port: int,
    dataset_id: int,
    import_name: Optional[str],
    file_name: str,
    group_id: Optional[int] = None,
    group_name: Optional[str] = None,
) -> list[str]:
    """Query OMERO for images matching *import_name* (or *file_name*) in the
    target dataset.  Returns a list of Image ID strings if found, else [].

    This is a lightweight fallback for cases where the OMERO CLI returns
    non-zero or produces no object-ID output despite having committed the
    Image on the server side.
    """
    if not username:
        return []
    admin_conn = None
    conn = None
    try:
        admin_conn = _open_admin_connection(host, port)
        if admin_conn is None:
            return []
        conn = admin_conn.suConn(username)
        if not conn:
            return []
        if group_id is not None:
            conn.SERVICE_OPTS.setOmeroGroup(str(int(group_id)))
        elif group_name:
            conn.SERVICE_OPTS.setOmeroGroup(group_name)
        params = omero.sys.ParametersI()
        params.addId(dataset_id)
        # Search for the exact import name or file name in this dataset.
        candidates = [n for n in (import_name, file_name) if n]
        if not candidates:
            return []
        _params_add_string_list(params, "names", candidates)
        query = (
            "SELECT i.id FROM Image i "
            "JOIN i.datasetLinks dl "
            "WHERE dl.parent.id = :id AND i.name IN (:names)"
        )
        qs = conn.getQueryService()
        rows = qs.projection(query, params, conn.SERVICE_OPTS)
        return [str(row[0].val) for row in rows] if rows else []
    except Exception as exc:
        logger.debug(
            "OMERO API verification failed for dataset %s: %s",
            dataset_id,
            sanitize_log_value(exc),
        )
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)
        if admin_conn:
            try:
                admin_conn.close()
            except Exception:
                logger.debug("Suppressed exception in cleanup", exc_info=True)


def _import_job_entry(
    entry,
    upload_root,
    session_key,
    host,
    port,
    dataset_map,
    orphan_dataset_name,
    group_id=None,
    progress_job=None,
    username=None,
    group_name=None,
):
    rel_path = entry.get("relative_path")
    if not rel_path:
        return {"skip": True}

    cleanup_staged_paths = entry.get("cleanup_staged_paths") or []
    covered_indexes = entry.get("covered_indexes") or [entry.get("index")]
    covered_relative_paths = entry.get("covered_relative_paths") or [rel_path]

    staged_path = entry.get("staged_path") or rel_path
    file_path, staged_error = _resolve_staged_target_path(upload_root, staged_path)
    if staged_error:
        return {
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": staged_error,
            "job_error": staged_error,
            "job_message": staged_error,
        }
    if not file_path.exists():
        error_msg = errors.missing_staged_file(rel_path)
        return {
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": error_msg,
            "job_message": error_msg,
        }

    # Allow callers (SEM-EDX) to override dataset selection.
    dataset_id = entry.get("dataset_id_override")
    if dataset_id is None:
        dataset_name = _dataset_name_for_import_entry(entry, orphan_dataset_name)
        dataset_id = dataset_map.get(dataset_name)

    normalization_context = _build_import_name_normalization_context(entry, dataset_id)
    import_name = None
    if normalization_context:
        import_name = (normalization_context.get("desired_name") or "").strip() or None

    # For directory packages (.zarr), ensure the import name is set to the
    # directory name so OMERO doesn't fall back to an internal chunk
    # filename.  Uses the full name including extension — consistent with
    # _logical_import_entry_display_name() which returns PurePosixPath.name.
    if (
        import_name is None
        and file_path.is_dir()
        and any(
            file_path.name.lower().endswith(ext) for ext in DIRECTORY_PACKAGE_EXTENSIONS
        )
    ):
        import_name = file_path.name

    is_directory_zarr = file_path.is_dir() and any(
        file_path.name.lower().endswith(ext) for ext in DIRECTORY_PACKAGE_EXTENSIONS
    )
    _native_import_on = is_directory_zarr and _native_zarr_import_enabled()
    native_plan = (
        _deserialize_native_zarr_plan(entry.get("native_zarr_plan"))
        if _native_import_on
        else _NativeZarrImportPlan()
    )
    zarr_scan_status = None
    zarr_scan_details = ""
    zarr_import_backend = None
    has_precomputed_zarr_routing = (
        is_directory_zarr
        and entry.get("compatibility") in {"compatible", "incompatible", "error"}
        and entry.get("import_backend")
        in {
            _ZARR_IMPORT_BACKEND_BIOFORMATS,
            _ZARR_IMPORT_BACKEND_NATIVE,
        }
    )
    if has_precomputed_zarr_routing:
        zarr_scan_status = entry.get("compatibility")
        zarr_scan_details = entry.get("compatibility_details", "") or ""
        zarr_import_backend = entry.get("import_backend")
        if not _native_import_on and zarr_import_backend == _ZARR_IMPORT_BACKEND_NATIVE:
            zarr_import_backend = None
            zarr_scan_status = "incompatible"
        elif (
            zarr_import_backend == _ZARR_IMPORT_BACKEND_NATIVE and not native_plan.kind
        ):
            native_plan = _native_zarr_import_plan(file_path)
    elif is_directory_zarr:
        if _native_import_on:
            native_plan = _native_zarr_import_plan(file_path)
        try:
            zarr_scan_result = _run_local_import_scan(file_path)
        except subprocess.TimeoutExpired:
            timeout_seconds = _get_local_import_scan_timeout_seconds()
            zarr_scan_status = "error"
            zarr_scan_details = (
                f"Compatibility check timeout after {timeout_seconds} seconds"
            )
        except FileNotFoundError as exc:
            zarr_scan_status = "error"
            zarr_scan_details = f"OMERO CLI not found: {exc}"
        except Exception as exc:
            zarr_scan_status = "error"
            zarr_scan_details = f"Unexpected error during compatibility check: {exc}"
        else:
            zarr_scan_status, zarr_scan_details = _classify_compatibility_output(
                zarr_scan_result.returncode,
                zarr_scan_result.stdout,
                zarr_scan_result.stderr,
                expected_file_path=file_path,
            )
            if zarr_scan_status == "compatible":
                zarr_import_backend = _ZARR_IMPORT_BACKEND_BIOFORMATS
            elif (
                zarr_scan_status == "incompatible"
                and _native_import_on
                and native_plan
                and native_plan.kind
            ):
                zarr_import_backend = _ZARR_IMPORT_BACKEND_NATIVE

    # ------------------------------------------------------------------
    # Native OME-Zarr import path.
    #
    # Parse .zarr stores with ome-zarr first so routing stays grounded in the
    # upstream metadata model. Bio-Formats still remains the default import
    # path; the native branch only takes over when Bio-Formats explicitly
    # reports the staged .zarr as incompatible and ome-zarr recognizes it as a
    # layout supported by the installed omero-cli-zarr runtime.
    # ------------------------------------------------------------------
    with _background_import_session(
        username or "",
        host,
        port,
        group_id=group_id,
        group_name=group_name,
        timeout_hint_seconds=_get_import_timeout_seconds(),
    ) as background_session_key:
        if not background_session_key:
            error_msg = errors.missing_omero_connection_details()
            job_error = messages.job_error_with_path(rel_path, error_msg)
            return {
                "cleanup_staged_paths": cleanup_staged_paths,
                "covered_indexes": covered_indexes,
                "covered_relative_paths": covered_relative_paths,
                "index": entry.get("index"),
                "status": "error",
                "entry_error": error_msg,
                "job_error": job_error,
                "job_message": job_error,
            }
        if (
            is_directory_zarr
            and zarr_scan_status == "compatible"
            and zarr_import_backend == _ZARR_IMPORT_BACKEND_BIOFORMATS
        ):
            pass
        elif (
            is_directory_zarr
            and zarr_scan_status in {"compatible", "incompatible"}
            and zarr_import_backend == _ZARR_IMPORT_BACKEND_NATIVE
        ):
            if not native_plan or not native_plan.kind:
                error_msg = "Native OME-Zarr routing metadata is missing for the staged .zarr store."
                job_error = messages.job_error_with_path(rel_path, error_msg)
                return {
                    "cleanup_staged_paths": cleanup_staged_paths,
                    "covered_indexes": covered_indexes,
                    "covered_relative_paths": covered_relative_paths,
                    "index": entry.get("index"),
                    "status": "error",
                    "entry_error": error_msg,
                    "job_error": job_error,
                    "job_message": job_error,
                }
            if native_plan.validation_error:
                error_msg = native_plan.validation_error
                job_error = messages.job_error_with_path(rel_path, error_msg)
                return {
                    "cleanup_staged_paths": cleanup_staged_paths,
                    "covered_indexes": covered_indexes,
                    "covered_relative_paths": covered_relative_paths,
                    "index": entry.get("index"),
                    "status": "error",
                    "entry_error": error_msg,
                    "job_error": job_error,
                    "job_message": job_error,
                }
            return _import_zarr_via_cli(
                file_path=file_path,
                session_key=background_session_key,
                host=host,
                port=port,
                dataset_id=dataset_id,
                import_name=import_name,
                rel_path=rel_path,
                entry=entry,
                cleanup_staged_paths=cleanup_staged_paths,
                covered_indexes=covered_indexes,
                covered_relative_paths=covered_relative_paths,
                group_id=group_id,
                progress_job=progress_job,
                username=username,
                group_name=group_name,
                native_plan=native_plan,
            )
        if (
            has_precomputed_zarr_routing
            and is_directory_zarr
            and zarr_scan_status == "error"
        ):
            error_msg = zarr_scan_details or "Compatibility check failed."
            job_error = messages.job_error_with_path(rel_path, error_msg)
            return {
                "cleanup_staged_paths": cleanup_staged_paths,
                "covered_indexes": covered_indexes,
                "covered_relative_paths": covered_relative_paths,
                "index": entry.get("index"),
                "status": "error",
                "entry_error": error_msg,
                "job_error": job_error,
                "job_message": job_error,
            }
        if (
            is_directory_zarr
            and not has_precomputed_zarr_routing
            and zarr_scan_status == "incompatible"
            and native_plan
            and native_plan.recognized_zarr
            and native_plan.validation_error
        ):
            error_msg = native_plan.validation_error
            job_error = messages.job_error_with_path(rel_path, error_msg)
            return {
                "cleanup_staged_paths": cleanup_staged_paths,
                "covered_indexes": covered_indexes,
                "covered_relative_paths": covered_relative_paths,
                "index": entry.get("index"),
                "status": "error",
                "entry_error": error_msg,
                "job_error": job_error,
                "job_message": job_error,
            }
        if is_directory_zarr and zarr_scan_status == "incompatible":
            error_msg = (
                zarr_scan_details
                or "Bio-Formats did not recognize the staged .zarr store."
            )
            job_error = messages.job_error_with_path(rel_path, error_msg)
            return {
                "cleanup_staged_paths": cleanup_staged_paths,
                "covered_indexes": covered_indexes,
                "covered_relative_paths": covered_relative_paths,
                "index": entry.get("index"),
                "status": "error",
                "entry_error": error_msg,
                "job_error": job_error,
                "job_message": job_error,
            }

        try:
            success, stdout, stderr = _import_file(
                conn=None,
                session_key=background_session_key,
                host=host,
                port=port,
                path=file_path,
                dataset_id=dataset_id,
                import_name=import_name,
                progress_job=progress_job,
            )
        except Exception as exc:
            logger.error(
                "Import failed for %s: %s",
                sanitize_log_value(rel_path),
                sanitize_log_value(exc),
                exc_info=sanitized_exc_info(exc),
            )
            success = False
            stdout = ""
            stderr = ""

        # ------------------------------------------------------------------
        # Detect created objects.  The OMERO CLI prints object IDs to stdout
        # for most formats, but some formats/plugins use "Created Image 123".
        # Search both streams.  As a final fallback, query the OMERO API
        # through an independent admin-backed user connection.
        # ------------------------------------------------------------------
        combined_output = (stdout or "") + "\n" + (stderr or "")
        imported_objects = _extract_imported_object_ids(combined_output)

        if not imported_objects and dataset_id:
            api_objects = _verify_import_via_api(
                username or "",
                host,
                port,
                dataset_id,
                import_name,
                file_path.name,
                group_id=group_id,
                group_name=group_name,
            )
            if api_objects:
                imported_objects = api_objects
                logger.info(
                    "OMERO API verification found objects for %s: %s",
                    sanitize_log_value(rel_path),
                    sanitize_log_value(imported_objects[:5]),
                )

        if not success:
            if imported_objects:
                logger.warning(
                    "Import CLI returned non-zero for %s but %d objects "
                    "confirmed; treating as success.  stderr=%r",
                    sanitize_log_value(rel_path),
                    len(imported_objects),
                    _sanitize_cli_output_for_logging(str(stderr).strip()[:500]),
                )
            else:
                logger.warning(
                    "Import failed for %s (stdout=%r, stderr=%r).",
                    sanitize_log_value(rel_path),
                    _sanitize_cli_output_for_logging(str(stdout).strip()[:500]),
                    _sanitize_cli_output_for_logging(str(stderr).strip()[:500]),
                )
                error_msg = _classify_import_failure(
                    str(stdout).strip(), str(stderr).strip()
                )
                job_error = messages.job_error_with_path(rel_path, error_msg)
                return {
                    "cleanup_staged_paths": cleanup_staged_paths,
                    "covered_indexes": covered_indexes,
                    "covered_relative_paths": covered_relative_paths,
                    "index": entry.get("index"),
                    "status": "error",
                    "entry_error": error_msg,
                    "job_error": job_error,
                    "job_message": job_error,
                }

        if not imported_objects:
            logger.error(
                "Import CLI returned success for %s but no objects found in "
                "output or via API.  stdout=%r stderr=%r",
                sanitize_log_value(rel_path),
                _sanitize_cli_output_for_logging(str(stdout).strip()[:500]),
                _sanitize_cli_output_for_logging(str(stderr).strip()[:500]),
            )
            error_msg = errors.import_no_objects_created()
            job_error = messages.job_error_with_path(rel_path, error_msg)
            return {
                "cleanup_staged_paths": cleanup_staged_paths,
                "covered_indexes": covered_indexes,
                "covered_relative_paths": covered_relative_paths,
                "index": entry.get("index"),
                "status": "error",
                "entry_error": error_msg,
                "job_error": job_error,
                "job_message": job_error,
            }

        return {
            "cleanup_staged_paths": cleanup_staged_paths,
            "covered_indexes": covered_indexes,
            "covered_relative_paths": covered_relative_paths,
            "index": entry.get("index"),
            "status": "imported",
            "rel_path": rel_path,
            "file_path": file_path,
        }


def _mark_failed_job_for_deferred_cleanup(job_id: str) -> bool:
    retention_seconds = _get_failed_import_retention_seconds()
    upload_root = _get_upload_root()
    jobs_root = _get_jobs_root()
    results = [
        safe_mark_path_for_deferred_cleanup(
            upload_root / _validated_job_id(job_id),
            upload_root,
            ttl_seconds=retention_seconds,
        ),
        safe_mark_path_for_deferred_cleanup(
            _job_path(job_id),
            jobs_root,
            ttl_seconds=retention_seconds,
        ),
    ]
    if all(results):
        logger.info(
            "Marked failed job %s for deferred cleanup in %s seconds.",
            sanitize_log_value(job_id),
            retention_seconds,
        )
        return True
    logger.warning(
        "Failed to mark one or more artifacts for deferred cleanup for job %s.",
        sanitize_log_value(job_id),
    )
    return False


def _process_import_job(job_id: str):
    safe_job_id = sanitize_log_value(job_id)
    logger.info("Import thread started for job %s", safe_job_id)
    job = _load_job(job_id)
    if not job:
        logger.error("Import thread: job %s not found, aborting", safe_job_id)
        return

    try:
        username = job.get("username") or ""
        lock = _get_import_lock(username)
        safe_username = sanitize_log_value(username)

        LOCK_TIMEOUT = 900  # 15 minutes max wait for another import to finish
        logger.info(
            "Import thread: acquiring lock for user %s (job %s)",
            safe_username,
            safe_job_id,
        )
        acquired = lock.acquire(timeout=LOCK_TIMEOUT)
        if not acquired:
            logger.error(
                "Import lock timeout for user %s after %ds - a previous import may be stuck. "
                "Restart the OMERO-web container to clear stale locks.",
                safe_username,
                LOCK_TIMEOUT,
            )
            job = _load_job(job_id) or {"job_id": job_id}
            _append_job_error(
                job,
                "Import could not start: another import is stuck. Please restart OMERO-web.",
            )
            job["status"] = "error"
            _save_job(job)
            return

        logger.info(
            "Import thread: lock acquired for user %s (job %s)",
            safe_username,
            safe_job_id,
        )
        try:
            job = _load_job(job_id)
            if not job:
                return

            if job.get("status") in ("done", "error"):
                return

            job.setdefault("errors", [])
            job.setdefault("messages", [])
            job["status"] = "importing"
            job["import_progress_bytes"] = job.get("imported_bytes", 0)
            _save_job(job)

            host = job.get("host")
            port = job.get("port")
            if not username or not host or not port:
                job["status"] = "error"
                job["errors"].append(errors.missing_omero_connection_details())
                _save_job(job)
                return

            if not job.get("group_name") and job.get("group_id") is not None:
                admin_conn = _open_admin_connection(host, port)
                if admin_conn is not None:
                    try:
                        job["group_name"] = _resolve_group_name(
                            admin_conn,
                            job.get("group_id"),
                            group_name=job.get("group_name"),
                        )
                        _save_job(job)
                    finally:
                        try:
                            admin_conn.close()
                        except Exception:
                            logger.debug(
                                "Suppressed exception in cleanup", exc_info=True
                            )
            session_key = job.get("session_key")

            # IMPORTANT: never join/close the user's active OMERO.web session here.
            # Doing so can terminate their login. We validate session indirectly by
            # executing the import command and handling any authentication failure.

            upload_root = _get_upload_root() / job_id
            if not upload_root.exists():
                job["status"] = "error"
                job["errors"].append(errors.upload_folder_missing_on_server())
                _save_job(job)
                return

            batch_size = _resolve_job_batch_size(job)

            # ----------------------------------------------------------
            # Pre-process: mark skipped and incompatible files as done
            # so their bytes are counted in progress tracking.
            # ----------------------------------------------------------
            skipped_count = 0
            incompatible_skipped = 0
            for entry in job.get("files", []):
                if entry.get("status") not in ("uploaded", "pending"):
                    continue
                rel_path = entry.get("relative_path", "")

                # Files already flagged import_skip at job creation time
                if entry.get("import_skip"):
                    if entry.get("status") != "skipped":
                        entry["status"] = "skipped"
                        job["imported_bytes"] = job.get(
                            "imported_bytes", 0
                        ) + entry.get("size", 0)
                        _append_job_message(
                            job, messages.skipped_non_importable(rel_path)
                        )
                        skipped_count += 1
                    continue

                # Files the compatibility check marked as incompatible
                # should be auto-skipped rather than attempted and failed.
                if entry.get("compatibility") == "incompatible":
                    entry["status"] = "skipped"
                    entry["import_skip"] = True
                    job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get(
                        "size", 0
                    )
                    _append_job_message(job, messages.skipped_incompatible(rel_path))
                    incompatible_skipped += 1
                    continue

            if skipped_count or incompatible_skipped:
                logger.info(
                    "Import thread: pre-skipped %d non-importable + %d incompatible files for job %s",
                    skipped_count,
                    incompatible_skipped,
                    safe_job_id,
                )
                _save_job(job)

            # Keep OMERO CLI dry-run planning off the request path. Large grouped
            # formats such as .zarr can legitimately spend tens of seconds here.
            entries_to_import = _build_import_units(job, upload_root)
            datasets_ready, dataset_error = _ensure_job_dataset_targets(
                job, entries_to_import
            )
            if not datasets_ready:
                job["status"] = "error"
                _append_job_error(
                    job,
                    dataset_error or "Failed to create target dataset(s) for import.",
                )
                _save_job(job)
                return

            dataset_map = job.get("dataset_map") or {}
            orphan_dataset_name = job.get("orphan_dataset_name")
            _save_job(job)

            logger.info(
                "Import thread: %d logical import units to import for job %s (batch_size=%d)",
                len(entries_to_import),
                safe_job_id,
                batch_size,
            )

            for start in range(0, len(entries_to_import), batch_size):
                batch = entries_to_import[start : start + batch_size]
                if not batch:
                    continue
                logger.info(
                    "Import thread: processing batch %d-%d of %d for job %s",
                    start,
                    start + len(batch),
                    len(entries_to_import),
                    safe_job_id,
                )
                # Serialize live imports through a single CLI process.
                # The live stack shows intermittent OMERO.java/import-init failures when
                # several imports start at once against the shared CLI home/session.
                for entry_payload in batch:
                    try:
                        result = _import_job_entry(
                            entry_payload,
                            upload_root,
                            None,
                            host,
                            port,
                            dataset_map,
                            orphan_dataset_name,
                            group_id=job.get("group_id"),
                            progress_job=job,
                            username=job.get("username"),
                            group_name=job.get("group_name"),
                        )
                    except Exception as exc:
                        logger.error(
                            "Import future raised unexpected error: %s",
                            sanitize_log_value(exc),
                            exc_info=sanitized_exc_info(exc),
                        )
                        continue
                    if not result or result.get("skip"):
                        continue
                    covered_indexes = result.get("covered_indexes") or []
                    if not covered_indexes:
                        continue
                    covered_entries = [
                        job.get("files", [])[entry_index]
                        for entry_index in covered_indexes
                        if entry_index is not None
                        and entry_index < len(job.get("files", []))
                    ]
                    if not covered_entries:
                        continue

                    if result.get("status") == "error":
                        entry_error = result.get("entry_error")
                        for entry in covered_entries:
                            entry["status"] = "error"
                            if entry_error:
                                entry.setdefault("errors", []).append(entry_error)
                        if result.get("job_error"):
                            _append_job_error(job, result["job_error"])
                        if result.get("job_message"):
                            _append_job_message(job, result["job_message"])
                        # Count errored files as processed so the progress
                        # bar reflects that the file has been attempted.
                        job["imported_bytes"] = job.get("imported_bytes", 0) + sum(
                            entry.get("size", 0) for entry in covered_entries
                        )
                        job["import_progress_bytes"] = job["imported_bytes"]
                        _save_job(job)
                        continue

                    if result.get("status") == "imported":
                        rel_path = result.get("rel_path") or covered_entries[0].get(
                            "relative_path"
                        )
                        for entry in covered_entries:
                            entry["status"] = "imported"
                        job["imported_bytes"] = job.get("imported_bytes", 0) + sum(
                            entry.get("size", 0) for entry in covered_entries
                        )
                        job["import_progress_bytes"] = job["imported_bytes"]
                        if rel_path:
                            _append_job_message(job, messages.imported_file(rel_path))
                        cleanup_targets = []
                        for cleanup_staged_path in (
                            result.get("cleanup_staged_paths") or []
                        ):
                            cleanup_target, cleanup_error = _resolve_staged_target_path(
                                upload_root,
                                cleanup_staged_path,
                            )
                            if cleanup_error:
                                logger.warning(
                                    "Failed to resolve staged cleanup target %s: %s",
                                    sanitize_log_value(cleanup_staged_path),
                                    sanitize_log_value(cleanup_error),
                                )
                                continue
                            cleanup_targets.append(cleanup_target)
                        for cleanup_target in sorted(
                            set(cleanup_targets),
                            key=lambda path: (len(path.parts), str(path)),
                            reverse=True,
                        ):
                            try:
                                if cleanup_target.is_dir():
                                    shutil.rmtree(cleanup_target, ignore_errors=False)
                                elif cleanup_target.exists():
                                    cleanup_target.unlink()
                            except OSError as exc:
                                logger.warning(
                                    "Failed to remove staged import payload %s: %s",
                                    sanitize_log_value(cleanup_target),
                                    sanitize_log_value(exc),
                                )
                        _save_job(job)

            job = _load_job(job_id) or job
            sem_edx_associations = job.get("sem_edx_associations") or {}
            sem_edx_settings = job.get("sem_edx_settings") or {}
            create_tables = sem_edx_settings.get("create_tables", True)
            create_figures_attachments = sem_edx_settings.get(
                "create_figures_attachments", True
            )
            create_figures_images = sem_edx_settings.get("create_figures_images", True)

            if (
                job.get("special_upload") == "sem_edx_spectra"
                and not sem_edx_associations
            ):
                # Fallback: derive associations server-side from uploaded file list.
                derived = _build_sem_edx_associations_from_entries(job.get("files", []))
                if derived:
                    sem_edx_associations = derived
                    job["sem_edx_associations"] = derived
                    _append_job_message(
                        job,
                        f"SEM EDX: derived {sum(len(v) for v in derived.values())} TXT attachment(s) from uploaded files (no UI associations received)",
                    )
                    _save_job(job)
                else:
                    logger.info(
                        "SEM EDX mode enabled for job %s but no TXT/image associations could be derived; skipping TXT attachments",
                        safe_job_id,
                    )
                    _append_job_message(
                        job,
                        "SEM EDX: no TXT/image associations found; skipping TXT attachments",
                    )
                    _save_job(job)

            if job.get("special_upload") == "sem_edx_spectra" and sem_edx_associations:
                try:
                    conn = _open_service_connection(
                        host, port, group_id=job.get("group_id")
                    )
                    if not conn:
                        logger.error(
                            "Failed to open SEM-EDX service connection for TXT attachments"
                        )
                        _append_job_message(
                            job,
                            "SEM EDX: failed to open service connection for TXT attachments",
                        )
                        _save_job(job)
                    else:
                        try:
                            entries_by_path = {
                                entry.get("relative_path"): entry
                                for entry in job.get("files", [])
                            }
                            attachment_count = 0
                            total_attachments = sum(
                                len(txt_paths)
                                for txt_paths in sem_edx_associations.values()
                                if isinstance(txt_paths, list)
                            )

                            logger.info(
                                "Processing %d SEM EDX text attachments for job %s",
                                total_attachments,
                                safe_job_id,
                            )

                            # CRITICAL FIX: Batch lookup ALL images at once instead of one-by-one
                            logger.info(
                                "Pre-loading image cache for %d images",
                                len(sem_edx_associations),
                            )
                            all_image_names = []
                            image_to_dataset = {}  # Track which dataset each image should be in

                            for image_rel in sem_edx_associations.keys():
                                image_name = (
                                    PurePosixPath(image_rel).name if image_rel else ""
                                )
                                if image_name:
                                    all_image_names.append(image_name)
                                    dataset_name = _dataset_name_for_path(
                                        image_rel, orphan_dataset_name
                                    )
                                    dataset_id = dataset_map.get(dataset_name)
                                    image_to_dataset[image_name] = dataset_id

                            # Do batch lookup - this is 100-1000x faster than individual lookups
                            image_cache = {}
                            datasets_to_search = set(image_to_dataset.values())

                            for dataset_id in datasets_to_search:
                                if dataset_id:
                                    # Find all images for this dataset
                                    dataset_images = [
                                        name
                                        for name, did in image_to_dataset.items()
                                        if did == dataset_id
                                    ]
                                    if dataset_images:
                                        batch_results = _batch_find_images_by_name(
                                            conn, dataset_images, dataset_id
                                        )
                                        image_cache.update(
                                            {
                                                name: img
                                                for name, img in batch_results.items()
                                            }
                                        )

                            # Fallback: global search for images not found in datasets
                            missing_images = set(all_image_names) - set(
                                image_cache.keys()
                            )
                            if missing_images:
                                logger.info(
                                    "Searching globally for %d missing images",
                                    len(missing_images),
                                )
                                global_results = _batch_find_images_by_name(
                                    conn, list(missing_images), None
                                )
                                image_cache.update(global_results)

                            logger.info(
                                "Image cache loaded: %d/%d found",
                                len(image_cache),
                                len(all_image_names),
                            )

                            plot_cache = {}
                            plot_rel_cache = {}
                            imported_plots = set()
                            if create_figures_attachments or create_figures_images:
                                from ..services.omero.sem_edx_parser import (
                                    create_edx_spectrum_plot,
                                )

                            # Now process attachments using cached images
                            for attachment_idx, (image_rel, txt_paths) in enumerate(
                                sem_edx_associations.items()
                            ):
                                if not isinstance(txt_paths, list):
                                    continue

                                # Progress logging
                                progress_pct = (
                                    attachment_idx / len(sem_edx_associations)
                                ) * 100
                                logger.info(
                                    "Processing image %d/%d (%.1f%%) - %s",
                                    attachment_idx + 1,
                                    len(sem_edx_associations),
                                    progress_pct,
                                    sanitize_log_value(image_rel),
                                )

                                image_name = (
                                    PurePosixPath(image_rel).name if image_rel else ""
                                )

                                # Validate job-service session periodically (every 10 attachments).
                                # IMPORTANT: NEVER reconnect using the end-user session_key here.
                                if attachment_count > 0 and attachment_count % 10 == 0:
                                    if not _validate_session(conn):
                                        logger.warning(
                                            "job-service session expired, reopening service connection..."
                                        )
                                        try:
                                            try:
                                                conn.close()
                                            except Exception as close_exc:
                                                logger.debug(
                                                    "Failed to close expired job-service connection: %s",
                                                    sanitize_log_value(close_exc),
                                                )
                                            conn = _open_service_connection(
                                                host, port, group_id=job.get("group_id")
                                            )
                                        except Exception:
                                            conn = None

                                        if not conn:
                                            logger.error(
                                                "Failed to reopen job-service connection, aborting SEM EDX attachments"
                                            )
                                            break

                                        # Re-populate cache after reconnect
                                        logger.info(
                                            "Re-loading image cache after reconnect"
                                        )
                                        image_cache.clear()
                                        for dataset_id in datasets_to_search:
                                            if dataset_id:
                                                dataset_images = [
                                                    name
                                                    for name, did in image_to_dataset.items()
                                                    if did == dataset_id
                                                ]
                                                if dataset_images:
                                                    batch_results = (
                                                        _batch_find_images_by_name(
                                                            conn,
                                                            dataset_images,
                                                            dataset_id,
                                                        )
                                                    )
                                                    image_cache.update(batch_results)
                                        missing_images = set(all_image_names) - set(
                                            image_cache.keys()
                                        )
                                        if missing_images:
                                            global_results = _batch_find_images_by_name(
                                                conn, list(missing_images), None
                                            )
                                            image_cache.update(global_results)

                                # Get cached image (no query needed!)
                                image_obj = image_cache.get(image_name)

                                # Process each text file for this image
                                for txt_rel in txt_paths:
                                    txt_name = PurePosixPath(txt_rel).name
                                    attachment_count += 1

                                    if not image_obj:
                                        logger.warning(
                                            "Image not found for %s, skipping attachment",
                                            txt_name,
                                        )
                                        _append_txt_attachment_message(
                                            job,
                                            txt_name,
                                            image_name or image_rel,
                                            False,
                                        )
                                        continue

                                    image_id = _get_id(image_obj)
                                    if not image_id:
                                        logger.warning(
                                            "Could not get image ID for %s, skipping %s",
                                            sanitize_log_value(image_name),
                                            sanitize_log_value(txt_name),
                                        )
                                        _append_txt_attachment_message(
                                            job,
                                            txt_name,
                                            image_name or image_rel,
                                            False,
                                        )
                                        continue

                                    sem_dataset_id = None
                                    try:
                                        for ds in image_obj.listParents():
                                            sem_dataset_id = ds.getId()
                                            break
                                    except Exception:
                                        sem_dataset_id = None

                                    logger.info(
                                        "SEM-EDX: SEM image dataset resolved from OMERO: image=%s image_id=%s sem_dataset_id=%s",
                                        image_name,
                                        image_id,
                                        sem_dataset_id,
                                    )

                                    txt_entry = entries_by_path.get(txt_rel)
                                    if not txt_entry:
                                        logger.warning(
                                            "Text entry not found for %s, skipping",
                                            sanitize_log_value(txt_rel),
                                        )
                                        _append_txt_attachment_message(
                                            job, txt_name, image_name, False
                                        )
                                        continue

                                    staged_path = (
                                        txt_entry.get("staged_path") or txt_rel
                                    )
                                    txt_path, staged_error = (
                                        _resolve_staged_target_path(
                                            upload_root, staged_path
                                        )
                                    )
                                    if staged_error:
                                        logger.warning(
                                            "Rejected SEM-EDX text staged path for job %s: txt=%s staged=%s error=%s",
                                            safe_job_id,
                                            sanitize_log_value(txt_rel),
                                            sanitize_log_value(staged_path),
                                            sanitize_log_value(staged_error),
                                        )
                                        _append_job_error(job, staged_error)
                                        _append_txt_attachment_message(
                                            job, txt_name, image_name, False
                                        )
                                        continue

                                    if not txt_path.exists():
                                        logger.warning(
                                            "Text file not found at %s, skipping",
                                            sanitize_log_value(txt_path),
                                        )
                                        _append_txt_attachment_message(
                                            job, txt_name, image_name, False
                                        )
                                        continue

                                    plot_path = None
                                    plot_rel = None
                                    if (
                                        create_figures_attachments
                                        or create_figures_images
                                    ):
                                        if txt_rel in plot_cache:
                                            plot_path = plot_cache.get(txt_rel)
                                            plot_rel = plot_rel_cache.get(txt_rel)
                                        else:
                                            plot_path = create_edx_spectrum_plot(
                                                txt_path
                                            )
                                            plot_cache[txt_rel] = plot_path
                                            if plot_path:
                                                plot_rel = str(
                                                    PurePosixPath(txt_rel).with_name(
                                                        plot_path.name
                                                    )
                                                )
                                                plot_rel_cache[txt_rel] = plot_rel

                                    if (
                                        create_figures_images
                                        and plot_path
                                        and plot_rel
                                        and txt_rel not in imported_plots
                                    ):
                                        plot_import_rel = str(
                                            PurePosixPath(image_rel).with_name(
                                                PurePosixPath(plot_rel).name
                                            )
                                        )
                                        plot_staged_rel = _build_staged_relative_path(
                                            plot_import_rel
                                        )

                                        staged_plot_path, staged_plot_error = (
                                            _resolve_staged_target_path(
                                                upload_root,
                                                plot_staged_rel,
                                            )
                                        )
                                        if staged_plot_error:
                                            logger.warning(
                                                "Rejected SEM-EDX plot staged path for job %s: rel=%s staged=%s error=%s",
                                                safe_job_id,
                                                sanitize_log_value(plot_import_rel),
                                                sanitize_log_value(plot_staged_rel),
                                                sanitize_log_value(staged_plot_error),
                                            )
                                            _append_job_error(job, staged_plot_error)
                                            imported_plots.add(txt_rel)
                                            continue
                                        try:
                                            staged_plot_path.parent.mkdir(
                                                parents=True, exist_ok=True
                                            )
                                            shutil.copy2(plot_path, staged_plot_path)
                                        except Exception as exc:
                                            logger.error(
                                                "Failed to stage SEM-EDX plot PNG for import: src=%s dst=%s error=%s",
                                                sanitize_log_value(plot_path),
                                                sanitize_log_value(staged_plot_path),
                                                sanitize_log_value(exc),
                                                exc_info=sanitized_exc_info(exc),
                                            )
                                            _append_job_error(
                                                job,
                                                f"Failed to stage SEM-EDX plot PNG for import: {staged_plot_path.name}",
                                            )
                                            imported_plots.add(txt_rel)
                                            continue

                                        logger.info(
                                            "SEM-EDX: plot staged for import: rel=%s staged=%s exists=%s",
                                            sanitize_log_value(plot_import_rel),
                                            sanitize_log_value(staged_plot_path),
                                            staged_plot_path.exists(),
                                        )

                                        import_entry = {
                                            "relative_path": plot_import_rel,
                                            "staged_path": plot_staged_rel,
                                            "dataset_id_override": sem_dataset_id,
                                        }
                                        import_result = _import_job_entry(
                                            import_entry,
                                            upload_root,
                                            session_key,
                                            host,
                                            port,
                                            dataset_map,
                                            orphan_dataset_name,
                                            progress_job=job,
                                            username=job.get("username"),
                                            group_name=job.get("group_name"),
                                        )
                                        if import_result.get("status") == "error":
                                            if import_result.get("job_error"):
                                                _append_job_error(
                                                    job, import_result["job_error"]
                                                )
                                            if import_result.get("job_message"):
                                                _append_job_message(
                                                    job, import_result["job_message"]
                                                )
                                            logger.error(
                                                "Failed to import SEM EDX plot %s (dataset_id=%s staged=%s)",
                                                sanitize_log_value(plot_import_rel),
                                                sem_dataset_id,
                                                sanitize_log_value(
                                                    str(staged_plot_path)
                                                ),
                                            )
                                        elif import_result.get("status") == "imported":
                                            _append_job_message(
                                                job,
                                                messages.imported_file(plot_import_rel),
                                            )
                                            logger.info(
                                                "Imported SEM EDX plot %s into dataset_id=%s",
                                                sanitize_log_value(plot_import_rel),
                                                sem_dataset_id,
                                            )
                                        imported_plots.add(txt_rel)

                                    # Attach via OMERO API with a detached user session when available.
                                    # This keeps ownership/group context aligned with the importing
                                    # user without requiring job-service to be an OMERO administrator.
                                    try:
                                        logger.info(
                                            "Attaching %s to %s (Image:%d)",
                                            sanitize_log_value(txt_name),
                                            sanitize_log_value(image_name),
                                            image_id,
                                        )
                                        _attach_txt_to_image_service(
                                            conn,
                                            image_id,
                                            txt_path,
                                            username,
                                            create_tables,
                                            plot_path=plot_path
                                            if create_figures_attachments
                                            else None,
                                            session_key=session_key,
                                            host=host,
                                            port=port,
                                            group_id=job.get("group_id"),
                                        )

                                        # Mark as imported if not already
                                        if txt_entry.get("status") != "imported":
                                            txt_entry["status"] = "imported"
                                            job["imported_bytes"] = job.get(
                                                "imported_bytes", 0
                                            ) + txt_entry.get("size", 0)

                                        _append_txt_attachment_message(
                                            job, txt_name, image_name, True
                                        )
                                        logger.info(
                                            "Successfully attached %s to %s",
                                            sanitize_log_value(txt_name),
                                            sanitize_log_value(image_name),
                                        )

                                    except Exception as exc:
                                        logger.error(
                                            "Failed to attach %s to %s: %s",
                                            sanitize_log_value(txt_rel),
                                            sanitize_log_value(image_rel),
                                            sanitize_log_value(exc),
                                            exc_info=sanitized_exc_info(exc),
                                        )
                                        _append_txt_attachment_message(
                                            job, txt_name, image_name, False
                                        )

                                    # Save job state periodically
                                    if attachment_count % 5 == 0:
                                        _save_job(job)

                            # Final save
                            _save_job(job)
                            logger.info(
                                "Completed SEM EDX attachment processing for job %s: %d/%d processed",
                                safe_job_id,
                                attachment_count,
                                total_attachments,
                            )

                        finally:
                            try:
                                conn.close()
                            except Exception as exc:
                                logger.warning(
                                    "Error closing connection: %s",
                                    sanitize_log_value(exc),
                                )
                except Exception as exc:
                    logger.error(
                        "SEM EDX txt attachment failed for job %s: %s",
                        safe_job_id,
                        sanitize_log_value(exc),
                        exc_info=sanitized_exc_info(exc),
                    )

            job = _load_job(job_id) or job
            if job.get("errors"):
                job["status"] = "error"
                logger.warning(
                    "Import thread: job %s finished with errors (%d errors, %d messages)",
                    safe_job_id,
                    len(job.get("errors", [])),
                    len(job.get("messages", [])),
                )
            else:
                job["status"] = "done"
                logger.info(
                    "Import thread: job %s completed successfully "
                    "(imported_bytes=%s, total_bytes=%s, messages=%d)",
                    safe_job_id,
                    job.get("imported_bytes", 0),
                    job.get("total_bytes", 0),
                    len(job.get("messages", [])),
                )
            _save_job(job)
            if job.get("status") == "done":
                try:
                    # Immediately delete large temporary upload payloads after successful import.
                    # Keep the job JSON so the UI can still display final status/messages.
                    safe_remove_job_data(job_id, _get_upload_root())
                except Exception as exc:
                    logger.warning(
                        "Post-success cleanup failed for job %s: %s",
                        safe_job_id,
                        sanitize_log_value(exc),
                    )
            else:
                _mark_failed_job_for_deferred_cleanup(job_id)
        finally:
            lock.release()
            logger.info("Import thread: lock released for job %s", safe_job_id)
    except Exception as exc:
        logger.error(
            "Import job %s failed unexpectedly: %s",
            safe_job_id,
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        job = _load_job(job_id) or {"job_id": job_id}
        _append_job_error(job, errors.unexpected_import_failure(exc))
        job["status"] = "error"
        _save_job(job)


def _start_import_thread(job_id: str):
    job = _load_job(job_id)
    if not job:
        return
    if job.get("status") != "ready":
        return
    if job.get("import_thread_started"):
        return

    job["import_thread_started"] = True
    if not _save_job(job):
        job["import_thread_started"] = False
        logger.error(
            "Unable to persist import_thread_started for job %s.",
            sanitize_log_value(job_id),
        )
        return
    try:
        worker = threading.Thread(
            target=_process_import_job, args=(job_id,), daemon=True
        )
        worker.start()
    except Exception as exc:
        job["import_thread_started"] = False
        _save_job(job)
        logger.error(
            "Unable to start import thread for job %s: %s",
            sanitize_log_value(job_id),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )


# --------------------------------------------------------------------------
# VIEWS
# --------------------------------------------------------------------------
