import logging
import time

import omero
from celery import states
from omero.gateway import BlitzGateway

from .celery_app import app
from .imaris_service import (
    EXPORT_POLL_INTERVAL,
    EXPORT_TIMEOUT,
    _find_script_id,
    _infer_finished_from_outputs,
    _normalize_job_state,
    _run_script,
    _serialize_outputs,
    _wait_for_process,
    _get_job_state_and_outputs,
)

logger = logging.getLogger(__name__)


def _build_failure_meta(exc: Exception) -> dict[str, str]:
    exc_message = str(exc)
    return {
        "exc_type": exc.__class__.__name__,
        "exc_module": exc.__class__.__module__,
        "exc_message": exc_message,
        "error": exc_message,
    }


def _open_session_connection(session_key, host, port, secure=None):
    logger.debug("Opening OMERO session host=%s port=%s", host, port)
    client = omero.client(host, port)
    client.joinSession(session_key)
    conn = BlitzGateway(client_obj=client)
    conn.SERVICE_OPTS.setOmeroGroup("-1")
    return conn


@app.task(bind=True, name="omeroweb_imaris_connector.run_ims_export_task")
def run_ims_export_task(self, image_id, session_key, host, port, secure=None):
    conn = None
    try:
        logger.info(
            "IMS export task starting image_id=%s host=%s port=%s secure=%s",
            image_id,
            host,
            port,
            secure,
        )
        conn = _open_session_connection(session_key, host, port, secure=secure)
        script_id = _find_script_id(conn)
        if not script_id:
            raise RuntimeError("IMS export script not found on OMERO.server.")

        logger.info(
            "IMS export task running script_id=%s image_id=%s",
            script_id,
            image_id,
        )
        job_handle = _run_script(conn, script_id, image_id, wait_secs=0)
        if not job_handle:
            raise RuntimeError("Failed to start IMS export job.")

        outputs = None
        last_state = None

        if isinstance(job_handle, int):
            deadline = time.time() + EXPORT_TIMEOUT
            while time.time() < deadline:
                state, outs = _get_job_state_and_outputs(conn, job_handle)
                last_state = _normalize_job_state(state)
                if outs:
                    outputs = outs
                if not last_state and _infer_finished_from_outputs(outputs):
                    last_state = "FINISHED"
                logger.debug(
                    "IMS export job poll image_id=%s job_id=%s state=%s outputs=%s",
                    image_id,
                    job_handle,
                    last_state,
                    _serialize_outputs(outputs),
                )
                if last_state in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
                    break
                if last_state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                    raise RuntimeError("IMS export job failed.")
                time.sleep(EXPORT_POLL_INTERVAL)
        else:
            last_state, outputs = _wait_for_process(job_handle, EXPORT_TIMEOUT)
            logger.debug(
                "IMS export process handle completed image_id=%s state=%s outputs=%s",
                image_id,
                last_state,
                _serialize_outputs(outputs),
            )

        if not last_state:
            raise RuntimeError("Could not determine IMS export job status.")

        normalized_state = _normalize_job_state(last_state) or "UNKNOWN"
        if normalized_state not in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            raise RuntimeError("IMS export job did not complete successfully.")

        logger.info(
            "IMS export task completed image_id=%s state=%s",
            image_id,
            normalized_state,
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
            except Exception:
                pass
