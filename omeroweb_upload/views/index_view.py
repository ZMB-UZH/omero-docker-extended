import os
import json
import logging
import random
import re
import secrets
import stat
import string
import subprocess
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
UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"
DEFAULT_UPLOAD_CONCURRENCY = 3
DEFAULT_UPLOAD_BATCH_FILES = 5
UPLOAD_CLEANUP_INTERVAL_ENV = "OMERO_WEB_UPLOAD_CLEANUP_INTERVAL"
UPLOAD_CLEANUP_MAX_AGE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_MAX_AGE"
UPLOAD_CLEANUP_STALE_AGE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_STALE_AGE"
UPLOAD_CLEANUP_MAX_DELETE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_MAX_DELETE"
DEFAULT_UPLOAD_CLEANUP_INTERVAL = 300
DEFAULT_UPLOAD_CLEANUP_MAX_AGE = 12 * 60 * 60
DEFAULT_UPLOAD_CLEANUP_STALE_AGE = 48 * 60 * 60
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

# Cache for directory paths (initialized once per application lifecycle)
_UPLOAD_ROOT_CACHE = None
_JOBS_ROOT_CACHE = None
_DIRS_INITIALIZED = False


# --------------------------------------------------------------------------
# PATHS + JOB STORAGE
# --------------------------------------------------------------------------

def _resolve_upload_root() -> Path:
    configured = os.environ.get(UPLOAD_ROOT_ENV)
    return Path(configured) if configured else Path(DEFAULT_UPLOAD_ROOT)


def _resolve_jobs_root() -> Path:
    configured = os.environ.get(JOBS_DIR_ENV)
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


def _normalize_job_batch_size(value, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(10, normalized))


def _resolve_job_batch_size(job_dict) -> int:
    default_batch_size = _get_env_int(
        UPLOAD_BATCH_FILES_ENV,
        DEFAULT_UPLOAD_BATCH_FILES,
        1,
        10,
    )
    return _normalize_job_batch_size(job_dict.get("job_batch_size"), default_batch_size)


def _has_pending_uploads(job_dict) -> bool:
    return any(entry.get("status") == "pending" for entry in job_dict.get("files", []))


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

    # SEM-EDX: if nothing requires compatibility (e.g. only .txt files, or all skipped),
    # do NOT get stuck in "checking". Mark as compatible once uploads are complete.
    if job_dict.get("special_upload") == "sem_edx_spectra":
        pending_entries = _compatibility_pending_entries(job_dict)
        if not pending_entries and job_dict.get("compatibility_status") not in ("compatible", "incompatible", "error"):
            job_dict["compatibility_status"] = "compatible"

    compatibility_status = job_dict.get("compatibility_status")
    if compatibility_status == "incompatible":
        job_dict["status"] = "awaiting_confirmation"
    elif compatibility_status == "error":
        job_dict["status"] = "awaiting_confirmation"
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
# Omero IMPORT HELPERS
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


def _run_omero_cli(cmd):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
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

    result = _run_omero_cli(cmd)
    return result.returncode == 0, result.stdout, result.stderr


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


def _find_image_by_name(conn, file_name: str, dataset_id=None):
    if dataset_id:
        try:
            dataset = conn.getObject("Dataset", dataset_id)
            if dataset is not None:
                for image in dataset.listChildren():
                    if getattr(image, "getName", None) and image.getName() == file_name:
                        return image
        except Exception:
            return None
    try:
        for image in conn.getObjects("Image", attributes={"name": file_name}):
            if getattr(image, "getName", None) and image.getName() == file_name:
                return image
    except Exception:
        return None
    return None


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
            "job-service password missing. Set %s (or %s) in the omeroweb container environment.",
            JOB_SERVICE_PASS_ENV,
            JOB_SERVICE_PASS_ENV_FALLBACK,
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


