from __future__ import annotations

from contextlib import suppress
from functools import wraps

import omero
from django.conf import settings
from django.http import JsonResponse

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env
from omero_plugin_common.request_utils import (
    current_username as _current_username,
    parse_json_body,
)


AUTH_VALIDATION_FAILED_ERROR = "Credential validation failed."
CURRENT_USER_REQUIRED_ERROR = "Could not resolve the current OMERO user."
JSON_OBJECT_REQUIRED_ERROR = "Request body must be a JSON object."


def current_username(request, conn):
    """Return current username.

    Inputs: `request`, `conn`. Output: `_current_username` result.
    """
    return _current_username(request, conn)


def load_json_body(request):
    """Return load JSON body.

    Inputs: `request`. Output: tuple.
    """
    payload, error = parse_json_body(request)
    if error:
        return None, error
    return payload, None


def load_json_object(request):
    """Return load JSON object.

    Inputs: `request`. Output: tuple.
    """
    payload, error = load_json_body(request)
    if error:
        return None, error
    if not isinstance(payload, dict):
        return None, JSON_OBJECT_REQUIRED_ERROR
    return payload, None


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
            return JsonResponse({"error": CURRENT_USER_REQUIRED_ERROR}, status=403)
        if username == "root":
            return JsonResponse(
                {"error": "PLEASE LOGIN AS REGULAR USER\nTO USE THIS PLUGIN"},
                status=403,
            )
        return view_func(request, *remaining_args, conn=conn, url=url, **kwargs)

    return _wrapped


def resolve_omero_host_port(conn):
    """Return resolve OMERO host port.

    Inputs: `conn`. Output: tuple.
    """
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
    """Validate user password.

    Inputs: `conn`, `password`. Output: tuple.
    """
    if not password:
        return False, "Password is required."
    username = current_username(None, conn)
    host, port = resolve_omero_host_port(conn)
    if not username or not host or not port:
        return False, "Could not validate the provided password."
    client = None
    session_created = False
    try:
        client = omero.client(host=host, port=port)
        client.createSession(username, password)
        session_created = True
    except Exception:
        return False, AUTH_VALIDATION_FAILED_ERROR
    finally:
        if session_created and client is not None:
            with suppress(Exception):
                client.closeSession()
    return True, None
