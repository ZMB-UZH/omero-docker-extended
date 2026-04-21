from django.http import JsonResponse
from omeroweb.decorators import login_required
from omero_plugin_common import process_utils
from omero_plugin_common.logging_utils import (
    sanitize_log_value,
    sanitized_exc_info,
    summarize_process_output,
)
import logging

from ..services.core import collect_images_in_project, find_map_annotation_ids, get_id
from ..constants import OMERO_CLI
from ..services.rate_limit import (
    build_rate_limit_message,
    check_major_action_rate_limit,
)
from ..views.utils import (
    build_omero_cli_base_command,
    load_json_body,
    require_non_root_user,
    validate_user_password,
)
from ..strings import errors as error_messages

logger = logging.getLogger(__name__)
subprocess = process_utils

OMERO = OMERO_CLI


@login_required()
@require_non_root_user
def delete_all_keyvaluepairs(request, conn=None, _url=None, **kwargs):
    """
    Delete ALL MapAnnotations for ALL images in a given project using OMERO CLI.
    - Logs in once with the current OMERO.web user + provided password
    - Deletes in batches for speed
    """
    try:
        if request.method != "POST":
            return JsonResponse(
                {"error": error_messages.method_post_required()}, status=400
            )

        data, error = load_json_body(request)
        if error:
            return JsonResponse(
                {"error": error_messages.invalid_json_body()},
                status=400,
            )

        project_id = data.get("project_id")
        password = data.get("password")

        if not project_id:
            return JsonResponse(
                {"error": error_messages.missing_project_id()}, status=400
            )
        if not password:
            return JsonResponse(
                {"error": error_messages.missing_password()}, status=400
            )

        valid, _ = validate_user_password(conn, password)
        if not valid:
            logger.warning(
                "OMERO re-authentication failed for delete_all_keyvaluepairs user %s",
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
        image_ids = [str(get_id(img)) for img in images]

        if not image_ids:
            return JsonResponse(
                {
                    "ok": True,
                    "deleted_count": 0,
                    "errors": [],
                    "note": error_messages.no_images_found(),
                }
            )

        allowed, remaining = check_major_action_rate_limit(request, conn)
        if not allowed:
            return JsonResponse(
                {"error": build_rate_limit_message(remaining)},
                status=429,
            )

        deleted_count = 0
        deletion_errors = []

        CHUNK = 100
        for i in range(0, len(image_ids), CHUNK):
            chunk_ids = [str(int(x)) for x in image_ids[i : i + CHUNK]]
            target = "Image/Annotation:" + ",".join(chunk_ids)
            cmd = [
                *cli_base_cmd,
                "delete",
                target,
                "--include",
                "MapAnnotation",
                "--include",
                "ImageAnnotationLink",
                "--force",
            ]

            result = process_utils.run(
                cmd,
            )

            if result.returncode != 0:
                logger.warning(
                    "Failed to delete map annotations for image chunk %s: rc=%s %s",
                    chunk_ids,
                    result.returncode,
                    summarize_process_output(result.stdout, result.stderr),
                )
                deletion_errors.append(
                    {
                        "ids": chunk_ids,
                        "error": error_messages.unable_delete_annotations(),
                    }
                )
                continue

            for image_id in chunk_ids:
                remaining = find_map_annotation_ids(conn, image_id)
                if remaining:
                    deletion_errors.append(
                        {
                            "ids": [image_id],
                            "error": error_messages.map_annotations_still_present(),
                            "remaining": remaining,
                        }
                    )
                    continue
                deleted_count += 1

        return JsonResponse(
            {
                "ok": True,
                "deleted_count": deleted_count,
                "errors": deletion_errors,
            }
        )

    except Exception as e:
        logger.error(
            "delete_all_keyvaluepairs failed: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": error_messages.unexpected_error()}, status=500)
