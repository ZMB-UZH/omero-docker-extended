import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
import portalocker
import stat

from pathlib import Path, PurePosixPath
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from omero.model import DatasetI
from omero.rtypes import rstring
from omeroweb.decorators import login_required
from ..constants import MAX_UPLOAD_BATCH_BYTES, MAX_UPLOAD_BATCH_GB
from ..strings import errors, messages
from .utils import current_username, json_error, load_json_body

logger = logging.getLogger(__name__)

_IMPORT_LOCKS = {}
_IMPORT_LOCKS_GUARD = threading.Lock()
_UPLOAD_CLEANUP_GUARD = threading.Lock()
_LAST_UPLOAD_CLEANUP_TIME = 0.0

UPLOAD_ROOT_ENV = "OMERO_WEB_UPLOAD_DIR"
DEFAULT_UPLOAD_ROOT = "/opt/omero-upload-tmp"
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

# Cache for directory paths (initialized once per application lifecycle)
_UPLOAD_ROOT_CACHE = None
_JOBS_ROOT_CACHE = None
_DIRS_INITIALIZED = False


# --------------------------------------------------------------------------
# PATHS + JOB STORAGE
# --------------------------------------------------------------------------

def _get_base_tmp_path() -> Path:
    """
    Calculate the base tmp directory path at the same level as the plugin folder.
    
    If plugin is at /opt/omero-test/, returns /opt/tmp/
    This ensures tmp directory is outside the plugin folder.
    
    This calculation is lightweight and only performs path operations,
    no filesystem checks or modifications.
    """
    # Get the directory where this file (index_view.py) is located
    current_file = Path(__file__).resolve()
    
    # Go up from: omeroweb_upload/views/index_view.py -> omeroweb_upload/views/ -> omeroweb_upload/ -> omero-test/ -> /opt/
    plugin_views_dir = current_file.parent  # omeroweb_upload/views/
    plugin_root = plugin_views_dir.parent    # omeroweb_upload/
    project_root = plugin_root.parent        # omero-test/
    base_path = project_root.parent          # /opt/
    
    # Create tmp directory at same level as plugin folder
    return base_path / "tmp"


def _initialize_directories():
    """
    Initialize upload directories once per application lifecycle.
    
    This function:
    - Creates /opt/tmp with 0o755 (accessible for traversal)
    - Creates target directories with 0o700 (secure)
    - Only runs once, subsequent calls return immediately
    
    Called automatically by _get_upload_root() and _get_jobs_root()
    """
    global _DIRS_INITIALIZED
    
    if _DIRS_INITIALIZED:
        return  # Already initialized, skip
    
    base_tmp = _get_base_tmp_path()
    upload_root = base_tmp / "omero-upload-tmp"
    jobs_root = base_tmp / "omero_web_upload_jobs"
    
    # Create parent directory (/opt/tmp) with 0o755 if needed
    if not base_tmp.exists():
        try:
            base_tmp.mkdir(parents=True, mode=0o755, exist_ok=True)
            logger.info(f"Created base tmp directory: {base_tmp} with permissions 0o755")
        except OSError as exc:
            logger.error(f"Unable to create base tmp directory {base_tmp}: {exc}")
            return  # Don't mark as initialized if failed
    
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
    
    if UPLOAD_ROOT_ENV in os.environ:
        # Use environment variable if set (absolute path)
        configured = os.environ.get(UPLOAD_ROOT_ENV)
        return Path(configured)
    
    # Use cached path if available
    if _UPLOAD_ROOT_CACHE is None:
        _initialize_directories()
        base_tmp = _get_base_tmp_path()
        _UPLOAD_ROOT_CACHE = base_tmp / "omero-upload-tmp"
    
    return _UPLOAD_ROOT_CACHE


def _get_jobs_root() -> Path:
    """
    Get the jobs directory.
    
    Uses cached path after first initialization to avoid repeated filesystem checks.
    """
    global _JOBS_ROOT_CACHE
    
    if JOBS_DIR_ENV in os.environ:
        # Use environment variable if set (absolute path)
        configured = os.environ.get(JOBS_DIR_ENV)
        return Path(configured)
    
    # Use cached path if available
    if _JOBS_ROOT_CACHE is None:
        _initialize_directories()
        base_tmp = _get_base_tmp_path()
        _JOBS_ROOT_CACHE = base_tmp / "omero_web_upload_jobs"
    
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


def _save_job(job_dict):
    path = _job_path(job_dict["job_id"])
    job_dict["updated"] = time.time()
    try:
        with portalocker.Lock(path, "w", timeout=1) as handle:
            json.dump(job_dict, handle)
        return True
    except (portalocker.exceptions.LockException, OSError) as exc:
        logger.warning("Unable to lock job file %s for writing: %s", path, exc)
    try:
        with path.open("w") as handle:
            json.dump(job_dict, handle)
        return True
    except OSError as exc:
        logger.warning("Unable to write job file %s without lock: %s", path, exc)
    return False


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


def _dataset_name_for_path(relative_path: str):
    parts = PurePosixPath(relative_path).parts
    if len(parts) <= 1:
        return None
    return "\\".join(parts[:-1])


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


def _get_or_create_dataset(conn, name: str, dataset_map: dict):
    if not name:
        return None
    if name in dataset_map:
        return dataset_map[name]

    existing = None
    try:
        existing = next(conn.getObjects("Dataset", attributes={"name": name}), None)
    except Exception:
        existing = None

    if existing is not None:
        dataset_id = existing.getId().getValue()
        dataset_map[name] = dataset_id
        return dataset_id

    try:
        dataset = DatasetI()
        dataset.setName(rstring(name))
        dataset = conn.getUpdateService().saveAndReturnObject(dataset)
        dataset_id = dataset.getId().getValue()
    except Exception as exc:
        logger.warning("Failed to create dataset %s: %s", name, exc)
        return None

    dataset_map[name] = dataset_id
    return dataset_id


