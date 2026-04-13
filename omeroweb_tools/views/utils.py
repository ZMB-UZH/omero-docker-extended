from __future__ import annotations

from functools import wraps

import omero
from django.conf import settings
from django.http import JsonResponse

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env
from omero_plugin_common.logging_utils import sanitize_log_value
from omero_plugin_common.request_utils import (
    current_username as _current_username,
    parse_json_body,
)


def current_username(request, conn):
    return _current_username(request, conn)


def load_json_body(request):
    payload, error = parse_json_body(request)
    if error:
        return None, error
    return payload, None


def require_non_root_user(view_func):
    @wraps(view_func)
    def _wrapped(request, conn=None, url=None, *args, **kwargs):
        username = current_username(request, conn)
        if username == "root":
            return JsonResponse(
                {"error": "PLEASE LOGIN AS REGULAR USER\nTO USE THIS PLUGIN"},
                status=403,
            )
        return view_func(request, conn=conn, url=url, *args, **kwargs)

    return _wrapped


def resolve_omero_host_port(conn):
    host = getattr(conn, "host", None) or getattr(conn, "_host", None)
    port = getattr(conn, "port", None) or getattr(conn, "_port", None)
    if not host:
        host = getattr(settings, "OMERO_HOST", None) or get_env(
            "OMEROHOST",
            env_file=ENV_FILE_OMEROWEB,
        )
    if not port:
        port = getattr(settings, "OMERO_PORT", None) or get_env(
            "OMERO_PORT",
            env_file=ENV_FILE_OMEROWEB,
        )
    try:
        port = int(port) if port is not None else None
    except (TypeError, ValueError):
        port = None
    return host, port


def validate_user_password(conn, password):
    if not password:
        return False, "Password is required."
    username = current_username(None, conn)
    host, port = resolve_omero_host_port(conn)
    if not username or not host or not port:
        return False, "Could not validate the provided password."
    client = omero.client(host=host, port=port)
    try:
        client.createSession(username, password)
    except Exception as exc:
        return False, f"Password validation failed: {sanitize_log_value(exc)}"
    finally:
        try:
            client.closeSession()
        except Exception:
            pass
    return True, None
