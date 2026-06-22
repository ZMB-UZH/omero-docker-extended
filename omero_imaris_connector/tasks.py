import logging
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import omero
from celery import states
from omero.gateway import BlitzGateway
from omero_plugin_common import process_utils
from omero_plugin_common.logging_utils import (
    sanitize_log_value,
    sanitized_exc_info,
    summarize_process_output,
)

from .celery_app import app
from .config import (
    get_celery_broker_url,
    get_celery_result_expires,
    get_connector_tmp_dir,
    get_ome_tiff_staging_root,
    get_job_service_credentials,
    use_job_service_session,
)
from .imaris_service import (
    EXPORT_TIMEOUT,
    _find_script_id,
    _serialize_outputs,
)

logger = logging.getLogger(__name__)
subprocess = process_utils

_GENERIC_EXPORT_ERROR = "IMS export job failed."
_GENERIC_OME_TIFF_EXPORT_ERROR = "OME-TIFF export job failed."
_EXPORT_CANCELLED_MESSAGE = "IMS export stopped by user."
_EXPORT_CANCEL_MARKER_PREFIX = "omero_imaris_connector:export_cancel:"
_EXPORT_CANCEL_MARKER_MIN_TTL_SECONDS = 300
_DOWNLOADABLE_EXPORT_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR
_PRIVATE_EXPORT_DIR_MODE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
_PRESERVE_JOINED_SESSION_ATTR = "_omero_imaris_preserve_joined_session"
_PUBLIC_SCRIPT_MESSAGES = {
    "Conversion to IMS failed",
    "Could not get original file path",
    "Could not prepare source image for IMS conversion",
}
_SELECTED_IMAGE_OME_TIFF_EXPORT_FAILED = "Could not export selected Image as OME-TIFF"
_CLI_OUTPUT_KEYS = {"Message", "Export_Path", "Export_Name", "File_Annotation_Id"}
_CLI_OUTPUT_LINE_RE = re.compile(
    r"^\s*(?:\*)?\s*([A-Za-z_][A-Za-z0-9_]*)"
    r"\s*(?:=|:|\t+|\s{2,})\s*(.*?)\s*$"
)


class IMSExportTaskError(RuntimeError):
    """Error whose public message is safe to return to the XT client."""

    def __init__(self, message: str, public_message: str | None = None) -> None:
        """Initialize the error with an optional sanitized public message.

        Inputs: `message`, `public_message`. Output: None.
        """
        super().__init__(message)
        self.public_message = public_message


class OMEExportTaskError(RuntimeError):
    """Error whose public message is safe to return for OME-TIFF export jobs."""

    def __init__(self, message: str, public_message: str | None = None) -> None:
        """Initialize the error with an optional sanitized public message.

        Inputs: `message`, `public_message`. Output: None.
        """
        super().__init__(message)
        self.public_message = public_message


def _export_cancel_marker_key(task_id):
    """Return the Redis key used to mark user-requested export cancellation.

    Inputs: Celery task id. Output: marker key or None.
    """
    if not task_id:
        return None
    return f"{_EXPORT_CANCEL_MARKER_PREFIX}{task_id}"


def _export_cancel_marker_ttl():
    """Return the cancellation marker TTL.

    Inputs: none. Output: TTL seconds.
    """
    try:
        return max(_EXPORT_CANCEL_MARKER_MIN_TTL_SECONDS, get_celery_result_expires())
    except Exception:
        return _EXPORT_CANCEL_MARKER_MIN_TTL_SECONDS


def _export_cancel_redis_client():
    """Return a Redis client for cancellation markers when configured.

    Inputs: none. Output: Redis client or None.
    """
    try:
        redis_url = str(get_celery_broker_url() or "")
    except Exception:
        return None
    if not redis_url.startswith(("redis://", "rediss://")):
        return None
    try:
        from redis import Redis  # type: ignore[import-not-found,unused-ignore]
    except Exception:
        return None
    try:
        return Redis.from_url(redis_url)
    except Exception:
        logger.debug("Unable to create Redis client for export cancellation markers.")
        return None


