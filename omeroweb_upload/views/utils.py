from django.http import JsonResponse

from omero_plugin_common.request_utils import (
    current_username as _current_username,
    load_request_data as _load_request_data,
    parse_json_body,
)

def current_username(request, conn):
    return _current_username(request, conn)


def load_json_body(request):
    payload, _error = parse_json_body(request)
    return payload if payload is not None else {}


def load_request_data(request):
    return _load_request_data(request)


def json_error(message, status=200, extra=None):
    payload = {"ok": False, "error": message}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)
