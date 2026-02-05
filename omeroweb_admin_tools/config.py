"""Configuration helpers for admin tools logging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from omero_plugin_common.env_utils import (
    ENV_FILE_OMEROWEB,
    get_float_env,
    get_int_env,
    require_env,
)

@dataclass(frozen=True)
class LogConfig:
    """Configuration values for the Loki log backend."""

    loki_url: str
    lookback_seconds: int
    max_entries: int
    timeout_seconds: float


def build_log_config() -> LogConfig:
    """Build and validate the log configuration from environment variables."""
    loki_url = require_env(
        "ADMIN_TOOLS_LOKI_URL",
        env_file=ENV_FILE_OMEROWEB,
        hint="Expected the Loki base URL (e.g., http://loki:3100).",
    )

    lookback_seconds = get_int_env(
        "ADMIN_TOOLS_LOG_LOOKBACK_SECONDS",
        env_file=ENV_FILE_OMEROWEB,
    )
    max_entries = get_int_env(
        "ADMIN_TOOLS_LOG_MAX_ENTRIES",
        env_file=ENV_FILE_OMEROWEB,
    )
    timeout_seconds = get_float_env(
        "ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS",
        env_file=ENV_FILE_OMEROWEB,
    )

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
