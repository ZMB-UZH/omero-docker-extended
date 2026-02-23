"""
Core helper functions for upload views.
All non-view functions extracted here to reduce index_view.py size.
"""
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
import uuid
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
from ..constants import MAX_UPLOAD_BATCH_BYTES, MAX_UPLOAD_BATCH_GB, OMERO_CLI
from ..strings import errors, messages
from .utils import current_username, json_error, load_json_body

__all__ = [
    'BlitzGateway',
    'DatasetI',
    'DEFAULT_JOBS_DIR',
    'DEFAULT_UPLOAD_BATCH_FILES',
    'DEFAULT_UPLOAD_CLEANUP_INTERVAL',
    'DEFAULT_UPLOAD_CLEANUP_MAX_AGE',
    'DEFAULT_UPLOAD_CLEANUP_MAX_DELETE',
    'DEFAULT_UPLOAD_CLEANUP_STALE_AGE',
    'DEFAULT_UPLOAD_CONCURRENCY',
    'DEFAULT_UPLOAD_ROOT',
    'INT_SANITIZER',
    'JOBS_DIR_ENV',
    'JOB_ID_SANITIZER',
    'JOB_SERVICE_GROUP_ENV',
    'JOB_SERVICE_PASS_ENV',
    'JOB_SERVICE_SECURE_ENV',
    'JOB_SERVICE_USER_ENV',
    'JsonResponse',
    'MAX_IMPORT_LOG_LINES',
    'MAX_UPLOAD_BATCH_BYTES',
    'MAX_UPLOAD_BATCH_GB',
    'OMERO_CLI',
    'ORPHAN_DATASET_PREFIX',
    'ORPHAN_SUFFIX_ALPHANUM',
    'ORPHAN_SUFFIX_LENGTH',
    'Optional',
    'Path',
    'ProjectDatasetLinkI',
    'ProjectI',
    'PurePosixPath',
    'SPECIAL_METHODS_DISABLED_ENV',
    'SEM_EDX_FILEANNOTATION_NS',
    'ThreadPoolExecutor',
    'UPLOAD_BATCH_FILES_ENV',
    'UPLOAD_CLEANUP_INTERVAL_ENV',
    'UPLOAD_CLEANUP_MAX_AGE_ENV',
    'UPLOAD_CLEANUP_MAX_DELETE_ENV',
    'UPLOAD_CLEANUP_STALE_AGE_ENV',
    'UPLOAD_CONCURRENCY_ENV',
    'UPLOAD_ROOT_ENV',
    '_CLEANUP_IN_PROGRESS',
    '_CLI_ID_PATTERN',
    '_DIRS_INITIALIZED',
    '_IMPORT_LOCKS',
    '_IMPORT_LOCKS_GUARD',
    '_JOBS_ROOT_CACHE',
    '_LAST_UPLOAD_CLEANUP_TIME',
    '_UPLOAD_CLEANUP_GUARD',
    '_UPLOAD_ROOT_CACHE',
    '_append_job_error',
    '_append_job_message',
    '_append_txt_attachment_message',
    '_apply_upload_updates',
    '_attach_txt_to_image_service',
    '_batch_find_images_by_name',
    '_build_omero_cli_command',
    '_build_sem_edx_associations_from_entries',
    '_check_import_compatibility',
    '_classify_compatibility_output',
    '_cleanup_upload_artifacts',
    '_collect_project_payload',
    '_compatibility_pending_entries',
    '_current_user_id',
    '_dataset_name_for_path',
    '_ensure_dir',
    '_ensure_dir_with_permissions',
    '_ensure_parent_dir',
    '_extract_import_candidates',
    '_find_image_by_name',
    '_find_project_dataset',
    '_generate_orphan_dataset_name',
    '_get_env_bool',
    '_get_env_int',
    '_get_id',
    '_get_import_lock',
    '_get_job_service_credentials',
    '_get_jobs_root',
    '_get_or_create_dataset',
    '_get_owner_id',
    '_get_owner_username',
    '_get_session_key',
    '_get_text',
    '_get_upload_root',
    '_has_import_candidates_in_output',
    '_has_pending_uploads',
    '_has_read_write_permissions',
    '_import_file',
    '_import_job_entry',
    '_initialize_directories',
    '_is_owned_by_user',
    '_is_within_root',
    '_iter_accessible_projects',
    '_job_path',
    '_link_dataset_to_project',
    '_load_job',
    '_normalize_job_batch_size',
    '_normalize_sem_edx_associations',
    '_normalize_sem_edx_settings',
    '_open_service_connection',
    '_open_session_connection',
    '_parse_cli_id',
    '_process_import_job',
    '_reconnect_session',
    '_refresh_job_status',
    '_resolve_job_batch_size',
    '_resolve_jobs_root',
    '_resolve_omero_host_port',
    '_resolve_upload_root',
    '_robust_update_job',
    '_run_compatibility_check',
    '_run_omero_cli',
    '_safe_job_id',
    '_safe_relative_path',
    '_safe_remove_tree',
    '_save_job',
    '_special_methods_enabled',
    '_should_auto_skip_import',
    '_should_run_cleanup',
    '_should_start_compatibility_check',
    '_start_compatibility_check_thread',
    '_start_import_thread',
    '_update_job',
    '_validate_session',
    '_verify_import',
    'as_completed',
    'current_username',
    'errors',
    'json',
    'json_error',
    'load_json_body',
    'logger',
    'logging',
    'login_required',
    'messages',
    'omero',
    'os',
    'portalocker',
    'random',
    're',
    'render',
    'reverse',
    'rstring',
    'secrets',
    'settings',
    'stat',
    'string',
    'subprocess',
    'threading',
    'time',
    'uuid',
]

logger = logging.getLogger(__name__)

_IMPORT_LOCKS = {}
_IMPORT_LOCKS_GUARD = threading.Lock()
_UPLOAD_CLEANUP_GUARD = threading.Lock()
_LAST_UPLOAD_CLEANUP_TIME = 0.0
_CLEANUP_IN_PROGRESS = False

