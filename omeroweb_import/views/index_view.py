"""Import plugin views."""

import hashlib
import json
import time
import uuid
from pathlib import PurePosixPath
from typing import Any

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from omeroweb.decorators import login_required

from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from ..strings import errors, messages
from .core_functions import (
    DEFAULT_UPLOAD_BATCH_FILES,
    DEFAULT_UPLOAD_CONCURRENCY,
    MAX_UPLOAD_BATCH_BYTES,
    MAX_UPLOAD_BATCH_GB,
    UPLOAD_BATCH_FILES_ENV,
    UPLOAD_CONCURRENCY_ENV,
    _apply_upload_updates,
    _append_upload_chunks_to_staged_path,
    _build_staged_relative_path,
    _collect_project_payload,
    _compatibility_pending_entries,
    _current_user_id,
    _dataset_name_for_path,
    _ensure_dir,
    _get_env_int,
    _get_jobs_root,
    _get_text,
    _get_upload_root,
    _generate_orphan_dataset_name,
    _has_read_write_permissions,
    _is_managed_upload_internal_error,
    _is_owned_by_user,
    _load_job,
    _managed_upload_error_message,
    _normalize_job_batch_size,
    _normalize_dataset_name_override,
    _normalize_ngff_converter_settings,
    _normalize_sem_edx_associations,
    _normalize_sem_edx_settings,
    _normalize_upload_relative_path,
    _prepare_uploaded_job_for_request_path_import,
    _public_import_job_text_list,
    _refresh_job_status,
    _resolve_omero_host_port,
    _resolve_staged_target_path,
    _replace_staged_upload_file,
    _reset_staged_upload_file,
    _safe_job_id,
    _safe_relative_path,
    _save_job,
    _staged_upload_chunk_matches,
    _staged_upload_size,
    _should_auto_skip_import,
    _special_methods_enabled,
    _start_import_thread,
    _update_job,
    _validated_job_id,
    _validate_staged_target_path,
    logger,
)
from .utils import current_username, json_error, load_json_body, require_non_root_user


@login_required()
@ensure_csrf_cookie
def index(request, conn=None, _url=None, **kwargs):
    """Return the index.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: rendered Django response.
    """
    user_id = _current_user_id(conn)
    upload_root = _get_upload_root()
    upload_enabled = _ensure_dir(upload_root)
    job_dir_ok = _ensure_dir(_get_jobs_root())
    upload_concurrency = _get_env_int(
        UPLOAD_CONCURRENCY_ENV, DEFAULT_UPLOAD_CONCURRENCY, 1, 10
    )
    upload_batch_files = _get_env_int(
        UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10
    )
    projects = _collect_project_payload(conn, user_id)
    special_methods_enabled = _special_methods_enabled()
    return render(
        request,
        "omeroweb_import/index.html",
        {
            "upload_root": str(upload_root),
            "upload_enabled": upload_enabled and job_dir_ok,
            "upload_start_url": reverse("omeroweb_import_start"),
            "upload_concurrency": upload_concurrency,
            "upload_batch_files": upload_batch_files,
            "special_methods_enabled": special_methods_enabled,
            "user_id": user_id,
            "messages_json": json.dumps(messages.index_messages()),
            "projects": projects,
            "project_list_url": reverse("omeroweb_import_projects"),
        },
    )


@login_required()
@require_non_root_user
def list_projects(request, conn=None, _url=None, **kwargs):
    """Return list projects.

    Inputs: `request`, `conn`, `_url`, `**kwargs`. Output: `JsonResponse` result.
    """
    user_id = _current_user_id(conn)
    payload = _collect_project_payload(conn, user_id)
    return JsonResponse(payload, safe=False)


