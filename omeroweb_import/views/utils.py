from functools import wraps

from django.http import JsonResponse

from omero_plugin_common.request_utils import (
    current_username as _current_username,
    load_request_data as _load_request_data,
    parse_json_body,
)

from ..strings import errors


def current_username(request, conn):
    """Return current username.

    Inputs: `request`, `conn`. Output: `_current_username` result.
    """
    return _current_username(request, conn)


def load_json_body(request):
    """Return load JSON body.

    Inputs: `request`. Output: computed value.
    """
    payload, _error = parse_json_body(request)
    return payload if payload is not None else {}


def load_request_data(request):
    """Return load request data.

    Inputs: `request`. Output: `_load_request_data` result.
    """
    return _load_request_data(request)


def json_error(message, status=200, extra=None):
    """JSON error.

    Inputs: `message`, `status`, `extra`. Output: `JsonResponse` result.
    """
    payload = {"ok": False, "error": message}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)


def require_non_root_user(view_func):
    """Non root user.

    Inputs: `view_func`. Output: computed value.
    """

    @wraps(view_func)
    def _wrapped(request, *args, conn=None, url=None, **kwargs):
        """Wrapped.

        Inputs: `request`, `conn`, `url`, `*args`, `**kwargs`. Output: computed value.
        """
        remaining_args = args
        if remaining_args and conn is None:
            conn = remaining_args[0]
            remaining_args = remaining_args[1:]
        if remaining_args and url is None:
            url = remaining_args[0]
            remaining_args = remaining_args[1:]
        username = str(current_username(request, conn) or "").strip()
        if not username:
            return JsonResponse(
                {"error": errors.unable_to_determine_username()},
                status=403,
            )
        if username == "root":
            return JsonResponse(
                {"error": ("PLEASE LOGIN AS REGULAR USER\nTO USE THIS PLUGIN")},
                status=403,
            )
        return view_func(request, *remaining_args, conn=conn, url=url, **kwargs)

    return _wrapped
