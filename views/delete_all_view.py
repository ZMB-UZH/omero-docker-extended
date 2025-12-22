from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import subprocess
import logging
import json

from ..services.core import collect_images_in_project, get_id

logger = logging.getLogger(__name__)

# Use the correct Python venv path for Omero CLI
# ATTENTION!! Might change in future releases!
OMERO = "/opt/omero/web/venv-3.12/bin/omero"

@csrf_exempt
@login_required()
def delete_all_keyvaluepairs(request, conn=None, url=None, **kwargs):
    """
    Delete ALL MapAnnotations for ALL images in a given project using Omero CLI.
    - Logs in once with the current OMERO web user + provided password
    - Deletes in batches for speed
    """
    try:
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        project_id = data.get("project_id")
        password = data.get("password")

        if not project_id:
            return JsonResponse({"error": "Missing project_id"}, status=400)
        if not password:
            return JsonResponse({"error": "Missing password"}, status=400)

        # Omero web username from current web session
        username = conn.getUser().getName()

        # 1) LOGIN to the SECURE server
        login_cmd = [
            OMERO, "login",
            "-s", "omeroserver",
            "-u", username,
            "-w", password,
            "-p", "4064",
        ]

        login = subprocess.run(
            login_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if login.returncode != 0:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Omero web login failed",
                    "stdout": login.stdout,
                    "stderr": login.stderr,
                }
            )

        try:
            # 2) Collect all images for the project
            images = collect_images_in_project(conn, project_id)
            image_ids = [str(get_id(img)) for img in images]

            if not image_ids:
                return JsonResponse(
                    {"ok": True, "deleted_count": 0, "errors": [], "note": "No images found"}
                )

            deleted_count = 0
            errors = []

            # 3) Delete in batches using a single CLI call per chunk
            # DO NOT increase CHUNK too much else the users might be tempted to interrupt the process
            CHUNK = 100
            for i in range(0, len(image_ids), CHUNK):
                chunk_ids = image_ids[i:i + CHUNK]
                target = "Image/Annotation:" + ",".join(chunk_ids)
                cmd = [
                    OMERO,
                    "delete",
                    target,
                    "--include",
                    "MapAnnotation",
                    "--include",
                    "ImageAnnotationLink",
                    "--force",
                ]

                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                if result.returncode == 0:
                    deleted_count += len(chunk_ids)
                else:
                    errors.append(
                        {
                            "ids": chunk_ids,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                    )

            return JsonResponse(
                {
                    "ok": True,
                    "deleted_count": deleted_count,
                    "errors": errors,
                }
            )
        finally:
            subprocess.run(
                [OMERO, "logout"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

    except Exception as e:
        logger.exception("delete_all_keyvaluepairs failed: %s", e)
        return JsonResponse({"error": str(e)}, status=500)
