from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import subprocess
import logging
import json

from omero.model import MapAnnotationI

from ..services.core import collect_images_in_project, get_id, is_plugin_annotation
from ..constants import MAP_NS

logger = logging.getLogger(__name__)

# Use the correct Python venv path for Omero CLI
# ATTENTION!! Might change in future releases!
OMERO = "/opt/omero/web/venv-3.12/bin/omero"


@csrf_exempt
@login_required()
def delete_plugin_metadata(request, conn=None, url=None, **kwargs):
    """Delete ONLY plugin-generated MapAnnotations for a project."""
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

        username = conn.getUser().getName()

        login_cmd = [
            OMERO,
            "login",
            "-s",
            "omeroserver",
            "-u",
            username,
            "-w",
            password,
            "-p",
            "4064",
        ]

        login = subprocess.run(
            login_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
            images = collect_images_in_project(conn, project_id)
            if not images:
                return JsonResponse(
                    {
                        "ok": True,
                        "deleted_images": 0,
                        "deleted_annotations": 0,
                        "errors": [],
                    }
                )

            update = conn.getUpdateService()

            deleted_annotations = 0
            deleted_images = 0
            errors = []

            for img in images:
                try:
                    annotations = list(img.listAnnotations())
                except Exception as e:
                    logger.warning("Cannot list annotations for image %s: %s", get_id(img), e)
                    errors.append({"image": get_id(img), "error": str(e)})
                    continue

                removed_for_image = False

                for ann in annotations:
                    try:
                        map_ann = getattr(ann, "_obj", ann)
                        if not isinstance(map_ann, MapAnnotationI):
                            continue

                        try:
                            ns_obj = map_ann.getNs()
                            ns = ns_obj.getValue() if ns_obj else None
                        except Exception:
                            ns = None

                        if ns != MAP_NS:
                            continue

                        if is_plugin_annotation(map_ann):
                            update.deleteObject(map_ann)
                            deleted_annotations += 1
                            removed_for_image = True
                    except Exception as e:
                        logger.warning(
                            "Error deleting plugin annotation on image %s: %s",
                            get_id(img),
                            e,
                        )
                        errors.append({"image": get_id(img), "error": str(e)})
                        continue

                if removed_for_image:
                    deleted_images += 1

            return JsonResponse(
                {
                    "ok": True,
                    "deleted_images": deleted_images,
                    "deleted_annotations": deleted_annotations,
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
        logger.exception("delete_plugin_metadata failed: %s", e)
        return JsonResponse({"error": str(e)}, status=500)
