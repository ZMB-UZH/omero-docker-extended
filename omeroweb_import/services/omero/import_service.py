"""Backward-compatible import-service helpers.

The canonical import workflow lives in ``omeroweb_import.views.core_functions``.
This facade preserves legacy imports and patch points while keeping behavior
aligned with the production path.
"""

from ...views import core_functions as _core

BlitzGateway = _core.BlitzGateway
IMPORT_TIMEOUT_SECONDS = _core.IMPORT_TIMEOUT_SECONDS_DEFAULT
INT_SANITIZER = _core.INT_SANITIZER
JOB_ID_SANITIZER = _core.JOB_ID_SANITIZER
JOB_SERVICE_GROUP_ENV = _core.JOB_SERVICE_GROUP_ENV
JOB_SERVICE_GROUP_ENV_FALLBACK = _core.JOB_SERVICE_GROUP_ENV_FALLBACK
JOB_SERVICE_AUTH_ENV = _core.JOB_SERVICE_AUTH_ENV
JOB_SERVICE_AUTH_ENV_FALLBACK = _core.JOB_SERVICE_AUTH_ENV_FALLBACK
JOB_SERVICE_SECURE_ENV = _core.JOB_SERVICE_SECURE_ENV
JOB_SERVICE_SECURE_ENV_FALLBACK = _core.JOB_SERVICE_SECURE_ENV_FALLBACK
JOB_SERVICE_USER_ENV = _core.JOB_SERVICE_USER_ENV
JOB_SERVICE_USER_ENV_FALLBACK = _core.JOB_SERVICE_USER_ENV_FALLBACK
JOB_SERVICE_USERNAME_DEFAULT = _core.JOB_SERVICE_USERNAME_DEFAULT
JobServiceCredentials = _core.JobServiceCredentials
MAX_IMPORT_LOG_LINES = _core.MAX_IMPORT_LOG_LINES
OMERO_IMPORT_SCAN_DEPTH = _core.OMERO_IMPORT_SCAN_DEPTH
logger = _core.logger
sanitize_log_value = _core.sanitize_log_value

_append_job_error = _core.append_job_error
_append_job_message = _core.append_job_message
_append_txt_attachment_message = _core.append_txt_attachment_message
_apply_upload_updates = _core.apply_upload_updates
_attach_txt_to_image_service = _core.attach_txt_to_image_service
_batch_find_images_by_name = _core.batch_find_images_by_name
_build_omero_cli_command = _core.build_omero_cli_command
_check_import_compatibility = _core.check_import_compatibility
_classify_compatibility_output = _core.classify_compatibility_output
_extract_import_candidates = _core.extract_import_candidates
_find_image_by_name = _core.find_image_by_name
_get_env_int = _core.get_env_int
_get_import_lock = _core.get_import_lock
_get_import_timeout_seconds = _core.get_import_timeout_seconds
_get_job_service_credentials = _core.get_job_service_credentials
_get_jobs_root = _core.get_jobs_root
_normalize_job_service_credentials = _core.normalize_job_service_credentials
_get_upload_root = _core.get_upload_root
_has_import_candidates_in_output = _core.has_import_candidates_in_output
_open_session_connection = _core.open_session_connection
_parse_candidate_path_line = _core.parse_candidate_path_line
_parse_cli_id = _core.parse_cli_id
_reconnect_session = _core.reconnect_session
_run_compatibility_check = _core.run_compatibility_check
_run_omero_cli = _core.run_omero_cli
_safe_job_id = _core.safe_job_id
_start_compatibility_check_thread = _core.start_compatibility_check_thread
_update_job = _core.update_job
_validate_session = _core.validate_session
_verify_import = _core.verify_import


def _import_file(
    conn,
    session_key: str,
    host: str,
    port: int,
    path,
    dataset_id=None,
    import_name=None,
    progress_job=None,
):  # pylint: disable=unused-argument
    """Run the CLI import path while preserving legacy patch points."""
    cmd = _build_omero_cli_command(["import"], session_key, host, port)
    cmd.extend(["--depth", str(OMERO_IMPORT_SCAN_DEPTH)])
    if dataset_id:
        cmd.extend(["-d", str(dataset_id)])
    if import_name:
        cmd.extend(["-n", str(import_name)])
    cmd.append(str(path))
    result = _run_omero_cli(cmd, timeout=_get_import_timeout_seconds())
    return result.returncode == 0, result.stdout, result.stderr


