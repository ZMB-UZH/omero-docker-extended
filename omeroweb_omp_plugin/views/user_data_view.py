import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import (
    AiCredentialStoreError,
    UserDataStoreError,
    VariableStoreError,
    delete_all_ai_credentials,
    delete_all_user_data,
    delete_all_variable_sets,
)
from ..views.utils import current_username
from ..strings import errors


logger = logging.getLogger(__name__)


@csrf_exempt
@login_required()
def delete_api_keys(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        deleted = delete_all_ai_credentials(username)
        return JsonResponse({"ok": True, "deleted": deleted})
    except AiCredentialStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error deleting API keys: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
def delete_variable_sets(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        deleted = delete_all_variable_sets(username)
        return JsonResponse({"ok": True, "deleted": deleted})
    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error deleting variable sets: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
def delete_all_data(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        deleted = delete_all_user_data(username)
        return JsonResponse({"ok": True, "deleted": deleted})
    except UserDataStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error deleting all user data: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)
