"""
OMERO CLI import operations and verification.
"""
import json
import os
import re
import time
import logging
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Optional
import omero
import portalocker
from omero.gateway import BlitzGateway
from ...constants import OMERO_CLI
from ...utils.omero_helpers import get_id

logger = logging.getLogger(__name__)

MAX_IMPORT_LOG_LINES = 1000
INT_SANITIZER = re.compile(r"[^0-9]")
JOB_ID_SANITIZER = re.compile(r"^[0-9a-fA-F]{32}$")
_CLI_ID_PATTERN = re.compile(r"(?P<type>OriginalFile|FileAnnotation|ImageAnnotationLink):(?P<id>\\d+)")

JOB_SERVICE_USERNAME_DEFAULT = "job-service"
JOB_SERVICE_USER_ENV = "OMERO_JOB_SERVICE_USERNAME"
JOB_SERVICE_USER_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_USERNAME"
JOB_SERVICE_PASS_ENV = "OMERO_JOB_SERVICE_PASS"
JOB_SERVICE_PASS_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_PASS"
JOB_SERVICE_GROUP_ENV = "OMERO_JOB_SERVICE_GROUP"
JOB_SERVICE_GROUP_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_GROUP"
JOB_SERVICE_SECURE_ENV = "OMERO_JOB_SERVICE_SECURE"
JOB_SERVICE_SECURE_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_SECURE"
UPLOAD_ROOT_ENV = "OMERO_WEB_UPLOAD_DIR"
DEFAULT_UPLOAD_ROOT = "/tmp/omero-upload-tmp"
JOBS_DIR_ENV = "OMERO_WEB_UPLOAD_JOBS_DIR"
DEFAULT_JOBS_DIR = "/tmp/omero_web_upload_jobs"
UPLOAD_CLEANUP_INTERVAL_ENV = "OMERO_WEB_UPLOAD_CLEANUP_INTERVAL"
DEFAULT_UPLOAD_CLEANUP_INTERVAL = 300
UPLOAD_CLEANUP_MAX_AGE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_MAX_AGE"
DEFAULT_UPLOAD_CLEANUP_MAX_AGE = 12 * 60 * 60
UPLOAD_CLEANUP_STALE_AGE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_STALE_AGE"
DEFAULT_UPLOAD_CLEANUP_STALE_AGE = 48 * 60 * 60
UPLOAD_CLEANUP_MAX_DELETE_ENV = "OMERO_WEB_UPLOAD_CLEANUP_MAX_DELETE"
DEFAULT_UPLOAD_CLEANUP_MAX_DELETE = 25

_UPLOAD_ROOT_CACHE = None
_JOBS_ROOT_CACHE = None
_IMPORT_LOCKS = {}
_IMPORT_LOCKS_GUARD = threading.Lock()
_UPLOAD_CLEANUP_GUARD = threading.Lock()
_LAST_UPLOAD_CLEANUP_TIME = 0.0
_CLEANUP_IN_PROGRESS = False


def _get_env_int(env_key: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.environ.get(env_key, "")
    if raw:
        raw = INT_SANITIZER.sub("", str(raw))
    try:
        value = int(raw) if raw else default
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _get_upload_root() -> Path:
    global _UPLOAD_ROOT_CACHE
    if _UPLOAD_ROOT_CACHE is None:
        _UPLOAD_ROOT_CACHE = None
    return _UPLOAD_ROOT_CACHE


def _get_jobs_root() -> Path:
    global _JOBS_ROOT_CACHE
    if _JOBS_ROOT_CACHE is None:
        _JOBS_ROOT_CACHE = None
    return _JOBS_ROOT_CACHE

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


IMPORT_TIMEOUT_SECONDS = 600  # 10 minutes per file import


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
        result = _run_omero_cli(cmd, timeout=IMPORT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.error("Import CLI timed out after %ds for %s", IMPORT_TIMEOUT_SECONDS, path)
        return False, "", f"Import timed out after {IMPORT_TIMEOUT_SECONDS} seconds"
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
        sf = client.joinSession(session_key)
        sf.detachOnDestroy()
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
    sf = client.joinSession(session_key)
    sf.detachOnDestroy()
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
      - Optional PNG plot attachment (if plot_path provided)

    This is safe to run in background threads and does NOT touch the user's session.
    Uses suConn to impersonate the user so annotations are created in the correct group.
    """
    from omero.model import FileAnnotationI, OriginalFileI
    from omero.rtypes import rstring, rlong
    from omero.gateway import FileAnnotationWrapper
    from .sem_edx_parser import attach_sem_edx_tables

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