def _connection_has_last_error(conn) -> bool:
    """Handle connection has last error."""
    try:
        return bool(conn.getLastError())
    except Exception:
        return False


def _open_service_connection(host: str, port: int, group_id=None):
    """Login as the async service user without leaking credentials in logs."""
    credentials = _normalize_job_service_credentials(_get_job_service_credentials())

    if not credentials.password:
        logger.error(
            "job-service authentication missing. Set %s in the omeroweb container environment.",
            JOB_SERVICE_AUTH_ENV,
        )
        return None

    conn = BlitzGateway(
        credentials.user,
        credentials.password,
        host=host,
        port=int(port),
        secure=credentials.secure,
    )

    try:
        try:
            ok = conn.connect()
        except Exception as exc:
            logger.error(
                "job-service connect() raised: host=%s port=%s tls=%s "
                "error_type=%s has_last_error=%s",
                sanitize_log_value(host),
                port,
                "enabled" if credentials.secure else "disabled",
                sanitize_log_value(type(exc).__name__),
                _connection_has_last_error(conn),
            )
            try:
                conn.close()
            except Exception as close_exc:
                logger.debug(
                    "Suppressed non-fatal exception in import_service.py",
                    exc_info=close_exc,
                )
            return None

        if not ok:
            logger.error(
                "job-service connect() failed: host=%s port=%s tls=%s has_last_error=%s",
                sanitize_log_value(host),
                port,
                "enabled" if credentials.secure else "disabled",
                _connection_has_last_error(conn),
            )
            try:
                conn.close()
            except Exception as close_exc:
                logger.debug(
                    "Suppressed non-fatal exception in import_service.py",
                    exc_info=close_exc,
                )
            return None

        effective_group = None
        if credentials.group_override:
            try:
                effective_group = int(credentials.group_override)
            except Exception:
                logger.warning(
                    "Ignoring invalid %s override; falling back to the job group context.",
                    JOB_SERVICE_GROUP_ENV,
                )
        if effective_group is None and group_id is not None:
            effective_group = int(group_id)

        if effective_group is not None:
            try:
                conn.SERVICE_OPTS.setOmeroGroup(str(effective_group))
            except Exception as exc:
                logger.warning(
                    "Failed to set job-service group context to %s: %s",
                    effective_group,
                    exc,
                )

        return conn

    except Exception:
        try:
            conn.close()
        except Exception as close_exc:
            logger.debug(
                "Suppressed non-fatal exception in import_service.py",
                exc_info=close_exc,
            )
        raise


__all__ = [
    "MAX_IMPORT_LOG_LINES",
    "IMPORT_TIMEOUT_SECONDS",
    "OMERO_IMPORT_SCAN_DEPTH",
    "INT_SANITIZER",
    "JOB_ID_SANITIZER",
    "JobServiceCredentials",
    "JOB_SERVICE_USERNAME_DEFAULT",
    "JOB_SERVICE_USER_ENV",
    "JOB_SERVICE_USER_ENV_FALLBACK",
    "JOB_SERVICE_AUTH_ENV",
    "JOB_SERVICE_AUTH_ENV_FALLBACK",
    "JOB_SERVICE_GROUP_ENV",
    "JOB_SERVICE_GROUP_ENV_FALLBACK",
    "JOB_SERVICE_SECURE_ENV",
    "JOB_SERVICE_SECURE_ENV_FALLBACK",
    "_get_env_int",
    "_get_upload_root",
    "_get_jobs_root",
    "_normalize_job_service_credentials",
    "_build_omero_cli_command",
    "_run_omero_cli",
    "_parse_cli_id",
    "_import_file",
    "_validate_session",
    "_reconnect_session",
    "_open_session_connection",
    "_find_image_by_name",
    "_batch_find_images_by_name",
    "_get_job_service_credentials",
    "_open_service_connection",
    "_attach_txt_to_image_service",
    "_append_job_message",
    "_append_job_error",
    "_append_txt_attachment_message",
    "_verify_import",
    "_connection_has_last_error",
    "_get_import_lock",
    "_safe_job_id",
    "_apply_upload_updates",
    "_update_job",
    "_classify_compatibility_output",
    "_has_import_candidates_in_output",
    "_extract_import_candidates",
    "_parse_candidate_path_line",
    "_check_import_compatibility",
    "_run_compatibility_check",
    "_start_compatibility_check_thread",
]
