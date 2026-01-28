# FULL FILE — omeroweb_imaris_connector/views.py
# GENERATED AFTER DEBUGGING AGAINST OMERO 5.6.16 + OMERO.web 5.x
# NO REST /api/v0/scripts — BLITZGATEWAY ONLY

import os
import time

from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from omeroweb.decorators import login_required

from omero.gateway import BlitzGateway
from omero.scripts import client as script_client


SCRIPT_NAME = os.environ.get("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")

DEFAULT_EXPORT_ROOT = "/OMERO/ImarisExports"
DEFAULT_TIMEOUT = 3600
DEFAULT_POLL_INTERVAL = 2.0


def _get_job_service_conn():
    host = os.environ.get("OMERO_HOST", "omero-test-omeroserver-1")
    port = int(os.environ.get("OMERO_PORT", "4064"))

    user = os.environ["OMERO_WEB_JOB_SERVICE_USERNAME"]
    passwd = os.environ["OMERO_WEB_JOB_SERVICE_PASS"]

    conn = BlitzGateway(user, passwd, host=host, port=port)
    if not conn.connect():
        raise RuntimeError("Job-service BlitzGateway connection failed")

    return conn


def _find_script_id(conn):
    svc = conn.getScriptService()
    scripts = svc.getScripts()

    for s in scripts:
        name = getattr(getattr(s, "name", None), "val", None)
        path = getattr(getattr(s, "path", None), "val", None)

        if name == SCRIPT_NAME:
            return s.id.val

        if path and os.path.basename(path) == SCRIPT_NAME:
            return s.id.val

    return None


def _poll_activity(conn, job_id, timeout, poll_interval):
    svc = conn.getScriptService()
    deadline = time.time() + timeout

    while time.time() < deadline:
        jobs = svc.getJobs()
        for j in jobs:
            if j.id.val == job_id:
                status = j.status.val
                if status in ("FINISHED", "DONE"):
                    return j
                if status in ("ERROR", "FAILED", "CANCELLED"):
                    return j
        time.sleep(poll_interval)

    return None


@login_required()
def imaris_export(request, conn=None, **kwargs):
    image_id = request.GET.get("image")
    if not image_id:
        return HttpResponseBadRequest("Missing image id")

    try:
        image_id = int(image_id)
    except ValueError:
        return HttpResponseBadRequest("Invalid image id")

    export_root = request.GET.get("export_root", DEFAULT_EXPORT_ROOT)
    timeout = int(request.GET.get("timeout", DEFAULT_TIMEOUT))
    poll_interval = float(request.GET.get("poll_interval", DEFAULT_POLL_INTERVAL))

    job_conn = None

    try:
        job_conn = _get_job_service_conn()

        script_id = _find_script_id(job_conn)
        if not script_id:
            return HttpResponse("IMS_Export.py not found on server", status=500)

        sc = script_client(
            script_id,
            inputs={"Image_ID": image_id},
            client=job_conn._client,
        )

        job_id = sc.run()
        if not job_id:
            return HttpResponse("Failed to start IMS export job", status=500)

        job = _poll_activity(job_conn, job_id, timeout, poll_interval)
        if not job:
            return HttpResponse("IMS export timed out", status=504)

        outputs = sc.getOutputs()
        export_path = outputs.get("Export_Path")
        export_name = outputs.get("Export_Name")

        if not export_path:
            return HttpResponse("IMS export returned no file path", status=500)

        export_root = os.path.realpath(export_root)
        export_path = os.path.realpath(export_path)

        if not export_path.startswith(export_root + os.sep):
            return HttpResponse("Invalid export path", status=500)

        if not os.path.exists(export_path):
            return HttpResponse("Export file not found", status=404)

        filename = export_name or os.path.basename(export_path)

        return FileResponse(
            open(export_path, "rb"),
            as_attachment=True,
            filename=filename,
            content_type="application/octet-stream",
        )

    finally:
        if job_conn:
            job_conn.close()
