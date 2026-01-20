"""
OMERO connection and session management.
"""
import os
import logging
from typing import Optional
from omero.gateway import BlitzGateway
from omero.model import FileAnnotationI, OriginalFileI, ImageAnnotationLinkI
from omero.rtypes import rstring
from pathlib import Path

logger = logging.getLogger(__name__)

# Service account constants
JOB_SERVICE_USERNAME_DEFAULT = "job-service"
JOB_SERVICE_USER_ENV = "OMERO_JOB_SERVICE_USERNAME"
JOB_SERVICE_USER_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_USERNAME"
JOB_SERVICE_PASS_ENV = "OMERO_JOB_SERVICE_PASS"
JOB_SERVICE_PASS_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_PASS"
JOB_SERVICE_GROUP_ENV = "OMERO_JOB_SERVICE_GROUP"
JOB_SERVICE_GROUP_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_GROUP"
JOB_SERVICE_SECURE_ENV = "OMERO_JOB_SERVICE_SECURE"
JOB_SERVICE_SECURE_ENV_FALLBACK = "OMERO_WEB_JOB_SERVICE_SECURE"
SEM_EDX_FILEANNOTATION_NS = "sem_edx.spectra"

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
