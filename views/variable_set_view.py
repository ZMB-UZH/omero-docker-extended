import json
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
def list_sets(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)

    username = _current_username(request, conn)
    if not username:
        return JsonResponse({"error": "Unable to determine username."}, status=400)

    try:
        sets = list_variable_sets(username)
        return JsonResponse({"sets": sets})
    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error listing sets: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)


@csrf_exempt
@login_required()
def save_set(request, conn=None, url=None, **kwargs):
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

        set_name = (data.get("set_name") or "").strip()
        var_names = data.get("var_names")

        if not isinstance(var_names, list):
            return JsonResponse({"error": "Invalid variable payload."}, status=400)

        non_empty = [v for v in var_names if str(v or "").strip()]
        if not non_empty:
            return JsonResponse({"error": "Cannot save to database. List of variables empty."}, status=400)

        if not set_name:
            return JsonResponse({"error": "Please provide a name for this set."}, status=400)

        existing_sets = list_variable_sets(username)
        normalized_existing = {str(name).strip() for name in existing_sets}
        if set_name not in normalized_existing and len(existing_sets) >= MAX_VARIABLE_SET_ENTRIES:
            return JsonResponse(
                {
                    "error": (
                        "The maximum number of maximum entries in the database is 10. "
                        "Please delete a variable set first."
                    )
                },
                status=400,
            )

        save_variable_set(username, set_name, var_names)

        return JsonResponse({"message": "Saved variable set."})

    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error saving set: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)


@csrf_exempt
@login_required()
def load_set(request, conn=None, url=None, **kwargs):
    if request.method != "GET":
        return JsonResponse({"error": "GET required"}, status=405)

    username = _current_username(request, conn)
    if not username:
        return JsonResponse({"error": "Unable to determine username."}, status=400)

    set_name = (request.GET.get("set_name") or "").strip()
    if not set_name:
        return JsonResponse({"error": "Please select a set of variables from the dropdown menu first."}, status=400)

    try:
        existing_sets = list_variable_sets(username)
        if not existing_sets:
            return JsonResponse({"error": "Your user database is empty. Please save some variables first."}, status=400)

        var_names = load_variable_set(username, set_name)
        if var_names is None:
            return JsonResponse({"error": "Requested variable set was not found."}, status=404)

        return JsonResponse({"var_names": var_names})
    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error loading set: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)


@csrf_exempt
@login_required()
def delete_set(request, conn=None, url=None, **kwargs):
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

        set_name = (data.get("set_name") or "").strip()
        if not set_name:
            return JsonResponse({"error": "Missing set_name"}, status=400)

        delete_variable_set(username, set_name)

        return JsonResponse({"ok": True})

    except VariableStoreError as e:
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("Unexpected error deleting set: %s", e)
        return JsonResponse({"error": "Unexpected error."}, status=500)
