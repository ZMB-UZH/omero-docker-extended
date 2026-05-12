import json
import logging
import os
import signal
from pathlib import Path
import time
import urllib.parse

from celery import states as celery_states
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from omeroweb.decorators import login_required
from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from .celery_app import app as celery_app
from .config import get_celery_queue, use_celery
from .imaris_service import (
    EXPORT_POLL_INTERVAL,
    EXPORT_ROOT,
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
CELERY_QUEUE = get_celery_queue()
INVALID_BASE_URL_MESSAGE = "Invalid base_url parameter."
INVALID_OMERO_PORT_MESSAGE = "Invalid OMERO port parameter."
IMS_EXPORT_FAILED_MESSAGE = "IMS export failed."
IMS_EXPORT_JOB_FAILED_MESSAGE = "IMS export job failed."
IMS_EXPORT_CANCELLED_MESSAGE = "IMS export stopped by user."
TEXT_PLAIN_CONTENT_TYPE = "text/plain; charset=utf-8"
OMERO_IMS_EXPORT_CAPABILITY_FLAG = "omero_imaris_connector_v1"
OMERO_IMS_EXPORT_CAPABILITY_KEY = "omero_ims_export_capability"
IMS_EXPORT_CLI_TERMINATION_GRACE_SECONDS = 2.0
IMS_EXPORT_CLI_TERMINATION_POLL_SECONDS = 0.1


def _parse_base_url(value):
    """Parse and validate the base url input.

    Inputs: `value` input value. Output: URL string. Raises: ValueError when validation or the
    called operation fails.
    """
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
    """Build the absolute URL.

    Inputs: `request` Django request, `path` path, `base_url_override` base URL
    override. Output: `build_absolute_uri` result.
    """
    if base_url_override:
        base = base_url_override.rstrip("/") + "/"
        return urllib.parse.urljoin(base, path.lstrip("/"))
    return request.build_absolute_uri(path)


def _get_client_ip(request):
    """Extract client IP for logging purposes.

    Inputs: `request` Django request. Output: `get` result.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _job_error_message(meta):
    """Return the public error message for a polled job result.

    Inputs: `meta`. Output: `IMS_EXPORT_JOB_FAILED_MESSAGE`.
    """
    if meta and meta.get("public_error") and meta.get("error"):
        return str(meta.get("error"))
    return IMS_EXPORT_JOB_FAILED_MESSAGE


def _text_response(message, status):
    """Return plain-text response content without HTML interpretation.

    Inputs: `message`, `status`. Output: `response`.
    """
    response = HttpResponse(status=status, content_type=TEXT_PLAIN_CONTENT_TYPE)
    response.write(str(message))
    return response


def _celery_task_id(job_id):
    """Return the raw Celery task id for a public IMS export job id.

    Inputs: `job_id`. Output: task id or None.
    """
    if not isinstance(job_id, str) or not job_id.startswith(CELERY_JOB_PREFIX):
        return None
    task_id = job_id[len(CELERY_JOB_PREFIX) :]
    return task_id or None


def _safe_export_path(path_value):
    """Return a real export-root child path or None.

    Inputs: path value. Output: pathlib Path or None.
    """
    if not path_value:
        return None
    try:
        export_root = Path(os.path.realpath(EXPORT_ROOT))
        candidate = Path(os.path.realpath(str(path_value)))
    except (TypeError, ValueError, OSError):
        return None
    try:
        candidate.relative_to(export_root)
    except ValueError:
        return None
    return candidate


def _remove_export_file(path_value):
    """Remove one safe IMS export file if present.

    Inputs: path value. Output: bool.
    """
    candidate = _safe_export_path(path_value)
    if candidate is None:
        return False
    try:
        if candidate.is_file():
            candidate.unlink()
            return True
    except OSError as exc:
        logger.warning(
            "Failed to remove cancelled IMS export file %s: %s",
            sanitize_log_value(candidate),
            sanitize_log_value(exc),
        )
    return False


def _remove_recent_image_exports(meta):
    """Remove partial export files created during the cancelled task window.

    Inputs: Celery task meta. Output: removed file count.
    """
    if not isinstance(meta, dict):
        return 0
    raw_image_id = meta.get("image_id")
    raw_started_at = meta.get("started_at")
    if raw_image_id is None or raw_started_at is None:
        return 0
    try:
        image_id = int(raw_image_id)
        started_at = float(raw_started_at)
    except (TypeError, ValueError):
        return 0
    image_dir = _safe_export_path(Path(EXPORT_ROOT) / f"image_{image_id}")
    if image_dir is None or not image_dir.is_dir():
        return 0
    removed_count = 0
    threshold = max(0.0, started_at - 1.0)
    for candidate in image_dir.rglob("*"):
        try:
            if (
                candidate.is_file()
                and candidate.stat().st_mtime >= threshold
                and _safe_export_path(candidate) is not None
            ):
                candidate.unlink()
                removed_count += 1
        except OSError as exc:
            logger.warning(
                "Failed to remove cancelled IMS export artifact %s: %s",
                sanitize_log_value(candidate),
                sanitize_log_value(exc),
            )
    for directory in sorted(
        (path for path in image_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            continue
    try:
        image_dir.rmdir()
    except OSError as exc:
        logger.debug(
            "Skipped removing non-empty IMS export image directory %s: %s",
            sanitize_log_value(image_dir),
            sanitize_log_value(exc),
        )
    return removed_count


def _delete_file_annotation(conn, file_ann_id):
    """Best-effort deletion of a created IMS FileAnnotation.

    Inputs: OMERO connection and annotation id. Output: bool.
    """
    try:
        ann_id = int(file_ann_id)
    except (TypeError, ValueError):
        return False
    delete_objects = getattr(conn, "deleteObjects", None)
    if callable(delete_objects):
        try:
            delete_objects("Annotation", [ann_id], wait=True)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to delete cancelled IMS file annotation %s: %s",
                sanitize_log_value(ann_id),
                sanitize_log_value(exc),
            )
    return False


def _cleanup_cancelled_export(conn, outputs, meta):
    """Cleanup known server-side IMS export artifacts for a cancelled task.

    Inputs: OMERO connection, outputs, task metadata. Output: cleanup summary.
    """
    cleanup = {
        "export_file_removed": False,
        "recent_artifacts_removed": 0,
        "file_annotation_removed": False,
    }
    export_path = _extract_output_value(outputs or {}, "Export_Path")
    file_ann_id = _extract_output_value(outputs or {}, "File_Annotation_Id")
    cleanup["export_file_removed"] = _remove_export_file(export_path)
    cleanup["recent_artifacts_removed"] = _remove_recent_image_exports(meta)
    if conn is not None and file_ann_id:
        cleanup["file_annotation_removed"] = _delete_file_annotation(conn, file_ann_id)
    return cleanup


def _export_cli_pid_from_meta(meta):
    """Return a local OMERO CLI pid from trusted task metadata.

    Inputs: Celery task metadata. Output: pid or None.
    """
    if not isinstance(meta, dict):
        return None
    if meta.get("status") != "running_script":
        return None
    raw_pid = meta.get("cli_pid")
    if raw_pid is None:
        return None
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return None
    if pid <= 1:
        return None
    return pid


def _read_proc_cmdline(pid):
    """Read a process command line without exposing it to the response.

    Inputs: pid. Output: argv tuple or empty tuple.
    """
    try:
        raw = (Path("/proc") / str(int(pid)) / "cmdline").read_bytes()
    except (OSError, TypeError, ValueError):
        return ()
    return tuple(
        part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part
    )


def _is_expected_ims_export_cli_process(pid):
    """Return whether pid still belongs to the expected OMERO CLI launch.

    Inputs: pid. Output: bool.
    """
    parts = _read_proc_cmdline(pid)
    if not parts:
        return False
    executable = Path(parts[0]).name
    return executable == "omero" and "script" in parts and "launch" in parts


def _process_is_alive(pid):
    """Return whether a local process id exists.

    Inputs: pid. Output: bool.
    """
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminate_export_cli_process(meta):
    """Terminate the live OMERO CLI process for a cancelled IMS export.

    Inputs: Celery task metadata. Output: cleanup summary.
    """
    pid = _export_cli_pid_from_meta(meta)
    result = {
        "local_cli_termination_attempted": False,
        "local_cli_process_stopped": False,
    }
    if pid is None:
        return result
    if not _is_expected_ims_export_cli_process(pid):
        logger.warning(
            "IMS export cancellation skipped local process termination for pid=%s; "
            "command line no longer matches OMERO CLI script launch.",
            sanitize_log_value(pid),
        )
        return result

    result["local_cli_termination_attempted"] = True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        result["local_cli_process_stopped"] = True
        return result
    except OSError as exc:
        logger.warning(
            "Failed to terminate IMS export CLI process pid=%s: %s",
            sanitize_log_value(pid),
            sanitize_log_value(exc),
        )
        return result

    deadline = time.time() + IMS_EXPORT_CLI_TERMINATION_GRACE_SECONDS
    while time.time() < deadline:
        if not _process_is_alive(pid):
            result["local_cli_process_stopped"] = True
            return result
        time.sleep(IMS_EXPORT_CLI_TERMINATION_POLL_SECONDS)

    if not _is_expected_ims_export_cli_process(pid):
        result["local_cli_process_stopped"] = not _process_is_alive(pid)
        return result

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        result["local_cli_process_stopped"] = True
        return result
    except OSError as exc:
        logger.warning(
            "Failed to kill IMS export CLI process pid=%s: %s",
            sanitize_log_value(pid),
            sanitize_log_value(exc),
        )
        return result

    result["local_cli_process_stopped"] = not _process_is_alive(pid)
    return result


def _cancel_celery_job(job_id, conn=None):
    """Revoke a Celery-backed IMS export and cleanup any known artifacts.

    Inputs: public job id and optional OMERO connection. Output: dict payload.
    """
    task_id = _celery_task_id(job_id)
    if task_id is None:
        return {
            "ok": False,
            "error": "Only Celery-backed IMS export jobs are supported.",
        }
    state, outputs, _error, meta = _poll_celery_job(job_id)
    async_result = celery_app.AsyncResult(task_id)
    try:
        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
    except Exception as exc:
        logger.warning(
            "Failed to revoke IMS export task %s: %s",
            sanitize_log_value(task_id),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
    try:
        async_result.backend.store_result(
            task_id,
            {"state": "CANCELLED", "error": IMS_EXPORT_CANCELLED_MESSAGE},
            state=celery_states.REVOKED,
        )
    except Exception as exc:
        logger.debug(
            "Failed to record cancelled IMS export result %s: %s",
            sanitize_log_value(task_id),
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
    cleanup = _cleanup_cancelled_export(conn, outputs, meta)
    cleanup.update(_terminate_export_cli_process(meta))
    logger.info(
        "IMS export task cancelled job_id=%s prior_state=%s cleanup=%s",
        sanitize_log_value(job_id),
        sanitize_log_value(state),
        sanitize_log_value(cleanup),
    )
    return {
        "ok": True,
        "job_id": job_id,
        "state": "CANCELLED",
        "cancelled": True,
        "cleanup": cleanup,
    }


def _cancel_requested(request):
    """Return whether an IMS export status request asks to cancel the job.

    Inputs: Django request. Output: bool.
    """
    if _bool_from_request(request.GET.get("cancel")):
        return True
    post_data = getattr(request, "POST", {})
    if _bool_from_request(post_data.get("cancel")):
        return True
    content_type = str(request.META.get("CONTENT_TYPE") or "").lower()
    if "application/json" not in content_type:
        return False
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return _bool_from_request(payload.get("cancel"))


@login_required()
def imaris_export(request, conn=None, **kwargs):
    """Return the Imaris export.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `**kwargs`
    keyword arguments. Output: Django `JsonResponse`.
    """
    client_ip = _get_client_ip(request)
    safe_client_ip = sanitize_log_value(client_ip)
    safe_query = sanitize_log_value(request.GET.urlencode())
    safe_user = sanitize_log_value(
        getattr(conn, "getUser", lambda: None)() if conn else "unknown"
    )

    # Log request for debugging
    logger.debug(
        "IMS export request from %s: %s (user=%s)",
        safe_client_ip,
        safe_query,
        safe_user,
    )

    base_url_override = None
    if "base_url" in request.GET:
        try:
            base_url_override = _parse_base_url(request.GET.get("base_url"))
        except ValueError:
            return HttpResponseBadRequest(INVALID_BASE_URL_MESSAGE)
    if "omero_port" in request.GET:
        try:
            _parse_port_param(request.GET.get("omero_port"))
        except ValueError:
            return HttpResponseBadRequest(INVALID_OMERO_PORT_MESSAGE)

    if _bool_from_request(request.GET.get("capabilities")):
        celery_available = use_celery()
        script_available = False
        if celery_available:
            try:
                script_available = bool(_find_script_id(conn))
            except Exception as exc:
                logger.warning(
                    "IMS export capability probe failed: %s",
                    sanitize_log_value(exc),
                    exc_info=sanitized_exc_info(exc),
                )
        omero_available = bool(celery_available and script_available)
        return JsonResponse(
            {
                OMERO_IMS_EXPORT_CAPABILITY_KEY: OMERO_IMS_EXPORT_CAPABILITY_FLAG,
                "converters": {
                    "OMERO": omero_available,
                    "Imaris": True,
                },
                "omero_ims_export": omero_available,
            }
        )

    job_id = request.GET.get("job") or request.GET.get("job_id")
    if job_id:
        logger.debug(
            "IMS export status request job_id=%s from %s",
            sanitize_log_value(job_id),
            safe_client_ip,
        )
        if not job_id.startswith(CELERY_JOB_PREFIX):
            return HttpResponse(
                "Only Celery-backed IMS export jobs are supported.",
                status=400,
            )
        if _cancel_requested(request):
            if request.method != "POST":
                return HttpResponse(
                    "IMS export cancellation requires POST.",
                    status=405,
                )
            return JsonResponse(_cancel_celery_job(job_id, conn))
        state, outputs, _error, meta = _poll_celery_job(job_id)
        normalized_state = _normalize_job_state(state)
        finished_states = {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}
        failed_states = {"FAILED", "ERROR", "CANCELLED", "CANCELED"}
        is_finished = normalized_state in finished_states
        is_failed = normalized_state in failed_states
        if normalized_state == "TIMEOUT":
            is_failed = True

        if _bool_from_request(request.GET.get("download")):
            if not is_finished:
                return HttpResponse("IMS export is not ready for download.", status=409)
            logger.info(
                "IMS export download requested job_id=%s from %s",
                sanitize_log_value(job_id),
                safe_client_ip,
            )
            return _build_download_response(conn, outputs)

        payload = {
            "job_id": job_id,
            "state": normalized_state,
            "finished": is_finished,
            "failed": is_failed,
        }
        if meta and meta.get("status"):
            payload["status"] = meta.get("status")
        if meta and meta.get("job_state") and not payload.get("status"):
            payload["status"] = meta.get("job_state")
        if is_finished:
            download_url = _build_absolute_url(
                request,
                f"{request.path}?job={job_id}&download=1",
                base_url_override=base_url_override,
            )
            payload["download_url"] = download_url
        if is_failed:
            payload["error"] = _job_error_message(meta)
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
    safe_wait_param = sanitize_log_value(wait_param)
    if wait_param is not None:
        async_mode = not _bool_from_request(wait_param)
    if not use_celery():
        return HttpResponse(
            "Celery is required for IMS exports. Set OMERO_IMS_USE_CELERY=true and "
            "ensure the OMERO.web Imaris Celery worker is running.",
            status=500,
        )

    try:
        logger.info(
            "IMS export request image_id=%s async=%s wait_param=%s from %s",
            image_id,
            async_mode,
            safe_wait_param,
            safe_client_ip,
        )
        script_id = _find_script_id(conn)
        if not script_id:
            return HttpResponse(
                "IMS export script not found on OMERO.server.", status=500
            )

        celery_job_id = _start_celery_job(conn, image_id)
        status_params = {"job": celery_job_id}
        if base_url_override:
            status_params["base_url"] = base_url_override
        status_url = _build_absolute_url(
            request,
            f"{request.path}?{urllib.parse.urlencode(status_params)}",
            base_url_override=base_url_override,
        )
        if async_mode:
            logger.debug(
                "IMS export async response image_id=%s job_id=%s",
                image_id,
                celery_job_id,
            )
            return JsonResponse({"job_id": celery_job_id, "status_url": status_url})

        deadline = time.time() + EXPORT_TIMEOUT
        outputs = None
        last_state = None
        last_error = None

        while time.time() < deadline:
            state, outs, error, meta = _poll_celery_job(celery_job_id)
            last_state = _normalize_job_state(state)
            if outs:
                outputs = outs
            if error:
                last_error = error
            if not last_error and meta and meta.get("error"):
                last_error = meta.get("error")
            logger.debug(
                "IMS export poll job_id=%s state=%s error=%s",
                celery_job_id,
                last_state,
                sanitize_log_value(last_error),
            )
            if last_state in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
                break
            if last_state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                logger.warning(
                    "IMS export job %s failed for image %s: %s",
                    celery_job_id,
                    image_id,
                    sanitize_log_value(last_error or "unknown error"),
                )
                return _text_response(_job_error_message(meta), status=500)
            time.sleep(EXPORT_POLL_INTERVAL)

        if not last_state:
            return HttpResponse(
                "Could not determine IMS export job status.", status=500
            )

        if last_state not in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            return HttpResponse("Timed out waiting for IMS export job.", status=504)

        export_name = _extract_output_value(outputs or {}, "Export_Name")
        return _build_download_response(conn, outputs, export_name)

    except Exception as exc:
        logger.error(
            "IMS export failed: %s",
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        return HttpResponse(IMS_EXPORT_FAILED_MESSAGE, status=500)


def _poll_celery_job(job_id):
    """Poll a Celery job for its current state and results.

    Inputs: `job_id`. Output: tuple.
    """
    task_id = job_id[len(CELERY_JOB_PREFIX) :]
    async_result = celery_app.AsyncResult(task_id)
    logger.debug(
        "Polling Celery job task_id=%s state=%s",
        sanitize_log_value(task_id),
        async_result.state,
    )

    meta = async_result.info if isinstance(async_result.info, dict) else None

    if async_result.state in {
        celery_states.PENDING,
        celery_states.RECEIVED,
        celery_states.STARTED,
    }:
        return "RUNNING", None, None, meta
    if async_result.state in {celery_states.FAILURE, celery_states.IGNORED}:
        error = None
        if meta:
            error = meta.get("error")
        if not error:
            # Try to get error from result
            try:
                error = str(async_result.result)
            except Exception:
                error = "Unknown error"
        return "FAILED", None, error, meta
    if async_result.state == celery_states.SUCCESS:
        payload = async_result.result or {}
        logger.debug(
            "Celery job %s success payload=%s", sanitize_log_value(task_id), payload
        )
        result_meta = payload if payload.get("public_error") else meta
        return (
            payload.get("state", "FINISHED"),
            payload.get("outputs"),
            payload.get("error"),
            result_meta,
        )
    if async_result.state == celery_states.REVOKED:
        return "CANCELLED", None, "Job was cancelled", meta

    # Unknown state - return as-is
    return async_result.state, None, None, meta


def _start_celery_job(
    conn,
    image_id,
):
    """Start the celery job.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID. Output: start
    celery job result. Raises: RuntimeError when validation or the called operation fails.
    """
    session_key = _get_session_key(conn)
    host, port = _resolve_omero_host_port(conn)
    secure = _resolve_omero_secure(conn)

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
    """Parse and validate the port param input.

    Inputs: `value` input value. Output: `port`. Raises: ValueError when validation or
    external operations fail.
    """
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
    """Return session key.

    Inputs: `conn` OMERO gateway connection. Output: `val`.
    """
    if conn is None:
        return None

    # Try getSessionId method first (most reliable)
    if callable(getattr(conn, "getSessionId", None)):
        try:
            session_id = conn.getSessionId()
            if session_id:
                return session_id
        except Exception as e:
            logger.debug("getSessionId() failed: %s", sanitize_log_value(e))

    # Try to get from connection attributes
    for attr in ("_sessionUuid", "_session", "session"):
        val = getattr(conn, attr, None)
        if val:
            return val

    # Try to get from underlying client
    try:
        if hasattr(conn, "c") and conn.c and hasattr(conn.c, "getSessionId"):
            session_id = conn.c.getSessionId()
            if session_id:
                return session_id
    except Exception as e:
        logger.debug("conn.c.getSessionId() failed: %s", sanitize_log_value(e))

    return None


def _resolve_omero_host_port(conn):
    """Resolve the OMERO host port.

    Inputs: `conn` OMERO gateway connection. Output: `tuple`.
    """
    host = getattr(conn, "host", None) or getattr(conn, "_host", None)
    port = getattr(conn, "port", None) or getattr(conn, "_port", None)

    if not host:
        host = get_env("OMEROHOST", env_file=ENV_FILE_OMEROWEB)
    if not port:
        port = get_env("OMERO_PORT", env_file=ENV_FILE_OMEROWEB)

    if port is not None:
        port_text = str(port).strip()
        if not port_text:
            port = None
        elif port_text.isdigit():
            port = int(port_text)
        else:
            port = None

    return host, port


def _resolve_omero_secure(conn):
    """Resolve the OMERO secure.

    Inputs: `conn` OMERO gateway connection. Output: `secure`.
    """
    secure = getattr(conn, "secure", None)
    if secure is None:
        env_val = get_env("CONFIG_omero_security_ssl", env_file=ENV_FILE_OMEROWEB)
        secure = _bool_from_request(env_val)
    return secure
