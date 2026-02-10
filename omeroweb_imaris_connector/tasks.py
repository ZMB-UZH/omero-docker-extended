import logging
import time
from typing import Any

import omero
from celery import states
from omero.gateway import BlitzGateway

from .celery_app import app
from .config import get_job_service_credentials, use_job_service_session
from .imaris_service import (
    EXPORT_TIMEOUT,
    _find_script_id,
    _normalize_job_state,
    _run_script,
    _serialize_outputs,
    _wait_for_process,
)

logger = logging.getLogger(__name__)


def _build_failure_meta(exc: Exception) -> dict[str, str]:
    """Build metadata dictionary for failed tasks."""
    exc_message = str(exc)
    return {
        "exc_type": exc.__class__.__name__,
        "exc_module": exc.__class__.__module__,
        "exc_message": exc_message,
        "error": exc_message,
    }


def _open_session_connection(session_key, host, port, secure=None):
    """Open an OMERO connection using an existing session key.

    This creates a new BlitzGateway connection by joining an existing
    OMERO session, allowing background tasks to work with the user's
    data access permissions.
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
    """Open an OMERO connection using the job-service account."""
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
            raise RuntimeError("Failed to connect to OMERO with job-service credentials.")
        conn.SERVICE_OPTS.setOmeroGroup("-1")
        logger.debug("Successfully connected to OMERO as job-service=%s", username)
        return conn
    except Exception as e:
        logger.error("Failed to open OMERO job-service session: %s", e)
        raise RuntimeError(f"Failed to open OMERO job-service session: {e}") from e


@app.task(bind=True, name="omeroweb_imaris_connector.run_ims_export_task")
def run_ims_export_task(self, image_id, session_key, host, port, secure=None):
    """Execute an IMS export task.

    This task runs in the Celery worker and performs the actual OMERO
    script execution for IMS conversion.
    """
    conn = None
    start_time = time.time()

    def _update_task_state(status: str, extra_meta: dict[str, Any] | None = None) -> None:
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

        # Run the script
        _update_task_state("running_script")

        def _script_status_callback(status: str, details: dict) -> None:
            _update_task_state(status, details)

        proc = _run_script(
            conn,
            script_id,
            image_id,
            wait_secs=0,
            status_callback=_script_status_callback,
        )
        if not proc:
            raise RuntimeError("Failed to start IMS export job.")

        # _run_script always returns a ScriptProcess handle.
        # Poll via proc.poll(), collect via proc.getResults(),
        # _wait_for_process detaches in its finally block (frees Processor slot).
        logger.debug("IMS export polling process handle for image_id=%s", image_id)
        last_state, outputs = _wait_for_process(proc, EXPORT_TIMEOUT)
        logger.debug(
            "IMS export process completed image_id=%s state=%s outputs=%s",
            image_id,
            last_state,
            _serialize_outputs(outputs),
        )

        if not last_state:
            raise RuntimeError("Could not determine IMS export job status.")

        normalized_state = _normalize_job_state(last_state) or "UNKNOWN"
        if normalized_state not in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            raise RuntimeError(
                "IMS export job did not complete successfully "
                f"(state: {normalized_state})"
            )

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
        self.update_state(state=states.FAILURE, meta=_build_failure_meta(exc))
        raise
    finally:
        if conn:
            try:
                conn.close()
                logger.debug("OMERO connection closed for image_id=%s", image_id)
            except Exception as e:
                logger.warning("Error closing OMERO connection: %s", e)
