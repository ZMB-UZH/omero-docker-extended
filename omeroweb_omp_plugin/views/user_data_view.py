import logging

from django.http import JsonResponse
from omeroweb.decorators import login_required
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from ..services.data_store import (
    AiCredentialStoreError,
    UserDataStoreError,
    VariableStoreError,
    delete_all_ai_credentials,
    delete_all_user_data,
    delete_all_variable_sets,
)
from ..views.utils import current_username, require_non_root_user
from ..strings import errors


logger = logging.getLogger(__name__)


@login_required()
@require_non_root_user
def delete_api_keys(request, conn=None, _url=None, **kwargs):
    """Delete API keys.

    Inputs: `request`, `conn`, `_url`, `**kwargs`. Output: `JsonResponse` result.
    """
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse(
            {"error": errors.unable_to_determine_username()}, status=400
        )

    try:
        deleted = delete_all_ai_credentials(username)
        return JsonResponse({"ok": True, "deleted": deleted})
    except AiCredentialStoreError as exc:
        logger.error(
            "AI credential store failure while deleting API keys.",
            exc_info=sanitized_exc_info(exc),
        )
        return JsonResponse(
            {"error": errors.ai_credentials_delete_failed()}, status=500
        )
    except Exception as e:
        logger.error(
            "Unexpected error deleting stored provider entries: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@login_required()
@require_non_root_user
def delete_variable_sets(request, conn=None, _url=None, **kwargs):
    """Delete variable sets.

    Inputs: `request`, `conn`, `_url`, `**kwargs`. Output: `JsonResponse` result.
    """
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse(
            {"error": errors.unable_to_determine_username()}, status=400
        )

    try:
        deleted = delete_all_variable_sets(username)
        return JsonResponse({"ok": True, "deleted": deleted})
    except VariableStoreError as exc:
        logger.error(
            "Variable store failure while deleting variable sets.",
            exc_info=sanitized_exc_info(exc),
        )
        return JsonResponse({"error": errors.variable_sets_delete_failed()}, status=500)
    except Exception as e:
        logger.error(
            "Unexpected error deleting variable sets: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@login_required()
@require_non_root_user
def delete_all_data(request, conn=None, _url=None, **kwargs):
    """Delete all data.

    Inputs: `request`, `conn`, `_url`, `**kwargs`. Output: `JsonResponse` result.
    """
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse(
            {"error": errors.unable_to_determine_username()}, status=400
        )

    try:
        deleted = delete_all_user_data(username)
        return JsonResponse({"ok": True, "deleted": deleted})
    except UserDataStoreError as exc:
        logger.error(
            "User data store failure while deleting all data.",
            exc_info=sanitized_exc_info(exc),
        )
        return JsonResponse({"error": errors.user_data_delete_failed()}, status=500)
    except Exception as e:
        logger.error(
            "Unexpected error deleting all user data: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": errors.unexpected_error()}, status=500)
