import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Iterator

import omero

logger = logging.getLogger(__name__)

SCRIPT_NAME = os.environ.get("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")
SCRIPT_BASENAME = os.path.splitext(SCRIPT_NAME)[0]
EXPORT_ROOT = os.environ.get("OMERO_IMS_EXPORT_DIR", "/OMERO/ImarisExports")
EXPORT_TIMEOUT = int(os.environ.get("OMERO_IMS_EXPORT_TIMEOUT", "3600"))
EXPORT_POLL_INTERVAL = float(os.environ.get("OMERO_IMS_EXPORT_POLL_INTERVAL", "2"))
PROCESS_JOB_DIR = os.environ.get("OMERO_IMS_PROCESS_JOB_DIR", "/tmp/omero_ims_process_jobs")
SCRIPT_START_TIMEOUT = int(os.environ.get("OMERO_IMS_SCRIPT_START_TIMEOUT", "180"))
SCRIPT_START_RETRY_INTERVAL = float(os.environ.get("OMERO_IMS_SCRIPT_START_RETRY_INTERVAL", "5"))

_PROCESS_JOBS = {}
_PROCESS_JOBS_LOCK = threading.Lock()


def _process_job_path(job_id):
    return os.path.join(PROCESS_JOB_DIR, f"{job_id}.json")


def _ensure_process_job_dir():
    try:
        os.makedirs(PROCESS_JOB_DIR, exist_ok=True)
    except Exception:
        logger.exception("Failed to create process job dir: %s", PROCESS_JOB_DIR)


def _write_process_job_file(job_id, payload):
    _ensure_process_job_dir()
    path = _process_job_path(job_id)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_path, path)
    except Exception:
        logger.exception("Failed to write process job file for %s", job_id)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _read_process_job_file(job_id):
    path = _process_job_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.exception("Failed to read process job file for %s", job_id)
        return None


def _serialize_outputs(outputs):
    if not isinstance(outputs, dict):
        return None
    serialized = {}
    for key, value in outputs.items():
        serialized[str(key)] = _unwrap_rtype(value)
    return serialized


def _monitor_process_job(job_id, proc):
    state, outputs = _wait_for_process(proc, EXPORT_TIMEOUT)
    normalized_state = _normalize_job_state(state) if state else "TIMEOUT"
    error = None
    if normalized_state == "TIMEOUT":
        error = "Timed out waiting for IMS export job."
    payload = {
        "job_id": job_id,
        "state": normalized_state,
        "outputs": _serialize_outputs(outputs),
        "error": error,
        "created": time.time(),
    }
    _write_process_job_file(job_id, payload)
    _forget_process_job(job_id)


def _register_process_job(proc):
    job_id = f"proc-{uuid.uuid4().hex}"
    logger.debug("Registering IMS process job %s", job_id)
    with _PROCESS_JOBS_LOCK:
        _PROCESS_JOBS[job_id] = {
            "handle": proc,
            "created": time.time(),
        }
    _write_process_job_file(
        job_id,
        {
            "job_id": job_id,
            "state": "RUNNING",
            "outputs": None,
            "error": None,
            "created": time.time(),
        },
    )
    thread = threading.Thread(
        target=_monitor_process_job,
        args=(job_id, proc),
        daemon=True,
    )
    thread.start()
    return job_id


def _get_process_job(job_id):
    with _PROCESS_JOBS_LOCK:
        return _PROCESS_JOBS.get(job_id)


def _forget_process_job(job_id):
    with _PROCESS_JOBS_LOCK:
        _PROCESS_JOBS.pop(job_id, None)


def _poll_process_job(job_id):
    logger.debug("Polling process job %s", job_id)
    record = _get_process_job(job_id)
    if not record:
        file_record = _read_process_job_file(job_id)
        if not file_record:
            logger.debug("Process job %s not found in memory or on disk", job_id)
            return None, None, "Unknown job id"

        created = file_record.get("created")
        state = file_record.get("state")
        outputs = file_record.get("outputs")
        error = file_record.get("error")
        if state == "RUNNING" and created and time.time() - created > EXPORT_TIMEOUT:
            state = "TIMEOUT"
            error = "Timed out waiting for IMS export job."
            file_record.update({"state": state, "error": error})
            _write_process_job_file(job_id, file_record)
        return state, outputs, error

    if time.time() - record["created"] > EXPORT_TIMEOUT:
        _forget_process_job(job_id)
        return "TIMEOUT", None, "Timed out waiting for IMS export job."

    proc = record["handle"]
    try:
        state = _normalize_job_state(proc.poll())
    except Exception:
        state = None

    if not state:
        logger.debug("Process job %s still running", job_id)
        return None, None, None

    outputs = None
    try:
        outputs = proc.getResults(0)
    except Exception:
        outputs = None
    logger.debug("Process job %s finished state=%s outputs=%s", job_id, state, _serialize_outputs(outputs))
    _write_process_job_file(
        job_id,
        {
            "job_id": job_id,
            "state": state,
            "outputs": _serialize_outputs(outputs),
            "error": None,
            "created": record["created"],
        },
    )
    _forget_process_job(job_id)
    return state, outputs, None


