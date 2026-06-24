def method_post_required():
    """Return the method post required.

    Inputs: none. Output: `str`.
    """
    return "POST required"


def method_get_required():
    """Return the method get required.

    Inputs: none. Output: `str`.
    """
    return "GET required"


def invalid_json_body():
    """Return the invalid JSON body.

    Inputs: none. Output: `str`.
    """
    return "Invalid JSON body"


def missing_project_id():
    """Return the missing project ID.

    Inputs: none. Output: `str`.
    """
    return "Missing project_id"


def missing_project_id_lower():
    """Return the missing project ID lower.

    Inputs: none. Output: `str`.
    """
    return "missing project_id"


def missing_password():
    """Return the missing password.

    Inputs: none. Output: `str`.
    """
    return "Missing password"


def missing_set_name():
    """Return the missing set name.

    Inputs: none. Output: `str`.
    """
    return "Missing set_name"


def omero_web_login_failed():
    """Return the OMERO web login failed.

    Inputs: none. Output: `str`.
    """
    return "OMERO.web login failed"


def no_images_found():
    """Return the no images found.

    Inputs: none. Output: `str`.
    """
    return "No images found"


def project_write_access_required():
    """Return the project write access required message.

    Inputs: none. Output: `str`.
    """
    return "Project write access is required for this destructive action."


def map_annotations_still_present():
    """Map the annotations still present.

    Inputs: none. Output: `str`.
    """
    return "Map annotations still present after delete."


def annotation_links_still_exist():
    """Return the annotation links still exist.

    Inputs: none. Output: `str`.
    """
    return "Annotation links still exist; skipping delete."


def annotation_still_exists():
    """Return the annotation still exists.

    Inputs: none. Output: `str`.
    """
    return "Annotation still exists after delete."


def select_project_first():
    """Select the project first.

    Inputs: none. Output: `str`.
    """
    return "Select a project first."


def datasets_required():
    """Return the datasets required.

    Inputs: none. Output: `str`.
    """
    return "Please select one or more datasets."


def no_filenames_available():
    """Return the no filenames available.

    Inputs: none. Output: `str`.
    """
    return "No filenames available in the selected datasets."


def no_filenames_provided():
    """Return the no filenames provided.

    Inputs: none. Output: `str`.
    """
    return "No filenames were provided."


def no_data_to_process():
    """Return the no data to process.

    Inputs: none. Output: `str`.
    """
    return "No data to process is available in the selected dataset(s)."


def unable_to_determine_username():
    """Return the unable to determine username.

    Inputs: none. Output: `str`.
    """
    return "Unable to determine username."


def ai_api_key_required():
    """AI API key required.

    Inputs: none. Output: 'Please add an API key for this provider in Settings.'.
    """
    return "Please add an API key for this provider in Settings."


def unable_to_process_filenames():
    """Return the unable to process filenames.

    Inputs: none. Output: `str`.
    """
    return (
        "Unable to process filenames. Try again or change your selections in this menu."
    )


def filename_input_empty():
    """Return the filename input empty.

    Inputs: none. Output: `str`.
    """
    return "The input field for filename parsing cannot be empty."


def invalid_variable_payload():
    """Return the invalid variable payload.

    Inputs: none. Output: `str`.
    """
    return "Invalid variable payload."


def variable_names_empty():
    """Return the variable names empty.

    Inputs: none. Output: `str`.
    """
    return "Variable names cannot be empty."


def variable_set_name_required():
    """Return the variable set name required.

    Inputs: none. Output: `str`.
    """
    return "Please provide a name for this set."


def variable_set_already_exists():
    """Return the variable set already exists.

    Inputs: none. Output: `str`.
    """
    return (
        "A variable set with the same name already exists in database. "
        "Please rename or delete the existing set first."
    )


def variable_set_max_entries(max_sets):
    """Return the variable set max entries.

    Inputs: `max_sets`. Output: variable set max entries result.
    """
    return (
        f"The maximum number of entries in the database is {max_sets}. "
        "Please delete a variable set first or check your user settings."
    )


def variable_set_dropdown_required():
    """Return the variable set dropdown required.

    Inputs: none. Output: `str`.
    """
    return "Please select a set of variables from the dropdown menu first."


