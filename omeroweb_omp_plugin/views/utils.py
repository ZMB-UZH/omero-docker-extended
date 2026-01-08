import json

from .. import errors


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


def load_request_data(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return request.POST


def load_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8")), None
    except Exception:
        return None, errors.invalid_json_body()