def _unwrap_rtype(v):
    # OMERO.rtypes: rstring/rlong/etc have .val
    try:
        return v.val
    except Exception:
        return v


def _get_script_services(conn):
    services = []
    if conn is None:
        return services
    try:
        svc = conn.getScriptService()
        if svc:
            services.append(svc)
    except Exception:
        logger.exception("Failed to get ScriptService via conn.getScriptService()")
    try:
        raw_svc = conn.c.sf.getScriptService()
        if raw_svc and raw_svc not in services:
            services.append(raw_svc)
    except Exception:
        logger.exception("Failed to get ScriptService via conn.c.sf.getScriptService()")
    return services


def _find_script_id(conn):
    for svc in _get_script_services(conn):
        try:
            scripts = svc.getScripts()
        except Exception:
            logger.exception("ScriptService.getScripts failed")
            continue
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


def _is_async_result(job):
    if job is None:
        return False
    return hasattr(job, "waitForCompleted") and (
        hasattr(job, "getResponse")
        or hasattr(job, "getResult")
        or hasattr(job, "getResults")
        or hasattr(job, "get")
    )


def _resolve_async_result(svc, meth_name, async_result):
    if async_result is None:
        return None
    if not _is_async_result(async_result):
        return async_result

    candidates = []
    if meth_name.startswith("begin_"):
        candidates.append("end_" + meth_name[len("begin_"):])
    if meth_name.endswith("_async"):
        base_name = meth_name[:-6]
        candidates.append(base_name)
        candidates.append("end_" + base_name)
    candidates.extend(["end_runScript", "end_run_script"])

    for end_name in candidates:
        end_meth = getattr(svc, end_name, None)
        if callable(end_meth):
            try:
                return end_meth(async_result)
            except Exception:
                logger.exception("ScriptService.%s failed to end async call", end_name)

    try:
        async_result.waitForCompleted()
    except Exception:
        logger.exception("AsyncResult.waitForCompleted failed")

    for getter in ("getResponse", "getResult", "getResults", "get"):
        meth = getattr(async_result, getter, None)
        if callable(meth):
            try:
                return meth()
            except Exception:
                logger.exception("AsyncResult.%s failed", getter)
    return async_result


def _iter_script_methods(svc):
    preferred = [
        "runScriptAsync",
        "runScript",
        "run_script",
        "run",
        "runScript_async",
        "run_script_async",
        "runScriptEx",
        "executeScript",
        "execute_script",
    ]
    seen = set()
    for name in preferred:
        try:
            meth = getattr(svc, name, None)
        except Exception:
            meth = None
        if callable(meth):
            seen.add(name)
            yield name, meth
    try:
        for name in dir(svc):
            if name in seen:
                continue
            lowered = name.lower()
            if lowered.startswith("begin_") or lowered.startswith("end_"):
                continue
            if "canrun" in lowered or "can_run" in lowered:
                continue
            lower_name = name.lower()
            if "script" not in lower_name:
                continue
            if "run" not in lower_name and "exec" not in lower_name:
                continue
            try:
                meth = getattr(svc, name, None)
            except Exception:
                meth = None
            if callable(meth):
                seen.add(name)
                yield name, meth
    except Exception:
        logger.exception("Failed to introspect ScriptService methods")