def variable_set_empty_db():
    """Variable set empty DB.

    Inputs: none. Output: 'Your user database is empty. Please save some variables
    first.'.

    first.'.
    """
    return "Your user database is empty. Please save some variables first."


def variable_set_not_found():
    """Return the variable set not found.

    Inputs: none. Output: `str`.
    """
    return "Requested variable set was not found."


def invalid_user_settings_payload():
    """Return the invalid user settings payload.

    Inputs: none. Output: `str`.
    """
    return "Invalid user settings payload."


def unknown_job():
    """Return the unknown job.

    Inputs: none. Output: `str`.
    """
    return "unknown job"


def invalid_regex_pattern(_detail=None):
    """Return the invalid regex pattern.

    Inputs: `_detail`. Output: `str`.
    """
    return "Invalid regex pattern."


def invalid_ai_parsing_data():
    """Invalid AI parsing data.

    Inputs: none. Output: 'Invalid AI parsing data.'.
    """
    return "Invalid AI parsing data."


def ai_parsing_data_missing():
    """AI parsing data missing.

    Inputs: none. Output: 'AI parsing data is missing. Please run the AI-assisted
    filename parsing routine first.'.

    filename parsing routine first.'.
    """
    return "AI parsing data is missing. Please run the AI-assisted filename parsing routine first."


def invalid_regex_pattern_title():
    """Return the invalid regex pattern title.

    Inputs: none. Output: `str`.
    """
    return "Invalid regex pattern."


def wrong_password():
    """Return the wrong password.

    Inputs: none. Output: `str`.
    """
    return "Wrong password."


def validation_unavailable():
    """Return the validation unavailable.

    Inputs: none. Output: `str`.
    """
    return (
        "Unable to validate credentials. Please try again later or contact the "
        "server administrator."
    )


def provider_and_key_required():
    """Return the provider and key required.

    Inputs: none. Output: `str`.
    """
    return "Provider and API key are required."


def api_key_empty():
    """Return the API key empty.

    Inputs: none. Output: `str`.
    """
    return "API key cannot be empty."


def connection_test_passed():
    """Return the connection test passed.

    Inputs: none. Output: `str`.
    """
    return "Connection test passed."


def connection_test_failed_status(status):
    """Return the connection test failed status.

    Inputs: `status` status. Output: status value.
    """
    return f"Connection test failed with status {status}."


def connection_test_failed():
    """Return the connection test failed.

    Inputs: none. Output: `str`.
    """
    return "Connection test failed. Please verify the API key."


def connection_test_not_supported(provider):
    """Return the connection test not supported.

    Inputs: `provider`. Output: connection test not supported result.
    """
    return f"Connection testing is not supported for provider '{provider}'."


def provider_http_status(code):
    """Return the provider HTTP status.

    Inputs: `code`. Output: ID value.
    """
    return f"Provider returned status {code}."


def provider_http_status_with_detail(code, detail):
    """Return the provider HTTP status with detail.

    Inputs: `code`, `detail`. Output: ID value.
    """
    return f"Provider returned status {code}. {detail}"


def provider_http_retry_after(message, retry_after):
    """Return the provider HTTP retry after.

    Inputs: `message`, `retry_after`. Output: ID value.
    """
    return f"{message} Retry after {retry_after} seconds."


def provider_unreachable():
    """Return the provider unreachable.

    Inputs: none. Output: `str`.
    """
    return "Unable to reach the AI provider."


def provider_not_supported(provider):
    """Return the provider not supported.

    Inputs: `provider`. Output: ID value.
    """
    return f"Provider '{provider}' is not supported."


def provider_response_missing_regex():
    """Return the provider response missing regex.

    Inputs: none. Output: `str`.
    """
    return "Provider response was missing the regex suggestion."


def provider_response_no_regex():
    """Return the provider response no regex.

    Inputs: none. Output: `str`.
    """
    return "Provider response did not include a regex suggestion."


def provider_response_empty():
    """Return the provider response empty.

    Inputs: none. Output: `str`.
    """
    return "Provider response was empty."