def _attach_txt_to_image_service(conn: BlitzGateway, image_id: int, txt_path: Path):
    """Attach a TXT file to an Image using OMERO API (no CLI).

    Creates:
      - OriginalFile
      - FileAnnotation (ns=SEM_EDX_FILEANNOTATION_NS)
      - ImageAnnotationLink

    This is safe to run in background threads and does NOT touch the user's session.
    """
    from omero.model import FileAnnotationI, OriginalFileI, ImageAnnotationLinkI
    from omero.rtypes import rstring, rlong

    image = conn.getObject("Image", int(image_id))
    if image is None:
        raise RuntimeError(f"Image:{image_id} not found (service user cannot access it)")

    # Read bytes
    try:
        binary = txt_path.read_bytes()
    except Exception as exc:
        raise RuntimeError(f"Unable to read txt file {txt_path}: {exc}")

    update = conn.getUpdateService()

    of = OriginalFileI()
    of.setName(rstring(txt_path.name))
    of.setPath(rstring(f"sem_edx/img_{image_id}/"))
    of.setSize(rlong(len(binary)))
    of.setMimetype(rstring("text/plain"))

    of = update.saveAndReturnObject(of)

    store = conn.c.sf.createRawFileStore()
    try:
        store.setFileId(of.getId().getValue())
        store.write(binary, 0, len(binary))
        store.save()
    finally:
        try:
            store.close()
        except Exception:
            pass

    fa = FileAnnotationI()
    fa.setNs(rstring(SEM_EDX_FILEANNOTATION_NS))
    fa.setFile(of)

    fa = update.saveAndReturnObject(fa)

    link = ImageAnnotationLinkI()
    link.setParent(image._obj)
    link.setChild(fa)

    update.saveAndReturnObject(link)


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
        DEFAULT_UPLOAD_CLEANUP_INTERVAL,
        60,
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
            DEFAULT_UPLOAD_CLEANUP_MAX_AGE,
            15 * 60,
            14 * 24 * 60 * 60,
        )
        stale_age = _get_env_int(
            UPLOAD_CLEANUP_STALE_AGE_ENV,
            DEFAULT_UPLOAD_CLEANUP_STALE_AGE,
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
    
    CRITICAL FIX: The -f flag returns:
    - Exit code 0: ALWAYS (even for incompatible files)
    - Actual compatibility is determined by checking if import candidates exist in stdout
    """
    details = (stderr or stdout or "").strip()
    lowered = details.lower()
    
    # CRITICAL: Check stderr first for fatal errors (missing file, CLI errors, etc.)
    if stderr and stderr.strip():
        stderr_lower = stderr.lower()
        # These indicate real errors, not just incompatibility
        error_indicators = [
            "exception",
            "error:",
            "failed to",
            "cannot access",
            "no such file",
            "permission denied",
            "timeout",
        ]
        if any(indicator in stderr_lower for indicator in error_indicators):
            return "error", stderr.strip()
    
    # Check stdout for explicit incompatibility messages
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
    
    # CRITICAL FIX: Check if stdout contains actual import candidates
    # The -f flag ALWAYS returns 0, so we MUST parse stdout
    has_candidates = _has_import_candidates_in_output(stdout or "")
    
    if has_candidates:
        return "compatible", "File format supported by OMERO"
    else:
        # No candidates found = file is incompatible
        return "incompatible", "No importable files detected by Bio-Formats"




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
    job = _load_job(job_id)
    if not job:
        return

    try:
        username = job.get("username") or ""
        lock = _get_import_lock(username)

        with lock:
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

            upload_root = _get_upload_root() / job_id
            if not upload_root.exists():
                job["status"] = "error"
                job["errors"].append(errors.upload_folder_missing_on_server())
                _save_job(job)
                return

            dataset_map = job.get("dataset_map") or {}
            orphan_dataset_name = job.get("orphan_dataset_name")
            batch_size = _resolve_job_batch_size(job)
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

            for start in range(0, len(entries_to_import), batch_size):
                batch = entries_to_import[start:start + batch_size]
                if not batch:
                    continue
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
                        result = future.result()
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
                            image_cache = {}
                            attachment_count = 0
                            total_attachments = sum(
                                len(txt_paths) for txt_paths in sem_edx_associations.values() 
                                if isinstance(txt_paths, list)
                            )
                            
                            logger.info("Processing %d SEM EDX text attachments for job %s", total_attachments, job_id)
                            
                            for image_rel, txt_paths in sem_edx_associations.items():
                                if not isinstance(txt_paths, list):
                                    continue

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

                                        # Clear caches because OMERO objects become stale after reconnect
                                        image_cache.clear()

                                # Find or cache the image
                                if image_rel not in image_cache:
                                    dataset_name = _dataset_name_for_path(image_rel, orphan_dataset_name)
                                    dataset_id = dataset_map.get(dataset_name)

                                    try:
                                        image_cache[image_rel] = _find_image_by_name(
                                            conn, image_name, dataset_id=dataset_id
                                        )
                                    except Exception as exc:
                                        logger.warning("Failed to find image %s: %s", image_name, exc)
                                        image_cache[image_rel] = None

                                        # If it looks like a session issue, reopen job-service connection (NOT user session)
                                        if "session" in str(exc).lower():
                                            try:
                                                try:
                                                    conn.close()
                                                except Exception:
                                                    pass
                                                conn = _open_service_connection(host, port, group_id=job.get("group_id"))
                                            except Exception:
                                                conn = None

                                            if conn:
                                                image_cache.clear()
                                                try:
                                                    image_cache[image_rel] = _find_image_by_name(
                                                        conn, image_name, dataset_id=dataset_id
                                                    )
                                                except Exception:
                                                    image_cache[image_rel] = None

                                image_obj = image_cache.get(image_rel)

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

                                    # IMPORTANT: Attach via OMERO API using job-service connection (NO CLI, NO user session)
                                    try:
                                        logger.info("Attaching %s to %s (Image:%d)", txt_name, image_name, image_id)
                                        _attach_txt_to_image_service(
                                            conn,
                                            image_id,
                                            txt_path,
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
            else:
                job["status"] = "done"
            _save_job(job)
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

@login_required()
def index(request, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    username = current_username(request, conn)
    user_id = _current_user_id(conn)
    upload_root = _get_upload_root()
    upload_enabled = _ensure_dir(upload_root)
    job_dir_ok = _ensure_dir(_get_jobs_root())
    upload_concurrency = _get_env_int(UPLOAD_CONCURRENCY_ENV, DEFAULT_UPLOAD_CONCURRENCY, 1, 10)
    upload_batch_files = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10)
    projects = _collect_project_payload(conn, user_id)
    return render(
        request,
        "omeroweb_upload/index.html",
        {
            "upload_root": str(upload_root),
            "upload_enabled": upload_enabled and job_dir_ok,
            "upload_start_url": reverse("omeroweb_upload_start"),
            "upload_concurrency": upload_concurrency,
            "upload_batch_files": upload_batch_files,
            "user_id": user_id,
            "messages_json": json.dumps(messages.index_messages()),
            "projects": projects,
            "project_list_url": reverse("omeroweb_upload_projects"),
        },
    )


@login_required()
def list_projects(request, conn=None, url=None, **kwargs):
    user_id = _current_user_id(conn)
    payload = _collect_project_payload(conn, user_id)
    return JsonResponse(payload)


@login_required()
def root_status(request, conn=None, url=None, **kwargs):
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})


@login_required()
def start_upload(request, conn=None, url=None, **kwargs):
    try:
        return _start_upload(request, conn)
    except Exception:
        logger.exception("Unhandled error while starting upload job.")
        return json_error(errors.unexpected_server_error_start_upload(), status=500)


def _start_upload(request, conn):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.upload_start_post_required())

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root) or not _ensure_dir(_get_jobs_root()):
        logger.warning("Upload folder not writable or job dir missing.")
        return json_error(errors.upload_folder_not_writable())

    payload = load_json_body(request)
    if not isinstance(payload, dict):
        payload = {}

    raw_project_id = (payload.get("project_id") or "").strip()
    project_id = None
    project_name = ""
    if raw_project_id:
        try:
            project_id = int(raw_project_id)
        except (TypeError, ValueError):
            return json_error(errors.invalid_project_selection(), status=400)
        try:
            project = conn.getObject("Project", project_id)
        except Exception:
            project = None
        if project is None or not (
            _is_owned_by_user(project, _current_user_id(conn)) or _has_read_write_permissions(project)
        ):
            return json_error(errors.invalid_project_selection(), status=400)
        project_name = _get_text(project.getName())

    files = payload.get("files") or []
    if not isinstance(files, list):
        files = []
    if not files:
        logger.info("Upload start request missing files payload.")
        return json_error(errors.no_files_provided())
    special_upload = (payload.get("special_upload") or "").strip()
    raw_sem_edx_associations = payload.get("sem_edx_associations") or {}
    if special_upload != "sem_edx_spectra":
        raw_sem_edx_associations = {}
    default_batch_size = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10)
    batch_size = _normalize_job_batch_size(payload.get("batch_size"), default_batch_size)

    session_key = _get_session_key(conn)
    if not session_key:
        logger.warning("Unable to resolve Omero session key for upload start.")
        return json_error(errors.unable_resolve_session())

    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        logger.warning("Unable to resolve Omero host/port for upload start.")
        return json_error(errors.unable_resolve_host_port())

    normalized = []
    total_bytes = 0
    invalid = []

    for entry in files:
        if not isinstance(entry, dict):
            invalid.append(str(entry))
            continue
        raw_name = entry.get("relative_path") or entry.get("name")
        size = entry.get("size")
        rel_path = _safe_relative_path(raw_name or "")
        if rel_path is None:
            invalid.append(raw_name)
            continue
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        if size < 0:
            size = 0
        upload_id = uuid.uuid4().hex
        compatibility_skip = bool(entry.get("compatibility_skip"))
        import_skip = bool(entry.get("import_skip"))

        filename = PurePosixPath(rel_path).name

        # SEM-EDX: TXT files must NEVER be imported or compatibility-checked
        if special_upload == "sem_edx_spectra" and filename.lower().endswith(".txt"):
            import_skip = True
            compatibility_skip = True

        staged_path = f"_staged/{upload_id}/{filename}"

        total_bytes += size
        if total_bytes > MAX_UPLOAD_BATCH_BYTES:
            logger.info(
                "Upload start rejected batch exceeding %d GB for user %s.",
                MAX_UPLOAD_BATCH_GB,
                current_username(request, conn),
            )
            return json_error(errors.upload_batch_too_large(MAX_UPLOAD_BATCH_GB))
        normalized.append(
            {
                "upload_id": upload_id,
                "relative_path": rel_path,
                "staged_path": staged_path,
                "size": size,
                "status": "pending",
                "errors": [],
                "compatibility_skip": compatibility_skip,
                "import_skip": import_skip,
            }
        )

    if invalid:
        logger.info("Upload start rejected invalid paths: %s", invalid)
        return json_error(errors.invalid_file_paths(invalid))

    sem_edx_associations = _normalize_sem_edx_associations(raw_sem_edx_associations, normalized)

    dataset_map = {}
    orphan_dataset_name = None
    try:
        dataset_names = set()
        if any(_dataset_name_for_path(entry["relative_path"]) is None for entry in normalized):
            orphan_dataset_name = _generate_orphan_dataset_name()
        for entry in normalized:
            dataset_name = _dataset_name_for_path(entry["relative_path"], orphan_dataset_name)
            if dataset_name:
                dataset_names.add(dataset_name)
        for dataset_name in sorted(dataset_names):
            dataset_id = _get_or_create_dataset(conn, dataset_name, dataset_map, project_id=project_id)
            if dataset_id is None:
                logger.warning("Unable to resolve dataset for %s", dataset_name)
    except Exception:
        logger.exception("Unable to prepare datasets for upload request.")

    job_id = uuid.uuid4().hex
    username = current_username(request, conn)
    current_group_id = None
    try:
        # Preserve the user's current group context so the service account can attach in the same group.
        current_group_id = conn.SERVICE_OPTS.getOmeroGroup()
    except Exception:
        current_group_id = None
    job = {
        "job_id": job_id,
        "username": username,
        "session_key": session_key,
        "group_id": current_group_id,
        "host": host,
        "port": port,
        "project_id": project_id,
        "project_name": project_name,
        "files": normalized,
        "total_bytes": total_bytes,
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "status": "uploading",
        "errors": [],
        "created": time.time(),
        "dataset_map": dataset_map,
        "orphan_dataset_name": orphan_dataset_name,
        "import_index": 0,
        "messages": [],
        "import_thread_started": False,
        "job_batch_size": batch_size,
        "compatibility_status": "pending",
        "incompatible_files": [],
        "compatibility_thread_active": False,
        "compatibility_confirmed": False,
        "special_upload": special_upload,
        "sem_edx_associations": sem_edx_associations,
    }
    _save_job(job)

    logger.info(
        "Upload job %s created for user %s with %d files (%d bytes).",
        job_id,
        username,
        len(normalized),
        total_bytes,
    )

    return JsonResponse(
        {
            "ok": True,
            "job_id": job_id,
            "upload_url": reverse("omeroweb_upload_files", kwargs={"job_id": job_id}),
            "import_step_url": reverse("omeroweb_upload_import_step", kwargs={"job_id": job_id}),
            "status_url": reverse("omeroweb_upload_status", kwargs={"job_id": job_id}),
            "confirm_url": reverse("omeroweb_upload_confirm", kwargs={"job_id": job_id}),
            "prune_url": reverse("omeroweb_upload_prune", kwargs={"job_id": job_id}),
        }
    )


@login_required()
def upload_files(request, job_id, conn=None, url=None, **kwargs):
    try:
        return _upload_files(request, job_id)
    except Exception:
        logger.exception("Unhandled error while uploading files for job %s.", job_id)
        return json_error(errors.unexpected_server_error_uploading_files(), status=500)


def _upload_files(request, job_id):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.upload_endpoint_post_required())

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root):
        logger.warning("Upload root not writable for job %s.", job_id)
        return json_error(errors.upload_folder_not_writable())

    job = _load_job(job_id)
    if not job:
        logger.warning("Upload job %s not found.", job_id)
        return json_error(errors.upload_job_not_found())

    files = request.FILES.getlist("files")
    if not files:
        logger.info("Upload job %s received no files.", job_id)
        return json_error(errors.no_files_provided())

    relative_paths = request.POST.getlist("relative_paths")
    if relative_paths and len(relative_paths) != len(files):
        logger.warning("Upload payload mismatch for job %s.", job_id)
        return json_error(errors.upload_payload_mismatch())

    job_root = upload_root / job_id
    if not _ensure_dir(job_root):
        logger.warning("Unable to initialize upload folder for job %s.", job_id)
        return json_error(errors.unable_initialize_upload_folder())

    saved = []
    upload_errors = []
    entries_by_path = {}
    updates = []
    for file_entry in job["files"]:
        if file_entry.get("status") in ("pending", "error"):
            entries_by_path.setdefault(file_entry["relative_path"], []).append(file_entry)

    for index, upload in enumerate(files):
        raw_name = relative_paths[index] if relative_paths else upload.name
        rel_path = _safe_relative_path(raw_name)
        if rel_path is None:
            upload_errors.append(errors.invalid_filename(raw_name))
            continue

        entry_queue = entries_by_path.get(rel_path) or []
        if not entry_queue:
            upload_errors.append(errors.unexpected_file(rel_path))
            continue
        entry = entry_queue.pop(0)

        staged_path = entry.get("staged_path") or rel_path
        target = job_root / staged_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            saved.append(rel_path)
            entry["status"] = "uploaded"
            updates.append({"upload_id": entry.get("upload_id"), "status": "uploaded"})
        except OSError as exc:
            logger.warning("Failed to save upload %s: %s", rel_path, exc)
            upload_errors.append(f"{rel_path}: {exc}")
            entry["status"] = "error"
            entry.setdefault("errors", []).append(str(exc))
            updates.append(
                {"upload_id": entry.get("upload_id"), "status": "error", "errors": [str(exc)]}
            )

    updated_job = _apply_upload_updates(job_id, updates, upload_errors)
    if not updated_job:
        return json_error(errors.unable_update_upload_job_state())

    if _should_start_compatibility_check(updated_job):
        _start_compatibility_check_thread(job_id)
        logger.info("Upload job %s checking compatibility.", job_id)
    if updated_job["status"] == "ready":
        _start_import_thread(job_id)
        logger.info("Upload job %s ready; import thread started.", job_id)

    return JsonResponse(
        {
            "ok": len(upload_errors) == 0,
            "saved": saved,
            "errors": upload_errors,
            "error": upload_errors[0] if upload_errors else None,
            "uploaded_bytes": updated_job.get("uploaded_bytes", 0),
            "total_bytes": updated_job.get("total_bytes", 0),
            "ready": updated_job.get("status") == "ready",
        }
    )


@login_required()
def import_step(request, job_id, conn=None, url=None, **kwargs):
    try:
        return _import_step(request, job_id)
    except Exception:
        logger.exception("Unhandled error while importing job %s.", job_id)
        return json_error(errors.unexpected_server_error_importing(), status=500)


def _import_step(request, job_id):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.import_endpoint_post_required())

    job = _load_job(job_id)
    if not job:
        logger.warning("Import job %s not found.", job_id)
        return json_error(errors.import_job_not_found())

    if job.get("status") == "ready":
        _start_import_thread(job_id)
        job = _load_job(job_id) or job

    return JsonResponse(
        {
            "ok": True,
            "done": job.get("status") in ("done", "error"),
            "status": job.get("status"),
            "imported_bytes": job.get("imported_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "messages": job.get("messages", []),
        }
    )


@login_required()
def confirm_import(request, job_id, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.method_post_required())

    job = _load_job(job_id)
    if not job:
        return json_error(errors.upload_job_not_found())

    if job.get("status") != "awaiting_confirmation":
        return JsonResponse({"ok": True, "status": job.get("status")})

    job["compatibility_confirmed"] = True
    job["compatibility_thread_active"] = False
    job["status"] = "ready"
    job["updated"] = time.time()
    _save_job(job)
    _start_import_thread(job_id)

    return JsonResponse({"ok": True, "status": "ready"})


@login_required()
def prune_upload(request, job_id, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.method_post_required())

    job = _load_job(job_id)
    if not job:
        return json_error(errors.upload_job_not_found())

    payload = load_json_body(request)
    if not isinstance(payload, dict):
        payload = {}

    keep_paths = payload.get("keep_paths") or []
    if not isinstance(keep_paths, list):
        keep_paths = []

    keep_set = set()
    for path in keep_paths:
        rel_path = _safe_relative_path(path)
        if rel_path:
            keep_set.add(rel_path)

    upload_root = _get_upload_root() / job_id

    def apply_prune(job_dict):
        removed = []
        kept_entries = []
        for entry in job_dict.get("files", []):
            rel_path = entry.get("relative_path")
            if not rel_path or rel_path not in keep_set:
                removed.append(entry)
                continue
            kept_entries.append(entry)

        for entry in removed:
            staged_path = entry.get("staged_path") or entry.get("relative_path")
            if not staged_path:
                continue
            file_path = upload_root / staged_path
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError as exc:
                logger.warning("Failed to remove staged file %s: %s", file_path, exc)

        job_dict["files"] = kept_entries
        job_dict["total_bytes"] = sum(entry.get("size", 0) for entry in kept_entries)
        job_dict["uploaded_bytes"] = sum(
            entry.get("size", 0) for entry in kept_entries if entry.get("status") == "uploaded"
        )
        job_dict["incompatible_files"] = sorted(
            entry.get("relative_path")
            for entry in kept_entries
            if entry.get("compatibility") == "incompatible" and entry.get("relative_path")
        )

        pending_after = _compatibility_pending_entries(job_dict)
        has_errors = any(entry.get("compatibility") == "error" for entry in kept_entries)
        if job_dict["incompatible_files"]:
            job_dict["compatibility_status"] = "incompatible"
        elif pending_after:
            job_dict["compatibility_status"] = "checking"
        elif has_errors:
            job_dict["compatibility_status"] = "error"
        else:
            job_dict["compatibility_status"] = "compatible"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    job = _update_job(job_id, apply_prune)
    if not job:
        return json_error(errors.unable_update_upload_job_state())

    if job.get("status") == "ready":
        _start_import_thread(job_id)

    return JsonResponse({"ok": True, "status": job.get("status")})


@login_required()
def job_status(request, job_id, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    job = _load_job(job_id)
    if not job:
        return json_error(errors.upload_job_not_found())

    return JsonResponse(
        {
            "ok": True,
            "status": job.get("status"),
            "uploaded_bytes": job.get("uploaded_bytes", 0),
            "imported_bytes": job.get("imported_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "errors": job.get("errors", []),
            "messages": job.get("messages", []),
            "compatibility_status": job.get("compatibility_status"),
            "compatibility_checked": sum(
                1 for f in job.get("files", []) if f.get("compatibility")
            ),
            "compatibility_total": sum(
                1
                for f in job.get("files", [])
                if f.get("status") == "uploaded" and not f.get("compatibility_skip")
            ),
            "incompatible_files": job.get("incompatible_files", []),
            "confirmation_required": job.get("status") == "awaiting_confirmation",
        }
    )
