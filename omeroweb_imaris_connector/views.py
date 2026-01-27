import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from omeroweb.decorators import login_required

SCRIPT_NAME = os.environ.get("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")
EXPORT_ROOT = os.environ.get("OMERO_IMS_EXPORT_DIR", "/OMERO/ImarisExports")
EXPORT_TIMEOUT = int(os.environ.get("OMERO_IMS_EXPORT_TIMEOUT", "3600"))
EXPORT_POLL_INTERVAL = float(os.environ.get("OMERO_IMS_EXPORT_POLL_INTERVAL", "2"))


def _api_request(conn, request, endpoint, method="GET", payload=None, timeout=30):
    base_url = request.build_absolute_uri("/api/v0/")
    if not base_url.endswith("/"):
        base_url += "/"
    url = urllib.parse.urljoin(base_url, endpoint)
    headers = {"X-OMERO-SESSION": conn.getSessionId()}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _find_script_id(conn, request):
    data = _api_request(conn, request, "scripts/")
    scripts_list = data.get("data") or data.get("scripts") or []
    for item in scripts_list:
        name = item.get("name") or item.get("Name") or item.get("scriptName")
        path = item.get("path") or item.get("Path")
        script_id = item.get("id") or item.get("@id")
        if not script_id:
            continue
        if name == SCRIPT_NAME or path == SCRIPT_NAME:
            return script_id
        if name and os.path.basename(name) == SCRIPT_NAME:
            return script_id
        if path and os.path.basename(path) == SCRIPT_NAME:
            return script_id
    return None


def _poll_activity(conn, request, job_id):
    deadline = time.time() + EXPORT_TIMEOUT
    while time.time() < deadline:
        data = _api_request(conn, request, f"activities/{job_id}/")
        status = (data.get("status") or data.get("state") or "").upper()
        if status in {"FINISHED", "SUCCESS", "COMPLETE", "DONE"}:
            return data
        if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            return data
        time.sleep(EXPORT_POLL_INTERVAL)
    return None


def _extract_output_value(output, key):
    value = output.get(key)
    if isinstance(value, dict):
        return value.get("value") or value.get("id")
    return value


@login_required()
def imaris_export(request, conn=None, **kwargs):
    image_id = request.GET.get("image") or request.GET.get("image_id")
    if not image_id:
        return HttpResponseBadRequest("Missing image id")
    try:
        image_id = int(image_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid image id")

    try:
        script_id = _find_script_id(conn, request)
        if not script_id:
            return HttpResponse("IMS export script not found.", status=500)

        run_response = _api_request(
            conn,
            request,
            f"scripts/{script_id}/run/",
            method="POST",
            payload={"inputs": {"Image_ID": image_id}},
            timeout=60,
        )
        job_id = (
            run_response.get("job_id")
            or run_response.get("jobId")
            or run_response.get("id")
        )
        if not job_id:
            return HttpResponse("Failed to start IMS export job.", status=500)

        activity = _poll_activity(conn, request, job_id)
        if not activity:
            return HttpResponse("Timed out waiting for IMS export job.", status=504)

        status = (activity.get("status") or activity.get("state") or "").upper()
        if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            return HttpResponse("IMS export job failed.", status=500)

        outputs = (
            activity.get("outputs")
            or activity.get("output")
            or activity.get("results")
            or activity.get("result")
            or {}
        )
        if not isinstance(outputs, dict):
            return HttpResponse("IMS export did not return outputs.", status=500)

        export_path = _extract_output_value(outputs, "Export_Path")
        export_name = _extract_output_value(outputs, "Export_Name")
        if not export_path:
            return HttpResponse("IMS export did not return a file path.", status=500)

        export_root = os.path.realpath(EXPORT_ROOT)
        export_path = os.path.realpath(export_path)
        if not export_path.startswith(export_root + os.sep):
            return HttpResponse("IMS export path is invalid.", status=500)
        if not os.path.exists(export_path):
            return HttpResponse("IMS export file not found on server.", status=404)

        filename = export_name or os.path.basename(export_path)
        response = FileResponse(
            open(export_path, "rb"),
            as_attachment=True,
            filename=filename,
        )
        response["Content-Type"] = "application/octet-stream"
        return response
    except urllib.error.HTTPError as exc:
        return HttpResponse(f"IMS export failed: {exc}", status=500)
    except Exception as exc:
        return HttpResponse(f"IMS export failed: {exc}", status=500)