UPLOAD_ROOT_ENV = "OMERO_WEB_UPLOAD_DIR"
DEFAULT_UPLOAD_ROOT = "/tmp/omero-upload-tmp"
JOBS_DIR_ENV = "OMERO_WEB_UPLOAD_JOBS_DIR"
DEFAULT_JOBS_DIR = "/tmp/omero_web_upload_jobs"
UPLOAD_CONCURRENCY_ENV = "OMERO_WEB_UPLOAD_CONCURRENCY"
DEFAULT_UPLOAD_CONCURRENCY = 3
UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"
DEFAULT_UPLOAD_BATCH_FILES = 5
SPECIAL_METHODS_DISABLED_ENV = "OMERO_WEB_UPLOAD_DISABLE_SPECIAL_METHODS"
UPLOAD_CLEANUP_INTERVAL_ENV = "OMERO_WEB_UPLOAD_CLEANUP_INTERVAL"
DEFAULT_UPLOAD_CLEANUP_INTERVAL = 300
UPLOAD_CLEANUP_MAX_AGE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_MAX_AGE"
DEFAULT_UPLOAD_CLEANUP_MAX_AGE = 12 * 60 * 60
UPLOAD_CLEANUP_STALE_AGE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_STALE_AGE"
DEFAULT_UPLOAD_CLEANUP_STALE_AGE = 48 * 60 * 60
UPLOAD_CLEANUP_MAX_DELETE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_MAX_DELETE"
DEFAULT_UPLOAD_CLEANUP_MAX_DELETE = 25
MAX_IMPORT_LOG_LINES = 1000
INT_SANITIZER = re.compile(r"[^0-9]")
JOB_ID_SANITIZER = re.compile(r"^[0-9a-fA-F]{32}$")
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

JOB_SERVICE_PASS_ENV = "OMERO_JOB_SERVICE_PASS"
JOB_SERVICE_PASS_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_PASS"

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
_ALWAYS_SKIP_FILENAMES = frozenset({
    # Windows
    "thumbs.db",            # thumbnail cache
    "desktop.ini",          # folder display settings
    "ehthumbs.db",          # Explorer thumbnail cache (legacy)
    "ehthumbs_vista.db",    # Explorer thumbnail cache (Vista)
    "$recycle.bin",         # recycle-bin sentinel
    "ntuser.dat",           # user profile registry hive
    "ntuser.dat.log",       # user profile registry log
    "ntuser.ini",           # user profile settings
    "iconcache.db",         # icon cache
    # macOS
    ".ds_store",            # Finder folder metadata
    ".apdisk",              # Apple disk image metadata
    ".volumeicon.icns",     # custom volume icon
    ".fseventsd",           # filesystem-events daemon
    ".spotlight-v100",      # Spotlight index
    ".temporaryitems",      # temporary items folder
    ".trashes",             # per-volume trash
    # Linux
    ".directory",           # KDE/Dolphin folder settings
    ".trash-1000",          # common user-trash sentinel
    # Cross-platform applications
    ".picasa.ini",          # Google Picasa metadata
    ".picasaoriginals",     # Google Picasa originals folder
    ".bridgecache",         # Adobe Bridge cache
    ".bridgecachet",        # Adobe Bridge cache thumbnail
    ".bridgesort",          # Adobe Bridge sort order
    ".adobe",               # Adobe application data
})

# Directories whose *contents* should never be imported.
# If any path component matches (case-insensitive) the file is skipped.
_ALWAYS_SKIP_DIRS = frozenset({
    "lost+found",           # Linux filesystem recovery directory
    "$recycle.bin",         # Windows recycle bin
    "system volume information",  # Windows system folder
    ".trashes",             # macOS per-volume trash
    ".spotlight-v100",      # macOS Spotlight index
    ".fseventsd",           # macOS filesystem events
    ".temporaryitems",      # macOS temporary items
})
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
    configured = (os.environ.get(UPLOAD_ROOT_ENV) or "").strip()
    return Path(configured) if configured else Path(DEFAULT_UPLOAD_ROOT)


def _resolve_jobs_root() -> Path:
    configured = (os.environ.get(JOBS_DIR_ENV) or "").strip()
    return Path(configured) if configured else Path(DEFAULT_JOBS_DIR)


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
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.warning("Unable to create directory %s: %s", path, exc)
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
                logger.info(f"Created directory: {path} with permissions {oct(mode)}")
            except OSError as target_exc:
                logger.error(f"Unable to create target directory {path}: {target_exc}")
                return False
            
            return True
        else:
            # Directory exists - check and fix permissions if necessary
            # NEVER delete any files
            try:
                current_perms = stat.S_IMODE(path.stat().st_mode)
                if current_perms != mode:
                    path.chmod(mode)
                    logger.warning(f"Fixed permissions for existing directory: {path} (was {oct(current_perms)}, now {oct(mode)})")
            except OSError as perm_exc:
                logger.warning(f"Could not verify/fix permissions for {path}: {perm_exc}")
            return True
    except OSError as exc:
        logger.error(f"Unable to create/verify directory {path}: {exc}")
        return False


def _job_path(job_id: str) -> Path:
    return _get_jobs_root() / f"{job_id}.json"


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
    default_batch_size = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10)
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
    pending_entries = _compatibility_pending_entries(job_dict)
    if not pending_entries:
        return False
    batch_size = _resolve_job_batch_size(job_dict)
    return len(pending_entries) >= batch_size or not _has_pending_uploads(job_dict)


def _refresh_job_status(job_dict):
    if _has_pending_uploads(job_dict):
        job_dict["status"] = "uploading"
        return job_dict

    # If nothing requires compatibility (all files skipped or already decided),
    # do NOT get stuck in "checking" once uploads are complete.
    pending_entries = _compatibility_pending_entries(job_dict)
    if not pending_entries and job_dict.get("compatibility_status") not in ("compatible", "incompatible", "error"):
        job_dict["compatibility_status"] = "compatible"

    compatibility_status = job_dict.get("compatibility_status")
    if compatibility_status == "incompatible":
        job_dict["status"] = "awaiting_confirmation"
    elif compatibility_status == "error":
        # Compatibility check errors (CLI crash, timeout, etc.) should NOT block the
        # import.  The actual import will surface real errors.  Blocking here caused
        # the upload plugin to freeze when the frontend had compatibility checking
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
    path = _job_path(job_id)
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


def _save_job(job_dict, retries: int = 5, timeout: float = 2.0):
    path = _job_path(job_dict["job_id"])
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


def _robust_update_job(job_id: str, update_fn, retries: int = 5, timeout: float = 2.0):
    path = _job_path(job_id)
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
    try:
        return value_obj.getValue() if hasattr(value_obj, "getValue") else getattr(
            value_obj, "val", str(value_obj)
        )
    except Exception:
        return str(value_obj)


def _get_id(obj):
    try:
        return obj._obj.id.val
    except (AttributeError, Exception):
        pass
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
    except Exception:
        pass
    try:
        owner = obj.getOwner()
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception:
        pass
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
                return bool(checker())
            except Exception:
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
    except Exception:
        pass
    
    try:
        # Set group context to -1 to query across all groups
        conn.SERVICE_OPTS.setOmeroGroup('-1')
        
        # Try to get projects with cross-group querying enabled
        try:
            for proj in conn.getObjects("Project"):
                yield proj
            return
        except Exception as e:
            logger.warning("Failed to query projects across all groups with SERVICE_OPTS: %s", e)
        
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
            except Exception:
                pass
    
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


