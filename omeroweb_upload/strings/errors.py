
def unexpected_server_error_start_upload():
    return "Unexpected server error while starting upload."


def upload_start_post_required():
    return "Upload start expects POST."


def upload_folder_not_writable():
    return "Upload folder is not writable. Please configure Omero_WEB_UPLOAD_DIR."


def no_files_provided():
    return "No files provided."


def unable_resolve_session():
    return "Unable to resolve Omero session."


def unable_resolve_host_port():
    return "Unable to resolve Omero host/port."


def invalid_file_paths(paths):
    return f"Invalid file paths: {', '.join(paths)}."


def upload_endpoint_post_required():
    return "Upload endpoint expects POST."


def upload_job_not_found():
    return "Upload job not found."


def upload_payload_mismatch():
    return "Upload payload mismatch. Please retry the upload."


def upload_batch_too_large(max_bytes):
    return f"Upload batch exceeds the limit of {max_bytes} bytes."


def unable_initialize_upload_folder():
    return "Unable to initialize upload folder."


def invalid_filename(name):
    return f"Invalid filename: {name}"


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
    return "Missing Omero connection details for import."


def upload_folder_missing_on_server():
    return "Upload folder missing on server."


def missing_staged_file(path):
    return f"Missing staged file: {path}"


def import_failed():
    return "Import failed."


def unexpected_import_failure(detail):
    return f"Unexpected import failure: {detail}"
