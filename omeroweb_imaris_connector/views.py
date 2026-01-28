import logging
import os
import time

from celery import states as celery_states
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from omeroweb.decorators import login_required

from .celery_app import app as celery_app
from .imaris_service import (
    EXPORT_POLL_INTERVAL,
    EXPORT_TIMEOUT,
    _bool_from_request,
    _build_download_response,
    _extract_output_value,
    _find_script_id,
    _normalize_job_state,
)
from .tasks import run_ims_export_task

logger = logging.getLogger(__name__)

CELERY_JOB_PREFIX = "celery-"
CELERY_QUEUE = os.environ.get("OMERO_IMS_CELERY_QUEUE", "imaris_export")


@login_required()
def imaris_export(request, conn=None, **kwargs):
    job_id = request.GET.get("job") or request.GET.get("job_id")
    if job_id:
        if not job_id.startswith(CELERY_JOB_PREFIX):
            return HttpResponse(
                "Only Celery-backed IMS export jobs are supported.",
                status=400,
            )
        state, outputs, error = _poll_celery_job(job_id)
        normalized_state = _normalize_job_state(state)
        finished_states = {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}
        failed_states = {"FAILED", "ERROR", "CANCELLED", "CANCELED"}
        is_finished = normalized_state in finished_states
        is_failed = normalized_state in failed_states
        if normalized_state == "TIMEOUT":
            is_failed = True
            error = error or "Timed out waiting for IMS export job."

        if _bool_from_request(request.GET.get("download")):
            if not is_finished:
                return HttpResponse("IMS export is not ready for download.", status=409)
            return _build_download_response(conn, outputs)

        payload = {
            "job_id": job_id,
            "state": normalized_state,
            "finished": is_finished,
            "failed": is_failed,
        }
        if is_finished:
            download_url = request.build_absolute_uri(
                f"{request.path}?job={job_id}&download=1"
            )
            payload["download_url"] = download_url
        if is_failed:
            payload["error"] = error or "IMS export job failed."
        return JsonResponse(payload)

    image_id = request.GET.get("image") or request.GET.get("image_id")
    if not image_id:
        return HttpResponseBadRequest("Missing image id")
    try:
        image_id = int(image_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid image id")

    async_mode = _bool_from_request(request.GET.get("async"))
    wait_param = request.GET.get("wait")
    if wait_param is not None:
        async_mode = not _bool_from_request(wait_param)
    use_celery = _bool_from_request(os.environ.get("OMERO_IMS_USE_CELERY", "true"))
    if not use_celery:
        return HttpResponse(
            "Celery is required for IMS exports. Set OMERO_IMS_USE_CELERY=true and "
            "ensure the OMERO.web Imaris Celery worker is running.",
            status=500,
        )

    try:
        logger.info(
            "IMS export request image_id=%s async=%s wait_param=%s",
            image_id,
            async_mode,
            wait_param,
        )
        script_id = _find_script_id(conn)
        if not script_id:
            return HttpResponse("IMS export script not found on OMERO.server.", status=500)

        celery_job_id = _start_celery_job(conn, image_id)
        status_url = request.build_absolute_uri(f"{request.path}?job={celery_job_id}")
        if async_mode:
            return JsonResponse({"job_id": celery_job_id, "status_url": status_url})

        deadline = time.time() + EXPORT_TIMEOUT
        outputs = None
        last_state = None
        last_error = None

        while time.time() < deadline:
            state, outs, error = _poll_celery_job(celery_job_id)
            last_state = _normalize_job_state(state)
            if outs:
                outputs = outs
            if error:
                last_error = error
            if last_state in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
                break
            if last_state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                return HttpResponse(
                    f"IMS export job failed: {last_error or 'unknown error'}",
                    status=500,
                )
            time.sleep(EXPORT_POLL_INTERVAL)

        if not last_state:
            return HttpResponse("Could not determine IMS export job status.", status=500)

        if last_state not in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            return HttpResponse("Timed out waiting for IMS export job.", status=504)

        export_name = _extract_output_value(outputs or {}, "Export_Name")
        return _build_download_response(conn, outputs, export_name)

    except Exception as exc:
        logger.exception("IMS export failed: %s", exc)
        return HttpResponse(f"IMS export failed: {exc}", status=500)


def _poll_celery_job(job_id):
    task_id = job_id[len(CELERY_JOB_PREFIX):]
    async_result = celery_app.AsyncResult(task_id)
    if async_result.state in {
        celery_states.PENDING,
        celery_states.RECEIVED,
        celery_states.STARTED,
    }:
        return "RUNNING", None, None
    if async_result.state == celery_states.FAILURE:
        return "FAILED", None, str(async_result.result)
    if async_result.state == celery_states.SUCCESS:
        payload = async_result.result or {}
        return (
            payload.get("state", "FINISHED"),
            payload.get("outputs"),
            payload.get("error"),
        )
    return async_result.state, None, None


def _start_celery_job(conn, image_id):
    session_key = _get_session_key(conn)
    host, port = _resolve_omero_host_port(conn)
    secure = _resolve_omero_secure(conn)
    if not session_key:
        raise RuntimeError("IMS export session key unavailable for background job.")
    if not host or not port:
        raise RuntimeError("IMS export host/port unavailable for background job.")
    logger.info(
        "Dispatching IMS export task image_id=%s host=%s port=%s secure=%s queue=%s",
        image_id,
        host,
        port,
        secure,
        CELERY_QUEUE,
    )
    async_result = run_ims_export_task.apply_async(
        kwargs={
            "image_id": int(image_id),
            "session_key": session_key,
            "host": host,
            "port": int(port),
            "secure": secure,
        },
        queue=CELERY_QUEUE,
    )
    task_id = async_result.id
    logger.info(
        "Dispatched IMS export task image_id=%s task_id=%s queue=%s",
        image_id,
        task_id,
        CELERY_QUEUE,
    )
    return f"{CELERY_JOB_PREFIX}{task_id}"


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


def _resolve_omero_host_port(conn):
    host = getattr(conn, "host", None) or getattr(conn, "_host", None)
    port = getattr(conn, "port", None) or getattr(conn, "_port", None)
    if not host:
        host = os.environ.get("OMEROHOST")
    if not port:
        port = os.environ.get("OMERO_PORT")
    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None
    return host, port


def _resolve_omero_secure(conn):
    secure = getattr(conn, "secure", None)
    if secure is None:
        env_val = os.environ.get("OMERO_SECURE")
        if env_val is None:
            env_val = os.environ.get("CONFIG_omero_security_ssl")
        if env_val is not None:
            secure = _bool_from_request(env_val)
    return secure
