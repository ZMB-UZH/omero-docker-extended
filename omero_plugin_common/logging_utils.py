"""Logging helpers shared across OMERO web plugins."""

import logging
from typing import Any


_OMERO_GATEWAY_UTILS_LOGGER = "omero.gateway.utils"
_LOGGER_CONFIGURED = False


def sanitize_log_value(value: Any) -> str:
    """Return a single-line representation safe for structured log sinks.

    Replaces carriage return and newline characters to prevent log injection
    (forged extra log lines) when logging untrusted input.
    """
    text = str(value)
    return text.replace("\r", r"\\r").replace("\n", r"\\n")


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
