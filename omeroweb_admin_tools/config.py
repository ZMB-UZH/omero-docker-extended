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


def _get_required_positive_int_env(name: str) -> int:
    """Return a required positive integer environment variable.

    Inputs: `name`. Output: `int`. Raises on invalid or unavailable state.
    """
    value = get_int_env(name, env_file=ENV_FILE_OMEROWEB)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


@dataclass(frozen=True)
class LogConfig:
    """Configuration values for the Loki log backend."""

    loki_url: str
    lookback_seconds: int
    max_entries: int
    timeout_seconds: float
    cache_max_bytes: int
    internal_file_batch_size: int
    max_parallel_queries: int


def build_log_config() -> LogConfig:
    """And validate the log configuration from environment variables.

    Inputs: none. Output: `LogConfig`. Raises on invalid or unavailable state.
    """
    loki_url = require_env(
        "ADMIN_TOOLS_LOKI_URL",
        env_file=ENV_FILE_OMEROWEB,
        hint="Expected the Loki base URL (e.g., http://loki:3100).",  # DevSkim: ignore DS137138,
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
    cache_max_mb = _get_required_positive_int_env(
        "ADMIN_TOOLS_LOG_CACHE_MAX_MB",
    )
    internal_file_batch_size = _get_required_positive_int_env(
        "ADMIN_TOOLS_LOG_INTERNAL_FILE_BATCH_SIZE",
    )
    max_parallel_queries = _get_required_positive_int_env(
        "ADMIN_TOOLS_LOG_MAX_PARALLEL_QUERIES",
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
        internal_file_batch_size=internal_file_batch_size,
        max_parallel_queries=max_parallel_queries,
    )


def optional_log_config() -> Optional[LogConfig]:
    """Return a LogConfig instance if configuration is valid, otherwise None.

    Inputs: none. Output: `Optional[LogConfig]`.
    """
    try:
        return build_log_config()
    except (RuntimeError, ValueError):
        return None