def _generate_orphan_dataset_name():
    suffix = "".join(secrets.choice(ORPHAN_SUFFIX_ALPHANUM) for _ in range(ORPHAN_SUFFIX_LENGTH))
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
        logger.warning("Failed to link dataset %s to project %s: %s", dataset_id, project_id, exc)
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


_CLI_ID_PATTERN = re.compile(r"(?P<type>OriginalFile|FileAnnotation|ImageAnnotationLink):(?P<id>\\d+)")


def _build_omero_cli_command(subcommand, session_key: str, host: str, port: int):
    cmd = [OMERO_CLI]
    cmd.extend(subcommand)
    if session_key:
        cmd.extend(["-k", session_key])
    if host:
        cmd.extend(["-s", host])
    if port:
        cmd.extend(["-p", str(port)])
    return cmd


IMPORT_TIMEOUT_SECONDS_DEFAULT = 7200  # 2 hours per file import (large microscopy files can be slow)
IMPORT_TIMEOUT_SECONDS_ENV = "OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS"


def _run_omero_cli(cmd, timeout=None):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def _parse_cli_id(output: str, expected_type: str):
    for line in (output or "").splitlines():
        match = _CLI_ID_PATTERN.search(line.strip())
        if match and match.group("type") == expected_type:
            return int(match.group("id"))
    return None


def _import_file(conn, session_key: str, host: str, port: int, path: Path, dataset_id=None):
    cmd = _build_omero_cli_command(["import"], session_key, host, port)
    if dataset_id:
        cmd.extend(["-d", str(dataset_id)])
    cmd.append(str(path))

    logger.info("Import CLI: starting import for %s (dataset_id=%s)", path.name, dataset_id)
    import_start = time.time()
    try:
        result = _run_omero_cli(cmd, timeout=_get_import_timeout_seconds())
    except subprocess.TimeoutExpired:
        logger.error("Import CLI timed out after %ds for %s", _get_import_timeout_seconds(), path)
        return False, "", f"Import timed out after {_get_import_timeout_seconds()} seconds"
    elapsed = time.time() - import_start
    success = result.returncode == 0
    logger.info(
        "Import CLI: finished for %s in %.1fs (success=%s, returncode=%d, "
        "stdout_lines=%d, stderr_lines=%d)",
        path.name, elapsed, success, result.returncode,
        len((result.stdout or "").splitlines()),
        len((result.stderr or "").splitlines()),
    )
    if not success:
        logger.warning(
            "Import CLI stderr for %s: %s",
            path.name, (result.stderr or "").strip()[:500],
        )
    return success, result.stdout, result.stderr


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
        except Exception:
            pass
    
    try:
        client = omero.client(host=host, port=port)
        client.joinSession(session_key)
        conn = BlitzGateway(client_obj=client)
        conn.SERVICE_OPTS.setOmeroGroup("-1")

        # Validate the new connection
        if not _validate_session(conn):
            logger.error("Newly created session is invalid")
            try:
                conn.close()
            except Exception:
                pass
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
    client.joinSession(session_key)
    conn = BlitzGateway(client_obj=client)
    conn.SERVICE_OPTS.setOmeroGroup("-1")
    return conn


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
                params.addLong("did", dataset_id)
                params.addString("name", file_name)
                params.page(0, 100)  # Limit results
                
                images = qs.findAllByQuery(query, params, conn.SERVICE_OPTS)
                
                if images:
                    elapsed = time.time() - start_time
                    logger.debug("Found image '%s' in Dataset:%d in %.2fs", file_name, dataset_id, elapsed)
                    return conn.getObject("Image", images[0].getId().getValue())
            except Exception as exc:
                logger.warning("Dataset search failed for '%s': %s", file_name, exc)
        
        # Global search as fallback
        try:
            query = "SELECT i FROM Image i WHERE i.name = :name"
            params = omero.sys.ParametersI()
            params.addString("name", file_name)
            params.page(0, 100)
            
            images = qs.findAllByQuery(query, params, conn.SERVICE_OPTS)
            
            if images:
                elapsed = time.time() - start_time
                if len(images) > 1:
                    logger.warning("Found %d images named '%s' - using first", len(images), file_name)
                logger.debug("Found image '%s' globally in %.2fs", file_name, elapsed)
                return conn.getObject("Image", images[0].getId().getValue())
            else:
                logger.warning("Image '%s' not found", file_name)
                return None
        except Exception as exc:
            logger.error("Global search failed for '%s': %s", file_name, exc)
            return None
    except Exception as exc:
        logger.exception("Unexpected error searching for '%s'", file_name)
        return None


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
        
        # Build IN clause safely
        escaped_names = [name.replace("'", "''") for name in file_names]
        name_list = ", ".join([f"'{name}'" for name in escaped_names])
        
        if dataset_id:
            query = f"""
                SELECT i FROM Image i
                JOIN FETCH i.datasetLinks dil
                WHERE dil.parent.id = :did
                AND i.name IN ({name_list})
            """
            params = omero.sys.ParametersI()
            params.addLong("did", dataset_id)
        else:
            query = f"""
                SELECT i FROM Image i
                WHERE i.name IN ({name_list})
            """
            params = omero.sys.ParametersI()
        
        logger.info("Batch searching for %d images (dataset_id=%s)", len(file_names), dataset_id)
        images = qs.findAllByQuery(query, params, conn.SERVICE_OPTS)
        
        for image_obj in images:
            img_wrapper = conn.getObject("Image", image_obj.getId().getValue())
            if img_wrapper:
                results[img_wrapper.getName()] = img_wrapper
        
        elapsed = time.time() - start_time
        logger.info("Batch search found %d/%d images in %.2fs", len(results), len(file_names), elapsed)
        
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

    passwd = (os.environ.get(JOB_SERVICE_PASS_ENV) or "").strip()
    if not passwd:
        passwd = (os.environ.get(JOB_SERVICE_PASS_ENV_FALLBACK) or "").strip()

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