@login_required()
def root_status(request, conn=None, _url=None, **kwargs):
    """Return the root status.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})


@login_required()
@require_non_root_user
def start_upload(request, conn=None, _url=None, **kwargs):
    """Start the upload.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: `_start_upload` result.
    """
    try:
        return _start_upload(request, conn)
    except Exception as exc:
        logger.error(
            "Unhandled error while starting upload job.",
            exc_info=sanitized_exc_info(exc),
        )
        return json_error(errors.unexpected_server_error_start_upload(), status=500)


def _upload_start_payload(request):
    """Return a dictionary payload for upload-start requests.

    Inputs: `request` Django request. Output: payload mapping.
    """
    payload = load_json_body(request)
    return payload if isinstance(payload, dict) else {}


def _upload_start_roots_response():
    """Upload the start roots response.

    Inputs: none. Output: `tuple`.
    """
    upload_root = _get_upload_root()
    if _ensure_dir(upload_root) and _ensure_dir(_get_jobs_root()):
        return upload_root, None
    logger.warning("Upload folder not writable or job dir missing.")
    return None, json_error(errors.upload_folder_not_writable())


def _upload_start_identity(payload):
    """Upload the start identity.

    Inputs: `payload` payload. Output: `tuple`.
    """
    client_upload_id, client_upload_id_error = _normalize_client_upload_id(
        payload.get("client_upload_id")
    )
    if client_upload_id_error:
        return None, None, json_error(client_upload_id_error, status=400)

    dataset_name_override, dataset_name_override_error = (
        _normalize_dataset_name_override(payload.get("dataset_name_override"))
    )
    if dataset_name_override_error:
        return None, None, json_error(dataset_name_override_error, status=400)

    return client_upload_id, dataset_name_override, None


def _upload_start_files_payload(payload):
    """Return the upload-start file list or a validation response.

    Inputs: `payload`. Output: tuple.
    """
    files = payload.get("files") or []
    if not isinstance(files, list):
        files = []
    if files:
        return files, None
    logger.info("Upload start request missing files payload.")
    return None, json_error(errors.no_files_provided())


def _upload_start_options(payload):
    """Upload the start options.

    Inputs: `payload` payload. Output: `tuple`.
    """
    special_upload = (payload.get("special_upload") or "").strip()
    compatibility_enabled = payload.get("compatibility_enabled")
    if compatibility_enabled is None:
        compatibility_enabled = True
    else:
        compatibility_enabled = bool(compatibility_enabled)

    raw_sem_edx_associations = payload.get("sem_edx_associations") or {}
    raw_sem_edx_settings = payload.get("sem_edx_settings") or {}
    raw_ngff_converter_settings = payload.get("ngff_converter_settings") or {}

    if not _special_methods_enabled():
        return "", compatibility_enabled, {}, {}, {}
    if special_upload != "sem_edx_spectra":
        raw_sem_edx_associations = {}
        raw_sem_edx_settings = {}
    if special_upload != "ngff_converter":
        raw_ngff_converter_settings = {}
    return (
        special_upload,
        compatibility_enabled,
        raw_sem_edx_associations,
        raw_sem_edx_settings,
        raw_ngff_converter_settings,
    )


def _upload_start_batch_size(payload):
    """Return the normalized upload-start job batch size.

    Inputs: `payload` payload. Output: `_normalize_job_batch_size` result.
    """
    default_batch_size = _get_env_int(
        UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10
    )
    return _normalize_job_batch_size(payload.get("batch_size"), default_batch_size)


def _upload_path_conflict(rel_path, seen_relative_paths, seen_parent_paths):
    """Return a path hierarchy conflict message for an upload path, if any.

    Inputs: `rel_path`, `seen_relative_paths`, `seen_parent_paths`. Output: computed
    value or None.
    """
    if rel_path in seen_relative_paths:
        return f"Duplicate file path: {rel_path}"
    if rel_path in seen_parent_paths:
        return f"Conflicting file path hierarchy: {rel_path}"

    rel_parts = PurePosixPath(rel_path).parts
    for depth in range(1, len(rel_parts)):
        ancestor = PurePosixPath(*rel_parts[:depth]).as_posix()
        if ancestor in seen_relative_paths:
            return f"Conflicting file path hierarchy: {ancestor} <-> {rel_path}"
    return None


def _upload_start_file_path(entry, seen_relative_paths, seen_parent_paths):
    """Upload the start file path.

    Inputs: `entry`, `seen_relative_paths`, `seen_parent_paths`. Output: `tuple`.
    """
    raw_name = entry.get("relative_path") or entry.get("name")
    rel_path, rel_error = _normalize_upload_relative_path(raw_name or "")
    if rel_error:
        return None, rel_error

    conflict_error = _upload_path_conflict(
        rel_path,
        seen_relative_paths,
        seen_parent_paths,
    )
    if conflict_error:
        return None, conflict_error

    seen_relative_paths.add(rel_path)
    rel_parts = PurePosixPath(rel_path).parts
    for depth in range(1, len(rel_parts)):
        seen_parent_paths.add(PurePosixPath(*rel_parts[:depth]).as_posix())
    return rel_path, None


def _upload_start_file_size(raw_size):
    """Upload the start file size.

    Inputs: `raw_size`. Output: `int` size. Raises: ValueError when validation or
    external operations fail.
    """
    try:
        if raw_size is None:
            raise ValueError
        size = int(raw_size)
    except (TypeError, ValueError):
        size = 0
    return max(size, 0)


def _upload_start_file_flags(entry, rel_path, special_upload):
    """Return compatibility/import skip flags for one upload-start file.

    Inputs: `entry`, `rel_path`, `special_upload`. Output: tuple.
    """
    compatibility_skip = bool(entry.get("compatibility_skip"))
    import_skip = bool(entry.get("import_skip"))
    filename = PurePosixPath(rel_path).name

    # SEM-EDX TXT files are metadata and must not be imported as images.
    if special_upload == "sem_edx_spectra" and filename.lower().endswith(".txt"):
        import_skip = True
        compatibility_skip = True
    if _should_auto_skip_import(rel_path):
        import_skip = True
        compatibility_skip = True
    return compatibility_skip, import_skip


def _normalize_upload_start_file(
    entry,
    upload_root,
    special_upload,
    seen_relative_paths,
    seen_parent_paths,
):
    """Normalize the upload start file.

    Inputs: `entry`, `upload_root`, `special_upload`, `seen_relative_paths`,
    `seen_parent_paths`. Output: `tuple`.
    """
    if not isinstance(entry, dict):
        return None, str(entry)

    rel_path, rel_error = _upload_start_file_path(
        entry,
        seen_relative_paths,
        seen_parent_paths,
    )
    if rel_error:
        return None, rel_error

    staged_path = _build_staged_relative_path(rel_path)
    staged_error = _validate_staged_target_path(upload_root / ("0" * 32), staged_path)
    if staged_error:
        return None, staged_error

    compatibility_skip, import_skip = _upload_start_file_flags(
        entry,
        rel_path,
        special_upload,
    )
    return (
        {
            "upload_id": uuid.uuid4().hex,
            "relative_path": rel_path,
            "staged_path": staged_path,
            "size": _upload_start_file_size(entry.get("size")),
            "status": "pending",
            "errors": [],
            "compatibility_skip": compatibility_skip,
            "import_skip": import_skip,
        },
        None,
    )


def _normalize_upload_start_files(request, conn, upload_root, files, special_upload):
    """Normalize the upload start files.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `upload_root`,
    `files`, `special_upload`. Output: `tuple`.
    """
    normalized = []
    total_bytes = 0
    invalid = []
    seen_relative_paths: set[str] = set()
    seen_parent_paths: set[str] = set()

    for entry in files:
        normalized_entry, entry_error = _normalize_upload_start_file(
            entry,
            upload_root,
            special_upload,
            seen_relative_paths,
            seen_parent_paths,
        )
        if entry_error:
            invalid.append(entry_error)
            continue

        total_bytes += normalized_entry["size"]
        if total_bytes > MAX_UPLOAD_BATCH_BYTES:
            logger.info(
                "Upload start rejected batch exceeding %d GB for user %s.",
                MAX_UPLOAD_BATCH_GB,
                sanitize_log_value(current_username(request, conn)),
            )
            return (
                None,
                0,
                json_error(errors.upload_batch_too_large(MAX_UPLOAD_BATCH_GB)),
            )
        normalized.append(normalized_entry)

    if invalid:
        logger.info(
            "Upload start rejected invalid paths: %s", sanitize_log_value(invalid)
        )
        return None, 0, json_error(errors.invalid_file_paths(invalid))
    return normalized, total_bytes, None


def _upload_start_special_settings(
    special_upload,
    raw_sem_edx_associations,
    raw_sem_edx_settings,
    raw_ngff_converter_settings,
    normalized_files,
):
    """Upload the start special settings.

    Inputs: `special_upload`, `raw_sem_edx_associations`, `raw_sem_edx_settings`,
    `raw_ngff_converter_settings`, `normalized_files`. Output: `tuple`.
    """
    sem_edx_associations = _normalize_sem_edx_associations(
        raw_sem_edx_associations, normalized_files
    )
    sem_edx_settings = (
        _normalize_sem_edx_settings(raw_sem_edx_settings)
        if special_upload == "sem_edx_spectra"
        else {}
    )
    ngff_converter_settings = (
        _normalize_ngff_converter_settings(raw_ngff_converter_settings)
        if special_upload == "ngff_converter"
        else {}
    )
    return sem_edx_associations, sem_edx_settings, ngff_converter_settings


def _upload_start_orphan_dataset_name(dataset_name_override, normalized_files):
    """Return a generated orphan dataset name when upload paths need one.

    Inputs: `dataset_name_override`, `normalized_files`. Output: name string.
    """
    if dataset_name_override:
        return None
    needs_orphan_dataset = any(
        _dataset_name_for_path(entry["relative_path"]) is None
        for entry in normalized_files
    )
    return _generate_orphan_dataset_name() if needs_orphan_dataset else None


def _upload_start_group_name(conn, current_group_id):
    """Upload the start group name.

    Inputs: `conn` OMERO gateway connection, `current_group_id`. Output: `bool`.
    """
    try:
        group_obj = conn.getObject("ExperimenterGroup", int(current_group_id))
    except Exception:
        group_obj = None
    if group_obj is None:
        return None
    return _get_text(group_obj.getName()) or None


def _upload_start_group_context(conn, username):
    """Return the active OMERO group context for a new upload job.

    Inputs: `conn`, `username`. Output: tuple.
    """
    current_group_id = None
    current_group_name = None
    try:
        event_context = conn.getEventContext()
        current_group_id = event_context.groupId
        current_group_name = getattr(event_context, "groupName", None)
        if current_group_name:
            current_group_name = str(current_group_name).strip() or None
        if not current_group_name and current_group_id is not None:
            current_group_name = _upload_start_group_name(conn, current_group_id)
        logger.debug(
            "Captured user's group context for upload start: group_id=%s group_name=%s user=%s",
            current_group_id,
            sanitize_log_value(current_group_name),
            sanitize_log_value(username),
        )
    except Exception as exc:
        logger.warning(
            "Unable to get user's group context: %s", sanitize_log_value(exc)
        )
    return current_group_id, current_group_name


def _start_upload(request, conn):
    """Start the upload.

    Inputs: `request` Django request, `conn` OMERO gateway connection. Output: Django
    `JsonResponse`.
    """
    if request.method != "POST":
        return json_error(errors.upload_start_post_required())

    upload_root, roots_error = _upload_start_roots_response()
    if roots_error is not None:
        return roots_error

    payload = _upload_start_payload(request)
    client_upload_id, dataset_name_override, identity_error = _upload_start_identity(
        payload
    )
    if identity_error is not None:
        return identity_error

    project_id, project_name, project_error = _resolve_upload_project(
        conn, payload.get("project_id")
    )
    if project_error is not None:
        return project_error

    files, files_error = _upload_start_files_payload(payload)
    if files_error is not None:
        return files_error
    (
        special_upload,
        compatibility_enabled,
        raw_sem_edx_associations,
        raw_sem_edx_settings,
        raw_ngff_converter_settings,
    ) = _upload_start_options(payload)
    batch_size = _upload_start_batch_size(payload)

    normalized, total_bytes, normalize_error = _normalize_upload_start_files(
        request,
        conn,
        upload_root,
        files,
        special_upload,
    )
    if normalize_error is not None:
        return normalize_error

    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        logger.warning("Unable to resolve OMERO host/port for upload start.")
        return json_error(errors.unable_resolve_host_port())

    sem_edx_associations, sem_edx_settings, ngff_converter_settings = (
        _upload_start_special_settings(
            special_upload,
            raw_sem_edx_associations,
            raw_sem_edx_settings,
            raw_ngff_converter_settings,
            normalized,
        )
    )
    username = current_username(request, conn)
    retry_response = _client_upload_retry_response(
        username,
        client_upload_id,
        normalized,
        dataset_name_override,
        project_id,
    )
    if retry_response is not None:
        return retry_response

    dataset_map: dict[str, str] = {}
    orphan_dataset_name = _upload_start_orphan_dataset_name(
        dataset_name_override,
        normalized,
    )
    job_id = uuid.uuid4().hex
    current_group_id, current_group_name = _upload_start_group_context(conn, username)
    job = {
        "job_id": job_id,
        "client_upload_id": client_upload_id,
        "username": username,
        "group_id": current_group_id,
        "group_name": current_group_name,
        "host": host,
        "port": port,
        "project_id": project_id,
        "project_name": project_name,
        "files": normalized,
        "total_bytes": total_bytes,
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "status": "uploading",
        "errors": [],
        "created": time.time(),
        "dataset_map": dataset_map,
        "orphan_dataset_name": orphan_dataset_name,
        "dataset_name_override": dataset_name_override,
        "import_index": 0,
        "messages": [],
        "import_thread_started": False,
        "job_batch_size": batch_size,
        "compatibility_status": "pending",
        "compatibility_enabled": compatibility_enabled,
        "incompatible_files": [],
        "compatibility_thread_active": False,
        "compatibility_confirmed": False,
        "planned_import_units": [],
        "special_upload": special_upload,
        "sem_edx_associations": sem_edx_associations,
        "sem_edx_settings": sem_edx_settings,
        "ngff_converter_settings": ngff_converter_settings,
    }
    if not _save_job(job):
        logger.error(
            "Unable to persist upload job %s for user %s.",
            sanitize_log_value(job_id),
            sanitize_log_value(username),
        )
        return json_error(errors.unable_update_upload_job_state(), status=500)

    logger.info(
        "Upload job %s created for user %s with %d files (%s bytes).",
        sanitize_log_value(job_id),
        sanitize_log_value(username),
        len(normalized),
        sanitize_log_value(total_bytes),
    )

    return JsonResponse(_upload_job_response(job))


@login_required()
@require_non_root_user
def upload_files(request, job_id, conn=None, _url=None, **kwargs):
    """Upload the files.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: `_upload_files` result.
    """
    try:
        return _upload_files(request, job_id, conn)
    except Exception as exc:
        logger.error(
            "Unhandled error while uploading files for job %s.",
            sanitize_log_value(job_id),
            exc_info=sanitized_exc_info(exc),
        )
        return json_error(errors.unexpected_server_error_uploading_files(), status=500)


def _find_job_upload_entry(job, rel_path, statuses=("pending", "error")):
    """Find the job upload entry.

    Inputs: `job`, `rel_path`, `statuses`. Output: `entry`.
    """
    allowed_statuses = set(statuses or ())
    for entry in job.get("files", []):
        if (
            entry.get("relative_path") == rel_path
            and entry.get("status") in allowed_statuses
        ):
            return entry
    return None


def _job_owned_by_request(job, request, conn):
    """Return the job owned by request.

    Inputs: `job`, `request` Django request, `conn` OMERO gateway connection. Output:
    `bool`.
    """
    if not isinstance(job, dict):
        return False
    job_username = str(job.get("username") or "").strip()
    request_username = str(current_username(request, conn) or "").strip()
    return bool(job_username and request_username and job_username == request_username)


def _load_owned_job(request, conn, job_id, missing_error):
    """Load the owned job.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `job_id`,
    `missing_error`. Output: `tuple`.
    """
    if not _safe_job_id(job_id):
        return None, json_error(missing_error)
    job = _load_job(job_id)
    if not job or not _job_owned_by_request(job, request, conn):
        return None, json_error(missing_error)
    return job, None


def _prepare_ready_job_for_import_start(job_id, job, conn):
    """Prepare the ready job for import start.

    Inputs: `job_id`, `job`, `conn` OMERO gateway connection. Output: `tuple`.
    """
    prepared_job, prep_error = _prepare_uploaded_job_dataset_targets(job_id, job, conn)
    if prep_error:
        return prepared_job or job, prep_error

    job = prepared_job or job
    if job.get("status") != "ready":
        return job, None

    return job, None


def _prepare_uploaded_job_dataset_targets(job_id, job, conn):
    """Prepare the uploaded job dataset targets.

    Inputs: `job_id`, `job`, `conn` OMERO gateway connection. Output:
    `_prepare_uploaded_job_for_request_path_import` result.
    """
    return _prepare_uploaded_job_for_request_path_import(job_id, job, conn)


def _prepare_job_import_datasets(job_id, job, conn):
    """Compatibility wrapper retained for tests and callers that patch this symbol.

    Inputs: `job_id`, `job`, `conn` OMERO gateway connection. Output:
    `_prepare_uploaded_job_dataset_targets` result.
    """
    return _prepare_uploaded_job_dataset_targets(job_id, job, conn)


def _upload_internal_error_response(job_id, detail, *, context: str):
    """Upload the internal error response.

    Inputs: `job_id`, `detail`, `context` (str). Output: `json_error` result.
    """
    logger.warning(
        "%s for upload job %s: %s",
        context,
        sanitize_log_value(job_id),
        sanitize_log_value(detail),
    )
    return json_error(errors.unexpected_server_error_uploading_files(), status=500)


def _import_internal_error_response(job_id, detail, *, context: str):
    """Import the internal error response.

    Inputs: `job_id`, `detail`, `context` (str). Output: `json_error` result.
    """
    logger.warning(
        "%s for import job %s: %s",
        context,
        sanitize_log_value(job_id),
        sanitize_log_value(detail),
    )
    return json_error(errors.unexpected_server_error_importing(), status=500)


def _get_session_key(conn):
    """Return session key.

    Inputs: `conn`. Output: `_core_get_session_key` result.
    """
    from .core_functions import _get_session_key as _core_get_session_key

    return _core_get_session_key(conn)


def _get_or_create_dataset(conn, name, dataset_map, project_id=None):
    """Return or create dataset.

    Inputs: `conn` OMERO gateway connection, `name` name, `dataset_map`, `project_id`
    OMERO project ID. Output: `_core_get_or_create_dataset` result.
    """
    from .core_functions import _get_or_create_dataset as _core_get_or_create_dataset

    return _core_get_or_create_dataset(conn, name, dataset_map, project_id=project_id)


def _parse_chunk_int(raw_value, field_name):
    """Parse and validate the chunk int input.

    Inputs: `raw_value` raw value, `field_name`. Output: `tuple`.
    """
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None, errors.upload_chunk_metadata_invalid(
            f"{field_name} must be an integer"
        )
    if value < 0:
        return None, errors.upload_chunk_metadata_invalid(
            f"{field_name} must be non-negative"
        )
    return value, None


def _as_bool(raw_value):
    """Return the as bool.

    Inputs: `raw_value` raw value. Output: `bool`.
    """
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_client_upload_id(raw_value):
    """Normalize the client upload ID.

    Inputs: `raw_value` raw value. Output: `tuple`.
    """
    value = str(raw_value or "").strip()
    if not value:
        return "", None
    if len(value) > 64 or not all(
        char.isalnum() or char in {"_", "-"} for char in value
    ):
        return "", errors.invalid_client_upload_id()
    return value, None


def _resolve_upload_project(conn, raw_project_id):
    """Resolve the upload project.

    Inputs: `conn` OMERO gateway connection, `raw_project_id`. Output: `tuple`.
    """
    raw_project_id = (raw_project_id or "").strip()
    if not raw_project_id:
        return None, "", None
    try:
        project_id = int(raw_project_id)
    except (TypeError, ValueError):
        return None, "", json_error(errors.invalid_project_selection(), status=400)

    project = conn.getObject("Project", project_id)
    can_write = project is not None and (
        _is_owned_by_user(project, _current_user_id(conn))
        or _has_read_write_permissions(project)
    )
    if not can_write:
        return None, "", json_error(errors.invalid_project_selection(), status=400)
    return project_id, _get_text(project.getName()), None


def _upload_job_response(job):
    """Upload the job response.

    Inputs: `job`. Output: `dict`.
    """
    job_id = job.get("job_id")
    return {
        "ok": True,
        "job_id": job_id,
        "upload_url": reverse("omeroweb_import_files", kwargs={"job_id": job_id}),
        "import_step_url": reverse(
            "omeroweb_import_import_step", kwargs={"job_id": job_id}
        ),
        "status_url": reverse("omeroweb_import_status", kwargs={"job_id": job_id}),
        "confirm_url": reverse("omeroweb_import_confirm", kwargs={"job_id": job_id}),
        "prune_url": reverse("omeroweb_import_prune", kwargs={"job_id": job_id}),
    }


def _same_upload_manifest(job, normalized_files, dataset_name_override, project_id):
    """Return whether a retry matches the already-created upload job.

    Inputs: `job`, `normalized_files`, `dataset_name_override`, `project_id`. Output:
    bool.
    """
    if job.get("dataset_name_override") != dataset_name_override:
        return False
    if job.get("project_id") != project_id:
        return False
    existing = [
        (entry.get("relative_path"), int(entry.get("size") or 0))
        for entry in list(job.get("files") or [])
    ]
    requested = [
        (entry.get("relative_path"), int(entry.get("size") or 0))
        for entry in list(normalized_files or [])
    ]
    return existing == requested


def _find_client_upload_job(username, client_upload_id):
    """Find the client upload job.

    Inputs: `username` username, `client_upload_id`. Output: `job`.
    """
    if not username or not client_upload_id:
        return None
    try:
        job_paths = sorted(_get_jobs_root().glob("*.json"))
    except OSError as exc:
        logger.warning(
            "Unable to list upload jobs while resolving retry id: %s",
            sanitize_log_value(exc),
        )
        return None
    for job_path in job_paths:
        job_id = job_path.stem
        if not _safe_job_id(job_id):
            continue
        job = _load_job(job_id)
        if (
            isinstance(job, dict)
            and job.get("client_upload_id") == client_upload_id
            and str(job.get("username") or "").strip() == username
        ):
            return job
    return None


def _client_upload_retry_response(
    username,
    client_upload_id,
    normalized_files,
    dataset_name_override,
    project_id,
):
    """Return an existing upload response for a matching client retry id.

    Inputs: `username` username, `client_upload_id`, `normalized_files`,
    `dataset_name_override`, `project_id` OMERO project ID. Output: Django
    `JsonResponse`.
    """
    if not client_upload_id:
        return None
    existing_job = _find_client_upload_job(username, client_upload_id)
    if existing_job is None:
        return None
    if not _same_upload_manifest(
        existing_job,
        normalized_files,
        dataset_name_override,
        project_id,
    ):
        return json_error(errors.upload_retry_id_conflict(), status=409)
    logger.info(
        "Returning existing upload job %s for idempotent retry.",
        sanitize_log_value(existing_job.get("job_id")),
    )
    return JsonResponse(_upload_job_response(existing_job))


def _uploaded_file_sha256(upload):
    """Hash an uploaded chunk and rewind it for later saving.

    Inputs: `upload`. Output: tuple.
    """
    digest = hashlib.sha256()
    try:
        for piece in upload.chunks():
            digest.update(piece)
        if hasattr(upload, "seek"):
            upload.seek(0)
        elif hasattr(getattr(upload, "file", None), "seek"):
            upload.file.seek(0)
    except OSError as exc:
        logger.warning("Unable to hash uploaded chunk: %s", sanitize_log_value(exc))
        return None, errors.unexpected_server_error_uploading_files()
    return digest.hexdigest(), None


def _is_sha256_digest(value):
    """Return whether a text value is a lowercase SHA-256 hex digest.

    Inputs: `value`. Output: bool.
    """
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _complete_chunk_upload_response(job_id, conn, entry, rel_path, saved_size=None):
    """Mark an uploaded file complete and return the chunk response.

    Inputs: `job_id`, `conn` OMERO gateway connection, `entry`, `rel_path`,
    `saved_size`. Output: Django `JsonResponse`.
    """
    update = {"upload_id": entry.get("upload_id"), "status": "uploaded"}
    if saved_size is not None:
        update["saved_size"] = saved_size
    updated_job = _apply_upload_updates(job_id, [update], [])
    if not updated_job:
        return json_error(errors.unable_update_upload_job_state(), status=500)

    updated_job, prep_error = _prepare_uploaded_job_dataset_targets(
        job_id, updated_job, conn
    )
    if prep_error:
        return _upload_internal_error_response(
            job_id,
            prep_error,
            context="Failed to prepare uploaded chunk batch for import",
        )

    if updated_job["status"] == "ready":
        _start_import_thread(job_id)
        logger.info(
            "Upload job %s ready after chunked upload; import thread started.",
            sanitize_log_value(job_id),
        )

    return JsonResponse(
        {
            "ok": True,
            "complete": True,
            "saved": [rel_path],
            "errors": [],
            "error": None,
            "relative_path": rel_path,
            "uploaded_bytes": updated_job.get("uploaded_bytes", 0),
            "total_bytes": updated_job.get("total_bytes", 0),
            "ready": updated_job.get("status") == "ready",
        }
    )


def _chunk_upload_already_complete_response(job, rel_path):
    """Return an idempotent completion response for an already uploaded file.

    Inputs: `job`, `rel_path`. Output: `JsonResponse` result.
    """
    return JsonResponse(
        {
            "ok": True,
            "complete": True,
            "saved": [rel_path],
            "errors": [],
            "error": None,
            "relative_path": rel_path,
            "uploaded_bytes": job.get("uploaded_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "ready": job.get("status") == "ready",
        }
    )


def _chunk_upload_incomplete_retry_response(rel_path, existing_size):
    """Return an idempotent response for a previously staged non-final chunk.

    Inputs: `rel_path`, `existing_size`. Output: `JsonResponse` result.
    """
    return JsonResponse(
        {
            "ok": True,
            "complete": False,
            "saved": [],
            "errors": [],
            "error": None,
            "relative_path": rel_path,
            "uploaded_bytes_for_file": existing_size,
        }
    )


def _find_chunk_upload_entry(job, rel_path):
    """Return the upload entry accepted by chunked upload handling.

    Inputs: `job`, `rel_path`. Output: `entry`.
    """
    entry = _find_job_upload_entry(job, rel_path)
    if entry is not None:
        return entry
    for candidate in job.get("files", []):
        if (
            candidate.get("relative_path") == rel_path
            and candidate.get("status") == "uploaded"
        ):
            return candidate
    return None


def _chunk_upload_error_response(job_id, entry, rel_path, upload_error):
    """Persist and return a staged-upload error response.

    Inputs: `job_id`, `entry`, `rel_path`, `upload_error`. Output: `json_error` result.
    """
    if not (
        _is_managed_upload_internal_error(upload_error)
        or isinstance(upload_error, OSError)
    ):
        return json_error(upload_error, status=400)
    logger.warning(
        "Failed to handle staged upload %s.",
        sanitize_log_value(rel_path),
    )
    generic_error = (
        _managed_upload_error_message(upload_error)
        if _is_managed_upload_internal_error(upload_error)
        else errors.unexpected_server_error_uploading_files()
    )
    updated_job = _apply_upload_updates(
        job_id,
        [
            {
                "upload_id": entry.get("upload_id"),
                "status": "error",
                "errors": [generic_error],
            }
        ],
        [generic_error],
    )
    if not updated_job:
        return json_error(errors.unable_update_upload_job_state(), status=500)
    return json_error(generic_error, status=500)


def _validate_uploaded_chunk_checksum(upload, expected_checksum):
    """Validate the uploaded chunk checksum.

    Inputs: `upload`, `expected_checksum`. Output: `json_error` result.
    """
    if not expected_checksum:
        return None
    if not _is_sha256_digest(expected_checksum):
        return json_error(
            errors.upload_chunk_metadata_invalid(
                "chunk_sha256 must be a 64-character hexadecimal SHA-256 digest"
            ),
            status=400,
        )
    actual_checksum, checksum_error = _uploaded_file_sha256(upload)
    if checksum_error:
        return json_error(checksum_error, status=500)
    if actual_checksum != expected_checksum:
        return json_error(
            errors.upload_chunk_metadata_invalid(
                "chunk_sha256 does not match uploaded bytes"
            ),
            status=400,
        )
    return None


def _idempotent_chunk_retry_response(
    request,
    job_id,
    conn,
    job,
    job_root,
    entry,
    rel_path,
    staged_path,
    existing_size,
    chunk_start,
    chunk_end,
    file_size,
    expected_checksum,
):
    """Return a response for a chunk retry already present in staging.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `job`,
    `job_root`, `entry`, `rel_path`, `staged_path`, `existing_size`, `chunk_start`,
    `chunk_end`, `file_size`, `expected_checksum`. Output:
    `_complete_chunk_upload_response` result.
    """
    if existing_size <= chunk_start or not expected_checksum:
        return None
    already_saved, match_error = _staged_upload_chunk_matches(
        job_root,
        staged_path,
        chunk_start,
        chunk_end,
        expected_checksum,
    )
    if match_error:
        if _is_managed_upload_internal_error(match_error):
            return json_error(_managed_upload_error_message(match_error), status=500)
        return json_error(match_error, status=400)
    if not already_saved:
        return None
    logger.info(
        "Accepted idempotent chunk retry for %s in job %s.",
        sanitize_log_value(rel_path),
        sanitize_log_value(job_id),
    )
    is_last_retry = _as_bool(request.POST.get("is_last_chunk")) or (
        existing_size >= file_size and chunk_end >= file_size
    )
    if not is_last_retry:
        return _chunk_upload_incomplete_retry_response(rel_path, existing_size)
    if entry.get("status") == "uploaded":
        return _chunk_upload_already_complete_response(job, rel_path)
    return _complete_chunk_upload_response(job_id, conn, entry, rel_path, existing_size)


def _reset_staged_chunk_upload(job_id, job_root, entry, rel_path, staged_path):
    """Reset the staged file for a first-chunk retry.

    Inputs: `job_id`, `job_root`, `entry`, `rel_path`, `staged_path`. Output: call
    result or None.
    """
    reset_error = _reset_staged_upload_file(job_root, staged_path)
    if reset_error:
        return _chunk_upload_error_response(job_id, entry, rel_path, reset_error)
    return None


def _prepare_staged_chunk_write(
    job_id,
    job_root,
    entry,
    rel_path,
    staged_path,
    existing_size,
    chunk_start,
):
    """Prepare the staged chunk write.

    Inputs: `job_id`, `job_root`, `entry`, `rel_path`, `staged_path`, `existing_size`,
    `chunk_start`. Output: `json_error` result.
    """
    if chunk_start == 0:
        return _reset_staged_chunk_upload(
            job_id, job_root, entry, rel_path, staged_path
        )
    if existing_size == chunk_start:
        return None

    logger.warning(
        "Chunk offset mismatch for %s in job %s: existing=%s request_start=%s",
        sanitize_log_value(rel_path),
        sanitize_log_value(job_id),
        sanitize_log_value(existing_size),
        sanitize_log_value(chunk_start),
    )
    return json_error(
        errors.upload_chunk_offset_mismatch(rel_path, existing_size, chunk_start),
        status=409,
    )


def _incomplete_chunk_upload_response(rel_path, saved_size):
    """Return the standard response for a chunked upload still in progress.

    Inputs: `rel_path`, `saved_size`. Output: `JsonResponse` result.
    """
    return JsonResponse(
        {
            "ok": True,
            "complete": False,
            "saved": [],
            "errors": [],
            "error": None,
            "relative_path": rel_path,
            "uploaded_bytes_for_file": saved_size,
        }
    )


def _chunk_write_validation_response(
    job_id,
    rel_path,
    bytes_written,
    saved_size,
    chunk_start,
    chunk_end,
    file_size,
    is_last_chunk,
):
    """Return a chunk write validation error, an incomplete response, or None.

    Inputs: `job_id`, `rel_path`, `bytes_written`, `saved_size`, `chunk_start`,
    `chunk_end`, `file_size`, `is_last_chunk`. Output: `json_error` result.
    """
    expected_chunk_size = chunk_end - chunk_start
    if bytes_written != expected_chunk_size:
        logger.warning(
            "Chunk size mismatch for %s in job %s: expected=%s wrote=%s",
            sanitize_log_value(rel_path),
            sanitize_log_value(job_id),
            sanitize_log_value(expected_chunk_size),
            sanitize_log_value(bytes_written),
        )
        return json_error(
            errors.upload_chunk_size_mismatch(
                rel_path, expected_chunk_size, bytes_written
            ),
            status=400,
        )

    if not is_last_chunk:
        return _incomplete_chunk_upload_response(rel_path, saved_size)

    if saved_size != file_size:
        logger.warning(
            "Final chunk saved unexpected size for %s in job %s: expected=%s actual=%s",
            sanitize_log_value(rel_path),
            sanitize_log_value(job_id),
            sanitize_log_value(file_size),
            sanitize_log_value(saved_size),
        )
        return json_error(
            errors.upload_chunk_incomplete(rel_path, file_size, saved_size), status=400
        )
    return None


def _chunk_upload_request_metadata(request):
    """And return chunk upload request metadata.

    Inputs: `request`. Output: tuple.
    """
    upload = request.FILES.get("file")
    if upload is None:
        return None, json_error(errors.upload_chunk_missing_file(), status=400)

    rel_path, rel_error = _normalize_upload_relative_path(
        request.POST.get("relative_path") or ""
    )
    if rel_error:
        return None, json_error(rel_error, status=400)

    chunk_start, start_error = _parse_chunk_int(
        request.POST.get("chunk_start"), "chunk_start"
    )
    if start_error:
        return None, json_error(start_error, status=400)
    chunk_end, end_error = _parse_chunk_int(request.POST.get("chunk_end"), "chunk_end")
    if end_error:
        return None, json_error(end_error, status=400)
    file_size, size_error = _parse_chunk_int(request.POST.get("file_size"), "file_size")
    if size_error:
        return None, json_error(size_error, status=400)

    if chunk_end < chunk_start:
        return None, json_error(
            errors.upload_chunk_metadata_invalid(
                "chunk_end must be greater than or equal to chunk_start"
            ),
            status=400,
        )
    if chunk_end > file_size:
        return None, json_error(
            errors.upload_chunk_metadata_invalid("chunk_end cannot exceed file_size"),
            status=400,
        )
    return (upload, rel_path, chunk_start, chunk_end, file_size), None


def _handle_chunk_upload(request, job_id, conn, job, job_root):
    """Return the handle chunk upload.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `job`,
    `job_root`. Output: `_complete_chunk_upload_response` result.
    """
    metadata, metadata_error = _chunk_upload_request_metadata(request)
    if metadata_error is not None:
        return metadata_error
    upload, rel_path, chunk_start, chunk_end, file_size = metadata

    entry = _find_chunk_upload_entry(job, rel_path)
    if not entry:
        return json_error(errors.unexpected_file(rel_path), status=400)

    staged_path = entry.get("staged_path") or rel_path
    expected_checksum = str(request.POST.get("chunk_sha256") or "").strip().lower()
    checksum_response = _validate_uploaded_chunk_checksum(upload, expected_checksum)
    if checksum_response is not None:
        return checksum_response

    existing_size, staged_error = _staged_upload_size(job_root, staged_path)
    if staged_error:
        return _chunk_upload_error_response(job_id, entry, rel_path, staged_error)

    retry_response = _idempotent_chunk_retry_response(
        request,
        job_id,
        conn,
        job,
        job_root,
        entry,
        rel_path,
        staged_path,
        existing_size,
        chunk_start,
        chunk_end,
        file_size,
        expected_checksum,
    )
    if retry_response is not None:
        return retry_response

    write_ready_response = _prepare_staged_chunk_write(
        job_id,
        job_root,
        entry,
        rel_path,
        staged_path,
        existing_size,
        chunk_start,
    )
    if write_ready_response is not None:
        return write_ready_response

    bytes_written, saved_size, write_error = _append_upload_chunks_to_staged_path(
        job_root, staged_path, upload
    )
    if write_error:
        return _chunk_upload_error_response(job_id, entry, rel_path, write_error)

    is_last_chunk = (
        _as_bool(request.POST.get("is_last_chunk")) or saved_size >= file_size
    )
    validation_response = _chunk_write_validation_response(
        job_id,
        rel_path,
        bytes_written,
        saved_size,
        chunk_start,
        chunk_end,
        file_size,
        is_last_chunk,
    )
    if validation_response is not None:
        return validation_response

    return _complete_chunk_upload_response(job_id, conn, entry, rel_path, saved_size)


def _upload_files(request, job_id, conn):
    """Upload the files.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection. Output:
    Django `JsonResponse`.
    """
    safe_job_id = sanitize_log_value(job_id)
    if request.method != "POST":
        return json_error(errors.upload_endpoint_post_required())

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root):
        logger.warning("Upload root not writable for job %s.", safe_job_id)
        return json_error(errors.upload_folder_not_writable())

    job, error_response = _load_owned_job(
        request,
        conn,
        job_id,
        errors.upload_job_not_found(),
    )
    if error_response:
        logger.warning("Upload job %s not found.", safe_job_id)
        return error_response

    try:
        job_id = _validated_job_id(job.get("job_id"))
    except (TypeError, ValueError):
        logger.warning(
            "Upload job %s contained an invalid persisted identifier.",
            safe_job_id,
        )
        return json_error(errors.upload_job_not_found())
    safe_job_id = sanitize_log_value(job_id)

    job_root = upload_root / job_id
    if not _ensure_dir(job_root):
        logger.warning("Unable to initialize upload folder for job %s.", safe_job_id)
        return json_error(errors.unable_initialize_upload_folder())

    if request.POST.get("upload_mode") == "chunked":
        return _handle_chunk_upload(request, job_id, conn, job, job_root)

    files = request.FILES.getlist("files")
    if not files:
        logger.info("Upload job %s received no files.", safe_job_id)
        return json_error(errors.no_files_provided())

    relative_paths = request.POST.getlist("relative_paths")
    if relative_paths and len(relative_paths) != len(files):
        logger.warning("Upload payload mismatch for job %s.", safe_job_id)
        return json_error(errors.upload_payload_mismatch())

    saved: list[dict[str, Any]] = []
    upload_errors: list[str] = []
    entries_by_path: dict[str, list[dict[str, Any]]] = {}
    updates: list[dict[str, Any]] = []
    for file_entry in job["files"]:
        if file_entry.get("status") in ("pending", "error"):
            entries_by_path.setdefault(file_entry["relative_path"], []).append(
                file_entry
            )

    for file_index, upload in enumerate(files):
        raw_name = relative_paths[file_index] if relative_paths else upload.name
        rel_path, rel_error = _normalize_upload_relative_path(raw_name)
        if rel_error:
            upload_errors.append(rel_error)
            continue

        entry_queue = entries_by_path.get(rel_path) or []
        if not entry_queue:
            upload_errors.append(errors.unexpected_file(rel_path))
            continue
        entry = entry_queue.pop(0)

        staged_path = entry.get("staged_path") or rel_path
        saved_size, save_error = _replace_staged_upload_file(
            job_root, staged_path, upload
        )
        if save_error:
            if isinstance(save_error, str) and not _is_managed_upload_internal_error(
                save_error
            ):
                staged_error = save_error
                logger.warning(
                    "Rejected staged upload target for %s: %s",
                    sanitize_log_value(rel_path),
                    sanitize_log_value(staged_error),
                )
                upload_errors.append(staged_error)
                entry["status"] = "error"
                entry.setdefault("errors", []).append(staged_error)
                updates.append(
                    {
                        "upload_id": entry.get("upload_id"),
                        "status": "error",
                        "errors": [staged_error],
                    }
                )
                continue

            logger.warning(
                "Failed to save upload %s.",
                sanitize_log_value(rel_path),
            )
            generic_error = (
                _managed_upload_error_message(save_error)
                if _is_managed_upload_internal_error(save_error)
                else errors.unexpected_server_error_uploading_files()
            )
            upload_errors.append(generic_error)
            entry["status"] = "error"
            entry.setdefault("errors", []).append(generic_error)
            updates.append(
                {
                    "upload_id": entry.get("upload_id"),
                    "status": "error",
                    "errors": [generic_error],
                }
            )
            continue

        if saved_size is None:
            logger.warning(
                "Failed to save upload %s: missing saved size",
                sanitize_log_value(rel_path),
            )
            generic_error = errors.unexpected_server_error_uploading_files()
            upload_errors.append(generic_error)
            entry["status"] = "error"
            entry.setdefault("errors", []).append(generic_error)
            updates.append(
                {
                    "upload_id": entry.get("upload_id"),
                    "status": "error",
                    "errors": [generic_error],
                }
            )
            continue

        saved.append(rel_path)
        entry["status"] = "uploaded"
        updates.append(
            {
                "upload_id": entry.get("upload_id"),
                "status": "uploaded",
                "saved_size": saved_size,
            }
        )

    updated_job = _apply_upload_updates(job_id, updates, upload_errors)
    if not updated_job:
        return json_error(errors.unable_update_upload_job_state())

    updated_job, prep_error = _prepare_uploaded_job_dataset_targets(
        job_id, updated_job, conn
    )
    if prep_error:
        return _upload_internal_error_response(
            job_id,
            prep_error,
            context="Failed to prepare uploaded files for import",
        )

    if updated_job["status"] == "ready":
        _start_import_thread(job_id)
        logger.info("Upload job %s ready; import thread started.", safe_job_id)

    return JsonResponse(
        {
            "ok": len(upload_errors) == 0,
            "saved": saved,
            "errors": upload_errors,
            "error": upload_errors[0] if upload_errors else None,
            "uploaded_bytes": updated_job.get("uploaded_bytes", 0),
            "total_bytes": updated_job.get("total_bytes", 0),
            "ready": updated_job.get("status") == "ready",
        }
    )


@login_required()
@require_non_root_user
def import_step(request, job_id, conn=None, _url=None, **kwargs):
    """Import the step.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: `_import_step` result.
    """
    try:
        return _import_step(request, job_id, conn)
    except Exception as exc:
        logger.error(
            "Unhandled error while importing job %s.",
            sanitize_log_value(job_id),
            exc_info=sanitized_exc_info(exc),
        )
        return json_error(errors.unexpected_server_error_importing(), status=500)


def _import_step(request, job_id, conn):
    """Import the step.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection. Output:
    Django `JsonResponse`.
    """
    safe_job_id = sanitize_log_value(job_id)
    if request.method != "POST":
        return json_error(errors.import_endpoint_post_required())

    job, error_response = _load_owned_job(
        request,
        conn,
        job_id,
        errors.import_job_not_found(),
    )
    if error_response:
        logger.warning("Import job %s not found.", safe_job_id)
        return error_response

    if job.get("status") == "ready":
        job, prep_error = _prepare_ready_job_for_import_start(job_id, job, conn)
        if prep_error:
            return _import_internal_error_response(
                job_id,
                prep_error,
                context="Failed to prepare import job before starting import",
            )
        _start_import_thread(job_id)
        job = _load_job(job_id) or job

    return JsonResponse(
        {
            "ok": True,
            "done": job.get("status") in ("done", "error"),
            "status": job.get("status"),
            "imported_bytes": job.get("imported_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "messages": _public_import_job_text_list(job.get("messages", [])),
        }
    )


@login_required()
@require_non_root_user
def confirm_import(request, job_id, conn=None, _url=None, **kwargs):
    """Confirm the import.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    if request.method != "POST":
        return json_error(errors.method_post_required())

    job, error_response = _load_owned_job(
        request,
        conn,
        job_id,
        errors.upload_job_not_found(),
    )
    if error_response:
        return error_response

    if job.get("status") != "awaiting_confirmation":
        return JsonResponse({"ok": True, "status": job.get("status")})

    job["compatibility_confirmed"] = True
    job["compatibility_thread_active"] = False
    job["status"] = "ready"
    job["updated"] = time.time()
    if not _save_job(job):
        logger.error(
            "Unable to persist confirmation state for upload job %s.",
            sanitize_log_value(job_id),
        )
        return json_error(errors.unable_update_upload_job_state(), status=500)
    _prepared_job, prep_error = _prepare_ready_job_for_import_start(job_id, job, conn)
    if prep_error:
        return _import_internal_error_response(
            job_id,
            prep_error,
            context="Failed to prepare confirmed import job",
        )
    _start_import_thread(job_id)

    return JsonResponse({"ok": True, "status": "ready"})


