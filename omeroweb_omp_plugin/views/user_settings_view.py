import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import UserSettingsStoreError, save_user_settings


logger = logging.getLogger(__name__)


def _current_username(request, conn):
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception:
        pass

    try:
        return request.user.username
    except Exception:
        return None


@csrf_exempt
@login_required()
def save_settings(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    username = _current_username(request, conn)
    if not username:
        return JsonResponse({"error": "Unable to determine username."}, status=400)

    try:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = request.POST

        settings_payload = data.get("settings")
        if not isinstance(settings_payload, dict):
            return JsonResponse({"error": "Invalid user settings payload."}, status=400)

        save_user_settings(username, settings_payload)
        return JsonResponse({"message": "Saved user settings."})
    except UserSettingsStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving user settings: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)
