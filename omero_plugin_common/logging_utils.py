"""Logging helpers shared across OMERO web plugins."""

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_OMERO_GATEWAY_UTILS_LOGGER = "omero.gateway.utils"
_LOGGER_CONFIGURED = False


def sanitize_log_value(value: Any) -> str:
    """Return a single-line representation safe for structured log sinks.

    Replaces carriage return and newline characters to prevent log injection
    (forged extra log lines) when logging untrusted input.
    """
    text = str(value)
    return text.replace("\r", r"\\r").replace("\n", r"\\n")


_SENSITIVE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "key",
    "password",
    "passwd",
    "token",
    "session",
    "session_key",
}


def sanitize_url_for_logging(url: Any) -> str:
    """Return a URL with obvious credentials redacted for logging."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except Exception:
        return sanitize_log_value(raw)

    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    if parsed.username:
        netloc = f"{parsed.username}:***@{hostname}{port}"
    else:
        netloc = f"{hostname}{port}"

    redacted_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS:
            redacted_query.append((key, "***"))
        else:
            redacted_query.append((key, value))

    sanitized = urlunsplit(
        (parsed.scheme, netloc, parsed.path, urlencode(redacted_query), parsed.fragment)
    )
    return sanitize_log_value(sanitized)


def configure_omero_gateway_logging() -> None:
    """Reduce noisy OMERO gateway debug logs in production web logs.

    OMERO's ``setOmeroShare()`` helper emits a debug line on every regular
    non-share request because ``omero.share`` is not present in default
    service options. This is expected behavior, not an error. Raising only this
    logger to ``INFO`` removes repeated noise while preserving warning/error
    signals from the same module.
    """
    global _LOGGER_CONFIGURED

    if _LOGGER_CONFIGURED:
        return

    logging.getLogger(_OMERO_GATEWAY_UTILS_LOGGER).setLevel(logging.INFO)
    _LOGGER_CONFIGURED = True
