from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info
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
from ..views.utils import (
    build_omero_cli_base_command,
    load_json_body,
    require_non_root_user,
    validate_user_password,
)
from ..strings import errors as error_messages
logger = logging.getLogger(__name__)

OMERO = OMERO_CLI


@csrf_exempt
@login_required()
@require_non_root_user
def delete_plugin_keyvaluepairs(request, conn=None, url=None, **kwargs):
    """Delete ONLY plugin-generated MapAnnotations for a project."""
    try:
        if request.method != "POST":
            return JsonResponse({"error": error_messages.method_post_required()}, status=400)

        data, error = load_json_body(request)
        if error:
            return JsonResponse({"error": error}, status=400)

        project_id = data.get("project_id")
        password = data.get("password")

        if not project_id:
            return JsonResponse({"error": error_messages.missing_project_id()}, status=400)
        if not password:
            return JsonResponse({"error": error_messages.missing_password()}, status=400)

        valid, _ = validate_user_password(conn, password)
        if not valid:
            logger.warning(
                "OMERO password validation failed for delete_plugin_keyvaluepairs user %s",
                conn.getUser().getName(),
            )
            return JsonResponse(
                {
                    "ok": False,
                    "error": error_messages.omero_web_login_failed(),
                }
            )

        cli_base_cmd = build_omero_cli_base_command(conn)

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
        deletion_errors = []

        for img in images:
            try:
                iid = get_id(img)
                plugin_ann_ids = find_plugin_annotation_ids(conn, iid)
            except Exception as e:
                logger.warning(
                    "Cannot resolve annotations for image %s: %s",
                    sanitize_log_value(get_id(img)),
                    sanitize_log_value(e),
                )
                deletion_errors.append(
                    {"image": get_id(img), "error": error_messages.unexpected_error()}
                )
                continue

            if not plugin_ann_ids:
                continue

            removed_for_image = False

            for aid in plugin_ann_ids:
                try:
                    link_ids = find_annotation_link_ids(conn, aid)
                    for lid in link_ids:
                        link_cmd = [
                            *cli_base_cmd,
                            "delete",
                            f"ImageAnnotationLink:{int(lid)}",
                            "--force",
                        ]
                        link_result = subprocess.run(
                            link_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            stdin=subprocess.DEVNULL,
                        )
                        if link_result.returncode != 0:
                            logger.warning(
                                "Failed to delete annotation link %s for image %s annotation %s: rc=%s stdout=%r stderr=%r",
                                lid,
                                iid,
                                aid,
                                link_result.returncode,
                                link_result.stdout,
                                link_result.stderr,
                            )
                            deletion_errors.append(
                                {
                                    "image": iid,
                                    "annotation": aid,
                                    "link": lid,
                                    "error": error_messages.unable_delete_plugin_annotations(),
                                }
                            )

                    remaining_links = find_annotation_link_ids(conn, aid)
                    if remaining_links:
                        deletion_errors.append(
                            {
                                "image": iid,
                                "annotation": aid,
                                "links_remaining": remaining_links,
                                "error": error_messages.annotation_links_still_exist(),
                            }
                        )
                        continue

                    cmd = [
                        *cli_base_cmd,
                        "delete",
                        f"Annotation:{int(aid)}",
                        "--force",
                    ]

                    result = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        stdin=subprocess.DEVNULL,
                    )

                    if result.returncode != 0:
                        logger.warning(
                            "Failed to delete plugin annotation %s for image %s: rc=%s stdout=%r stderr=%r",
                            aid,
                            iid,
                            result.returncode,
                            result.stdout,
                            result.stderr,
                        )
                        deletion_errors.append(
                            {
                                "image": iid,
                                "annotation": aid,
                                "error": error_messages.unable_delete_plugin_annotations(),
                            }
                        )
                        continue

                    ann_obj = conn.getObject("MapAnnotation", int(aid))
                    if ann_obj is not None:
                        deletion_errors.append(
                            {
                                "image": iid,
                                "annotation": aid,
                                "error": error_messages.annotation_still_exists(),
                            }
                        )
                        continue

                    deleted_annotations += 1
                    removed_for_image = True
                except Exception as e:
                    logger.warning(
                        "Error deleting plugin annotation %s on image %s: %s",
                        sanitize_log_value(aid),
                        sanitize_log_value(iid),
                        sanitize_log_value(e),
                    )
                    deletion_errors.append(
                        {
                            "image": iid,
                            "annotation": aid,
                            "error": error_messages.unexpected_error(),
                        }
                    )
                    continue

            if removed_for_image:
                deleted_images += 1

        return JsonResponse(
            {
                "ok": True,
                "deleted_images": deleted_images,
                "deleted_annotations": deleted_annotations,
                "errors": deletion_errors,
            }
        )

    except Exception as e:
        logger.error(
            "delete_plugin_keyvaluepairs failed: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": error_messages.unexpected_error()}, status=500)
