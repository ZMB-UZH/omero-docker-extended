from django.http import JsonResponse
from omeroweb.decorators import login_required
from omero_plugin_common.logging_utils import (
    sanitize_log_value,
    sanitized_exc_info,
)
import logging
from ..services.core import (
    collect_images_in_project,
    delete_existing_annotations,
    find_plugin_annotation_ids,
    get_id,
)
from ..services.rate_limit import (
    build_rate_limit_message,
    check_major_action_rate_limit,
)
from ..views.utils import (
    load_json_body,
    require_non_root_user,
    validate_user_password,
)
from .project_access import require_destructive_project_access
from ..strings import errors as error_messages

logger = logging.getLogger(__name__)


@login_required()
@require_non_root_user
def delete_plugin_keyvaluepairs(request, conn=None, _url=None, **kwargs):
    """Delete the plugin keyvaluepairs.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
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
                "OMERO re-authentication failed for delete_plugin_keyvaluepairs user %s",
                conn.getUser().getName(),
            )
            return JsonResponse(
                {
                    "ok": False,
                    "error": error_messages.omero_web_login_failed(),
                }
            )

        access_ok, access_error = require_destructive_project_access(conn, project_id)
        if not access_ok:
            return JsonResponse({"error": access_error}, status=403)

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

        update = conn.getUpdateService()
        for img in images:
            try:
                iid = get_id(img)
                targeted_annotations = find_plugin_annotation_ids(conn, iid)
            except Exception as e:
                logger.warning(
                    "Cannot resolve annotations for image %s: %s",
                    sanitize_log_value(get_id(img)),
                    sanitize_log_value(type(e).__name__),
                )
                deletion_errors.append(
                    {"image": get_id(img), "error": error_messages.unexpected_error()}
                )
                continue

            if not targeted_annotations:
                continue

            try:
                deleted_sets, _deleted_pairs, _targeted_sets = (
                    delete_existing_annotations(conn, update, img, [], "plugin")
                )
            except Exception as e:
                logger.warning(
                    "Error deleting plugin annotations on image %s: %s",
                    sanitize_log_value(iid),
                    sanitize_log_value(type(e).__name__),
                )
                deletion_errors.append(
                    {
                        "image": iid,
                        "error": error_messages.unexpected_error(),
                    }
                )
                continue

            remaining = find_plugin_annotation_ids(conn, iid)
            if remaining:
                deletion_errors.append(
                    {
                        "image": iid,
                        "annotations_remaining": remaining,
                        "error": error_messages.annotation_still_exists(),
                    }
                )
                continue

            deleted_annotations += deleted_sets
            if targeted_annotations:
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
