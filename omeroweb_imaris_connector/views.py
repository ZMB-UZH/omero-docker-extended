import os
import time
import logging

from django.http import (
    FileResponse,
    HttpResponse,
    HttpResponseBadRequest,
    StreamingHttpResponse,
    JsonResponse,
)
from omeroweb.decorators import login_required

logger = logging.getLogger(__name__)

SCRIPT_NAME = os.environ.get("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")
SCRIPT_BASENAME = os.path.splitext(SCRIPT_NAME)[0]
EXPORT_ROOT = os.environ.get("OMERO_IMS_EXPORT_DIR", "/OMERO/ImarisExports")
EXPORT_TIMEOUT = int(os.environ.get("OMERO_IMS_EXPORT_TIMEOUT", "3600"))
EXPORT_POLL_INTERVAL = float(os.environ.get("OMERO_IMS_EXPORT_POLL_INTERVAL", "2"))


def _unwrap_rtype(v):
    # OMERO.rtypes: rstring/rlong/etc have .val
    try:
        return v.val
    except Exception:
        return v


def _find_script_id(conn):
    svc = conn.getScriptService()
    scripts = svc.getScripts()
    for s in scripts:
        name = _unwrap_rtype(getattr(s, "name", None))
        path = _unwrap_rtype(getattr(s, "path", None))
        sid = (
            _unwrap_rtype(getattr(getattr(s, "id", None), "val", None))
            if hasattr(getattr(s, "id", None), "val")
            else _unwrap_rtype(getattr(s, "id", None))
        )
        # some versions: s.id is omero.RLong
        if not sid:
            try:
                sid = s.id.val
            except Exception:
                sid = None
        if not sid:
            continue

        for candidate in (name, path):
            if not candidate:
                continue
            candidate = str(candidate)
            basename = os.path.basename(candidate)
            basename_no_ext = os.path.splitext(basename)[0]
            candidate_no_ext = os.path.splitext(candidate)[0]
            if (
                candidate in {SCRIPT_NAME, SCRIPT_BASENAME}
                or candidate_no_ext in {SCRIPT_NAME, SCRIPT_BASENAME}
                or basename in {SCRIPT_NAME, SCRIPT_BASENAME}
                or basename_no_ext in {SCRIPT_NAME, SCRIPT_BASENAME}
            ):
                return int(sid)
    return None


def _is_process_handle(job):
    return hasattr(job, "poll") and hasattr(job, "getResults")


def _run_script(conn, script_id, image_id):
    svc = conn.getScriptService()

    # Build inputs
    try:
        from omero.rtypes import rlong
        inputs = {"Image_ID": rlong(int(image_id))}
    except Exception:
        inputs = {"Image_ID": int(image_id)}

    # Different omero-py versions expose different method names; try a few.
    for meth_name in ("runScript", "run_script", "run"):
        meth = getattr(svc, meth_name, None)
        if meth is None:
            continue
        try:
            # Common signature: runScript(scriptId, inputs, None)
            try:
                job = meth(script_id, inputs, None)
            except TypeError:
                job = meth(script_id, inputs)
            job_id = _extract_job_id(job)
            if job_id is not None:
                return job_id
            if _is_process_handle(job):
                return job
            return None
        except Exception as e:
            logger.exception("ScriptService.%s failed: %s", meth_name, e)
            continue

    raise RuntimeError("Could not start script: ScriptService has no supported run method")


def _extract_job_id(job):
    if job is None:
        return None
    job_id = _unwrap_rtype(job)
    if isinstance(job_id, (int, str)):
        try:
            return int(job_id)
        except (TypeError, ValueError):
            pass
    if isinstance(job_id, dict):
        for key in ("job_id", "jobId", "id", "JobId", "JobID"):
            if key in job_id:
                try:
                    return int(_unwrap_rtype(job_id[key]))
                except (TypeError, ValueError):
                    continue
    if isinstance(job_id, (list, tuple)) and job_id:
        for entry in job_id:
            try:
                return int(_unwrap_rtype(entry))
            except (TypeError, ValueError):
                continue

    def _get_attr_value(obj, attr_name):
        attr = getattr(obj, attr_name, None)
        if attr is None:
            return None
        try:
            return attr() if callable(attr) else attr
        except Exception:
            return None

    for attr_name in (
        "getJobId",
        "get_job_id",
        "jobId",
        "job_id",
        "getId",
        "get_id",
        "id",
        "value",
        "getValue",
    ):
        value = _get_attr_value(job_id, attr_name)
        if value is None:
            continue
        try:
            return int(_unwrap_rtype(value))
        except (TypeError, ValueError):
            continue
    return None


