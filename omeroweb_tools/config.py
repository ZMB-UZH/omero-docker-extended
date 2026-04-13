from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from omero_plugin_common.env_utils import (
    ENV_FILE_OMERO_CELERY,
    ENV_FILE_OMEROWEB,
    get_optional_env,
)


logger = logging.getLogger(__name__)

ENHANCED_SEARCH_BATCH_SIZE_ENV = "TOOLS_ENHANCED_SEARCH_INDEX_BATCH_SIZE"
ENHANCED_SEARCH_MAX_RESULTS_ENV = "TOOLS_ENHANCED_SEARCH_MAX_RESULTS"
ENHANCED_SEARCH_STALE_SECONDS_ENV = "TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS"
ENHANCED_SEARCH_SCHEMA_VERSION_ENV = "TOOLS_ENHANCED_SEARCH_SCHEMA_VERSION"

ENHANCED_SEARCH_USE_CELERY_ENV = "TOOLS_ENHANCED_SEARCH_USE_CELERY"
ENHANCED_SEARCH_CELERY_BROKER_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL"
ENHANCED_SEARCH_CELERY_BACKEND_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_BACKEND_URL"
ENHANCED_SEARCH_CELERY_QUEUE_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_QUEUE"
ENHANCED_SEARCH_CELERY_RESULT_EXPIRES_ENV = (
    "TOOLS_ENHANCED_SEARCH_CELERY_RESULT_EXPIRES"
)
ENHANCED_SEARCH_CELERY_TIME_LIMIT_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_TIME_LIMIT"
ENHANCED_SEARCH_CELERY_LOGLEVEL_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_LOGLEVEL"
ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY_ENV = (
    "TOOLS_ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY"
)
ENHANCED_SEARCH_CELERY_MAX_RETRIES_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_MAX_RETRIES"
ENHANCED_SEARCH_CELERY_PREFETCH_ENV = "TOOLS_ENHANCED_SEARCH_CELERY_PREFETCH"

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_RESULTS = 50
DEFAULT_STALE_SECONDS = 600
DEFAULT_SCHEMA_VERSION = 1
DEFAULT_USE_CELERY = True
DEFAULT_CELERY_QUEUE = "enhanced_search"
DEFAULT_CELERY_RESULT_EXPIRES = 7200
DEFAULT_CELERY_TIME_LIMIT = 7200
DEFAULT_CELERY_LOGLEVEL = "info"
DEFAULT_CELERY_WORKER_CONCURRENCY = 1
DEFAULT_CELERY_MAX_RETRIES = 20
DEFAULT_CELERY_PREFETCH = 1
MAX_BATCH_SIZE = 500
MAX_MAX_RESULTS = 200


@dataclass(frozen=True)
class EnhancedSearchScope:
    scope_type: str
    scope_id: int
    label: str

    @property
    def scope_key(self) -> str:
        return f"{self.scope_type}:{self.scope_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "scope_key": self.scope_key,
            "label": self.label,
        }


@dataclass(frozen=True)
class EnhancedSearchRuntimeConfig:
    batch_size: int
    max_results: int
    sync_stale_seconds: int
    schema_version: int


@dataclass(frozen=True)
class EnhancedSearchCeleryConfig:
    enabled: bool
    broker_url: str
    backend_url: str
    queue: str
    result_expires: int
    time_limit: int
    loglevel: str
    worker_concurrency: int
    max_retries: int
    prefetch_multiplier: int


def _bounded_int(
    raw_value: str | None, default: int, minimum: int, maximum: int
) -> int:
    if raw_value is None or str(raw_value).strip() == "":
        return default
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        logger.warning(
            "Invalid integer value %r for enhanced-search config; using %d.",
            raw_value,
            default,
        )
        return default
    return max(minimum, min(maximum, parsed))


def _optional_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None or str(raw_value).strip() == "":
        return default
    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "Invalid boolean value %r for enhanced-search config; using %s.",
        raw_value,
        default,
    )
    return default


def build_enhanced_search_config() -> EnhancedSearchRuntimeConfig:
    return EnhancedSearchRuntimeConfig(
        batch_size=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_BATCH_SIZE_ENV,
                env_file=ENV_FILE_OMEROWEB,
            ),
            DEFAULT_BATCH_SIZE,
            1,
            MAX_BATCH_SIZE,
        ),
        max_results=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_MAX_RESULTS_ENV,
                env_file=ENV_FILE_OMEROWEB,
            ),
            DEFAULT_MAX_RESULTS,
            1,
            MAX_MAX_RESULTS,
        ),
        sync_stale_seconds=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_STALE_SECONDS_ENV,
                env_file=ENV_FILE_OMEROWEB,
            ),
            DEFAULT_STALE_SECONDS,
            60,
            86400,
        ),
        schema_version=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_SCHEMA_VERSION_ENV,
                env_file=ENV_FILE_OMEROWEB,
            ),
            DEFAULT_SCHEMA_VERSION,
            1,
            1000,
        ),
    )


def build_enhanced_search_celery_config() -> EnhancedSearchCeleryConfig:
    return EnhancedSearchCeleryConfig(
        enabled=_optional_bool(
            get_optional_env(
                ENHANCED_SEARCH_USE_CELERY_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            ),
            DEFAULT_USE_CELERY,
        ),
        broker_url=str(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_BROKER_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            )
            or "redis://redis:6379/3"
        ).strip(),
        backend_url=str(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_BACKEND_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            )
            or "redis://redis:6379/3"
        ).strip(),
        queue=str(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_QUEUE_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            )
            or DEFAULT_CELERY_QUEUE
        ).strip(),
        result_expires=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_RESULT_EXPIRES_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            ),
            DEFAULT_CELERY_RESULT_EXPIRES,
            60,
            604800,
        ),
        time_limit=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_TIME_LIMIT_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            ),
            DEFAULT_CELERY_TIME_LIMIT,
            60,
            604800,
        ),
        loglevel=str(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_LOGLEVEL_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            )
            or DEFAULT_CELERY_LOGLEVEL
        ).strip()
        or DEFAULT_CELERY_LOGLEVEL,
        worker_concurrency=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            ),
            DEFAULT_CELERY_WORKER_CONCURRENCY,
            1,
            64,
        ),
        max_retries=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_MAX_RETRIES_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            ),
            DEFAULT_CELERY_MAX_RETRIES,
            1,
            1000,
        ),
        prefetch_multiplier=_bounded_int(
            get_optional_env(
                ENHANCED_SEARCH_CELERY_PREFETCH_ENV,
                env_file=ENV_FILE_OMERO_CELERY,
            ),
            DEFAULT_CELERY_PREFETCH,
            1,
            128,
        ),
    )
