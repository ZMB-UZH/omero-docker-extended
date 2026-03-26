"""Configuration helpers for admin tools logging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from omero_plugin_common.env_utils import (
    ENV_FILE_OMEROWEB,
    get_float_env,
    get_int_env,
    get_optional_env,
    require_env,
)

_DEFAULT_LOG_CACHE_MAX_MB = 512


def _get_optional_positive_int_env(name: str, default: int) -> int:
    """Return an optional positive integer environment variable."""
    raw = get_optional_env(name, env_file=ENV_FILE_OMEROWEB)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer when set.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer when set.")
    return value


@dataclass(frozen=True)
class LogConfig:
    """Configuration values for the Loki log backend."""

    loki_url: str
    lookback_seconds: int
    max_entries: int
    timeout_seconds: float
    cache_max_bytes: int


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
    cache_max_mb = _get_optional_positive_int_env(
        "ADMIN_TOOLS_LOG_CACHE_MAX_MB",
        _DEFAULT_LOG_CACHE_MAX_MB,
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
        cache_max_bytes=cache_max_mb * 1024 * 1024,
    )


def optional_log_config() -> Optional[LogConfig]:
    """Return a LogConfig instance if configuration is valid, otherwise None."""
    try:
        return build_log_config()
    except ValueError:
        return None
