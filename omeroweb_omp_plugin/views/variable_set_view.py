import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..services.data_store import (
    VariableStoreError,
    list_variable_sets,
    load_variable_set,
    save_variable_set,
    delete_variable_set,
)
from ..constants import MAX_VARIABLE_SET_ENTRIES
from ..views.utils import current_username, load_request_data, require_non_root_user
from ..strings import errors, messages


logger = logging.getLogger(__name__)


@csrf_exempt
@login_required()
@require_non_root_user
def list_sets(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": errors.method_get_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        sets = list_variable_sets(username)
        return JsonResponse({"sets": sets})
    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error listing sets: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
@require_non_root_user
def save_set(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        data = load_request_data(request)

        set_name = (data.get("set_name") or "").strip()
        var_names = data.get("var_names")
        
        # Read user's max_sets
        user_max_sets = data.get("max_sets")
        try:
            max_sets = int(user_max_sets) if user_max_sets else MAX_VARIABLE_SET_ENTRIES
            if max_sets < 5 or max_sets > 30:
                max_sets = MAX_VARIABLE_SET_ENTRIES
        except (ValueError, TypeError):
            max_sets = MAX_VARIABLE_SET_ENTRIES

        if not isinstance(var_names, list):
            return JsonResponse({"error": errors.invalid_variable_payload()}, status=400)

        has_empty = any(not str(v or "").strip() for v in var_names)
        if has_empty:
            return JsonResponse({"error": errors.variable_names_empty()}, status=400)

        if not set_name:
            return JsonResponse({"error": errors.variable_set_name_required()}, status=400)

        existing_sets = list_variable_sets(username)
        normalized_existing = {str(name).strip() for name in existing_sets}
        
        # Check if name already exists - prevent overwrite
        if set_name in normalized_existing:
            return JsonResponse({"error": errors.variable_set_already_exists()}, status=400)
        
        # Check max limit for new sets only
        if len(existing_sets) >= max_sets:
            return JsonResponse({"error": errors.variable_set_max_entries(max_sets)}, status=400)

        save_variable_set(username, set_name, var_names)

        return JsonResponse({"message": messages.variable_set_saved_response()})

    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving set: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
@require_non_root_user
def load_set(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": errors.method_get_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    set_name = (request.GET.get("set_name") or "").strip()
    if not set_name:
        return JsonResponse({"error": errors.variable_set_dropdown_required()}, status=400)

    try:
        existing_sets = list_variable_sets(username)
        if not existing_sets:
            return JsonResponse({"error": errors.variable_set_empty_db()}, status=400)

        var_names = load_variable_set(username, set_name)
        if var_names is None:
            return JsonResponse({"error": errors.variable_set_not_found()}, status=404)

        return JsonResponse({"var_names": var_names})
    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error loading set: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)


@csrf_exempt
@login_required()
@require_non_root_user
def delete_set(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"error": errors.method_post_required()}, status=405)

    username = current_username(request, conn)
    if not username:
        return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

    try:
        data = load_request_data(request)

        set_name = (data.get("set_name") or "").strip()
        if not set_name:
            return JsonResponse({"error": errors.missing_set_name()}, status=400)

        delete_variable_set(username, set_name)

        return JsonResponse({"ok": True})

    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error deleting set: %s", e)
        return JsonResponse({"error": errors.unexpected_error()}, status=500)