def _import_file(conn, session_key: str, host: str, port: int, path: Path, dataset_id=None):
    cmd = ["omero", "import", "-k", session_key]
    if host:
        cmd.extend(["-s", host])
    if port:
        cmd.extend(["-p", str(port)])
    if dataset_id:
        cmd.extend(["-d", str(dataset_id)])
    cmd.append(str(path))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.stdout, result.stderr


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
    global _LAST_UPLOAD_CLEANUP_TIME
    now = time.time()
    with _UPLOAD_CLEANUP_GUARD:
        if now - _LAST_UPLOAD_CLEANUP_TIME < interval:
            return False
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


def _apply_upload_updates(job_id: str, updates: list, errors: list):
    path = _job_path(job_id)

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
        pending_entries = any(entry.get("status") == "pending" for entry in job_dict.get("files", []))
        if not pending_entries:
            job_dict["status"] = "ready"
        job_dict["updated"] = time.time()
        return job_dict

    try:
        with portalocker.Lock(path, "r+", timeout=5) as handle:
            job_dict = json.load(handle)
            job_dict = apply_updates(job_dict)
            handle.seek(0)
            handle.truncate()
            json.dump(job_dict, handle)
        return job_dict
    except (portalocker.exceptions.LockException, OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to lock job file %s for upload update: %s", path, exc)

    job_dict = _load_job(job_id)
    if not job_dict:
        return None
    job_dict = apply_updates(job_dict)
    _save_job(job_dict)
    return job_dict


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

            for entry in job.get("files", []):
                if entry.get("status") not in ("uploaded", "pending"):
                    continue

                rel_path = entry.get("relative_path")
                if not rel_path:
                    continue

                staged_path = entry.get("staged_path") or rel_path
                file_path = upload_root / staged_path
                if not file_path.exists():
                    error_msg = errors.missing_staged_file(rel_path)
                    entry["status"] = "error"
                    entry.setdefault("errors", []).append(error_msg)
                    _append_job_error(job, error_msg)
                    _append_job_message(job, error_msg)
                    _save_job(job)
                    continue

                dataset_name = _dataset_name_for_path(rel_path)
                dataset_id = dataset_map.get(dataset_name)

                success, stdout, stderr = _import_file(
                    conn=None,
                    session_key=session_key,
                    host=host,
                    port=port,
                    path=file_path,
                    dataset_id=dataset_id,
                )
                if not success:
                    logger.warning(
                        "Import failed for %s (stdout=%r, stderr=%r).",
                        rel_path,
                        stdout.strip(),
                        stderr.strip(),
                    )
                    error_msg = errors.import_failed()
                    entry["status"] = "error"
                    entry.setdefault("errors", []).append(error_msg)
                    _append_job_error(job, messages.job_error_with_path(rel_path, error_msg))
                    _append_job_message(job, messages.job_error_with_path(rel_path, error_msg))
                    _save_job(job)
                    continue

                entry["status"] = "imported"
                job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                _append_job_message(job, messages.imported_file(rel_path))
                try:
                    file_path.unlink()
                except OSError as exc:
                    logger.warning("Failed to remove staged file %s: %s", file_path, exc)
                _save_job(job)

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
    is_root_user = username == "root"
    upload_root = _get_upload_root()
    upload_enabled = _ensure_dir(upload_root)
    job_dir_ok = _ensure_dir(_get_jobs_root())
    upload_concurrency = _get_env_int(UPLOAD_CONCURRENCY_ENV, DEFAULT_UPLOAD_CONCURRENCY, 1, 10)
    upload_batch_files = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 25)
    return render(
        request,
        "omeroweb_upload/index.html",
        {
            "upload_root": str(upload_root),
            "upload_enabled": upload_enabled and job_dir_ok,
            "upload_start_url": reverse("omeroweb_upload_start"),
            "upload_concurrency": upload_concurrency,
            "upload_batch_files": upload_batch_files,
            "is_root_user": is_root_user,
        },
    )


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

    files = payload.get("files") or []
    if not isinstance(files, list):
        files = []
    if not files:
        logger.info("Upload start request missing files payload.")
        return json_error(errors.no_files_provided())

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
        filename = PurePosixPath(rel_path).name
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
            }
        )

    if invalid:
        logger.info("Upload start rejected invalid paths: %s", invalid)
        return json_error(errors.invalid_file_paths(invalid))

    dataset_map = {}
    try:
        dataset_names = set()
        for entry in normalized:
            dataset_name = _dataset_name_for_path(entry["relative_path"])
            if dataset_name:
                dataset_names.add(dataset_name)
        for dataset_name in sorted(dataset_names):
            dataset_id = _get_or_create_dataset(conn, dataset_name, dataset_map)
            if dataset_id is None:
                logger.warning("Unable to resolve dataset for %s", dataset_name)
    except Exception:
        logger.exception("Unable to prepare datasets for upload request.")

    job_id = uuid.uuid4().hex
    username = current_username(request, conn)
    job = {
        "job_id": job_id,
        "username": username,
        "session_key": session_key,
        "host": host,
        "port": port,
        "files": normalized,
        "total_bytes": total_bytes,
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "status": "uploading",
        "errors": [],
        "created": time.time(),
        "dataset_map": dataset_map,
        "import_index": 0,
        "messages": [],
        "import_thread_started": False,
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
        }
    )
