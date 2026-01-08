from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import subprocess
import logging
from ..services.core import (
    collect_images_in_project,
    find_annotation_link_ids,
    find_plugin_annotation_ids,
    get_id,
)
from ..constants import OMERO_CLI
from ..services.rate_limit import build_rate_limit_message, check_major_action_rate_limit
from ..views.utils import load_json_body
from ..strings import errors
logger = logging.getLogger(__name__)

OMERO = OMERO_CLI


@csrf_exempt
@login_required()
def delete_plugin_keyvaluepairs(request, conn=None, url=None, **kwargs):
    """Delete ONLY plugin-generated MapAnnotations for a project."""
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
            login_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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

            allowed, remaining = check_major_action_rate_limit(request, conn)
            if not allowed:
                return JsonResponse(
                    {"error": build_rate_limit_message(remaining)},
                    status=429,
                )

            deleted_annotations = 0
            deleted_images = 0
            errors = []

            for img in images:
                try:
                    iid = get_id(img)
                    plugin_ann_ids = find_plugin_annotation_ids(conn, iid)
                except Exception as e:
                    logger.warning("Cannot resolve annotations for image %s: %s", get_id(img), e)
                    errors.append({"image": get_id(img), "error": str(e)})
                    continue

                if not plugin_ann_ids:
                    continue

                removed_for_image = False

                for aid in plugin_ann_ids:
                    try:
                        link_ids = find_annotation_link_ids(conn, aid)
                        for lid in link_ids:
                            link_cmd = [
                                OMERO,
                                "delete",
                                f"ImageAnnotationLink:{lid}",
                                "--force",
                            ]
                            link_result = subprocess.run(
                                link_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                            )
                            if link_result.returncode != 0:
                                errors.append(
                                    {
                                        "image": iid,
                                        "annotation": aid,
                                        "link": lid,
                                        "stdout": link_result.stdout,
                                        "stderr": link_result.stderr,
                                    }
                                )

                        remaining_links = find_annotation_link_ids(conn, aid)
                        if remaining_links:
                            errors.append(
                                {
                                    "image": iid,
                                    "annotation": aid,
                                    "links_remaining": remaining_links,
                                    "error": errors.annotation_links_still_exist(),
                                }
                            )
                            continue

                        cmd = [
                            OMERO,
                            "delete",
                            f"Annotation:{aid}",
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
                                    "image": iid,
                                    "annotation": aid,
                                    "stdout": result.stdout,
                                    "stderr": result.stderr,
                                }
                            )
                            continue

                        ann_obj = conn.getObject("MapAnnotation", int(aid))
                        if ann_obj is not None:
                            errors.append(
                                {
                                    "image": iid,
                                    "annotation": aid,
                                    "error": errors.annotation_still_exists(),
                                }
                            )
                            continue

                        deleted_annotations += 1
                        removed_for_image = True
                    except Exception as e:
                        logger.warning(
                            "Error deleting plugin annotation %s on image %s: %s",
                            aid,
                            iid,
                            e,
                        )
                        errors.append({"image": iid, "annotation": aid, "error": str(e)})
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
        logger.exception("delete_plugin_keyvaluepairs failed: %s", e)
        return JsonResponse({"error": str(e)}, status=500)