def mark_export_task_cancel_requested(task_id):
    """Mark a Celery export task as user-cancelled.

    Inputs: Celery task id. Output: whether the marker was stored.
    """
    key = _export_cancel_marker_key(task_id)
    client = _export_cancel_redis_client()
    if key is None or client is None:
        return False
    try:
        client.setex(key, _export_cancel_marker_ttl(), b"1")
        return True
    except Exception as exc:
        logger.debug(
            "Unable to mark export task cancellation for %s: %s",
            sanitize_log_value(task_id),
            sanitize_log_value(exc),
        )
        return False


def export_task_cancel_requested(task_id):
    """Return whether a Celery export task has a user-cancel marker.

    Inputs: Celery task id. Output: bool.
    """
    key = _export_cancel_marker_key(task_id)
    client = _export_cancel_redis_client()
    if key is None or client is None:
        return False
    try:
        return bool(client.get(key))
    except Exception as exc:
        logger.debug(
            "Unable to read export task cancellation marker for %s: %s",
            sanitize_log_value(task_id),
            sanitize_log_value(exc),
        )
        return False


def _cancelled_task_result(owner_token=None):
    """Return a stable cancelled export task payload.

    Inputs: optional owner token. Output: result dict.
    """
    result = {
        "state": "CANCELLED",
        "outputs": None,
        "error": _EXPORT_CANCELLED_MESSAGE,
    }
    if owner_token:
        result["owner_token"] = owner_token
    return result


def _public_script_message(message: str | None) -> str | None:
    """Return a safe public message from script-controlled output.

    Inputs: `message`. Output: `str | None`.
    """
    if message is None:
        return None
    cleaned = str(message).strip()
    if not cleaned:
        return None
    if cleaned in _PUBLIC_SCRIPT_MESSAGES:
        return cleaned
    if cleaned.startswith("Image ") and cleaned.endswith(" not found"):
        return cleaned
    if cleaned.startswith("Original file not found:"):
        return "Original file not found."
    return None


def _public_failure_message(
    exc: Exception,
    default_message: str = _GENERIC_EXPORT_ERROR,
) -> str:
    """Return the public failure message for a task exception.

    Inputs: `exc`. Output: `str`.
    """
    if isinstance(exc, OMEExportTaskError):
        return exc.public_message or _GENERIC_OME_TIFF_EXPORT_ERROR
    if isinstance(exc, IMSExportTaskError):
        return exc.public_message or _GENERIC_EXPORT_ERROR
    return default_message


def _build_failure_meta(
    exc: Exception,
    default_message: str = _GENERIC_EXPORT_ERROR,
) -> dict[str, Any]:
    """Metadata dictionary for failed tasks.

    Inputs: `exc`. Output: `dict[str, Any]`.
    """
    public_message = _public_failure_message(exc, default_message=default_message)
    return {
        "exc_type": exc.__class__.__name__,
        "exc_module": exc.__class__.__module__,
        "exc_message": public_message,
        "error": public_message,
        "public_error": isinstance(exc, (IMSExportTaskError, OMEExportTaskError)),
    }


def _resolve_omero_cli() -> str:
    """Resolve the OMERO cli.

    Inputs: none. Output: `str`. Raises: RuntimeError for the exercised failure path.
    """
    for candidate in _iter_omero_cli_candidates():
        resolved = _resolve_executable_candidate(candidate)
        if resolved:
            return resolved
    raise RuntimeError("OMERO CLI binary not found in OMERO.web container.")


