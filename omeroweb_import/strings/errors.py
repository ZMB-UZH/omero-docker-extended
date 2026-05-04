def unexpected_server_error_start_upload():
    """Return the unexpected server error start upload.

    Inputs: none. Output: `str`.
    """
    return "Unexpected server error while starting upload."


def upload_start_post_required():
    """Upload the start post required.

    Inputs: none. Output: `str`.
    """
    return "Upload start expects POST."


def upload_folder_not_writable():
    """Upload the folder not writable.

    Inputs: none. Output: `str`.
    """
    return "Upload folder is not writable. Please check OMERO_TMP_PATH configuration."


def no_files_provided():
    """Return the no files provided.

    Inputs: none. Output: `str`.
    """
    return "No files provided."


def invalid_project_selection():
    """Return the invalid project selection.

    Inputs: none. Output: `str`.
    """
    return "Invalid project selection."


def unable_resolve_session():
    """Return the unable resolve session.

    Inputs: none. Output: `str`.
    """
    return "Unable to resolve OMERO session."


def unable_resolve_host_port():
    """Return the unable resolve host port.

    Inputs: none. Output: `str`.
    """
    return "Unable to resolve OMERO host/port."


def invalid_file_paths(paths):
    """Return the invalid file paths.

    Inputs: `paths`. Output: `Path` or path text.
    """
    return f"Invalid file paths: {', '.join(paths)}."


def invalid_dataset_name_override(detail):
    """Return the invalid dataset name override.

    Inputs: `detail`. Output: ID value.
    """
    return f"Invalid dataset name override: {detail}."


def upload_endpoint_post_required():
    """Upload the endpoint post required.

    Inputs: none. Output: `str`.
    """
    return "Upload endpoint expects POST."


def upload_job_not_found():
    """Upload the job not found.

    Inputs: none. Output: `str`.
    """
    return "Upload job not found."


def upload_payload_mismatch():
    """Upload the payload mismatch.

    Inputs: none. Output: `str`.
    """
    return "Upload payload mismatch. Please retry the upload."


def upload_batch_too_large(max_gb):
    """Upload the batch too large.

    Inputs: `max_gb`. Output: upload batch too large result.
    """
    return f"Upload batch exceeds the limit of {max_gb} GB."


def unable_initialize_upload_folder():
    """Return the unable initialize upload folder.

    Inputs: none. Output: `str`.
    """
    return "Unable to initialize upload folder."


def upload_chunk_missing_file():
    """Upload the chunk missing file.

    Inputs: none. Output: `str`.
    """
    return "Chunk upload request missing file payload."


def upload_chunk_metadata_invalid(detail):
    """Upload the chunk metadata invalid.

    Inputs: `detail`. Output: ID value.
    """
    return f"Invalid chunk upload metadata: {detail}."


def upload_chunk_offset_mismatch(path, expected_offset, actual_offset):
    """Upload the chunk offset mismatch.

    Inputs: `path` path, `expected_offset`, `actual_offset`. Output: chunk payload or
    size.
    """
    return (
        f"Chunk upload offset mismatch for {path}: "
        f"server has {expected_offset} bytes, request started at {actual_offset}."
    )


def upload_chunk_size_mismatch(path, expected_size, actual_size):
    """Upload the chunk size mismatch.

    Inputs: `path` path, `expected_size`, `actual_size`. Output: `int` size.
    """
    return (
        f"Chunk upload size mismatch for {path}: "
        f"expected {expected_size} bytes, received {actual_size}."
    )


def upload_chunk_incomplete(path, expected_size, actual_size):
    """Upload the chunk incomplete.

    Inputs: `path` path, `expected_size`, `actual_size`. Output: chunk payload or size.
    """
    return (
        f"Chunk upload incomplete for {path}: "
        f"expected {expected_size} bytes, saved {actual_size}."
    )


def invalid_filename(name):
    """Return the invalid filename.

    Inputs: `name` name. Output: ID value.
    """
    return f"Invalid filename: {name}"


def filename_too_long(name, max_bytes):
    """Return the filename too long.

    Inputs: `name` name, `max_bytes`. Output: name string.
    """
    return f"Filename is too long ({max_bytes} byte limit): {name}"


def file_path_too_long(path, max_bytes):
    """Return the file path too long.

    Inputs: `path` path, `max_bytes`. Output: `Path` or path text.
    """
    return f"File path is too long ({max_bytes} byte limit): {path}"


def unexpected_file(path):
    """Return the unexpected file.

    Inputs: `path` path. Output: unexpected file result.
    """
    return f"Unexpected file: {path}"


def unable_update_upload_job_state():
    """Return the unable update upload job state.

    Inputs: none. Output: `str`.
    """
    return "Unable to update upload job state."


def invalid_client_upload_id():
    """Return the invalid client upload ID.

    Inputs: none. Output: `str`.
    """
    return "Invalid upload retry identifier."


def upload_retry_id_conflict():
    """Upload the retry ID conflict.

    Inputs: none. Output: `str`.
    """
    return "Upload retry identifier already belongs to a different upload."


def unexpected_server_error_uploading_files():
    """Return the unexpected server error uploading files.

    Inputs: none. Output: `str`.
    """
    return "Unexpected server error while uploading files."


def import_endpoint_post_required():
    """Import the endpoint post required.

    Inputs: none. Output: `str`.
    """
    return "Import endpoint expects POST."


def import_job_not_found():
    """Import the job not found.

    Inputs: none. Output: `str`.
    """
    return "Import job not found."


