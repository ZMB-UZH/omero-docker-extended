import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import UserSettingsStoreError, save_user_settings
from ..views.utils import current_username, load_request_data, require_non_root_user
from ..strings import errors, messages


logger = logging.getLogger(__name__)


@csrf_exempt
@login_required()
@require_non_root_user
def save_settings(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        data = load_request_data(request)

        settings_payload = data.get("settings")
        if not isinstance(settings_payload, dict):
            return JsonResponse({"error": errors.invalid_user_settings_payload()}, status=400)

        save_user_settings(username, settings_payload)

        return JsonResponse({
            "success": True,
            "message": messages.user_settings_saved(),
            "settings": settings_payload,
        })
    except UserSettingsStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving user settings: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)