def _version_sort_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Return a natural sort key for versioned virtualenv paths.

    Inputs: `path`. Output: tuple key.
    """
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", str(path))
        if part
    )


def _iter_omero_cli_candidates() -> list[str]:
    """Return OMERO CLI candidate paths in env-driven preference order.

    Inputs: none. Output: list of candidate path strings.
    """
    candidates: list[str] = []
    for env_name in ("OMERO_WEB_OMERO_BIN", "OMERO_BIN"):
        explicit = os.environ.get(env_name)
        if explicit:
            candidates.append(explicit)

    web_root_raw = os.environ.get("OMERO_WEB_ROOT")
    try:
        web_root = Path(web_root_raw) if web_root_raw else None
    except (TypeError, ValueError):
        web_root = None
    configured_venv = os.environ.get("OMERO_WEB_VENV")
    if configured_venv:
        try:
            configured_root = Path(configured_venv)
        except (TypeError, ValueError):
            configured_root = None
        if configured_root is not None and not configured_root.is_absolute():
            configured_root = web_root / configured_root if web_root else None
        if configured_root is not None:
            candidates.append(str(configured_root / "bin" / "omero"))

    if web_root is not None:
        try:
            candidates.extend(
                str(candidate)
                for candidate in sorted(
                    web_root.glob("venv*/bin/omero"),
                    key=_version_sort_key,
                    reverse=True,
                )
            )
        except (OSError, ValueError):
            logger.debug(
                "Unable to inspect OMERO_WEB_ROOT for OMERO CLI candidates.",
                exc_info=True,
            )

    path_candidate = shutil.which("omero")
    if path_candidate:
        candidates.append(path_candidate)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def _resolve_executable_candidate(candidate: str) -> str | None:
    """Return an executable candidate path or None.

    Inputs: `candidate`. Output: resolved path string or None.
    """
    if not candidate:
        return None
    if os.path.basename(candidate) == candidate:
        candidate = shutil.which(candidate) or candidate
    try:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        return None
    except (OSError, ValueError):
        return None


def _extract_cli_outputs(text: str) -> dict[str, str]:
    """Extract key output parameters from `omero script launch` text output.

    Inputs: `text`. Output: `dict[str, str]`.
    """
    outputs: dict[str, str] = {}
    for line in text.splitlines():
        match = _CLI_OUTPUT_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip()
        if key not in _CLI_OUTPUT_KEYS:
            continue
        value = match.group(2).strip()
        if key:
            outputs[key] = value
    return outputs


def _get_connection_session_key(conn) -> str | None:
    """Return the current OMERO session key from a connected gateway.

    Inputs: `conn`. Output: `str | None`.
    """
    if conn is None:
        return None
    for attr_name in ("getSessionId",):
        getter = getattr(conn, attr_name, None)
        if callable(getter):
            try:
                session_id = getter()
                if session_id:
                    return str(session_id)
            except Exception:
                logger.debug("Failed to get session key via conn.%s", attr_name)
    client = getattr(conn, "c", None)
    getter = getattr(client, "getSessionId", None)
    if callable(getter):
        try:
            session_id = getter()
            if session_id:
                return str(session_id)
        except Exception:
            logger.debug("Failed to get session key via conn.c.getSessionId")
    return None


def _run_script_via_omero_cli(
    script_id: int,
    image_id: int,
    host: str,
    port: int,
    session_key: str | None = None,
    status_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, str]:
    """Launch IMS export with OMERO CLI inside the OMERO.web container.

    Inputs: `script_id` (int), `image_id` (int) OMERO image ID, `host` (str), `port`
    (int), `session_key` (str | None). Output: `dict[str, str]`. Raises:
    IMSExportTaskError, RuntimeError when validation or the called operation fails.
    """
    omero_cli = _resolve_omero_cli()

    cmd = [
        omero_cli,
        "-q",
        "script",
        "launch",
        str(int(script_id)),
        f"Image_ID={int(image_id)}",
        "-s",
        str(host),
        "-p",
        str(int(port)),
    ]

    if not session_key:
        raise RuntimeError("OMERO CLI launch requires a live OMERO session key.")
    cmd.extend(["-k", str(session_key)])

    logger.info(
        "Launching IMS export via OMERO CLI script_id=%s image_id=%s",
        script_id,
        image_id,
    )
    env = os.environ.copy()
    # Keep OMERO CLI session/cache files on the managed plugin tmp volume
    # rather than a shared world-writable system temp directory.
    omero_userdir_root = get_connector_tmp_dir("omero-cli", create=True)
    omero_userdir = Path(
        tempfile.mkdtemp(
            prefix=f"ims-export-{int(image_id)}-",
            dir=omero_userdir_root,
        )
    )
    os.chmod(omero_userdir, _PRIVATE_EXPORT_DIR_MODE)
    session_dir = omero_userdir / "sessions"
    tmp_dir = omero_userdir / "tmp"
    session_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(omero_userdir)
    env["OMERO_USERDIR"] = str(omero_userdir)
    env["OMERO_SESSIONDIR"] = str(session_dir)
    env["OMERO_TMPDIR"] = str(tmp_dir)

    def _report_cli_tick(pid: int, elapsed: float) -> None:
        """Report live OMERO CLI metadata. Inputs: `pid`, `elapsed`. Output: None."""
        if status_callback is None:
            return
        try:
            status_callback(
                "running_script",
                {
                    "script_id": int(script_id),
                    "cli_pid": int(pid),
                    "cli_pgid": int(pid),
                    "elapsed": float(elapsed),
                },
            )
        except Exception:
            logger.exception("Failed to update IMS export CLI process metadata")

    try:
        result = process_utils.run_streaming(
            cmd,
            timeout=EXPORT_TIMEOUT + 120,
            check=False,
            env=env,
            tick_interval=1.0,
            on_tick=_report_cli_tick,
            start_new_session=True,
        )
    finally:
        shutil.rmtree(omero_userdir, ignore_errors=True)

    combined = (
        (result.stdout or "")
        + ("\n" if result.stdout and result.stderr else "")
        + (result.stderr or "")
    )
    outputs = _extract_cli_outputs(combined)

    if result.returncode != 0:
        public_message = _public_script_message(outputs.get("Message"))
        logger.error(
            "OMERO CLI launch failed script_id=%s image_id=%s exit_code=%s %s",
            script_id,
            image_id,
            result.returncode,
            summarize_process_output(result.stdout, result.stderr),
        )
        raise IMSExportTaskError(
            "IMS export CLI launch failed.",
            public_message=public_message,
        )

    if outputs.get("Export_Path"):
        return outputs

    public_message = _public_script_message(outputs.get("Message"))
    logger.error(
        "OMERO CLI launch returned no export path script_id=%s image_id=%s %s",
        script_id,
        image_id,
        summarize_process_output(result.stdout, result.stderr),
    )
    detail = public_message or "script returned no public failure message"
    raise IMSExportTaskError(
        f"IMS export CLI launch returned no export path: {detail}",
        public_message=public_message,
    )


def _open_session_connection(session_key, host, port, secure=None):
    """Open the session connection.

    Inputs: `session_key`, `host`, `port`, `secure`. Output: `conn`. Raises:
    RuntimeError when validation or the called operation fails.
    """
    logger.debug("Opening OMERO session host=%s port=%s secure=%s", host, port, secure)

    # Validate parameters
    if not session_key:
        raise RuntimeError("Session key is required")
    if not host:
        raise RuntimeError("OMERO host is required")
    if not port:
        raise RuntimeError("OMERO port is required")

    try:
        port = int(port)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"Invalid port value: {port}") from e

    try:
        # Create OMERO client
        client = omero.client(host, port)

        # Join the existing session
        logger.debug("Joining requester OMERO session for background export.")
        session = client.joinSession(session_key)

        if not session:
            raise RuntimeError("Failed to join OMERO session")

        session.detachOnDestroy()

        # Create BlitzGateway from the client
        conn = BlitzGateway(client_obj=client)
        setattr(conn, _PRESERVE_JOINED_SESSION_ATTR, True)

        # Enable cross-group access for the export
        conn.SERVICE_OPTS.setOmeroGroup("-1")

        logger.debug("Successfully connected to requester OMERO session.")
        return conn

    except omero.ClientError as e:
        logger.error("OMERO client error: %s", e)
        raise RuntimeError(f"Failed to connect to OMERO: {e}") from e
    except omero.SecurityViolation as e:
        logger.error("OMERO security violation: %s", e)
        raise RuntimeError(f"Access denied: {e}") from e
    except Exception as e:
        logger.error("Failed to open OMERO session: %s", e)
        raise RuntimeError(f"Failed to open OMERO session: {e}") from e


def _open_job_service_connection(host, port, secure=None):
    """Open the job service connection.

    Inputs: `host`, `port`, `secure`. Output: `conn`. Raises: RuntimeError when validation or
    the called operation fails.
    """
    logger.debug(
        "Opening OMERO job-service session host=%s port=%s secure=%s",
        host,
        port,
        secure,
    )

    username, password = get_job_service_credentials()
    if not username:
        raise RuntimeError("OMERO job-service username is required but not set.")
    if not password:
        raise RuntimeError("OMERO job-service password is required but not set.")
    if not host:
        raise RuntimeError("OMERO host is required")
    if not port:
        raise RuntimeError("OMERO port is required")

    try:
        port = int(port)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"Invalid port value: {port}") from e

    try:
        conn = BlitzGateway(
            username,
            password,
            host=host,
            port=port,
            secure=secure,
        )
        if not conn.connect():
            raise RuntimeError(
                "Failed to connect to OMERO with job-service credentials."
            )
        setattr(conn, _PRESERVE_JOINED_SESSION_ATTR, False)
        conn.SERVICE_OPTS.setOmeroGroup("-1")
        logger.debug("Successfully connected to OMERO using the job-service account.")
        return conn
    except Exception as e:
        logger.error("Failed to open OMERO job-service session: %s", e)
        raise RuntimeError("Failed to open OMERO job-service session.") from e


def _open_export_connection(session_key, host, port, secure=None):
    """Open the configured OMERO connection for background export jobs.

    Inputs: `session_key`, `host`, `port`, `secure`. Output: BlitzGateway.
    """
    if session_key:
        return _open_session_connection(session_key, host, port, secure=secure)
    if use_job_service_session():
        return _open_job_service_connection(host, port, secure=secure)
    return _open_session_connection(session_key, host, port, secure=secure)


def _close_export_connection(conn) -> None:
    """Close an export connection without killing joined requester sessions.

    Inputs: OMERO gateway connection. Output: None.
    """
    close = getattr(conn, "close", None)
    if not callable(close):
        return
    hard_close = not bool(getattr(conn, _PRESERVE_JOINED_SESSION_ATTR, False))
    try:
        close(hard=hard_close)
    except TypeError:
        try:
            close(hard_close)
        except TypeError:
            close()


def _update_export_task_state(
    self,
    image_id,
    start_time,
    status,
    extra_meta=None,
    owner_token=None,
):
    """Update a Celery export task state with shared metadata.

    Inputs: task instance, image id, start time, status, metadata. Output: None.
    """
    meta = {
        "image_id": image_id,
        "status": status,
        "started_at": start_time,
    }
    if owner_token:
        meta["owner_token"] = owner_token
    if extra_meta:
        meta.update(extra_meta)
    self.update_state(state="STARTED", meta=meta)


def _ims_export_script_module():
    """Return the IMS export script helpers only when export work needs them.

    Inputs: none. Output: IMS export script module.
    """
    from .omero_scripts import IMS_Export as ims_export_script

    return ims_export_script


def _public_ome_tiff_materialization_error(ims_export_script, exc):
    """Return a safe public message for selected-image OME-TIFF failures.

    Inputs: IMS export script module and exception. Output: public message.
    """
    failure_message = getattr(
        ims_export_script,
        "public_ome_tiff_export_failure_message",
        None,
    )
    if callable(failure_message):
        public_message = failure_message(exc)
        if public_message:
            return public_message
    return _SELECTED_IMAGE_OME_TIFF_EXPORT_FAILED


def _run_ome_tiff_export(conn, image_id, status_callback=None):
    """Materialize one OMERO image as an OME-TIFF file on the export volume.

    Inputs: OMERO connection, image id, optional status callback. Output: outputs.
    """
    image = conn.getObject("Image", image_id)
    if not image:
        raise OMEExportTaskError(
            f"OME-TIFF export image {int(image_id)} not found.",
            public_message=f"Image {int(image_id)} not found",
        )
    ims_export_script = _ims_export_script_module()
    export_root = get_ome_tiff_staging_root(create=True)
    export_name = (
        ims_export_script.safe_filename(
            image.getName(),
            fallback=f"omero_image_{int(image_id)}",
        )
        + ".ome.tif"
    )
    if status_callback is not None:
        status_callback("running_export", {"export_name": export_name})
    try:
        export_path = ims_export_script.materialize_ome_tiff_source(
            conn,
            image,
            int(image_id),
            export_root,
        )
    except Exception as exc:
        raise OMEExportTaskError(
            "OME-TIFF export failed while materializing source.",
            public_message=_public_ome_tiff_materialization_error(
                ims_export_script,
                exc,
            ),
        ) from exc
    if not export_path:
        raise OMEExportTaskError(
            "OME-TIFF export did not produce a file.",
            public_message=_SELECTED_IMAGE_OME_TIFF_EXPORT_FAILED,
        )
    os.chmod(export_path, _DOWNLOADABLE_EXPORT_FILE_MODE)
    return {
        "Export_Path": export_path,
        "Export_Name": export_name,
    }


@app.task(bind=True, name="omero_imaris_connector.run_ims_export_task")
def run_ims_export_task(
    self,
    image_id,
    session_key,
    host,
    port,
    secure=None,
    owner_token=None,
):
    """An IMS export task.

    Inputs: `image_id` OMERO image ID, `session_key`, `host`, `port`, `secure`. Output:
    `dict`. Raises: RuntimeError when validation or the called operation fails.
    """
    conn = None
    script_id = None
    start_time = time.time()

    def _update_task_state(
        status: str, extra_meta: dict[str, Any] | None = None
    ) -> None:
        """Update the task state.

        Inputs: `status` (str) status, `extra_meta` (dict[str, Any] | None). Output:
        None.
        """
        _update_export_task_state(
            self,
            image_id,
            start_time,
            status,
            extra_meta,
            owner_token=owner_token,
        )

    try:
        logger.info(
            "IMS export task starting image_id=%s host=%s port=%s secure=%s task_id=%s",
            image_id,
            host,
            port,
            secure,
            self.request.id,
        )

        # Update task state to show we're starting
        _update_task_state("connecting")

        conn = _open_export_connection(session_key, host, port, secure=secure)

        # Find the export script
        _update_task_state("finding_script")
        script_id = _find_script_id(conn)
        if not script_id:
            raise RuntimeError("IMS export script not found on OMERO.server.")

        logger.info(
            "IMS export task running script_id=%s image_id=%s task_id=%s",
            script_id,
            image_id,
            self.request.id,
        )

        # Run the script through OMERO CLI. This path is the live-validated
        # execution path in the OMERO.web container and avoids brittle
        # ScriptService callback/process-handle behavior.
        _update_task_state("running_script", {"script_id": script_id})
        cli_session_key = session_key
        if not cli_session_key and use_job_service_session():
            cli_session_key = _get_connection_session_key(conn)
            if not cli_session_key:
                raise RuntimeError("IMS export job-service session key unavailable.")

        outputs = _run_script_via_omero_cli(
            script_id=script_id,
            image_id=image_id,
            host=host,
            port=port,
            session_key=cli_session_key,
            status_callback=_update_task_state,
        )
        normalized_state = "FINISHED"

        logger.info(
            "IMS export task completed image_id=%s state=%s task_id=%s",
            image_id,
            normalized_state,
            self.request.id,
        )

        result = {
            "state": normalized_state,
            "outputs": _serialize_outputs(outputs),
            "error": None,
        }
        if owner_token:
            result["owner_token"] = owner_token
        return result

    except Exception as exc:
        logger.warning(
            "IMS export task failed image_id=%s task_id=%s: %s",
            sanitize_log_value(image_id),
            sanitize_log_value(self.request.id),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        if export_task_cancel_requested(self.request.id):
            return _cancelled_task_result(owner_token=owner_token)
        failure_meta = _build_failure_meta(exc)
        if owner_token:
            failure_meta["owner_token"] = owner_token
        if isinstance(exc, IMSExportTaskError):
            result = {
                "state": "FAILED",
                "outputs": None,
                "error": failure_meta["error"],
                "public_error": True,
            }
            if owner_token:
                result["owner_token"] = owner_token
            return result
        self.update_state(state=states.FAILURE, meta=failure_meta)
        raise
    finally:
        if conn:
            try:
                _close_export_connection(conn)
                logger.debug("OMERO connection closed for image_id=%s", image_id)
            except Exception as e:
                logger.warning(
                    "Error closing OMERO connection: %s",
                    sanitize_log_value(e),
                    exc_info=sanitized_exc_info(e),
                )


@app.task(bind=True, name="omero_imaris_connector.run_ome_tiff_export_task")
def run_ome_tiff_export_task(
    self,
    image_id,
    session_key,
    host,
    port,
    secure=None,
    owner_token=None,
):
    """An OME-TIFF export task for Imaris File Converter handoff.

    Inputs: `image_id` OMERO image ID, `session_key`, `host`, `port`, `secure`. Output:
    `dict`.
    """
    conn = None
    start_time = time.time()

    def _update_task_state(
        status: str, extra_meta: dict[str, Any] | None = None
    ) -> None:
        """Update the task state.

        Inputs: `status`, `extra_meta`. Output: None.
        """
        _update_export_task_state(
            self,
            image_id,
            start_time,
            status,
            extra_meta,
            owner_token=owner_token,
        )

    try:
        logger.info(
            "OME-TIFF export task starting image_id=%s host=%s port=%s secure=%s task_id=%s",
            image_id,
            host,
            port,
            secure,
            self.request.id,
        )
        _update_task_state("connecting")
        conn = _open_export_connection(session_key, host, port, secure=secure)
        outputs = _run_ome_tiff_export(
            conn, image_id, status_callback=_update_task_state
        )
        logger.info(
            "OME-TIFF export task completed image_id=%s task_id=%s",
            image_id,
            self.request.id,
        )
        result = {
            "state": "FINISHED",
            "outputs": _serialize_outputs(outputs),
            "error": None,
        }
        if owner_token:
            result["owner_token"] = owner_token
        return result
    except Exception as exc:
        logger.warning(
            "OME-TIFF export task failed image_id=%s task_id=%s: %s",
            sanitize_log_value(image_id),
            sanitize_log_value(self.request.id),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        if export_task_cancel_requested(self.request.id):
            return _cancelled_task_result(owner_token=owner_token)
        failure_meta = _build_failure_meta(
            exc,
            default_message=_GENERIC_OME_TIFF_EXPORT_ERROR,
        )
        if owner_token:
            failure_meta["owner_token"] = owner_token
        if isinstance(exc, OMEExportTaskError):
            result = {
                "state": "FAILED",
                "outputs": None,
                "error": failure_meta["error"],
                "public_error": True,
            }
            if owner_token:
                result["owner_token"] = owner_token
            return result
        self.update_state(state=states.FAILURE, meta=failure_meta)
        raise
    finally:
        if conn:
            try:
                _close_export_connection(conn)
                logger.debug("OMERO connection closed for image_id=%s", image_id)
            except Exception as e:
                logger.warning(
                    "Error closing OMERO connection: %s",
                    sanitize_log_value(e),
                    exc_info=sanitized_exc_info(e),
                )
