import logging

from django.http import JsonResponse
from omeroweb.decorators import login_required
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from ..services.data_store import (
    UserSettingsStoreError,
    load_special_method_settings,
    save_special_method_settings,
)
from ..views.utils import current_username, load_request_data, require_non_root_user
from ..strings import errors, messages


logger = logging.getLogger(__name__)


def _normalize_special_method_settings(settings_payload):
    """Normalize the special method settings.

    Inputs: `settings_payload`. Output: `normalized`.
    """
    if not isinstance(settings_payload, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, value in settings_payload.items():
        if isinstance(value, bool):
            normalized[key] = value
        elif isinstance(value, (int, float)):
            normalized[key] = value
        elif isinstance(value, str):
            normalized[key] = value
        else:
            normalized[key] = bool(value)
    return normalized


@login_required()
@require_non_root_user
def save_settings(request, conn=None, _url=None, **kwargs):
    """Save the settings.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse(
            {"error": errors.unable_to_determine_username()}, status=400
        )

    try:
        data = load_request_data(request)
        method_key = (data.get("method") or "").strip()
        if not method_key:
            return JsonResponse(
                {"error": errors.invalid_special_method_key()}, status=400
            )

        settings_payload = data.get("settings")
        if not isinstance(settings_payload, dict):
            return JsonResponse(
                {"error": errors.invalid_special_method_settings_payload()}, status=400
            )

        normalized = _normalize_special_method_settings(settings_payload)
        save_special_method_settings(username, method_key, normalized)

        return JsonResponse(
            {
                "success": True,
                "message": messages.special_method_settings_saved_db(),
                "settings": normalized,
            }
        )
    except UserSettingsStoreError as exc:
        logger.error(
            "Special method settings store failure on save.",
            exc_info=sanitized_exc_info(exc),
        )
        return JsonResponse(
            {"error": errors.special_method_settings_save_failed()}, status=500
        )
    except Exception as e:
        logger.error(
            "Unexpected error saving special method settings: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@login_required()
@require_non_root_user
def load_settings(request, conn=None, _url=None, **kwargs):
    """Return load settings.

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
        data = load_request_data(request)
        method_key = (data.get("method") or "").strip()
        if not method_key:
            return JsonResponse(
                {"error": errors.invalid_special_method_key()}, status=400
            )

        settings = load_special_method_settings(username, method_key)
        return JsonResponse(
            {
                "success": True,
                "settings": settings,
            }
        )
    except UserSettingsStoreError as exc:
        logger.error(
            "Special method settings store failure on load.",
            exc_info=sanitized_exc_info(exc),
        )
        return JsonResponse(
            {"error": errors.special_method_settings_load_failed()}, status=500
        )
    except Exception as e:
        logger.error(
            "Unexpected error loading special method settings: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": errors.unexpected_error()}, status=500)