def _call_script_method(meth, meth_name, script_id, inputs, wait_secs):
    import omero
    args_to_try = []
    lowered = meth_name.lower()
    is_async = "async" in lowered or lowered.startswith("begin_")
    if is_async:
        args_to_try.extend(
            [
                (script_id, inputs),
                (script_id, inputs, None),
                (script_id, inputs, ""),
            ]
        )
        if wait_secs is not None:
            args_to_try.append((script_id, inputs, int(wait_secs)))
    else:
        if wait_secs is None:
            args_to_try.extend(
                [
                    (script_id, inputs, None),
                    (script_id, inputs),
                    (script_id, inputs, ""),
                    (script_id, inputs, 0),
                ]
            )
            try:
                args_to_try.append((script_id, inputs, omero.rtypes.rint(0)))
            except Exception:
                pass
        else:
            try:
                args_to_try.append((script_id, inputs, omero.rtypes.rint(int(wait_secs))))
            except Exception:
                pass
            args_to_try.extend(
                [
                    (script_id, inputs, int(wait_secs)),
                    (script_id, inputs, None),
                    (script_id, inputs),
                    (script_id, inputs, ""),
                ]
            )
    args_to_try.extend(
        [
            (script_id, inputs, None, None),
            (script_id, inputs, int(wait_secs or 0), None),
        ]
    )
    try:
        args_to_try.append((script_id, inputs, omero.rtypes.rint(int(wait_secs or 0)), None))
    except Exception:
        pass
    last_type_error = None
    for args in args_to_try:
        try:
            return meth(*args)
        except TypeError as exc:
            last_type_error = exc
            continue
        except ValueError as exc:
            last_type_error = exc
            continue
    if last_type_error is not None:
        raise last_type_error
    return meth(script_id, inputs)


def _run_script(conn, script_id, image_id, wait_secs=None):
    # Build inputs
    try:
        from omero.rtypes import rlong

        inputs = {"Image_ID": rlong(int(image_id))}
    except Exception:
        inputs = {"Image_ID": int(image_id)}

    logger.debug(
        "Starting IMS export script id=%s image_id=%s wait_secs=%s",
        script_id,
        image_id,
        wait_secs,
    )
    services = _get_script_services(conn)
    logger.debug("ScriptService count=%s", len(services))
    if not services:
        raise RuntimeError("Could not start script: ScriptService unavailable")
    # Different omero-py versions expose different method names; try a few.
    start_time = time.time()
    attempt = 0
    while True:
        attempt += 1
        errors = []
        seen_methods = set()
        saw_no_processor = False
        saw_other_exception = False
        for svc in services:
            for meth_name, meth in _iter_script_methods(svc):
                seen_methods.add(meth_name)
                logger.debug(
                    "Attempting ScriptService.%s for IMS export (attempt %s)",
                    meth_name,
                    attempt,
                )
                try:
                    job = _call_script_method(meth, meth_name, script_id, inputs, wait_secs)
                    if job is None:
                        errors.append(f"{meth_name}: returned None")
                        continue
                    if _is_async_result(job):
                        job = _resolve_async_result(svc, meth_name, job)
                    if _is_process_handle(job):
                        logger.debug("IMS export script returned process handle via %s", meth_name)
                        return job
                    job_id = _extract_job_id(job)
                    if job_id is not None:
                        logger.debug("IMS export script returned job id=%s via %s", job_id, meth_name)
                        return job_id
                    errors.append(f"{meth_name}: unsupported return type {type(job)}")
                except Exception as exc:
                    is_no_processor = _is_no_processor_available(exc)
                    saw_no_processor = saw_no_processor or is_no_processor
                    saw_other_exception = saw_other_exception or not is_no_processor
                    logger.exception("ScriptService.%s failed: %s", meth_name, exc)
                    errors.append(f"{meth_name}: {_format_script_exception(exc)}")
                    continue

        if saw_no_processor and not saw_other_exception:
            elapsed = time.time() - start_time
            if elapsed < SCRIPT_START_TIMEOUT:
                logger.warning(
                    "No OMERO script processor available; retrying IMS export start in %ss "
                    "(attempt %s, elapsed %.1fs/%ss)",
                    SCRIPT_START_RETRY_INTERVAL,
                    attempt,
                    elapsed,
                    SCRIPT_START_TIMEOUT,
                )
                time.sleep(SCRIPT_START_RETRY_INTERVAL)
                continue
            raise RuntimeError(
                "Could not start script: No OMERO script processor is available to run IMS export "
                f"after waiting {elapsed:.1f}s. Start OMERO.script processors or increase "
                "omero.scripts.processors."
            )

        if errors:
            joined = "; ".join(errors)
            raise RuntimeError(f"Could not start script: {joined}")

        if seen_methods:
            raise RuntimeError("Could not start script: ScriptService run methods did not succeed")

        raise RuntimeError("Could not start script: ScriptService has no supported run method")


