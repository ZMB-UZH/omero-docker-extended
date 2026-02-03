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


def use_job_service_session() -> bool:
    """Return whether IMS exports should use the job-service account."""
    return _bool_from_env(
        os.environ.get("OMERO_IMS_USE_JOB_SERVICE_SESSION"),
        True,
    )


def get_job_service_credentials() -> tuple[str | None, str | None]:
    """Return (username, password) for the job-service account."""
    username = os.environ.get("OMERO_WEB_JOB_SERVICE_USERNAME")
    if not username:
        username = os.environ.get("OMERO_JOB_SERVICE_USERNAME")
    password = os.environ.get("OMERO_WEB_JOB_SERVICE_PASS")
    if not password:
        password = os.environ.get("OMERO_JOB_SERVICE_PASS")
    return username, password
