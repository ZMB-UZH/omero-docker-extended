"""Backward-compatible OMERO connection helpers.

The canonical import runtime lives in ``omeroweb_import.views.core_functions``.
This facade keeps legacy imports working while routing behavior through the
same implementation surface that production uses.
"""

from ...views import core_functions as _core

JOB_SERVICE_GROUP_ENV = _core.JOB_SERVICE_GROUP_ENV
JOB_SERVICE_GROUP_ENV_FALLBACK = _core.JOB_SERVICE_GROUP_ENV_FALLBACK
JOB_SERVICE_AUTH_ENV = _core.JOB_SERVICE_AUTH_ENV
JOB_SERVICE_AUTH_ENV_FALLBACK = _core.JOB_SERVICE_AUTH_ENV_FALLBACK
JOB_SERVICE_SECURE_ENV = _core.JOB_SERVICE_SECURE_ENV
JOB_SERVICE_SECURE_ENV_FALLBACK = _core.JOB_SERVICE_SECURE_ENV_FALLBACK
JOB_SERVICE_USER_ENV = _core.JOB_SERVICE_USER_ENV
JOB_SERVICE_USER_ENV_FALLBACK = _core.JOB_SERVICE_USER_ENV_FALLBACK
JOB_SERVICE_USERNAME_DEFAULT = _core.JOB_SERVICE_USERNAME_DEFAULT
OMERO_IMPORT_SCAN_DEPTH = _core.OMERO_IMPORT_SCAN_DEPTH
SEM_EDX_FILEANNOTATION_NS = _core.SEM_EDX_FILEANNOTATION_NS

_attach_txt_to_image_service = _core.attach_txt_to_image_service
_batch_find_images_by_name = _core.batch_find_images_by_name
_build_omero_cli_command = _core.build_omero_cli_command
_find_image_by_name = _core.find_image_by_name
_get_import_timeout_seconds = _core.get_import_timeout_seconds
_get_job_service_credentials = _core.get_job_service_credentials
_get_or_create_dataset = _core.get_or_create_dataset
_get_session_key = _core.get_session_key
_open_service_connection = _core.open_service_connection
_open_session_connection = _core.open_session_connection
_parse_cli_id = _core.parse_cli_id
_reconnect_session = _core.reconnect_session
_resolve_omero_host_port = _core.resolve_omero_host_port
_run_omero_cli = _core.run_omero_cli
_validate_session = _core.validate_session


def _import_file(conn, session_key: str, host: str, port: int, path, dataset_id=None):  # pylint: disable=unused-argument
    """Run the CLI import path while preserving legacy patch points."""
    cmd = _build_omero_cli_command(["import"], session_key, host, port)
    cmd.extend(["--depth", str(OMERO_IMPORT_SCAN_DEPTH)])
    if dataset_id:
        cmd.extend(["-d", str(dataset_id)])
    cmd.append(str(path))
    result = _run_omero_cli(cmd, timeout=_get_import_timeout_seconds())
    return result.returncode == 0, result.stdout, result.stderr


__all__ = [
    "JOB_SERVICE_USERNAME_DEFAULT",
    "JOB_SERVICE_USER_ENV",
    "JOB_SERVICE_USER_ENV_FALLBACK",
    "JOB_SERVICE_AUTH_ENV",
    "JOB_SERVICE_AUTH_ENV_FALLBACK",
    "JOB_SERVICE_GROUP_ENV",
    "JOB_SERVICE_GROUP_ENV_FALLBACK",
    "JOB_SERVICE_SECURE_ENV",
    "JOB_SERVICE_SECURE_ENV_FALLBACK",
    "OMERO_IMPORT_SCAN_DEPTH",
    "SEM_EDX_FILEANNOTATION_NS",
    "_resolve_omero_host_port",
    "_get_session_key",
    "_get_or_create_dataset",
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
]