@login_required()
@require_non_root_user
def prune_upload(request, job_id, conn=None, _url=None, **kwargs):
    """Return the prune upload.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    if request.method != "POST":
        return json_error(errors.method_post_required())

    job, error_response = _load_owned_job(
        request,
        conn,
        job_id,
        errors.upload_job_not_found(),
    )
    if error_response:
        return error_response

    payload = load_json_body(request)
    if not isinstance(payload, dict):
        payload = {}

    keep_paths = payload.get("keep_paths") or []
    if not isinstance(keep_paths, list):
        keep_paths = []

    keep_set = set()
    for path in keep_paths:
        rel_path = _safe_relative_path(path)
        if rel_path:
            keep_set.add(rel_path)

    upload_root = _get_upload_root() / job_id

    def apply_prune(job_dict):
        """Apply the prune.

        Inputs: `job_dict`. Output: `job_dict`.
        """
        removed = []
        kept_entries = []
        for entry in job_dict.get("files", []):
            rel_path = entry.get("relative_path")
            if not rel_path or rel_path not in keep_set:
                removed.append(entry)
                continue
            kept_entries.append(entry)

        for entry in removed:
            staged_path = entry.get("staged_path") or entry.get("relative_path")
            if not staged_path:
                continue
            file_path, staged_error = _resolve_staged_target_path(
                upload_root, staged_path
            )
            if staged_error:
                logger.warning(
                    "Rejected staged prune target for job %s.",
                    sanitize_log_value(job_id),
                )
                continue
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError as exc:
                logger.warning(
                    "Failed to remove staged file %s: %s",
                    sanitize_log_value(file_path),
                    sanitize_log_value(exc),
                )

        job_dict["files"] = kept_entries
        job_dict["total_bytes"] = sum(entry.get("size", 0) for entry in kept_entries)
        job_dict["uploaded_bytes"] = sum(
            entry.get("size", 0)
            for entry in kept_entries
            if entry.get("status") == "uploaded"
        )
        job_dict["incompatible_files"] = sorted(
            entry.get("relative_path")
            for entry in kept_entries
            if entry.get("compatibility") == "incompatible"
            and entry.get("relative_path")
        )

        pending_after = _compatibility_pending_entries(job_dict)
        has_errors = any(
            entry.get("compatibility") == "error" for entry in kept_entries
        )
        if job_dict["incompatible_files"]:
            job_dict["compatibility_status"] = "incompatible"
        elif pending_after:
            job_dict["compatibility_status"] = "checking"
        elif has_errors:
            job_dict["compatibility_status"] = "error"
        else:
            job_dict["compatibility_status"] = "compatible"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    job = _update_job(job_id, apply_prune)
    if not job:
        return json_error(errors.unable_update_upload_job_state())

    if job.get("status") == "ready":
        job, prep_error = _prepare_ready_job_for_import_start(job_id, job, conn)
        if prep_error:
            return _import_internal_error_response(
                job_id,
                prep_error,
                context="Failed to prepare pruned upload job for import",
            )
        _start_import_thread(job_id)

    return JsonResponse({"ok": True, "status": job.get("status")})


@login_required()
@require_non_root_user
def job_status(request, job_id, conn=None, _url=None, **kwargs):
    """Return the job status.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    job, error_response = _load_owned_job(
        request,
        conn,
        job_id,
        errors.upload_job_not_found(),
    )
    if error_response:
        return error_response

    job, prep_error = _prepare_uploaded_job_dataset_targets(job_id, job, conn)
    if prep_error:
        return _import_internal_error_response(
            job_id,
            prep_error,
            context="Failed to prepare upload job status for import",
        )

    if job.get("status") == "ready" and not job.get("import_thread_started"):
        _start_import_thread(job_id)
        job = _load_job(job_id) or job

    return JsonResponse(
        {
            "ok": True,
            "status": job.get("status"),
            "uploaded_bytes": job.get("uploaded_bytes", 0),
            "imported_bytes": job.get("imported_bytes", 0),
            "import_progress_bytes": job.get("import_progress_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "errors": _public_import_job_text_list(
                job.get("errors", []),
                errors_only=True,
            ),
            "messages": _public_import_job_text_list(job.get("messages", [])),
            "compatibility_status": job.get("compatibility_status"),
            "compatibility_enabled": bool(job.get("compatibility_enabled", True)),
            "compatibility_checked": sum(
                1 for f in job.get("files", []) if f.get("compatibility")
            ),
            "compatibility_total": sum(
                1
                for f in job.get("files", [])
                if f.get("status") == "uploaded" and not f.get("compatibility_skip")
            ),
            "incompatible_files": job.get("incompatible_files", []),
            "confirmation_required": job.get("status") == "awaiting_confirmation",
        }
    )
