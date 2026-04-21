"""Logging helpers shared across OMERO web plugins."""

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_OMERO_GATEWAY_UTILS_LOGGER = "omero.gateway.utils"


def sanitize_log_value(value: Any) -> str:
    """Return a single-line representation safe for structured log sinks.

    Replaces carriage return and newline characters to prevent log injection
    (forged extra log lines) when logging untrusted input.
    """
    text = str(value)
    return text.replace("\r", r"\\r").replace("\n", r"\\n")


def summarize_process_output(stdout: Any, stderr: Any) -> str:
    """Return a low-sensitivity summary of command output for logs."""
    stdout_text = str(stdout or "")
    stderr_text = str(stderr or "")
    return (
        f"stdout_lines={len(stdout_text.splitlines())} "
        f"stderr_lines={len(stderr_text.splitlines())} "
        f"stdout_chars={len(stdout_text)} "
        f"stderr_chars={len(stderr_text)}"
    )


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


def sanitized_exc_info(exc: BaseException):
    """Return exc_info with sanitized exception text while preserving traceback."""
    safe_message = sanitize_log_value(exc)
    exc_type = type(exc)
    try:
        sanitized_exc = exc_type(safe_message)
    except Exception:
        sanitized_exc = RuntimeError(
            f"{sanitize_log_value(exc_type.__name__)}: {safe_message}"
        )
    sanitized_exc = sanitized_exc.with_traceback(exc.__traceback__)
    return type(sanitized_exc), sanitized_exc, sanitized_exc.__traceback__


def _gateway_logging_configured() -> bool:
    return bool(getattr(configure_omero_gateway_logging, "_configured", False))


def _set_gateway_logging_configured(configured: bool) -> None:
    setattr(configure_omero_gateway_logging, "_configured", configured)


def configure_omero_gateway_logging() -> None:
    """Reduce noisy OMERO gateway debug logs in production web logs.

    OMERO's ``setOmeroShare()`` helper emits a debug line on every regular
    non-share request because ``omero.share`` is not present in default
    service options. This is expected behavior, not an error. Raising only this
    logger to ``INFO`` removes repeated noise while preserving warning/error
    signals from the same module.
    """
    if _gateway_logging_configured():
        return

    logging.getLogger(_OMERO_GATEWAY_UTILS_LOGGER).setLevel(logging.INFO)
    _set_gateway_logging_configured(True)


_set_gateway_logging_configured(False)
