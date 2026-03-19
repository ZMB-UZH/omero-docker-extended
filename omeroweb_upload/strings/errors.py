
def unexpected_server_error_start_upload():
    return "Unexpected server error while starting upload."


def upload_start_post_required():
    return "Upload start expects POST."


def upload_folder_not_writable():
    return "Upload folder is not writable. Please check OMERO_TMP_PATH configuration."


def no_files_provided():
    return "No files provided."


def invalid_project_selection():
    return "Invalid project selection."


def unable_resolve_session():
    return "Unable to resolve OMERO session."


def unable_resolve_host_port():
    return "Unable to resolve OMERO host/port."


def invalid_file_paths(paths):
    return f"Invalid file paths: {', '.join(paths)}."


def upload_endpoint_post_required():
    return "Upload endpoint expects POST."


def upload_job_not_found():
    return "Upload job not found."


def upload_payload_mismatch():
    return "Upload payload mismatch. Please retry the upload."


def upload_batch_too_large(max_gb):
    return f"Upload batch exceeds the limit of {max_gb} GB."


def unable_initialize_upload_folder():
    return "Unable to initialize upload folder."


def upload_chunk_missing_file():
    return "Chunk upload request missing file payload."


def upload_chunk_metadata_invalid(detail):
    return f"Invalid chunk upload metadata: {detail}."


def upload_chunk_offset_mismatch(path, expected_offset, actual_offset):
    return (
        f"Chunk upload offset mismatch for {path}: "
        f"server has {expected_offset} bytes, request started at {actual_offset}."
    )


def upload_chunk_size_mismatch(path, expected_size, actual_size):
    return (
        f"Chunk upload size mismatch for {path}: "
        f"expected {expected_size} bytes, received {actual_size}."
    )


def upload_chunk_incomplete(path, expected_size, actual_size):
    return (
        f"Chunk upload incomplete for {path}: "
        f"expected {expected_size} bytes, saved {actual_size}."
    )


def upload_file_save_failed(path):
    return f"Failed to save upload: {path}."


def invalid_filename(name):
    return f"Invalid filename: {name}"


def filename_too_long(name, max_bytes):
    return f"Filename is too long ({max_bytes} byte limit): {name}"


def file_path_too_long(path, max_bytes):
    return f"File path is too long ({max_bytes} byte limit): {path}"


def unexpected_file(path):
    return f"Unexpected file: {path}"


def unable_update_upload_job_state():
    return "Unable to update upload job state."


def unexpected_server_error_uploading_files():
    return "Unexpected server error while uploading files."


def import_endpoint_post_required():
    return "Import endpoint expects POST."


def import_job_not_found():
    return "Import job not found."


def unexpected_server_error_importing():
    return "Unexpected server error while importing."


def missing_omero_connection_details():
    return "Missing OMERO connection details for import."


def unable_prepare_import_destination():
    return "OMERO could not prepare the destination for this import."


def upload_folder_missing_on_server():
    return "Upload folder missing on server."


def missing_staged_file(path):
    return f"Missing staged file: {path}"


def import_failed():
    return "Import failed."


def import_no_objects_created():
    return (
        "Import command succeeded but no images were created in OMERO. "
        "The file format may not be supported, or the data may be corrupt."
    )


def import_zarr_not_recognized():
    return (
        "This .zarr folder is not in a format that OMERO can import. "
        "Automatic re-compression to zlib was attempted but the resulting "
        "zarr is still not recognised by Bio-Formats.  The zarr may use an "
        "unsupported layout or contain no importable image data."
    )


def import_session_expired():
    return "Import failed because the OMERO session expired during a long-running import."


def import_parent_directory_not_writable(group_name=None, parent_id=None):
    detail = "Import failed because OMERO denied write access to the managed repository parent directory"
    if group_name:
        detail += f" for group '{group_name}'"
    if parent_id:
        detail += f" (directory id {parent_id})"
    detail += ". This usually means the group-level repository folder already exists but is owned by a different user."
    return detail


def unexpected_import_failure(detail):
    return f"Unexpected import failure: {detail}"


def method_post_required():
    return "POST required"


def unable_to_determine_username():
    return "Unable to determine username."


def invalid_user_settings_payload():
    return "Invalid user settings payload."


def invalid_special_method_settings_payload():
    return "Invalid special method settings payload."


def invalid_special_method_key():
    return "Invalid special method key."


def psycopg2_missing():
    return "psycopg2 is not installed. Please install psycopg2-binary in the OMERO.web environment."


def missing_db_credentials():
    return (
        "Database credentials (docker compose environment variables) are missing "
        "(OMP_DATA_USER/OMP_DATA_PASS/OMP_DATA_HOST/OMP_DATA_DB)."
    )


def db_connection_failed():
    return "Could not connect to the database."


def user_settings_not_persisted():
    return "User settings were not persisted to the database."


def special_method_settings_not_persisted():
    return "Special method settings were not persisted to the database."


def user_settings_save_failed():
    return "Could not save user settings."


def special_method_settings_save_failed():
    return "Could not save special method settings."


def special_method_settings_load_failed():
    return "Could not load special method settings."


def upload_file_save_failed(path):
    return f"Failed to save uploaded file: {path}."


def unexpected_error():
    return "Unexpected error."
