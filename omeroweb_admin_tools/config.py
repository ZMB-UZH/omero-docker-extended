"""Configuration helpers for admin tools logging."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LogConfig:
    """Configuration values for the Loki log backend."""

    loki_url: str
    lookback_seconds: int
    max_entries: int
    timeout_seconds: float


def _get_int_env(name: str, default: int) -> int:
    """Read an integer environment variable with validation."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _get_float_env(name: str, default: float) -> float:
    """Read a float environment variable with validation."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc


def build_log_config() -> LogConfig:
    """Build and validate the log configuration from environment variables."""
    loki_url = os.environ.get("ADMIN_TOOLS_LOKI_URL")
    if loki_url is None or loki_url.strip() == "":
        raise ValueError(
            "ADMIN_TOOLS_LOKI_URL must be set to the Loki base URL (e.g., http://loki:3100)."
        )

    lookback_seconds = _get_int_env("ADMIN_TOOLS_LOG_LOOKBACK_SECONDS", 900)
    max_entries = _get_int_env("ADMIN_TOOLS_LOG_MAX_ENTRIES", 500)
    timeout_seconds = _get_float_env("ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS", 10.0)

    if lookback_seconds <= 0:
        raise ValueError("ADMIN_TOOLS_LOG_LOOKBACK_SECONDS must be a positive integer.")
    if max_entries <= 0:
        raise ValueError("ADMIN_TOOLS_LOG_MAX_ENTRIES must be a positive integer.")
    if timeout_seconds <= 0:
        raise ValueError("ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS must be positive.")

    return LogConfig(
        loki_url=loki_url.rstrip("/"),
        lookback_seconds=lookback_seconds,
        max_entries=max_entries,
        timeout_seconds=timeout_seconds,
    )


def optional_log_config() -> Optional[LogConfig]:
    """Return a LogConfig instance if configuration is valid, otherwise None."""
    try:
        return build_log_config()
    except ValueError:
        return None
