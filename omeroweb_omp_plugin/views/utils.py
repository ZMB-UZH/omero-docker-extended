from functools import wraps

from django.http import JsonResponse

from ..strings import errors
from omero_plugin_common.request_utils import (
    current_username as _current_username,
    load_request_data as _load_request_data,
    parse_json_body,
)


def current_username(request, conn):
    return _current_username(request, conn)


def load_request_data(request):
    return _load_request_data(request)


def load_json_body(request):
    payload, error = parse_json_body(request)
    if error:
        return None, errors.invalid_json_body()
    return payload, None


def require_non_root_user(view_func):
    @wraps(view_func)
    def _wrapped(request, conn=None, url=None, *args, **kwargs):
        username = current_username(request, conn)
        if username == "root":
            return JsonResponse(
                {
                    "error": "PLEASE LOGIN AS REGULAR USER\nTO USE THIS PLUGIN"
                },
                status=403,
            )
        return view_func(request, conn=conn, url=url, *args, **kwargs)

    return _wrapped
