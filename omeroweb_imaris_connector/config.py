import os


def _bool_from_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _int_from_env(value: str | None, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer value: {value}") from exc


def _float_from_env(value: str | None, default: float) -> float:
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid float value: {value}") from exc


def _get_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _get_int(name: str, default: int) -> int:
    return _int_from_env(os.environ.get(name), default)


def _get_float(name: str, default: float) -> float:
    return _float_from_env(os.environ.get(name), default)


def _get_bool(name: str, default: bool) -> bool:
    return _bool_from_env(os.environ.get(name), default)


def use_celery() -> bool:
    """Return whether Celery-backed IMS exports are enabled."""
    return _get_bool("OMERO_IMS_USE_CELERY", True)


def use_job_service_session() -> bool:
    """Return whether IMS exports should use the job-service account."""
    return _get_bool("OMERO_IMS_USE_JOB_SERVICE_SESSION", True)


def get_job_service_credentials() -> tuple[str | None, str | None]:
    """Return (username, password) for the job-service account."""
    username = os.environ.get("OMERO_WEB_JOB_SERVICE_USERNAME")
    if not username:
        username = os.environ.get("OMERO_JOB_SERVICE_USERNAME")
    password = os.environ.get("OMERO_WEB_JOB_SERVICE_PASS")
    if not password:
        password = os.environ.get("OMERO_JOB_SERVICE_PASS")
    return username, password


def get_celery_broker_url() -> str:
    """Return the Celery broker URL for IMS export tasks."""
    return _get_env("OMERO_IMS_CELERY_BROKER_URL", "redis://redis:6379/2")


def get_celery_backend_url() -> str:
    """Return the Celery result backend URL for IMS export tasks."""
    return _get_env("OMERO_IMS_CELERY_BACKEND_URL", get_celery_broker_url())


def get_celery_queue() -> str:
    """Return the Celery queue name used for IMS export tasks."""
    return _get_env("OMERO_IMS_CELERY_QUEUE")


def get_celery_result_expires() -> int:
    """Return Celery result expiry (seconds)."""
    return _get_int("OMERO_IMS_CELERY_RESULT_EXPIRES", 7200)


def get_celery_time_limit() -> int:
    """Return Celery task time limit (seconds)."""
    return _get_int("OMERO_IMS_CELERY_TIME_LIMIT", 7200)


def get_celery_max_retries() -> int:
    """Return Celery broker connection retry count."""
    return _get_int("OMERO_IMS_CELERY_MAX_RETRIES", 20)


def get_celery_prefetch_multiplier() -> int:
    """Return Celery prefetch multiplier."""
    return _get_int("OMERO_IMS_CELERY_PREFETCH", 1)


def get_export_timeout() -> int:
    """Return IMS export timeout (seconds)."""
    return _get_int("OMERO_IMS_EXPORT_TIMEOUT", 3600)


def get_export_poll_interval() -> float:
    """Return IMS export polling interval (seconds)."""
    return _get_float("OMERO_IMS_EXPORT_POLL_INTERVAL", 2.0)
