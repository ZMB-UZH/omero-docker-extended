import json

from django.http import JsonResponse


def current_username(request, conn):
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


def load_json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def load_request_data(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return request.POST


def json_error(message, status=200, extra=None):
    payload = {"ok": False, "error": message}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)