def provider_response_row_mismatch(received, expected):
    """Return the provider response row mismatch.

    Inputs: `received`, `expected`. Output: ID value.
    """
    return (
        "Provider response row count did not match the number of filenames "
        f"({received} received, {expected} expected)."
    )


def provider_response_invalid_format():
    """Return the provider response invalid format.

    Inputs: none. Output: `str`.
    """
    return "Provider response format was invalid."


def provider_required():
    """Return the provider required.

    Inputs: none. Output: `str`.
    """
    return "Provider is required."


def psycopg2_missing():
    """Return the psycopg2 missing.

    Inputs: none. Output: `str`.
    """
    return "psycopg2 is not installed. Please install psycopg2-binary in the OMERO.web environment."


def missing_db_credentials():
    """Missing DB credentials.

    Inputs: none. Output: 'Database credentials (docker compose environment variables)
    are missing (OMP_DATA_USER/OMP_DATA_PASS).'.

    are missing (OMP_DATA_USER/OMP_DATA_PASS).'.
    """
    return (
        "Database credentials (docker compose environment variables) are missing "
        "(OMP_DATA_USER/OMP_DATA_PASS)."
    )


def db_connection_failed():
    """DB connection failed.

    Inputs: none. Output: 'Could not connect to the database.'.
    """
    return "Could not connect to the database."


def variable_sets_fetch_failed():
    """Return the variable sets fetch failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to fetch saved variable sets."


def variable_set_not_persisted():
    """Return the variable set not persisted.

    Inputs: none. Output: `str`.
    """
    return "Variable set was not persisted to the database."


def variable_set_save_failed():
    """Return the variable set save failed.

    Inputs: none. Output: `str`.
    """
    return "Could not save variable set."


def variable_set_load_failed():
    """Return the variable set load failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to load variable set."


def variable_set_missing(set_name):
    """Return the variable set missing.

    Inputs: `set_name`. Output: variable set missing result.
    """
    return f"Variable set '{set_name}' does not exist."


def variable_set_delete_unconfirmed():
    """Return the variable set delete unconfirmed.

    Inputs: none. Output: `str`.
    """
    return "Variable set deletion could not be confirmed."


def variable_set_delete_failed():
    """Return the variable set delete failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete variable set."


def unable_delete_plugin_annotations():
    """Return the unable delete plugin annotations.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete plugin annotations."


def unable_delete_annotations():
    """Return the unable delete annotations.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete annotations."


def ai_credentials_fetch_failed():
    """AI credentials fetch failed.

    Inputs: none. Output: 'Unable to fetch saved AI credentials.'.
    """
    return "Unable to fetch saved AI credentials."


def ai_credentials_save_failed():
    """AI credentials save failed.

    Inputs: none. Output: 'Could not save AI credentials.'.
    """
    return "Could not save AI credentials."


def user_settings_not_persisted():
    """Return the user settings not persisted.

    Inputs: none. Output: `str`.
    """
    return "User settings were not persisted to the database."


def user_settings_save_failed():
    """Return the user settings save failed.

    Inputs: none. Output: `str`.
    """
    return "Could not save user settings."


def user_settings_delete_failed():
    """Return the user settings delete failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete user settings."


def variable_sets_delete_failed():
    """Return the variable sets delete failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete variable sets."


def ai_credentials_delete_failed():
    """AI credentials delete failed.

    Inputs: none. Output: 'Unable to delete AI credentials.'.
    """
    return "Unable to delete AI credentials."


def user_data_delete_failed():
    """Return the user data delete failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete user data."


def unexpected_error():
    """Return the unexpected error.

    Inputs: none. Output: `str`.
    """
    return "Unexpected error."


def rate_limit_exceeded(limit, window_seconds, time_str):
    """Return the rate limit exceeded.

    Inputs: `limit`, `window_seconds`, `time_str`. Output: rate limit exceeded result.
    """
    return (
        f"Rate limit exceeded: You have performed more than {limit} major actions in the last "
        f"{window_seconds} seconds. Please try again in {time_str}."
    )


def help_file_not_found(path):
    """Return the help file not found.

    Inputs: `path` path. Output: help file not found result.
    """
    return f"Help file not found: {path}"
