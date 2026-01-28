import logging
import time

import omero
from celery import states
from celery.exceptions import Ignore
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


def _open_session_connection(session_key, host, port):
    client = omero.client(host=host, port=port)
    client.joinSession(session_key)
    conn = BlitzGateway(client_obj=client)
    conn.SERVICE_OPTS.setOmeroGroup("-1")
    return conn


@app.task(bind=True, name="omeroweb_imaris_connector.run_ims_export_task")
def run_ims_export_task(self, image_id, session_key, host, port, secure=None):
    conn = None
    try:
        conn = _open_session_connection(session_key, host, port)
        script_id = _find_script_id(conn)
        if not script_id:
            raise RuntimeError("IMS export script not found on OMERO.server.")

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
                if last_state in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
                    break
                if last_state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                    raise RuntimeError("IMS export job failed.")
                time.sleep(EXPORT_POLL_INTERVAL)
        else:
            last_state, outputs = _wait_for_process(job_handle, EXPORT_TIMEOUT)

        if not last_state:
            raise RuntimeError("Could not determine IMS export job status.")

        normalized_state = _normalize_job_state(last_state) or "UNKNOWN"
        if normalized_state not in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            raise RuntimeError("IMS export job did not complete successfully.")

        return {
            "state": normalized_state,
            "outputs": _serialize_outputs(outputs),
            "error": None,
        }
    except Exception as exc:
        logger.exception("IMS export task failed: %s", exc)
        self.update_state(state=states.FAILURE, meta={"error": str(exc)})
        raise Ignore()
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