def _get_job_state_and_outputs(conn, job_id):
    """
    Try several ways to get job state/outputs across OMERO versions.
    Returns (state, outputs_dict_or_None).
    """
    svc = conn.getScriptService()

    # 1) Dedicated methods (if available)
    for state_m, out_m in (
        ("getJobStatus", "getJobOutputs"),
        ("getJobInfo", "getJobOutputs"),
        ("get_job_status", "get_job_outputs"),
    ):
        state_fn = getattr(svc, state_m, None)
        out_fn = getattr(svc, out_m, None)
        if state_fn and out_fn:
            try:
                state = state_fn(job_id)
                outputs = out_fn(job_id)
                return str(_unwrap_rtype(state)), outputs
            except Exception:
                pass

    # 2) Older pattern: getJobs() returns job objects with .id/.status and maybe outputs elsewhere
    get_jobs = getattr(svc, "getJobs", None)
    if get_jobs:
        try:
            jobs = get_jobs()
            for j in jobs:
                try:
                    jid = _unwrap_rtype(getattr(getattr(j, "id", None), "val", None))
                    if jid is None and hasattr(getattr(j, "id", None), "val"):
                        jid = j.id.val
                    if str(jid) != str(job_id):
                        continue
                    status = _unwrap_rtype(getattr(getattr(j, "status", None), "val", None)) or _unwrap_rtype(getattr(j, "status", None))
                    # Outputs usually via getJobOutputs, but if missing we return None
                    outputs = None
                    out_fn = getattr(svc, "getJobOutputs", None)
                    if out_fn:
                        try:
                            outputs = out_fn(job_id)
                        except Exception:
                            outputs = None
                    return str(status), outputs
                except Exception:
                    continue
        except Exception:
            pass

    return None, None


def _wait_for_process(proc, timeout):
    deadline = time.time() + timeout
    last_state = None
    while time.time() < deadline:
        try:
            last_state = _normalize_job_state(proc.poll())
        except Exception:
            last_state = None
        if last_state:
            break
        time.sleep(EXPORT_POLL_INTERVAL)
    outputs = None
    if last_state:
        try:
            outputs = proc.getResults(0)
        except Exception:
            outputs = None
    return last_state, outputs


def _normalize_job_state(state):
    if state is None:
        return None
    try:
        if hasattr(state, "val"):
            state = state.val
    except Exception:
        pass
    try:
        if hasattr(state, "getValue"):
            state = state.getValue()
    except Exception:
        pass
    try:
        if hasattr(state, "name"):
            state = state.name
    except Exception:
        pass
    try:
        state = str(state).strip()
    except Exception:
        return None
    if not state:
        return None
    return state.upper()


def _extract_output_value(outputs, key):
    if outputs is None:
        return None
    v = outputs.get(key) if isinstance(outputs, dict) else None
    if v is None:
        return None
    return _unwrap_rtype(v)


def _raw_file_generator(store, size, chunk_size=8 * 1024 * 1024):
    offset = 0
    try:
        while True:
            if size is not None and offset >= size:
                break
            to_read = chunk_size if size is None else min(chunk_size, size - offset)
            data = store.read(offset, to_read)
            if not data:
                break
            if isinstance(data, memoryview):
                data = data.tobytes()
            yield data
            offset += len(data)
    finally:
        try:
            store.close()
        except Exception:
            pass