def _format_script_exception(exc: Exception) -> str:
    if _is_no_processor_available(exc):
        return (
            "No OMERO script processor is available to run IMS export. "
            "Start OMERO.script processors or increase omero.scripts.processors."
        )
    return str(exc)


def _is_no_processor_available(exc: Exception) -> bool:
    no_processor_type = getattr(omero, "NoProcessorAvailable", None)
    for err in _iter_exception_chain(exc):
        if no_processor_type and isinstance(err, no_processor_type):
            return True
        name = err.__class__.__name__
        if name == "NoProcessorAvailable":
            return True
        message = str(err)
        if "NoProcessorAvailable" in message:
            return True
        if "No processor available" in message:
            return True
    return False


def _iter_exception_chain(exc: Exception) -> Iterator[BaseException]:
    seen = set()
    current = exc
    while current and id(current) not in seen:
        seen.add(id(current))
        yield current
        if current.__cause__ is not None:
            current = current.__cause__
            continue
        current = current.__context__


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
    for svc in _get_script_services(conn):
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
                    logger.debug(
                        "Job %s state via %s/%s: %s outputs=%s",
                        job_id,
                        state_m,
                        out_m,
                        state,
                        _serialize_outputs(outputs),
                    )
                    return str(_unwrap_rtype(state)), outputs
                except Exception:
                    pass

        # 1b) Outputs-only fallback (some versions expose getJobOutputs without status)
        out_fn = getattr(svc, "getJobOutputs", None) or getattr(svc, "get_job_outputs", None)
        if out_fn:
            try:
                outputs = out_fn(job_id)
                if outputs:
                    logger.debug("Job %s outputs via outputs-only path: %s", job_id, _serialize_outputs(outputs))
                    return "FINISHED", outputs
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
                        logger.debug("Job %s state via getJobs(): %s outputs=%s", job_id, status, _serialize_outputs(outputs))
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
    logger.debug("Process wait completed state=%s outputs=%s", last_state, _serialize_outputs(outputs))
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


def _infer_finished_from_outputs(outputs):
    if not isinstance(outputs, dict):
        return False
    for key in ("Export_Path", "File_Annotation_Id", "Export_Name"):
        if _extract_output_value(outputs, key):
            return True
    return False


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


def _sanitize_filename(filename, fallback="export.ims"):
    if not filename:
        return fallback
    safe_name = os.path.basename(str(filename))
    safe_name = re.sub(r"[\x00-\x1f\x7f]+", "", safe_name)
    safe_name = safe_name.replace(os.sep, "_")
    if os.altsep:
        safe_name = safe_name.replace(os.altsep, "_")
    safe_name = safe_name.strip().strip(". ")
    if not safe_name:
        return fallback
    return safe_name


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

    name = _sanitize_filename(
        _unwrap_rtype(name) or filename_fallback or "export.ims",
        fallback=filename_fallback or "export.ims",
    )
    try:
        size = int(_unwrap_rtype(size)) if size is not None else None
    except (TypeError, ValueError):
        size = None

    store = conn.c.sf.createRawFileStore()
    store.setFileId(int(_unwrap_rtype(original_file.getId())))
    from django.http import StreamingHttpResponse

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
    from django.http import FileResponse, HttpResponse

    export_path = _extract_output_value(outputs or {}, "Export_Path")
    export_name = export_name or _extract_output_value(outputs or {}, "Export_Name")
    file_ann_id = _extract_output_value(outputs or {}, "File_Annotation_Id")
    logger.debug(
        "Building IMS download response export_path=%s export_name=%s file_ann_id=%s",
        export_path,
        export_name,
        file_ann_id,
    )

    if export_path:
        export_root = os.path.realpath(EXPORT_ROOT)
        export_path = os.path.realpath(export_path)
        if export_path.startswith(export_root + os.sep) and os.path.exists(export_path):
            filename = _sanitize_filename(
                export_name or os.path.basename(export_path),
                fallback=os.path.basename(export_path),
            )
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
        logger.error("IMS export outputs missing Export_Path and File_Annotation_Id")
        return HttpResponse("IMS export did not return a file path.", status=500)
    if export_path and not os.path.exists(export_path):
        logger.error("IMS export path not found on server: %s", export_path)
        return HttpResponse("IMS export file not found on server.", status=404)
    logger.error("IMS export path invalid: %s", export_path)
    return HttpResponse("IMS export path is invalid.", status=500)
