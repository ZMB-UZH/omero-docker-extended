from omero_plugin_common.env_utils import (
    ENV_FILE_OMERO_CELERY,
    get_bool_env,
    get_env,
    get_float_env,
    get_int_env,
    require_env,
)


def use_celery() -> bool:
    """Return whether Celery-backed IMS exports are enabled."""
    return get_bool_env("OMERO_IMS_USE_CELERY", env_file=ENV_FILE_OMERO_CELERY)


def use_job_service_session() -> bool:
    """Return whether IMS exports should use the job-service account."""
    return get_bool_env(
        "OMERO_IMS_USE_JOB_SERVICE_SESSION",
        env_file=ENV_FILE_OMERO_CELERY,
    )


def get_job_service_credentials() -> tuple[str | None, str | None]:
    """Return (username, password) for the job-service account.
    
    Prefers OMERO_WEB_JOB_SERVICE_* variables, falls back to OMERO_JOB_SERVICE_*.
    """
    from omero_plugin_common.env_utils import get_optional_env
    
    # Try web-specific first
    username = get_optional_env(
        "OMERO_WEB_JOB_SERVICE_USERNAME",
        env_file=ENV_FILE_OMERO_CELERY,
    )
    password = get_optional_env(
        "OMERO_WEB_JOB_SERVICE_PASS",
        env_file=ENV_FILE_OMERO_CELERY,
    )
    
    # Fall back to server-side env vars
    if not username:
        username = get_optional_env(
            "OMERO_JOB_SERVICE_USERNAME",
            env_file=ENV_FILE_OMERO_CELERY,
        )
    if not password:
        password = get_optional_env(
            "OMERO_JOB_SERVICE_PASS",
            env_file=ENV_FILE_OMERO_CELERY,
        )
    
    return username, password


def get_celery_broker_url() -> str:
    """Return the Celery broker URL for IMS export tasks."""
    return get_env("OMERO_IMS_CELERY_BROKER_URL", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_backend_url() -> str:
    """Return the Celery result backend URL for IMS export tasks."""
    return get_env("OMERO_IMS_CELERY_BACKEND_URL", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_queue() -> str:
    """Return the Celery queue name used for IMS export tasks."""
    return require_env(
        "OMERO_IMS_CELERY_QUEUE",
        env_file=ENV_FILE_OMERO_CELERY,
        docs_url="docs/troubleshooting-imaris.md",
    )


def get_celery_result_expires() -> int:
    """Return Celery result expiry (seconds)."""
    return get_int_env("OMERO_IMS_CELERY_RESULT_EXPIRES", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_time_limit() -> int:
    """Return Celery task time limit (seconds)."""
    return get_int_env("OMERO_IMS_CELERY_TIME_LIMIT", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_max_retries() -> int:
    """Return Celery broker connection retry count."""
    return get_int_env("OMERO_IMS_CELERY_MAX_RETRIES", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_prefetch_multiplier() -> int:
    """Return Celery prefetch multiplier."""
    return get_int_env("OMERO_IMS_CELERY_PREFETCH", env_file=ENV_FILE_OMERO_CELERY)


def get_export_timeout() -> int:
    """Return IMS export timeout (seconds)."""
    return get_int_env("OMERO_IMS_EXPORT_TIMEOUT", env_file=ENV_FILE_OMERO_CELERY)


def get_export_poll_interval() -> float:
    """Return IMS export polling interval (seconds)."""
    return get_float_env("OMERO_IMS_EXPORT_POLL_INTERVAL", env_file=ENV_FILE_OMERO_CELERY)
