def unexpected_server_error_start_upload():
    """Unexpected server error start upload.

    Inputs: none. Output: 'Unexpected server error while starting upload.'.
    """
    return "Unexpected server error while starting upload."


def upload_start_post_required():
    """Upload start post required.

    Inputs: none. Output: 'Upload start expects POST.'.
    """
    return "Upload start expects POST."


def upload_folder_not_writable():
    """Upload folder not writable.

    Inputs: none. Output: 'Upload folder is not writable. Please check OMERO_TMP_PATH
    configuration.'.

    configuration.'.
    """
    return "Upload folder is not writable. Please check OMERO_TMP_PATH configuration."


def no_files_provided():
    """No files provided.

    Inputs: none. Output: 'No files provided.'.
    """
    return "No files provided."


def invalid_project_selection():
    """Invalid project selection.

    Inputs: none. Output: 'Invalid project selection.'.
    """
    return "Invalid project selection."


def unable_resolve_session():
    """Unable resolve session.

    Inputs: none. Output: 'Unable to resolve OMERO session.'.
    """
    return "Unable to resolve OMERO session."


def unable_resolve_host_port():
    """Unable resolve host port.

    Inputs: none. Output: 'Unable to resolve OMERO host/port.'.
    """
    return "Unable to resolve OMERO host/port."


def invalid_file_paths(paths):
    """Invalid file paths.

    Inputs: `paths`. Output: computed value.
    """
    return f"Invalid file paths: {', '.join(paths)}."


def invalid_dataset_name_override(detail):
    """Invalid dataset name override.

    Inputs: `detail`. Output: computed value.
    """
    return f"Invalid dataset name override: {detail}."


def upload_endpoint_post_required():
    """Upload endpoint post required.

    Inputs: none. Output: 'Upload endpoint expects POST.'.
    """
    return "Upload endpoint expects POST."


def upload_job_not_found():
    """Upload job not found.

    Inputs: none. Output: 'Upload job not found.'.
    """
    return "Upload job not found."


def upload_payload_mismatch():
    """Upload payload mismatch.

    Inputs: none. Output: 'Upload payload mismatch. Please retry the upload.'.
    """
    return "Upload payload mismatch. Please retry the upload."


def upload_batch_too_large(max_gb):
    """Upload batch too large.

    Inputs: `max_gb`. Output: computed value.
    """
    return f"Upload batch exceeds the limit of {max_gb} GB."


def unable_initialize_upload_folder():
    """Unable initialize upload folder.

    Inputs: none. Output: 'Unable to initialize upload folder.'.
    """
    return "Unable to initialize upload folder."


def upload_chunk_missing_file():
    """Upload chunk missing file.

    Inputs: none. Output: 'Chunk upload request missing file payload.'.
    """
    return "Chunk upload request missing file payload."


def upload_chunk_metadata_invalid(detail):
    """Upload chunk metadata invalid.

    Inputs: `detail`. Output: computed value.
    """
    return f"Invalid chunk upload metadata: {detail}."


def upload_chunk_offset_mismatch(path, expected_offset, actual_offset):
    """Upload chunk offset mismatch.

    Inputs: `path`, `expected_offset`, `actual_offset`. Output: computed value.
    """
    return (
        f"Chunk upload offset mismatch for {path}: "
        f"server has {expected_offset} bytes, request started at {actual_offset}."
    )


def upload_chunk_size_mismatch(path, expected_size, actual_size):
    """Upload chunk size mismatch.

    Inputs: `path`, `expected_size`, `actual_size`. Output: computed value.
    """
    return (
        f"Chunk upload size mismatch for {path}: "
        f"expected {expected_size} bytes, received {actual_size}."
    )


def upload_chunk_incomplete(path, expected_size, actual_size):
    """Upload chunk incomplete.

    Inputs: `path`, `expected_size`, `actual_size`. Output: computed value.
    """
    return (
        f"Chunk upload incomplete for {path}: "
        f"expected {expected_size} bytes, saved {actual_size}."
    )


def invalid_filename(name):
    """Invalid filename.

    Inputs: `name`. Output: computed value.
    """
    return f"Invalid filename: {name}"


def filename_too_long(name, max_bytes):
    """Filename too long.

    Inputs: `name`, `max_bytes`. Output: computed value.
    """
    return f"Filename is too long ({max_bytes} byte limit): {name}"


def file_path_too_long(path, max_bytes):
    """File path too long.

    Inputs: `path`, `max_bytes`. Output: computed value.
    """
    return f"File path is too long ({max_bytes} byte limit): {path}"


def unexpected_file(path):
    """Unexpected file.

    Inputs: `path`. Output: computed value.
    """
    return f"Unexpected file: {path}"


def unable_update_upload_job_state():
    """Unable update upload job state.

    Inputs: none. Output: 'Unable to update upload job state.'.
    """
    return "Unable to update upload job state."


def invalid_client_upload_id():
    """Invalid client upload ID.

    Inputs: none. Output: 'Invalid upload retry identifier.'.
    """
    return "Invalid upload retry identifier."


def upload_retry_id_conflict():
    """Upload retry ID conflict.

    Inputs: none. Output: 'Upload retry identifier already belongs to a different
    upload.'.

    upload.'.
    """
    return "Upload retry identifier already belongs to a different upload."


def unexpected_server_error_uploading_files():
    """Unexpected server error uploading files.

    Inputs: none. Output: 'Unexpected server error while uploading files.'.
    """
    return "Unexpected server error while uploading files."


