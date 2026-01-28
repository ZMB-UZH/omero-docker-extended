import os
import time

from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from omeroweb.decorators import login_required

# OMERO script name to execute on the server
SCRIPT_NAME = os.environ.get("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")

# Where the IMS export script is expected to write files (server-side path)
EXPORT_ROOT = os.environ.get("OMERO_IMS_EXPORT_DIR", "/OMERO/ImarisExports")

# How long to wait for the script job to finish (seconds)
EXPORT_TIMEOUT = int(os.environ.get("OMERO_IMS_EXPORT_TIMEOUT", "3600"))

# Poll interval while waiting for job completion (seconds)
EXPORT_POLL_INTERVAL = float(os.environ.get("OMERO_IMS_EXPORT_POLL_INTERVAL", "2"))


def _find_script_id(conn):
    """Find the script id for SCRIPT_NAME via ScriptService."""
    svc = conn.getScriptService()
    scripts = svc.getScripts() or []

    wanted_base = os.path.basename(SCRIPT_NAME)

    for s in scripts:
        sid = getattr(getattr(s, "id", None), "val", None)
        if not sid:
            continue

        name = getattr(getattr(s, "name", None), "val", None)
        path = getattr(getattr(s, "path", None), "val", None)

        # Match exact or basename
        if name == SCRIPT_NAME or path == SCRIPT_NAME:
            return int(sid)
        if name and os.path.basename(name) == wanted_base:
            return int(sid)
        if path and os.path.basename(path) == wanted_base:
            return int(sid)

    return None


def _job_state(job):
    # ScriptJob has status and maybe message; we normalize to uppercase string
    state = None
    if job is None:
        return None
    state = getattr(job, "status", None)
    state = getattr(state, "val", None) if state is not None else None
    if state is None:
        state = getattr(job, "state", None)
        state = getattr(state, "val", None) if state is not None else None
    return (state or "").upper()


def _poll_job(conn, job_id):
    """Poll ScriptService for a job until it finishes or times out."""
    svc = conn.getScriptService()
    deadline = time.time() + EXPORT_TIMEOUT

    # Prefer getJob if available, otherwise fall back to scanning getJobs()
    has_get_job = hasattr(svc, "getJob")

    while time.time() < deadline:
        job = None

        if has_get_job:
            try:
                job = svc.getJob(job_id)
            except Exception:
                job = None
        else:
            try:
                jobs = svc.getJobs() or []
                for j in jobs:
                    jid = getattr(getattr(j, "id", None), "val", None)
                    if jid and int(jid) == int(job_id):
                        job = j
                        break
            except Exception:
                job = None

        state = _job_state(job)
        if state in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            return job
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            return job

        time.sleep(EXPORT_POLL_INTERVAL)

    return None


def _get_job_outputs(conn, job_id):
    """Fetch job outputs as a Python dict (best-effort across OMERO versions)."""
    svc = conn.getScriptService()

    job = None
    if hasattr(svc, "getJob"):
        try:
            job = svc.getJob(int(job_id))
        except Exception:
            job = None

    # Try common attributes
    if job is not None:
        for attr in ("outputs", "output", "results", "result"):
            val = getattr(job, attr, None)
            if val is not None:
                # Some OMERO versions store results in an omero.rtypes.RMap
                try:
                    # RMap: ._map is dict-like mapping of rtypes
                    if hasattr(val, "_map"):
                        return val._map  # noqa: SLF001
                except Exception:
                    pass
                if isinstance(val, dict):
                    return val

                # Sometimes a list of NamedValue objects
                try:
                    items = list(val)  # type: ignore[arg-type]
                    out = {}
                    for item in items:
                        name = getattr(getattr(item, "name", None), "val", None)
                        v = getattr(item, "value", None)
                        if name:
                            out[name] = v
                    if out:
                        return out
                except Exception:
                    pass

    return {}
def _extract_output_value(outputs, key):
    """Handle both raw values and OMERO rtypes."""
    if not isinstance(outputs, dict):
        return None

    v = outputs.get(key)
    if v is None:
        return None

    # OMERO rtype: has .val
    if hasattr(v, "val"):
        return v.val

    # Sometimes dict-ish
    if isinstance(v, dict):
        return v.get("value") or v.get("val") or v.get("id") or v.get("@id")

    return v


@login_required()
def imaris_export(request, conn=None, **kwargs):
    """Run IMS_Export.py on the server for a given image id and return the exported file."""
    image_id = request.GET.get("image") or request.GET.get("image_id")
    if not image_id:
        return HttpResponseBadRequest("Missing image id")
    try:
        image_id = int(image_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid image id")

    try:
        script_id = _find_script_id(conn)
        if not script_id:
            return HttpResponse("IMS export script not found.", status=500)

        # Run the script via ScriptService (current user session)
        svc = conn.getScriptService()

        # Script inputs are case-sensitive and must match script parameters
        inputs = {"Image_ID": image_id}

        # runScript signature differs slightly; most versions accept (scriptId, inputs, wait)
        try:
            job = svc.runScript(script_id, inputs, None)
        except TypeError:
            job = svc.runScript(script_id, inputs)

        job_id = getattr(getattr(job, "id", None), "val", None) if job is not None else None
        if not job_id:
            return HttpResponse("Failed to start IMS export job.", status=500)

        job = _poll_job(conn, int(job_id))
        if not job:
            return HttpResponse("Timed out waiting for IMS export job.", status=504)

        state = _job_state(job)
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            return HttpResponse("IMS export job failed.", status=500)

        outputs = _get_job_outputs(conn, int(job_id))
        export_path = _extract_output_value(outputs, "Export_Path")
        export_name = _extract_output_value(outputs, "Export_Name")

        if not export_path:
            return HttpResponse("IMS export did not return a file path.", status=500)

        # Security: only allow files under EXPORT_ROOT
        export_root = os.path.realpath(EXPORT_ROOT)
        export_path = os.path.realpath(str(export_path))
        if not export_path.startswith(export_root + os.sep):
            return HttpResponse("IMS export path is invalid.", status=500)
        if not os.path.exists(export_path):
            return HttpResponse("IMS export file not found on server.", status=404)

        filename = export_name or os.path.basename(export_path)
        response = FileResponse(open(export_path, "rb"), as_attachment=True, filename=filename)
        response["Content-Type"] = "application/octet-stream"
        return response

    except Exception as exc:
        return HttpResponse(f"IMS export failed: {exc}", status=500)
