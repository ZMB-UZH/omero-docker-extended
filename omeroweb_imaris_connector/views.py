import logging
import os
import time
import urllib.parse

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


def _parse_base_url(value):
    if not value:
        return None
    try:
        raw = str(value).strip()
    except Exception as exc:
        raise ValueError("Invalid base_url value.") from exc
    if not raw:
        return None
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "base_url must include scheme and host, e.g. https://omero.example.org:4090"
        )
    if parsed.path not in {"", "/"}:
        raise ValueError("base_url must not include a path component.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_absolute_url(request, path, base_url_override=None):
    if base_url_override:
        base = base_url_override.rstrip("/") + "/"
        return urllib.parse.urljoin(base, path.lstrip("/"))
    return request.build_absolute_uri(path)


@login_required()
def imaris_export(request, conn=None, **kwargs):
    base_url_override = None
    if "base_url" in request.GET:
        try:
            base_url_override = _parse_base_url(request.GET.get("base_url"))
        except ValueError as exc:
            return HttpResponseBadRequest(str(exc))

    job_id = request.GET.get("job") or request.GET.get("job_id")
    if job_id:
        logger.debug("IMS export status request job_id=%s", job_id)
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
            logger.info("IMS export download requested job_id=%s", job_id)
            return _build_download_response(conn, outputs)

        payload = {
            "job_id": job_id,
            "state": normalized_state,
            "finished": is_finished,
            "failed": is_failed,
        }
        if is_finished:
            download_url = _build_absolute_url(
                request,
                f"{request.path}?job={job_id}&download=1",
                base_url_override=base_url_override,
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
        host_override = request.GET.get("omero_host")
        if host_override is not None:
            host_override = str(host_override).strip() or None

        port_override = None
        port_param = request.GET.get("omero_port")
        if port_param is not None and str(port_param).strip():
            try:
                port_override = _parse_port_param(port_param)
            except ValueError as exc:
                return HttpResponseBadRequest(str(exc))

        secure_override = None
        secure_param = request.GET.get("omero_secure")
        if secure_param is not None:
            secure_override = _bool_from_request(secure_param)

        logger.info(
            "IMS export request image_id=%s async=%s wait_param=%s",
            image_id,
            async_mode,
            wait_param,
        )
        script_id = _find_script_id(conn)
        if not script_id:
            return HttpResponse("IMS export script not found on OMERO.server.", status=500)

        celery_job_id = _start_celery_job(
            conn,
            image_id,
            host_override=host_override,
            port_override=port_override,
            secure_override=secure_override,
        )
        status_params = {"job": celery_job_id}
        if base_url_override:
            status_params["base_url"] = base_url_override
        status_url = _build_absolute_url(
            request,
            f"{request.path}?{urllib.parse.urlencode(status_params)}",
            base_url_override=base_url_override,
        )
        if async_mode:
            logger.debug("IMS export async response image_id=%s job_id=%s", image_id, celery_job_id)
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
            logger.debug(
                "IMS export poll job_id=%s state=%s error=%s",
                celery_job_id,
                last_state,
                last_error,
            )
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
    logger.debug("Polling Celery job task_id=%s state=%s", task_id, async_result.state)
    if async_result.state in {
        celery_states.PENDING,
        celery_states.RECEIVED,
        celery_states.STARTED,
    }:
        return "RUNNING", None, None
    if async_result.state in {celery_states.FAILURE, celery_states.IGNORED}:
        error = None
        if isinstance(async_result.info, dict):
            error = async_result.info.get("error")
        if not error:
            error = str(async_result.result)
        return "FAILED", None, error
    if async_result.state == celery_states.SUCCESS:
        payload = async_result.result or {}
        logger.debug("Celery job %s success payload=%s", task_id, payload)
        return (
            payload.get("state", "FINISHED"),
            payload.get("outputs"),
            payload.get("error"),
        )
    return async_result.state, None, None


def _start_celery_job(
    conn,
    image_id,
    host_override=None,
    port_override=None,
    secure_override=None,
):
    session_key = _get_session_key(conn)
    host, port = _resolve_omero_host_port(conn)
    secure = _resolve_omero_secure(conn)
    if host_override:
        host = host_override
    if port_override is not None:
        port = port_override
    if secure_override is not None:
        secure = secure_override
    if not session_key:
        raise RuntimeError("IMS export session key unavailable for background job.")
    if not host or not port:
        raise RuntimeError(
            "IMS export host/port unavailable for background job. "
            "Ensure OMEROHOST and OMERO_PORT are configured for OMERO.web."
        )
    if port <= 0 or port > 65535:
        raise RuntimeError(
            f"IMS export port is out of range: {port}. "
            "Ensure OMERO_PORT is set to a valid port."
        )
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
            "port": port,
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


def _parse_port_param(value):
    try:
        port_text = str(value).strip()
    except Exception:
        return None
    if not port_text:
        return None
    if not port_text.isdigit():
        raise ValueError(f"Invalid port value: {value}")
    port = int(port_text)
    if port <= 0 or port > 65535:
        raise ValueError(f"Port out of range: {port}")
    return port


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
        port_text = str(port).strip()
        if not port_text:
            port = None
        elif port_text.isdigit():
            try:
                port = int(port_text)
            except (TypeError, ValueError):
                port = None
        else:
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