def unexpected_server_error_importing():
    """Return the unexpected server error importing.

    Inputs: none. Output: `str`.
    """
    return "Unexpected server error while importing."


def missing_omero_connection_details():
    """Return the missing OMERO connection details.

    Inputs: none. Output: `str`.
    """
    return "Missing OMERO connection details for import."


def unable_prepare_import_destination():
    """Return the unable prepare import destination.

    Inputs: none. Output: `str`.
    """
    return "OMERO could not prepare the destination for this import."


def upload_folder_missing_on_server():
    """Upload the folder missing on server.

    Inputs: none. Output: `str`.
    """
    return "Upload folder missing on server."


def missing_staged_file(path):
    """Return the missing staged file.

    Inputs: `path` path. Output: missing staged file result.
    """
    return f"Missing staged file: {path}"


def import_failed():
    """Import the failed.

    Inputs: none. Output: `str`.
    """
    return "Import failed."


def import_path_not_readable():
    """Import the path not readable.

    Inputs: none. Output: `str`.
    """
    return (
        "Import failed because the OMERO CLI could not read a required import "
        "path. Check filesystem permissions for the staged source and any "
        "managed-repository bridge paths."
    )


def import_no_objects_created():
    """Import the no objects created.

    Inputs: none. Output: `str`.
    """
    return (
        "Import command succeeded but no images were created in OMERO. "
        "The file format may not be supported, or the data may be corrupt."
    )


def import_zarr_not_recognized():
    """Import the Zarr not recognized.

    Inputs: none. Output: `str`.
    """
    return (
        "This .zarr folder is not in a format that OMERO can import. "
        "Automatic re-compression to zlib was attempted but the resulting "
        "zarr is still not recognised by Bio-Formats.  The zarr may use an "
        "unsupported layout or contain no importable image data."
    )


def import_session_expired():
    """Import the session expired.

    Inputs: none. Output: `str`.
    """
    return (
        "Import failed because the OMERO session expired during a long-running import."
    )


def import_parent_directory_not_writable(group_name=None, parent_id=None):
    """Import the parent directory not writable.

    Inputs: `group_name`, `parent_id`. Output: `detail`.
    """
    detail = (
        "Import failed because OMERO denied write access to the managed "
        "repository parent directory"
    )
    if group_name:
        detail += f" for group '{group_name}'"
    if parent_id:
        detail += f" (directory id {parent_id})"
    detail += (
        ". This usually means the group-level repository folder already exists "
        "but is owned by a different user."
    )
    return detail


def unexpected_import_failure(detail):
    """Return the unexpected import failure.

    Inputs: `detail`. Output: unexpected import failure result.
    """
    return f"Unexpected import failure: {detail}"


def method_post_required():
    """Return the method post required.

    Inputs: none. Output: `str`.
    """
    return "POST required"


def unable_to_determine_username():
    """Return the unable to determine username.

    Inputs: none. Output: `str`.
    """
    return "Unable to determine username."


def invalid_user_settings_payload():
    """Return the invalid user settings payload.

    Inputs: none. Output: `str`.
    """
    return "Invalid user settings payload."


def invalid_special_method_settings_payload():
    """Return the invalid special method settings payload.

    Inputs: none. Output: `str`.
    """
    return "Invalid special method settings payload."


def invalid_special_method_key():
    """Return the invalid special method key.

    Inputs: none. Output: `str`.
    """
    return "Invalid special method key."


def psycopg2_missing():
    """Return the psycopg2 missing.

    Inputs: none. Output: `str`.
    """
    return "psycopg2 is not installed. Please install psycopg2-binary in the OMERO.web environment."


def missing_db_credentials():
    """Missing DB credentials.

    Inputs: none. Output: 'Database credentials (docker compose environment variables)
    are missing (OMP_DATA_USER/OMP_DATA_PASS/OMP_DATA_HOST/OMP_DATA_DB).'.

    are missing (OMP_DATA_USER/OMP_DATA_PASS/OMP_DATA_HOST/OMP_DATA_DB).'.
    """
    return (
        "Database credentials (docker compose environment variables) are missing "
        "(OMP_DATA_USER/OMP_DATA_PASS/OMP_DATA_HOST/OMP_DATA_DB)."
    )


def db_connection_failed():
    """DB connection failed.

    Inputs: none. Output: 'Could not connect to the database.'.
    """
    return "Could not connect to the database."


def user_settings_not_persisted():
    """Return the user settings not persisted.

    Inputs: none. Output: `str`.
    """
    return "User settings were not persisted to the database."


def special_method_settings_not_persisted():
    """Return the special method settings not persisted.

    Inputs: none. Output: `str`.
    """
    return "Special method settings were not persisted to the database."


def user_settings_save_failed():
    """Return the user settings save failed.

    Inputs: none. Output: `str`.
    """
    return "Could not save user settings."


def special_method_settings_save_failed():
    """Return the special method settings save failed.

    Inputs: none. Output: `str`.
    """
    return "Could not save special method settings."


def special_method_settings_load_failed():
    """Return the special method settings load failed.

    Inputs: none. Output: `str`.
    """
    return "Could not load special method settings."


def upload_file_save_failed(path):
    """Upload the file save failed.

    Inputs: `path` path. Output: upload file save failed result.
    """
    return f"Failed to save uploaded file: {path}."


def unexpected_error():
    """Return the unexpected error.

    Inputs: none. Output: `str`.
    """
    return "Unexpected error."
