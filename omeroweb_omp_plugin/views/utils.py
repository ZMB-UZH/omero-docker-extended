import logging

import omero
from django.conf import settings
from functools import wraps

from django.http import JsonResponse

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env
from omero_plugin_common.logging_utils import sanitize_log_value

from ..constants import OMERO_CLI
from ..strings import errors
from omero_plugin_common.request_utils import (
    current_username as _current_username,
    load_request_data as _load_request_data,
    parse_json_body,
)

logger = logging.getLogger(__name__)


def current_username(request, conn):
    """Handle current username."""
    return _current_username(request, conn)


def load_request_data(request):
    """Return load request data."""
    return _load_request_data(request)


def load_json_body(request):
    """Return load JSON body."""
    payload, error = parse_json_body(request)
    if error:
        return None, errors.invalid_json_body()
    return payload, None


def resolve_omero_host_port(conn):
    """Resolve OMERO host/port from the active connection or environment."""
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

    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None

    return host, port


def validate_user_password(conn, password):
    """Re-authenticate the current user without exposing the password to a shell."""
    if not password:
        return False, errors.missing_password()

    username = current_username(None, conn)
    host, port = resolve_omero_host_port(conn)
    if not username or not host or not port:
        logger.error(
            "Unable to resolve OMERO connection details for re-authentication "
            "(username=%s, host=%s, port=%s).",
            sanitize_log_value(username),
            sanitize_log_value(host),
            sanitize_log_value(port),
        )
        return False, errors.validation_unavailable()

    client = omero.client(host=host, port=port)
    try:
        client.createSession(username, password)
    except Exception as exc:
        logger.warning(
            "Re-authentication failed for user %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(exc),
        )
        return False, errors.wrong_password()
    finally:
        try:
            client.closeSession()
        except Exception as exc:
            logger.debug("Suppressed non-fatal exception in utils.py", exc_info=exc)

    return True, None


def get_session_key(conn):
    """Return the active OMERO session key for CLI reuse."""
    if conn is None:
        return None

    if callable(getattr(conn, "getSessionId", None)):
        try:
            session_id = conn.getSessionId()
            if session_id:
                return session_id
        except Exception as exc:
            logger.debug("getSessionId() failed in utils.py", exc_info=exc)

    for attr in ("_sessionUuid", "_session", "session"):
        value = getattr(conn, attr, None)
        if value:
            return value

    try:
        if hasattr(conn, "c") and conn.c and hasattr(conn.c, "getSessionId"):
            session_id = conn.c.getSessionId()
            if session_id:
                return session_id
    except Exception as exc:
        logger.debug("conn.c.getSessionId() failed in utils.py", exc_info=exc)

    return None


def build_omero_cli_base_command(conn):
    """Build a session-key-based OMERO CLI prefix for authenticated commands."""
    session_key = get_session_key(conn)
    host, port = resolve_omero_host_port(conn)
    if not session_key or not host or not port:
        raise ValueError("Missing OMERO session or connection metadata")
    return [OMERO_CLI, "-k", str(session_key), "-s", str(host), "-p", str(port)]


def require_non_root_user(view_func):
    """Handle require non root user."""

    @wraps(view_func)
    def _wrapped(request, *args, conn=None, url=None, **kwargs):
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
                {"error": "PLEASE LOGIN AS REGULAR USER\nTO USE THIS PLUGIN"},
                status=403,
            )
        return view_func(request, *remaining_args, conn=conn, url=url, **kwargs)

    return _wrapped
