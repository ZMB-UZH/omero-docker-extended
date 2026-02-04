from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import subprocess
import logging

from ..services.core import collect_images_in_project, find_map_annotation_ids, get_id
from ..constants import OMERO_CLI
from ..services.rate_limit import build_rate_limit_message, check_major_action_rate_limit
from ..views.utils import load_json_body
from ..strings import errors

logger = logging.getLogger(__name__)

OMERO = OMERO_CLI

@csrf_exempt
@login_required()
def delete_all_keyvaluepairs(request, conn=None, url=None, **kwargs):
    """
    Delete ALL MapAnnotations for ALL images in a given project using OMERO CLI.
    - Logs in once with the current OMERO.web user + provided password
    - Deletes in batches for speed
    """
    try:
        if request.method != "POST":
            return JsonResponse({"error": errors.method_post_required()}, status=400)

        data, error = load_json_body(request)
        if error:
            return JsonResponse({"error": error}, status=400)

        project_id = data.get("project_id")
        password = data.get("password")

        if not project_id:
            return JsonResponse({"error": errors.missing_project_id()}, status=400)
        if not password:
            return JsonResponse({"error": errors.missing_password()}, status=400)

        # OMERO.web username from current web session
        username = conn.getUser().getName()

        # 1) LOGOUT first to clear any cached sessions
        subprocess.run(
            [OMERO, "logout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # 2) LOGIN to the SECURE server (fresh login, no cached session)
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
                    "error": errors.omero_web_login_failed(),
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
                    {
                        "ok": True,
                        "deleted_count": 0,
                        "errors": [],
                        "note": errors.no_images_found(),
                    }
                )

            allowed, remaining = check_major_action_rate_limit(request, conn)
            if not allowed:
                return JsonResponse(
                    {"error": build_rate_limit_message(remaining)},
                    status=429,
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

                if result.returncode != 0:
                    errors.append(
                        {
                            "ids": chunk_ids,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                    )
                    continue

                for image_id in chunk_ids:
                    remaining = find_map_annotation_ids(conn, image_id)
                    if remaining:
                        errors.append(
                            {
                                "ids": [image_id],
                                "error": errors.map_annotations_still_present(),
                                "remaining": remaining,
                            }
                        )
                        continue
                    deleted_count += 1

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