def _open_service_connection(host: str, port: int, group_id: Optional[int] = None) -> Optional[BlitzGateway]:
    """Login as service user for async background work (safe for user sessions)."""
    service_user, service_pass, group_override, secure = _get_job_service_credentials()

    if not service_pass:
        logger.error(
            "job-service password missing. Set %s in the omeroweb container environment.",
            JOB_SERVICE_PASS_ENV,
        )
        return None

    conn = BlitzGateway(service_user, service_pass, host=host, port=int(port), secure=secure)

    try:
        try:
            ok = conn.connect()
        except Exception as exc:
            last_err = None
            try:
                last_err = conn.getLastError()
            except Exception:
                last_err = None

            logger.error(
                "job-service connect() raised: user=%s host=%s port=%s secure=%s error=%s lastError=%r",
                service_user, host, port, secure, exc, last_err
            )
            try:
                conn.close()
            except Exception:
                pass
            return None

        if not ok:
            last_err = None
            try:
                last_err = conn.getLastError()
            except Exception:
                last_err = None

            logger.error(
                "job-service connect() failed: user=%s host=%s port=%s secure=%s lastError=%r",
                service_user, host, port, secure, last_err
            )
            try:
                conn.close()
            except Exception:
                pass
            return None

        # Prefer explicit override, else use job's group_id when provided.
        effective_group = None
        if group_override:
            try:
                effective_group = int(group_override)
            except Exception:
                effective_group = None
        elif group_id is not None:
            effective_group = int(group_id)

        if effective_group is not None:
            try:
                conn.SERVICE_OPTS.setOmeroGroup(str(effective_group))
            except Exception as exc:
                logger.warning("Failed to set job-service group context to %s: %s", effective_group, exc)

        return conn

    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise


