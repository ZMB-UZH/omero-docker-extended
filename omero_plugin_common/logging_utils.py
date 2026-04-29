"""Logging helpers shared across OMERO web plugins."""

import logging
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


_OMERO_GATEWAY_UTILS_LOGGER = "omero.gateway.utils"


def _safe_text(value: Any) -> str:
    """Handle safe text."""
    try:
        return str(value)
    except Exception:
        return f"<unprintable {type(value).__name__}>"


def sanitize_log_value(value: Any) -> str:
    """Return a single-line representation safe for structured log sinks.

    Replaces carriage return and newline characters to prevent log injection
    (forged extra log lines) when logging untrusted input.
    """
    text = _safe_text(value)
    return text.replace("\r", r"\\r").replace("\n", r"\\n")


def summarize_process_output(stdout: Any, stderr: Any) -> str:
    """Return a low-sensitivity summary of command output for logs."""
    stdout_text = _safe_text("" if stdout is None else stdout)
    stderr_text = _safe_text("" if stderr is None else stderr)
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
    "access_token",
    "auth",
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "session",
    "session_key",
}
_REDACTED_VALUE = "REDACTED"


def _quote_userinfo(value: str) -> str:
    """Handle quote userinfo."""
    try:
        return quote(value, safe="")
    except UnicodeError:
        return _REDACTED_VALUE


def _redacted_netloc(parsed) -> str:
    """Handle redacted netloc."""
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        port = ""
    if not parsed.username and parsed.password is None:
        return f"{hostname}{port}"
    username = _quote_userinfo(parsed.username or "")
    return f"{username}:***@{hostname}{port}"


def _redact_query(query: str) -> str:
    """Handle redact query."""
    pairs = [
        (key, _REDACTED_VALUE if key.lower() in _SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(query, keep_blank_values=True)
    ]
    return urlencode(pairs)


def sanitize_url_for_logging(url: Any) -> str:
    """Return a URL with obvious credentials redacted for logging."""
    raw = _safe_text("" if url is None else url).strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        netloc = _redacted_netloc(parsed)
    except Exception:
        return sanitize_log_value(raw)

    sanitized = urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            _redact_query(parsed.query),
            "",
        )
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
    """Handle gateway logging configured."""
    return bool(getattr(configure_omero_gateway_logging, "_configured", False))


def _set_gateway_logging_configured(configured: bool) -> None:
    """Handle set gateway logging configured."""
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