def import_endpoint_post_required():
    """Import endpoint post required.

    Inputs: none. Output: 'Import endpoint expects POST.'.
    """
    return "Import endpoint expects POST."


def import_job_not_found():
    """Import job not found.

    Inputs: none. Output: 'Import job not found.'.
    """
    return "Import job not found."


def unexpected_server_error_importing():
    """Unexpected server error importing.

    Inputs: none. Output: 'Unexpected server error while importing.'.
    """
    return "Unexpected server error while importing."


def missing_omero_connection_details():
    """Missing OMERO connection details.

    Inputs: none. Output: 'Missing OMERO connection details for import.'.
    """
    return "Missing OMERO connection details for import."


def unable_prepare_import_destination():
    """Unable prepare import destination.

    Inputs: none. Output: 'OMERO could not prepare the destination for this import.'.
    """
    return "OMERO could not prepare the destination for this import."


def upload_folder_missing_on_server():
    """Upload folder missing on server.

    Inputs: none. Output: 'Upload folder missing on server.'.
    """
    return "Upload folder missing on server."


def missing_staged_file(path):
    """Missing staged file.

    Inputs: `path`. Output: computed value.
    """
    return f"Missing staged file: {path}"


def import_failed():
    """Import failed.

    Inputs: none. Output: 'Import failed.'.
    """
    return "Import failed."


def import_path_not_readable():
    """Import path not readable.

    Inputs: none. Output: 'Import failed because the OMERO CLI could not read a required
    import path. Check filesystem permissions for the staged source and any managed-
    repository bridge paths.'.

    import path. Check filesystem permissions for the staged source and any managed-
    repository bridge paths.'.
    """
    return (
        "Import failed because the OMERO CLI could not read a required import "
        "path. Check filesystem permissions for the staged source and any "
        "managed-repository bridge paths."
    )


def import_no_objects_created():
    """Import no objects created.

    Inputs: none. Output: 'Import command succeeded but no images were created in OMERO.
    The file format may not be supported, or the data may be corrupt.'.

    The file format may not be supported, or the data may be corrupt.'.
    """
    return (
        "Import command succeeded but no images were created in OMERO. "
        "The file format may not be supported, or the data may be corrupt."
    )


def import_zarr_not_recognized():
    """Import Zarr not recognized.

    Inputs: none. Output: 'This .zarr folder is not in a format that OMERO can import.
    Automatic re-compression to zlib was attempted but the resulting zarr is still not
    recognised by Bio-Formats.  The zarr may use an unsupported layout or contain no
    importable image data.'.

    Automatic re-compression to zlib was attempted but the resulting zarr is still not
    recognised by Bio-Formats.  The zarr may use an unsupported layout or contain no
    importable image data.'.
    """
    return (
        "This .zarr folder is not in a format that OMERO can import. "
        "Automatic re-compression to zlib was attempted but the resulting "
        "zarr is still not recognised by Bio-Formats.  The zarr may use an "
        "unsupported layout or contain no importable image data."
    )


def import_session_expired():
    """Import session expired.

    Inputs: none. Output: 'Import failed because the OMERO session expired during a
    long-running import.'.

    long-running import.'.
    """
    return (
        "Import failed because the OMERO session expired during a long-running import."
    )


def import_parent_directory_not_writable(group_name=None, parent_id=None):
    """Import parent directory not writable.

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
    """Unexpected import failure.

    Inputs: `detail`. Output: computed value.
    """
    return f"Unexpected import failure: {detail}"


def method_post_required():
    """Method post required.

    Inputs: none. Output: 'POST required'.
    """
    return "POST required"


def unable_to_determine_username():
    """Unable to determine username.

    Inputs: none. Output: 'Unable to determine username.'.
    """
    return "Unable to determine username."


def invalid_user_settings_payload():
    """Invalid user settings payload.

    Inputs: none. Output: 'Invalid user settings payload.'.
    """
    return "Invalid user settings payload."


def invalid_special_method_settings_payload():
    """Invalid special method settings payload.

    Inputs: none. Output: 'Invalid special method settings payload.'.
    """
    return "Invalid special method settings payload."


def invalid_special_method_key():
    """Invalid special method key.

    Inputs: none. Output: 'Invalid special method key.'.
    """
    return "Invalid special method key."


def psycopg2_missing():
    """Psycopg2 missing.

    Inputs: none. Output: 'psycopg2 is not installed. Please install psycopg2-binary in
    the OMERO.web environment.'.

    the OMERO.web environment.'.
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
    """User settings not persisted.

    Inputs: none. Output: 'User settings were not persisted to the database.'.
    """
    return "User settings were not persisted to the database."


def special_method_settings_not_persisted():
    """Special method settings not persisted.

    Inputs: none. Output: 'Special method settings were not persisted to the database.'.
    """
    return "Special method settings were not persisted to the database."


def user_settings_save_failed():
    """User settings save failed.

    Inputs: none. Output: 'Could not save user settings.'.
    """
    return "Could not save user settings."


def special_method_settings_save_failed():
    """Special method settings save failed.

    Inputs: none. Output: 'Could not save special method settings.'.
    """
    return "Could not save special method settings."


def special_method_settings_load_failed():
    """Special method settings load failed.

    Inputs: none. Output: 'Could not load special method settings.'.
    """
    return "Could not load special method settings."


def upload_file_save_failed(path):
    """Upload file save failed.

    Inputs: `path`. Output: computed value.
    """
    return f"Failed to save uploaded file: {path}."


def unexpected_error():
    """Unexpected error.

    Inputs: none. Output: 'Unexpected error.'.
    """
    return "Unexpected error."