def _response_from_file_annotation(conn, file_ann_id, filename_fallback=None):
    try:
        file_ann_id = int(file_ann_id)
    except (TypeError, ValueError):
        return None

    file_ann = conn.getObject("FileAnnotation", file_ann_id)
    if not file_ann:
        return None

    original_file = file_ann.getFile()
    if not original_file:
        return None

    name = None
    size = None
    try:
        name = original_file.getName()
    except Exception:
        name = None
    try:
        size = original_file.getSize()
    except Exception:
        size = None

    name = _unwrap_rtype(name) or filename_fallback or "export.ims"
    try:
        size = int(_unwrap_rtype(size)) if size is not None else None
    except (TypeError, ValueError):
        size = None

    store = conn.c.sf.createRawFileStore()
    store.setFileId(int(_unwrap_rtype(original_file.getId())))
    response = StreamingHttpResponse(
        _raw_file_generator(store, size),
        content_type="application/octet-stream",
    )
    if size is not None:
        response["Content-Length"] = str(size)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _bool_from_request(value):
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_download_response(conn, outputs, export_name=None):
    export_path = _extract_output_value(outputs or {}, "Export_Path")
    export_name = export_name or _extract_output_value(outputs or {}, "Export_Name")
    file_ann_id = _extract_output_value(outputs or {}, "File_Annotation_Id")

    if export_path:
        export_root = os.path.realpath(EXPORT_ROOT)
        export_path = os.path.realpath(export_path)
        if export_path.startswith(export_root + os.sep) and os.path.exists(export_path):
            filename = export_name or os.path.basename(export_path)
            response = FileResponse(
                open(export_path, "rb"),
                as_attachment=True,
                filename=filename,
            )
            response["Content-Type"] = "application/octet-stream"
            return response

    if file_ann_id:
        response = _response_from_file_annotation(conn, file_ann_id, export_name)
        if response:
            return response

    if not export_path:
        return HttpResponse("IMS export did not return a file path.", status=500)
    if export_path and not os.path.exists(export_path):
        return HttpResponse("IMS export file not found on server.", status=404)
    return HttpResponse("IMS export path is invalid.", status=500)


@login_required()
def imaris_export(request, conn=None, **kwargs):
    job_id = request.GET.get("job") or request.GET.get("job_id")
    if job_id:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Invalid job id")

        state, outputs = _get_job_state_and_outputs(conn, job_id)
        normalized_state = _normalize_job_state(state)
        finished_states = {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}
        failed_states = {"FAILED", "ERROR", "CANCELLED", "CANCELED"}
        is_finished = normalized_state in finished_states
        is_failed = normalized_state in failed_states

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
            payload["error"] = "IMS export job failed."
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

    try:
        script_id = _find_script_id(conn)
        if not script_id:
            return HttpResponse("IMS export script not found on OMERO.server.", status=500)

        job_handle = _run_script(conn, script_id, image_id)
        if not job_handle:
            return HttpResponse("Failed to start IMS export job.", status=500)

        if isinstance(job_handle, int):
            job_id = job_handle
            if async_mode:
                status_url = request.build_absolute_uri(
                    f"{request.path}?job={job_id}"
                )
                return JsonResponse({"job_id": job_id, "status_url": status_url})
        else:
            job_id = None
            if async_mode:
                logger.warning("Async IMS export requested but script returned a process handle.")
                async_mode = False

        deadline = time.time() + EXPORT_TIMEOUT
        outputs = None
        last_state = None

        if isinstance(job_handle, int):
            while time.time() < deadline:
                state, outs = _get_job_state_and_outputs(conn, job_id)
                last_state = _normalize_job_state(state)
                if outs:
                    outputs = outs

                if last_state in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
                    break
                if last_state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                    return HttpResponse("IMS export job failed.", status=500)

                time.sleep(EXPORT_POLL_INTERVAL)
        else:
            last_state, outputs = _wait_for_process(job_handle, EXPORT_TIMEOUT)
            if last_state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                return HttpResponse("IMS export job failed.", status=500)

        if not last_state:
            return HttpResponse("Could not determine IMS export job status.", status=500)

        if last_state not in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            return HttpResponse("Timed out waiting for IMS export job.", status=504)

        export_name = _extract_output_value(outputs or {}, "Export_Name")
        return _build_download_response(conn, outputs, export_name)

    except Exception as exc:
        logger.exception("IMS export failed: %s", exc)
        return HttpResponse(f"IMS export failed: {exc}", status=500)
