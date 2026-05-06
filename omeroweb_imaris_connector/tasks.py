import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import omero
from celery import states
from omero.gateway import BlitzGateway
from omero_plugin_common import process_utils
from omero_plugin_common.logging_utils import summarize_process_output
from omero_plugin_common.tmp_utils import get_plugin_tmp_dir

from .celery_app import app
from .config import get_job_service_credentials, use_job_service_session
from .imaris_service import (
    EXPORT_TIMEOUT,
    _find_script_id,
    _serialize_outputs,
)

logger = logging.getLogger(__name__)
subprocess = process_utils

_GENERIC_EXPORT_ERROR = "IMS export job failed."
_PUBLIC_SCRIPT_MESSAGES = {
    "Conversion to IMS failed",
    "Could not get original file path",
    "Could not prepare source image for IMS conversion",
}


class IMSExportTaskError(RuntimeError):
    """Error whose public message is safe to return to the XT client."""

    def __init__(self, message: str, public_message: str | None = None) -> None:
        """Initialize the error with an optional sanitized public message.

        Inputs: `message`, `public_message`. Output: None.
        """
        super().__init__(message)
        self.public_message = public_message


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


def _public_failure_message(exc: Exception) -> str:
    """Return the public failure message for a task exception.

    Inputs: `exc`. Output: `str`.
    """
    if isinstance(exc, IMSExportTaskError):
        return exc.public_message or _GENERIC_EXPORT_ERROR
    return _GENERIC_EXPORT_ERROR


def _build_failure_meta(exc: Exception) -> dict[str, Any]:
    """Metadata dictionary for failed tasks.

    Inputs: `exc`. Output: `dict[str, Any]`.
    """
    public_message = _public_failure_message(exc)
    return {
        "exc_type": exc.__class__.__name__,
        "exc_module": exc.__class__.__module__,
        "exc_message": public_message,
        "error": public_message,
        "public_error": isinstance(exc, IMSExportTaskError),
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
    allowed = {"Message", "Export_Path", "Export_Name", "File_Annotation_Id"}
    outputs: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*\*\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$", line)
        if not match:
            continue
        key = match.group(1).strip()
        if key not in allowed:
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
    omero_userdir = get_plugin_tmp_dir("omero-cli", create=True)
    session_dir = omero_userdir / "sessions"
    tmp_dir = omero_userdir / "tmp"
    session_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(omero_userdir)
    env["OMERO_USERDIR"] = str(omero_userdir)
    env["OMERO_SESSIONDIR"] = str(session_dir)
    env["OMERO_TMPDIR"] = str(tmp_dir)

    result = process_utils.run(
        cmd,
        timeout=EXPORT_TIMEOUT + 120,
        check=False,
        env=env,
    )

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
        logger.debug(
            "Joining session with key=%s...", session_key[:8] if session_key else "None"
        )
        session = client.joinSession(session_key)

        if not session:
            raise RuntimeError("Failed to join OMERO session")

        session.detachOnDestroy()

        # Create BlitzGateway from the client
        conn = BlitzGateway(client_obj=client)

        # Enable cross-group access for the export
        conn.SERVICE_OPTS.setOmeroGroup("-1")

        logger.debug("Successfully connected to OMERO as session=%s", session_key[:8])
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
        conn.SERVICE_OPTS.setOmeroGroup("-1")
        logger.debug("Successfully connected to OMERO using the job-service account.")
        return conn
    except Exception as e:
        logger.error("Failed to open OMERO job-service session: %s", e)
        raise RuntimeError("Failed to open OMERO job-service session.") from e


@app.task(bind=True, name="omeroweb_imaris_connector.run_ims_export_task")
def run_ims_export_task(self, image_id, session_key, host, port, secure=None):
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
        meta = {
            "image_id": image_id,
            "status": status,
            "started_at": start_time,
        }
        if extra_meta:
            meta.update(extra_meta)
        self.update_state(state="STARTED", meta=meta)

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

        if use_job_service_session():
            conn = _open_job_service_connection(host, port, secure=secure)
        else:
            conn = _open_session_connection(session_key, host, port, secure=secure)

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
        )
        normalized_state = "FINISHED"

        logger.info(
            "IMS export task completed image_id=%s state=%s task_id=%s",
            image_id,
            normalized_state,
            self.request.id,
        )

        return {
            "state": normalized_state,
            "outputs": _serialize_outputs(outputs),
            "error": None,
        }

    except Exception as exc:
        logger.exception("IMS export task failed: %s", exc)
        failure_meta = _build_failure_meta(exc)
        if isinstance(exc, IMSExportTaskError):
            return {
                "state": "FAILED",
                "outputs": None,
                "error": failure_meta["error"],
                "public_error": True,
            }
        self.update_state(state=states.FAILURE, meta=failure_meta)
        raise
    finally:
        if conn:
            try:
                conn.close()
                logger.debug("OMERO connection closed for image_id=%s", image_id)
            except Exception as e:
                logger.warning("Error closing OMERO connection: %s", e)
