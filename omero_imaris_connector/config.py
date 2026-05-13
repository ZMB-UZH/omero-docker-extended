from pathlib import Path

from omero_plugin_common.env_utils import (
    ENV_FILE_OMERO_CELERY,
    get_bool_env,
    get_env,
    get_float_env,
    get_int_env,
    require_env,
)
from omero_plugin_common.tmp_utils import get_plugin_tmp_dir

IMARIS_CONNECTOR_TMP_NAMESPACE = "omero-imaris-connector"


def use_celery() -> bool:
    """Return whether Celery-backed IMS exports are enabled.

    Inputs: none. Output: `bool`.
    """
    return get_bool_env("OMERO_IMS_USE_CELERY", env_file=ENV_FILE_OMERO_CELERY)


def use_job_service_session() -> bool:
    """Return whether IMS exports should use the job-service account.

    Inputs: none. Output: `bool`.
    """
    return get_bool_env(
        "OMERO_IMS_USE_JOB_SERVICE_SESSION",
        env_file=ENV_FILE_OMERO_CELERY,
    )


def get_job_service_credentials() -> tuple[str | None, str | None]:
    """Return (username, password) for the job-service account.

    Inputs: none. Output: `tuple[str | None, str | None]`.

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
    """Return the Celery broker URL for IMS export tasks.

    Inputs: none. Output: `str`.
    """
    return get_env("OMERO_IMS_CELERY_BROKER_URL", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_backend_url() -> str:
    """Return the Celery result backend URL for IMS export tasks.

    Inputs: none. Output: `str`.
    """
    return get_env("OMERO_IMS_CELERY_BACKEND_URL", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_queue() -> str:
    """Return the Celery queue name used for IMS export tasks.

    Inputs: none. Output: `str`.
    """
    return require_env(
        "OMERO_IMS_CELERY_QUEUE",
        env_file=ENV_FILE_OMERO_CELERY,
        docs_url="docs/troubleshooting-imaris.md",
    )


def get_celery_result_expires() -> int:
    """Return Celery result expiry (seconds).

    Inputs: none. Output: `int`.
    """
    return get_int_env(
        "OMERO_IMS_CELERY_RESULT_EXPIRES", env_file=ENV_FILE_OMERO_CELERY
    )


def get_celery_time_limit() -> int:
    """Return Celery task time limit (seconds).

    Inputs: none. Output: `int`.
    """
    return get_int_env("OMERO_IMS_CELERY_TIME_LIMIT", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_max_retries() -> int:
    """Return the celery broker connection retry count value exposed by this OMERO-compatible
    object.

    Inputs: none. Output: `int`.
    """
    return get_int_env("OMERO_IMS_CELERY_MAX_RETRIES", env_file=ENV_FILE_OMERO_CELERY)


def get_celery_prefetch_multiplier() -> int:
    """Return the celery prefetch multiplier value exposed by this OMERO-compatible object.

    Inputs: none. Output: `int`.
    """
    return get_int_env("OMERO_IMS_CELERY_PREFETCH", env_file=ENV_FILE_OMERO_CELERY)


def get_export_timeout() -> int:
    """Return IMS export timeout (seconds).

    Inputs: none. Output: `int`.
    """
    return get_int_env("OMERO_IMS_EXPORT_TIMEOUT", env_file=ENV_FILE_OMERO_CELERY)


def get_export_poll_interval() -> float:
    """Return IMS export polling interval (seconds).

    Inputs: none. Output: `float`.
    """
    return get_float_env(
        "OMERO_IMS_EXPORT_POLL_INTERVAL", env_file=ENV_FILE_OMERO_CELERY
    )


def get_connector_tmp_dir(subdir: str | None = None, *, create: bool = False) -> Path:
    """Return the connector-owned temporary directory.

    Inputs: optional `subdir` and `create`. Output: `Path`.
    """
    return get_plugin_tmp_dir(
        subdir,
        create=create,
        plugin=IMARIS_CONNECTOR_TMP_NAMESPACE,
    )


def get_ome_tiff_staging_root(*, create: bool = False) -> Path:
    """Return the connector-owned OME-TIFF staging root.

    Inputs: optional `create`. Output: `Path`.
    """
    return get_connector_tmp_dir("ome-tiff-source", create=create)
