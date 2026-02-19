import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import (
    UserSettingsStoreError,
    load_special_method_settings,
    save_special_method_settings,
)
from ..views.utils import current_username, load_request_data
from ..strings import errors, messages


logger = logging.getLogger(__name__)


def _normalize_special_method_settings(settings_payload):
    if not isinstance(settings_payload, dict):
        return {}
    return {key: bool(value) for key, value in settings_payload.items()}


@csrf_exempt
@login_required()
def save_settings(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        data = load_request_data(request)
        method_key = (data.get("method") or "").strip()
        if not method_key:
            return JsonResponse({"error": errors.invalid_special_method_key()}, status=400)

        settings_payload = data.get("settings")
        if not isinstance(settings_payload, dict):
            return JsonResponse({"error": errors.invalid_special_method_settings_payload()}, status=400)

        normalized = _normalize_special_method_settings(settings_payload)
        save_special_method_settings(username, method_key, normalized)

        return JsonResponse({
            "success": True,
            "message": messages.special_method_settings_saved_db(),
            "settings": normalized,
        })
    except UserSettingsStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving special method settings: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
def load_settings(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        data = load_request_data(request)
        method_key = (data.get("method") or "").strip()
        if not method_key:
            return JsonResponse({"error": errors.invalid_special_method_key()}, status=400)

        settings = load_special_method_settings(username, method_key)
        return JsonResponse({
            "success": True,
            "settings": settings,
        })
    except UserSettingsStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error loading special method settings: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)