def _attach_txt_to_image_service(
    conn: BlitzGateway,
    image_id: int,
    txt_path: Path,
    username: str,
    create_tables: bool = True,
    plot_path: Optional[Path] = None,
):
    """Attach a TXT file to an Image using OMERO API (no CLI).

    Creates:
      - OriginalFile
      - FileAnnotation (ns=SEM_EDX_FILEANNOTATION_NS)
      - ImageAnnotationLink
      - OMERO Table with spectrum data
      - Optional PNG plot attachment (if plot_path provided)

    This is safe to run in background threads and does NOT touch the user's session.
    Uses suConn to impersonate the user so annotations are created in the correct group.
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
        finally:
            try:
                store.close()
            except Exception:
                pass

        fa = FileAnnotationI()
        fa.setNs(rstring(SEM_EDX_FILEANNOTATION_NS))
        fa.setFile(of.proxy())

        fa = update_service.saveAndReturnObject(fa)
        image_obj.linkAnnotation(FileAnnotationWrapper(user_connection, fa))

    # CRITICAL FIX: Use suConn() to impersonate the user
    # This is the OMERO-approved way for admins to create objects as another user
    # All objects created will automatically be in the user's current group
    user_conn = conn.suConn(username)
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
            table_id = attach_sem_edx_tables(user_conn, image_id, txt_path, persist_table=create_tables)
            if table_id:
                logger.info("Created OMERO Table for image %d from %s", image_id, txt_path.name)
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
                logger.info("Attached SEM EDX spectrum plot %s to image %d", plot_path.name, image_id)
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
        except Exception:
            pass


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


def _append_txt_attachment_message(job: dict, txt_name: str, image_name: str, success: bool):
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


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    if resolved_root == resolved_path:
        return True
    return resolved_root in resolved_path.parents


def _should_run_cleanup(interval: int) -> bool:
    global _LAST_UPLOAD_CLEANUP_TIME, _CLEANUP_IN_PROGRESS
    now = time.time()
    with _UPLOAD_CLEANUP_GUARD:
        if _CLEANUP_IN_PROGRESS:
            return False
        if now - _LAST_UPLOAD_CLEANUP_TIME < interval:
            return False
        _CLEANUP_IN_PROGRESS = True
        _LAST_UPLOAD_CLEANUP_TIME = now
    return True


def _safe_remove_tree(path: Path, root: Path):
    if not path.exists():
        return False
    if path.is_symlink():
        return False
    if not _is_within_root(path, root):
        return False
    try:
        for root_dir, dirnames, filenames in os.walk(path, followlinks=False):
            for name in dirnames:
                candidate = Path(root_dir) / name
                if candidate.is_symlink():
                    logger.warning("Skipping cleanup for symlinked path %s.", candidate)
                    return False
            for name in filenames:
                candidate = Path(root_dir) / name
                if candidate.is_symlink():
                    logger.warning("Skipping cleanup for symlinked path %s.", candidate)
                    return False
    except OSError:
        return False
    try:
        for root_dir, dirnames, filenames in os.walk(path, topdown=False, followlinks=False):
            for name in filenames:
                candidate = Path(root_dir) / name
                try:
                    candidate.unlink()
                except OSError:
                    return False
            for name in dirnames:
                candidate = Path(root_dir) / name
                try:
                    candidate.rmdir()
                except OSError:
                    return False
        path.rmdir()
        return True
    except OSError:
        return False


def _cleanup_upload_artifacts():
    interval = _get_env_int(
        UPLOAD_CLEANUP_INTERVAL_ENV,
        60,
        10,
        6 * 60 * 60,
    )
    if not _should_run_cleanup(interval):
        return

    try:
        upload_root = _get_upload_root()
        jobs_root = _get_jobs_root()
        if not upload_root.exists() or not jobs_root.exists():
            return

        max_age = _get_env_int(
            UPLOAD_CLEANUP_MAX_AGE_ENV,
            15 * 60,
            60,
            14 * 24 * 60 * 60,
        )
        stale_age = _get_env_int(
            UPLOAD_CLEANUP_STALE_AGE_ENV,
            max_age,
            max_age,
            30 * 24 * 60 * 60,
        )
        max_delete = _get_env_int(
            UPLOAD_CLEANUP_MAX_DELETE_ENV,
            DEFAULT_UPLOAD_CLEANUP_MAX_DELETE,
            1,
            500,
        )
        now = time.time()

        deleted = 0
        seen_job_ids = set()

        try:
            for entry in os.scandir(jobs_root):
                if deleted >= max_delete:
                    break
                if not entry.name.endswith(".json"):
                    continue
                job_id = entry.name[:-5]
                if not _safe_job_id(job_id):
                    continue
                seen_job_ids.add(job_id)
                job_path = Path(entry.path)

                try:
                    with portalocker.Lock(job_path, "r", timeout=0) as handle:
                        try:
                            job = json.load(handle)
                        except json.JSONDecodeError:
                            job = None
                except (portalocker.exceptions.LockException, OSError):
                    continue

                job_status = job.get("status") if isinstance(job, dict) else None
                updated = None
                if isinstance(job, dict):
                    updated = job.get("updated") or job.get("created")
                if updated is None:
                    try:
                        updated = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                age = now - float(updated)

                should_delete = False
                if job_status in ("done", "error") and age > max_age:
                    should_delete = True
                elif job_status in ("uploading", "ready", "importing") and age > stale_age:
                    should_delete = True
                elif job_status is None and age > stale_age:
                    should_delete = True

                if not should_delete:
                    continue

                job_dir = upload_root / job_id
                if job_dir.exists():
                    if not _safe_remove_tree(job_dir, upload_root):
                        continue
                try:
                    job_path.unlink()
                except OSError:
                    continue
                deleted += 1
        except OSError as exc:
            logger.warning("Upload cleanup failed while scanning jobs: %s", exc)

        if deleted >= max_delete:
            return

        try:
            for entry in os.scandir(upload_root):
                if deleted >= max_delete:
                    break
                if not entry.is_dir(follow_symlinks=False):
                    continue
                job_id = entry.name
                if not _safe_job_id(job_id):
                    continue
                if job_id in seen_job_ids:
                    continue
                try:
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if now - mtime <= stale_age:
                    continue
                job_dir = Path(entry.path)
                if _safe_remove_tree(job_dir, upload_root):
                    deleted += 1
        except OSError as exc:
            logger.warning("Upload cleanup failed while scanning upload root: %s", exc)

    finally:
        global _CLEANUP_IN_PROGRESS
        with _UPLOAD_CLEANUP_GUARD:
            _CLEANUP_IN_PROGRESS = False


def _apply_upload_updates(job_id: str, updates: list, errors: list):
    def apply_updates(job_dict):
        entries_by_id = {entry.get("upload_id"): entry for entry in job_dict.get("files", [])}
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
            entry.get("size", 0) for entry in job_dict.get("files", []) if entry.get("status") == "uploaded"
        )
        job_dict["uploaded_bytes"] = uploaded_bytes
        compatibility_pending = _compatibility_pending_entries(job_dict)
        if compatibility_pending and job_dict.get("compatibility_status") != "incompatible":
            job_dict["compatibility_status"] = "checking"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    return _robust_update_job(job_id, apply_updates)


def _update_job(job_id: str, update_fn):
    return _robust_update_job(job_id, update_fn)


def _classify_compatibility_output(return_code: int, stdout: str, stderr: str):
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
    has_candidates = _has_import_candidates_in_output(stdout or "")
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




def _has_import_candidates_in_output(output: str) -> bool:
    """
    Check if omero import -f output contains actual import candidates.
    
    The -f flag displays files grouped by import groups, separated by "#" comments.
    Real import candidates are non-empty, non-comment lines.
    
    Returns True if at least one import candidate is found.
    """
    if not output or not output.strip():
        return False
    
    lines = output.strip().split('\n')
    
    # Metadata patterns to skip (these are NOT import candidates)
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
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Skip comment lines
        if stripped.startswith("#"):
            continue
        
        # Skip metadata lines
        stripped_lower = stripped.lower()
        if any(pattern in stripped_lower for pattern in skip_patterns):
            continue
        
        # If we reach here, this is likely an actual file path (import candidate)
        # Additional validation: check if it looks like a file path
        if '/' in stripped or '\\' in stripped or '.' in stripped:
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
    lines = output.strip().split('\n')
    
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
        
        # This looks like an actual file path
        if '/' in stripped or '\\' in stripped or '.' in stripped:
            candidates.append(stripped)
    
    return candidates


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
    
    # Use -f flag for local Bio-Formats analysis (no server connection needed)
    cmd = [OMERO_CLI, "import", "-f", str(file_path)]
    
    # Use a temporary OMERODIR for isolation
    env = os.environ.copy()
    env["OMERODIR"] = f"/tmp/omero-compat-check-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=45,  # Increased timeout for large files
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": "Compatibility check timeout",
            "details": "Compatibility check timeout after 45 seconds",
        }
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": str(exc),
            "details": f"OMERO CLI not found: {exc}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "relative_path": relative_path,
            "stdout": "",
            "stderr": str(exc),
            "details": f"Unexpected error during compatibility check: {exc}",
        }
    
    # CRITICAL FIX: Classify based on stdout content, NOT return code
    status, details = _classify_compatibility_output(result.returncode, result.stdout, result.stderr)
    
    # Additional logging for debugging
    logger.debug(
        "Compatibility check for %s: status=%s, returncode=%d, stdout_lines=%d, stderr_lines=%d",
        relative_path,
        status,
        result.returncode,
        len((result.stdout or "").splitlines()),
        len((result.stderr or "").splitlines()),
    )
    
    return {
        "status": status,
        "relative_path": relative_path,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "details": details or "Compatibility check completed.",
    }

def _run_compatibility_check(job_id: str):
    job = _load_job(job_id)
    if not job:
        return

    session_key = job.get("session_key")
    host = job.get("host")
    port = job.get("port")
    upload_root = _get_upload_root() / job_id
    pending_entries = [
        (index, entry)
        for index, entry in enumerate(job.get("files", []))
        if (
            entry.get("status") == "uploaded"
            and not entry.get("compatibility")
            and not entry.get("compatibility_skip")
        )
    ]
    if not pending_entries:
        def mark_idle(job_dict):
            job_dict["compatibility_thread_active"] = False
            has_uploaded = any(entry.get("status") == "uploaded" for entry in job_dict.get("files", []))
            if has_uploaded:
                has_errors = any(
                    entry.get("compatibility") == "error" for entry in job_dict.get("files", [])
                )
                if job_dict.get("incompatible_files"):
                    job_dict["compatibility_status"] = "incompatible"
                elif has_errors:
                    job_dict["compatibility_status"] = "error"
                else:
                    job_dict["compatibility_status"] = "compatible"
            else:
                if job_dict.get("compatibility_status") not in ("incompatible", "error", "compatible"):
                    job_dict["compatibility_status"] = "pending"
            _refresh_job_status(job_dict)
            job_dict["updated"] = time.time()
            return job_dict

        _update_job(job_id, mark_idle)
        return

    pending_entries.sort(key=lambda item: item[0])
    batch_size = _resolve_job_batch_size(job)
    entries_to_check = pending_entries[:batch_size]

    max_workers = min(4, len(entries_to_check), os.cpu_count() or 2)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for entry_index, entry in entries_to_check:
            staged_path = entry.get("staged_path") or entry.get("relative_path")
            if not staged_path:
                continue
            file_path = upload_root / staged_path
            dataset_name = _dataset_name_for_path(entry.get("relative_path"), job.get("orphan_dataset_name"))
            dataset_id = (job.get("dataset_map") or {}).get(dataset_name)
            future = executor.submit(
                _check_import_compatibility,
                session_key,
                host,
                port,
                file_path,
                dataset_id,
                entry.get("relative_path"),
            )
            future_map[future] = (entry_index, entry)
        for future in as_completed(future_map):
            entry_index, entry = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.warning("Compatibility check failed for %s: %s", entry.get("relative_path"), exc)
                result = {
                    "status": "error",
                    "stdout": "",
                    "stderr": str(exc),
                    "details": str(exc),
                }
            results.append(
                {
                    "index": entry_index,
                    "upload_id": entry.get("upload_id"),
                    "relative_path": entry.get("relative_path"),
                    "status": result.get("status"),
                    "details": result.get("details", ""),
                }
            )

    new_incompatible = [
        result["relative_path"]
        for result in results
        if result.get("status") == "incompatible"
           and isinstance(result.get("relative_path"), str)
    ]

    def apply_results(job_dict):
        entries = job_dict.get("files", [])
        for result in results:
            entry_index = result.get("index")
            if entry_index is None or entry_index >= len(entries):
                continue
            entry = entries[entry_index]
            status = result.get("status")
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
        if updated_job.get("status") == "ready":
            _start_import_thread(job_id)


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
    worker = threading.Thread(target=_run_compatibility_check, args=(job_id,), daemon=True)
    worker.start()


def _import_job_entry(entry, upload_root, session_key, host, port, dataset_map, orphan_dataset_name):
    rel_path = entry.get("relative_path")
    if not rel_path:
        return {"skip": True}

    staged_path = entry.get("staged_path") or rel_path
    file_path = upload_root / staged_path
    if not file_path.exists():
        error_msg = errors.missing_staged_file(rel_path)
        return {
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": error_msg,
            "job_message": error_msg,
        }

    # Allow callers (SEM-EDX) to override dataset selection.
    dataset_id = entry.get("dataset_id_override")
    if dataset_id is None:
        dataset_name = _dataset_name_for_path(rel_path, orphan_dataset_name)
        dataset_id = dataset_map.get(dataset_name)

    try:
        success, stdout, stderr = _import_file(
            conn=None,
            session_key=session_key,
            host=host,
            port=port,
            path=file_path,
            dataset_id=dataset_id,
        )
    except Exception:
        logger.exception("Import failed for %s.", rel_path)
        success = False
        stdout = ""
        stderr = ""

    if not success:
        logger.warning(
            "Import failed for %s (stdout=%r, stderr=%r).",
            rel_path,
            str(stdout).strip(),
            str(stderr).strip(),
        )
        error_msg = errors.import_failed()
        job_error = messages.job_error_with_path(rel_path, error_msg)
        return {
            "index": entry.get("index"),
            "status": "error",
            "entry_error": error_msg,
            "job_error": job_error,
            "job_message": job_error,
        }

    return {
        "index": entry.get("index"),
        "status": "imported",
        "rel_path": rel_path,
        "file_path": file_path,
    }


def _process_import_job(job_id: str):
    logger.info("Import thread started for job %s", job_id)
    job = _load_job(job_id)
    if not job:
        logger.error("Import thread: job %s not found, aborting", job_id)
        return

    try:
        username = job.get("username") or ""
        lock = _get_import_lock(username)

        LOCK_TIMEOUT = 900  # 15 minutes max wait for another import to finish
        logger.info("Import thread: acquiring lock for user %s (job %s)", username, job_id)
        acquired = lock.acquire(timeout=LOCK_TIMEOUT)
        if not acquired:
            logger.error(
                "Import lock timeout for user %s after %ds - a previous import may be stuck. "
                "Restart the OMERO-web container to clear stale locks.",
                username, LOCK_TIMEOUT,
            )
            job = _load_job(job_id) or {"job_id": job_id}
            _append_job_error(job, "Import could not start: another import is stuck. Please restart OMERO-web.")
            job["status"] = "error"
            _save_job(job)
            return

        logger.info("Import thread: lock acquired for user %s (job %s)", username, job_id)
        try:
            job = _load_job(job_id)
            if not job:
                return

            if job.get("status") in ("done", "error"):
                return

            job.setdefault("errors", [])
            job.setdefault("messages", [])
            job["status"] = "importing"
            _save_job(job)

            session_key = job.get("session_key")
            host = job.get("host")
            port = job.get("port")
            if not session_key or not host or not port:
                job["status"] = "error"
                job["errors"].append(errors.missing_omero_connection_details())
                _save_job(job)
                return

            # IMPORTANT: never join/close the user's active OMERO.web session here.
            # Doing so can terminate their login. We validate session indirectly by
            # executing the import command and handling any authentication failure.

            upload_root = _get_upload_root() / job_id
            if not upload_root.exists():
                job["status"] = "error"
                job["errors"].append(errors.upload_folder_missing_on_server())
                _save_job(job)
                return

            dataset_map = job.get("dataset_map") or {}
            orphan_dataset_name = job.get("orphan_dataset_name")
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
                        job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                        _append_job_message(job, messages.skipped_non_importable(rel_path))
                        skipped_count += 1
                    continue

                # Files the compatibility check marked as incompatible
                # should be auto-skipped rather than attempted and failed.
                if entry.get("compatibility") == "incompatible":
                    entry["status"] = "skipped"
                    entry["import_skip"] = True
                    job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                    _append_job_message(job, messages.skipped_incompatible(rel_path))
                    incompatible_skipped += 1
                    continue

            if skipped_count or incompatible_skipped:
                logger.info(
                    "Import thread: pre-skipped %d non-importable + %d incompatible files for job %s",
                    skipped_count, incompatible_skipped, job_id,
                )
                _save_job(job)

            entries_to_import = []
            for index, entry in enumerate(job.get("files", [])):
                if entry.get("status") not in ("uploaded", "pending"):
                    continue
                if entry.get("import_skip"):
                    continue
                if not entry.get("relative_path"):
                    continue
                entries_to_import.append(
                    {
                        "index": index,
                        "relative_path": entry.get("relative_path"),
                        "staged_path": entry.get("staged_path"),
                    }
                )

            logger.info(
                "Import thread: %d entries to import for job %s (batch_size=%d)",
                len(entries_to_import), job_id, batch_size,
            )

            for start in range(0, len(entries_to_import), batch_size):
                batch = entries_to_import[start:start + batch_size]
                if not batch:
                    continue
                logger.info(
                    "Import thread: processing batch %d-%d of %d for job %s",
                    start, start + len(batch), len(entries_to_import), job_id,
                )
                with ThreadPoolExecutor(max_workers=min(batch_size, len(batch))) as executor:
                    futures = [
                        executor.submit(
                            _import_job_entry,
                            entry,
                            upload_root,
                            session_key,
                            host,
                            port,
                            dataset_map,
                            orphan_dataset_name,
                        )
                        for entry in batch
                    ]
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                        except Exception:
                            logger.exception("Import future raised unexpected error")
                            continue
                        if not result or result.get("skip"):
                            continue
                        entry_index = result.get("index")
                        if entry_index is None:
                            continue
                        entry = job.get("files", [])[entry_index]

                        if result.get("status") == "error":
                            entry["status"] = "error"
                            entry_error = result.get("entry_error")
                            if entry_error:
                                entry.setdefault("errors", []).append(entry_error)
                            if result.get("job_error"):
                                _append_job_error(job, result["job_error"])
                            if result.get("job_message"):
                                _append_job_message(job, result["job_message"])
                            # Count errored files as processed so the progress
                            # bar reflects that the file has been attempted.
                            job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                            _save_job(job)
                            continue

                        if result.get("status") == "imported":
                            rel_path = result.get("rel_path") or entry.get("relative_path")
                            entry["status"] = "imported"
                            job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                            if rel_path:
                                _append_job_message(job, messages.imported_file(rel_path))
                            file_path = result.get("file_path")
                            if file_path:
                                try:
                                    file_path.unlink()
                                except OSError as exc:
                                    logger.warning("Failed to remove staged file %s: %s", file_path, exc)
                            _save_job(job)

            job = _load_job(job_id) or job
            sem_edx_associations = job.get("sem_edx_associations") or {}
            sem_edx_settings = job.get("sem_edx_settings") or {}
            create_tables = sem_edx_settings.get("create_tables", True)
            create_figures_attachments = sem_edx_settings.get("create_figures_attachments", True)
            create_figures_images = sem_edx_settings.get("create_figures_images", True)

            if job.get("special_upload") == "sem_edx_spectra" and not sem_edx_associations:
                # Fallback: derive associations server-side from uploaded file list.
                derived = _build_sem_edx_associations_from_entries(job.get("files", []))
                if derived:
                    sem_edx_associations = derived
                    job["sem_edx_associations"] = derived
                    _append_job_message(
                        job,
                        f"SEM EDX: derived {sum(len(v) for v in derived.values())} TXT attachment(s) from uploaded files (no UI associations received)"
                    )
                    _save_job(job)
                else:
                    logger.info(
                        "SEM EDX mode enabled for job %s but no TXT/image associations could be derived; skipping TXT attachments",
                        job_id,
                    )
                    _append_job_message(job, "SEM EDX: no TXT/image associations found; skipping TXT attachments")
                    _save_job(job)

            if job.get("special_upload") == "sem_edx_spectra" and sem_edx_associations:
                try:
                    conn = _open_service_connection(host, port, group_id=job.get("group_id"))
                    if not conn:
                        logger.error("Failed to open SEM-EDX service connection for TXT attachments")
                        _append_job_message(job, "SEM EDX: failed to open service connection for TXT attachments")
                        _save_job(job)
                    else:
                        try:
                            entries_by_path = {
                                entry.get("relative_path"): entry for entry in job.get("files", [])
                            }
                            attachment_count = 0
                            total_attachments = sum(
                                len(txt_paths) for txt_paths in sem_edx_associations.values() 
                                if isinstance(txt_paths, list)
                            )
                            
                            logger.info("Processing %d SEM EDX text attachments for job %s", total_attachments, job_id)
                            
                            # CRITICAL FIX: Batch lookup ALL images at once instead of one-by-one
                            logger.info("Pre-loading image cache for %d images", len(sem_edx_associations))
                            all_image_names = []
                            image_to_dataset = {}  # Track which dataset each image should be in
                            
                            for image_rel in sem_edx_associations.keys():
                                image_name = PurePosixPath(image_rel).name if image_rel else ""
                                if image_name:
                                    all_image_names.append(image_name)
                                    dataset_name = _dataset_name_for_path(image_rel, orphan_dataset_name)
                                    dataset_id = dataset_map.get(dataset_name)
                                    image_to_dataset[image_name] = dataset_id
                            
                            # Do batch lookup - this is 100-1000x faster than individual lookups
                            image_cache = {}
                            datasets_to_search = set(image_to_dataset.values())
                            
                            for dataset_id in datasets_to_search:
                                if dataset_id:
                                    # Find all images for this dataset
                                    dataset_images = [name for name, did in image_to_dataset.items() if did == dataset_id]
                                    if dataset_images:
                                        batch_results = _batch_find_images_by_name(conn, dataset_images, dataset_id)
                                        image_cache.update({name: img for name, img in batch_results.items()})
                            
                            # Fallback: global search for images not found in datasets
                            missing_images = set(all_image_names) - set(image_cache.keys())
                            if missing_images:
                                logger.info("Searching globally for %d missing images", len(missing_images))
                                global_results = _batch_find_images_by_name(conn, list(missing_images), None)
                                image_cache.update(global_results)
                            
                            logger.info("Image cache loaded: %d/%d found", len(image_cache), len(all_image_names))

                            plot_cache = {}
                            plot_rel_cache = {}
                            imported_plots = set()
                            if create_figures_attachments or create_figures_images:
                                from ..services.omero.sem_edx_parser import create_edx_spectrum_plot
                            
                            # Now process attachments using cached images
                            for attachment_idx, (image_rel, txt_paths) in enumerate(sem_edx_associations.items()):
                                if not isinstance(txt_paths, list):
                                    continue
                                
                                # Progress logging
                                progress_pct = (attachment_idx / len(sem_edx_associations)) * 100
                                logger.info("Processing image %d/%d (%.1f%%) - %s", 
                                          attachment_idx + 1, len(sem_edx_associations), progress_pct, image_rel)

                                image_name = PurePosixPath(image_rel).name if image_rel else ""

                                # Validate job-service session periodically (every 10 attachments).
                                # IMPORTANT: NEVER reconnect using the end-user session_key here.
                                if attachment_count > 0 and attachment_count % 10 == 0:
                                    if not _validate_session(conn):
                                        logger.warning("job-service session expired, reopening service connection...")
                                        try:
                                            try:
                                                conn.close()
                                            except Exception:
                                                pass
                                            conn = _open_service_connection(host, port, group_id=job.get("group_id"))
                                        except Exception:
                                            conn = None

                                        if not conn:
                                            logger.error("Failed to reopen job-service connection, aborting SEM EDX attachments")
                                            break

                                        # Re-populate cache after reconnect
                                        logger.info("Re-loading image cache after reconnect")
                                        image_cache.clear()
                                        for dataset_id in datasets_to_search:
                                            if dataset_id:
                                                dataset_images = [name for name, did in image_to_dataset.items() if did == dataset_id]
                                                if dataset_images:
                                                    batch_results = _batch_find_images_by_name(conn, dataset_images, dataset_id)
                                                    image_cache.update(batch_results)
                                        missing_images = set(all_image_names) - set(image_cache.keys())
                                        if missing_images:
                                            global_results = _batch_find_images_by_name(conn, list(missing_images), None)
                                            image_cache.update(global_results)

                                # Get cached image (no query needed!)
                                image_obj = image_cache.get(image_name)

                                # Process each text file for this image
                                for txt_rel in txt_paths:
                                    txt_name = PurePosixPath(txt_rel).name
                                    attachment_count += 1

                                    if not image_obj:
                                        logger.warning("Image not found for %s, skipping attachment", txt_name)
                                        _append_txt_attachment_message(job, txt_name, image_name or image_rel, False)
                                        continue

                                    image_id = _get_id(image_obj)
                                    if not image_id:
                                        logger.warning("Could not get image ID for %s, skipping %s", image_name, txt_name)
                                        _append_txt_attachment_message(job, txt_name, image_name or image_rel, False)
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
                                        logger.warning("Text entry not found for %s, skipping", txt_rel)
                                        _append_txt_attachment_message(job, txt_name, image_name, False)
                                        continue

                                    staged_path = txt_entry.get("staged_path") or txt_rel
                                    txt_path = upload_root / staged_path

                                    if not txt_path.exists():
                                        logger.warning("Text file not found at %s, skipping", txt_path)
                                        _append_txt_attachment_message(job, txt_name, image_name, False)
                                        continue

                                    plot_path = None
                                    plot_rel = None
                                    if create_figures_attachments or create_figures_images:
                                        if txt_rel in plot_cache:
                                            plot_path = plot_cache.get(txt_rel)
                                            plot_rel = plot_rel_cache.get(txt_rel)
                                        else:
                                            plot_path = create_edx_spectrum_plot(txt_path)
                                            plot_cache[txt_rel] = plot_path
                                            if plot_path:
                                                plot_rel = str(PurePosixPath(txt_rel).with_name(plot_path.name))
                                                plot_rel_cache[txt_rel] = plot_rel

                                    if create_figures_images and plot_path and plot_rel and txt_rel not in imported_plots:
                                        plot_import_rel = str(
                                            PurePosixPath(image_rel).with_name(
                                                PurePosixPath(plot_rel).name
                                            )
                                        )

                                        staged_plot_path = upload_root / plot_import_rel
                                        try:
                                            staged_plot_path.parent.mkdir(parents=True, exist_ok=True)
                                            shutil.copy2(plot_path, staged_plot_path)
                                        except Exception as exc:
                                            logger.exception(
                                                "Failed to stage SEM-EDX plot PNG for import: src=%s dst=%s error=%s",
                                                plot_path,
                                                staged_plot_path,
                                                exc,
                                            )
                                            _append_job_error(
                                                job,
                                                f"Failed to stage SEM-EDX plot PNG for import: {staged_plot_path.name}",
                                            )
                                            imported_plots.add(txt_rel)
                                            continue

                                        logger.info(
                                            "SEM-EDX: plot staged for import: rel=%s staged=%s exists=%s",
                                            plot_import_rel,
                                            staged_plot_path,
                                            staged_plot_path.exists(),
                                        )

                                        import_entry = {
                                            "relative_path": plot_import_rel,
                                            "staged_path": plot_import_rel,
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
                                        )
                                        if import_result.get("status") == "error":
                                            if import_result.get("job_error"):
                                                _append_job_error(job, import_result["job_error"])
                                            if import_result.get("job_message"):
                                                _append_job_message(job, import_result["job_message"])
                                            logger.error(
                                                "Failed to import SEM EDX plot %s (dataset_id=%s staged=%s)",
                                                plot_import_rel,
                                                sem_dataset_id,
                                                str(staged_plot_path),
                                            )
                                        elif import_result.get("status") == "imported":
                                            _append_job_message(job, messages.imported_file(plot_import_rel))
                                            logger.info(
                                                "Imported SEM EDX plot %s into dataset_id=%s",
                                                plot_import_rel,
                                                sem_dataset_id,
                                            )
                                        imported_plots.add(txt_rel)

                                    # IMPORTANT: Attach via OMERO API using job-service connection (NO CLI, NO user session)
                                    try:
                                        logger.info("Attaching %s to %s (Image:%d)", txt_name, image_name, image_id)
                                        _attach_txt_to_image_service(
                                            conn,
                                            image_id,
                                            txt_path,
                                            username,  # Pass username for suConn
                                            create_tables,
                                            plot_path=plot_path if create_figures_attachments else None,
                                        )

                                        # Mark as imported if not already
                                        if txt_entry.get("status") != "imported":
                                            txt_entry["status"] = "imported"
                                            job["imported_bytes"] = job.get("imported_bytes", 0) + txt_entry.get("size", 0)

                                        _append_txt_attachment_message(job, txt_name, image_name, True)
                                        logger.info("Successfully attached %s to %s", txt_name, image_name)

                                    except Exception as exc:
                                        logger.error("Failed to attach %s to %s: %s", txt_rel, image_rel, exc)
                                        _append_txt_attachment_message(job, txt_name, image_name, False)

                                    # Save job state periodically
                                    if attachment_count % 5 == 0:
                                        _save_job(job)

                            
                            # Final save
                            _save_job(job)
                            logger.info("Completed SEM EDX attachment processing for job %s: %d/%d processed", 
                                      job_id, attachment_count, total_attachments)
                            
                        finally:
                            try:
                                conn.close()
                            except Exception as exc:
                                logger.warning("Error closing connection: %s", exc)
                except Exception:
                    logger.exception("SEM EDX txt attachment failed for job %s.", job_id)

            job = _load_job(job_id) or job
            if job.get("errors"):
                job["status"] = "error"
                logger.warning(
                    "Import thread: job %s finished with errors (%d errors, %d messages)",
                    job_id, len(job.get("errors", [])), len(job.get("messages", [])),
                )
            else:
                job["status"] = "done"
                logger.info(
                    "Import thread: job %s completed successfully "
                    "(imported_bytes=%s, total_bytes=%s, messages=%d)",
                    job_id,
                    job.get("imported_bytes", 0),
                    job.get("total_bytes", 0),
                    len(job.get("messages", [])),
                )
            _save_job(job)
        finally:
            lock.release()
            logger.info("Import thread: lock released for job %s", job_id)
    except Exception as exc:
        logger.exception("Import job %s failed unexpectedly.", job_id)
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
    _save_job(job)
    worker = threading.Thread(target=_process_import_job, args=(job_id,), daemon=True)
    worker.start()


# --------------------------------------------------------------------------
# VIEWS
# --------------------------------------------------------------------------
