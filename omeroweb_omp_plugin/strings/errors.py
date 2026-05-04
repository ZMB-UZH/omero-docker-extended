def method_post_required():
    """Method post required.

    Inputs: none. Output: 'POST required'.
    """
    return "POST required"


def method_get_required():
    """Method get required.

    Inputs: none. Output: 'GET required'.
    """
    return "GET required"


def invalid_json_body():
    """Invalid JSON body.

    Inputs: none. Output: 'Invalid JSON body'.
    """
    return "Invalid JSON body"


def missing_project_id():
    """Missing project ID.

    Inputs: none. Output: 'Missing project_id'.
    """
    return "Missing project_id"


def missing_project_id_lower():
    """Missing project ID lower.

    Inputs: none. Output: 'missing project_id'.
    """
    return "missing project_id"


def missing_password():
    """Missing password.

    Inputs: none. Output: 'Missing password'.
    """
    return "Missing password"


def missing_set_name():
    """Missing set name.

    Inputs: none. Output: 'Missing set_name'.
    """
    return "Missing set_name"


def omero_web_login_failed():
    """OMERO web login failed.

    Inputs: none. Output: 'OMERO.web login failed'.
    """
    return "OMERO.web login failed"


def no_images_found():
    """No images found.

    Inputs: none. Output: 'No images found'.
    """
    return "No images found"


def map_annotations_still_present():
    """Map annotations still present.

    Inputs: none. Output: 'Map annotations still present after delete.'.
    """
    return "Map annotations still present after delete."


def annotation_links_still_exist():
    """Annotation links still exist.

    Inputs: none. Output: 'Annotation links still exist; skipping delete.'.
    """
    return "Annotation links still exist; skipping delete."


def annotation_still_exists():
    """Annotation still exists.

    Inputs: none. Output: 'Annotation still exists after delete.'.
    """
    return "Annotation still exists after delete."


def select_project_first():
    """Select project first.

    Inputs: none. Output: 'Select a project first.'.
    """
    return "Select a project first."


def datasets_required():
    """Datasets required.

    Inputs: none. Output: 'Please select one or more datasets.'.
    """
    return "Please select one or more datasets."


def no_filenames_available():
    """No filenames available.

    Inputs: none. Output: 'No filenames available in the selected datasets.'.
    """
    return "No filenames available in the selected datasets."


def no_filenames_provided():
    """No filenames provided.

    Inputs: none. Output: 'No filenames were provided.'.
    """
    return "No filenames were provided."


def no_data_to_process():
    """No data to process.

    Inputs: none. Output: 'No data to process is available in the selected dataset(s).'.
    """
    return "No data to process is available in the selected dataset(s)."


def unable_to_determine_username():
    """Unable to determine username.

    Inputs: none. Output: 'Unable to determine username.'.
    """
    return "Unable to determine username."


def ai_api_key_required():
    """AI API key required.

    Inputs: none. Output: 'Please add an API key for this provider in Settings.'.
    """
    return "Please add an API key for this provider in Settings."


def unable_to_process_filenames():
    """Unable to process filenames.

    Inputs: none. Output: 'Unable to process filenames. Try again or change your
    selections in this menu.'.

    selections in this menu.'.
    """
    return (
        "Unable to process filenames. Try again or change your selections in this menu."
    )


def filename_input_empty():
    """Filename input empty.

    Inputs: none. Output: 'The input field for filename parsing cannot be empty.'.
    """
    return "The input field for filename parsing cannot be empty."


def invalid_variable_payload():
    """Invalid variable payload.

    Inputs: none. Output: 'Invalid variable payload.'.
    """
    return "Invalid variable payload."


def variable_names_empty():
    """Variable names empty.

    Inputs: none. Output: 'Variable names cannot be empty.'.
    """
    return "Variable names cannot be empty."


def variable_set_name_required():
    """Variable set name required.

    Inputs: none. Output: 'Please provide a name for this set.'.
    """
    return "Please provide a name for this set."


def variable_set_already_exists():
    """Variable set already exists.

    Inputs: none. Output: 'A variable set with the same name already exists in database.
    Please rename or delete the existing set first.'.

    Please rename or delete the existing set first.'.
    """
    return (
        "A variable set with the same name already exists in database. "
        "Please rename or delete the existing set first."
    )


def variable_set_max_entries(max_sets):
    """Variable set max entries.

    Inputs: `max_sets`. Output: computed value.
    """
    return (
        f"The maximum number of entries in the database is {max_sets}. "
        "Please delete a variable set first or check your user settings."
    )


def variable_set_dropdown_required():
    """Variable set dropdown required.

    Inputs: none. Output: 'Please select a set of variables from the dropdown menu
    first.'.

    first.'.
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
    """Variable set not found.

    Inputs: none. Output: 'Requested variable set was not found.'.
    """
    return "Requested variable set was not found."


def invalid_user_settings_payload():
    """Invalid user settings payload.

    Inputs: none. Output: 'Invalid user settings payload.'.
    """
    return "Invalid user settings payload."


def unknown_job():
    """Unknown job.

    Inputs: none. Output: 'unknown job'.
    """
    return "unknown job"


def invalid_regex_pattern(_detail=None):
    """Invalid regex pattern.

    Inputs: `_detail`. Output: 'Invalid regex pattern.'.
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
    """Invalid regex pattern title.

    Inputs: none. Output: 'Invalid regex pattern.'.
    """
    return "Invalid regex pattern."


def wrong_password():
    """Wrong password.

    Inputs: none. Output: 'Wrong password.'.
    """
    return "Wrong password."


def validation_unavailable():
    """Validation unavailable.

    Inputs: none. Output: 'Unable to validate credentials. Please try again later or
    contact the server administrator.'.

    contact the server administrator.'.
    """
    return (
        "Unable to validate credentials. Please try again later or contact the "
        "server administrator."
    )


def provider_and_key_required():
    """Provider and key required.

    Inputs: none. Output: 'Provider and API key are required.'.
    """
    return "Provider and API key are required."


def api_key_empty():
    """API key empty.

    Inputs: none. Output: 'API key cannot be empty.'.
    """
    return "API key cannot be empty."


def connection_test_passed():
    """Connection test passed.

    Inputs: none. Output: 'Connection test passed.'.
    """
    return "Connection test passed."


def connection_test_failed_status(status):
    """Connection test failed status.

    Inputs: `status`. Output: computed value.
    """
    return f"Connection test failed with status {status}."


def connection_test_failed():
    """Connection test failed.

    Inputs: none. Output: 'Connection test failed. Please verify the API key.'.
    """
    return "Connection test failed. Please verify the API key."


def connection_test_not_supported(provider):
    """Connection test not supported.

    Inputs: `provider`. Output: computed value.
    """
    return f"Connection testing is not supported for provider '{provider}'."


def provider_http_status(code):
    """Provider HTTP status.

    Inputs: `code`. Output: computed value.
    """
    return f"Provider returned status {code}."


def provider_http_status_with_detail(code, detail):
    """Provider HTTP status with detail.

    Inputs: `code`, `detail`. Output: computed value.
    """
    return f"Provider returned status {code}. {detail}"


def provider_http_retry_after(message, retry_after):
    """Provider HTTP retry after.

    Inputs: `message`, `retry_after`. Output: computed value.
    """
    return f"{message} Retry after {retry_after} seconds."


def provider_unreachable():
    """Provider unreachable.

    Inputs: none. Output: 'Unable to reach the AI provider.'.
    """
    return "Unable to reach the AI provider."


def provider_not_supported(provider):
    """Provider not supported.

    Inputs: `provider`. Output: computed value.
    """
    return f"Provider '{provider}' is not supported."


def provider_response_missing_regex():
    """Provider response missing regex.

    Inputs: none. Output: 'Provider response was missing the regex suggestion.'.
    """
    return "Provider response was missing the regex suggestion."


def provider_response_no_regex():
    """Provider response no regex.

    Inputs: none. Output: 'Provider response did not include a regex suggestion.'.
    """
    return "Provider response did not include a regex suggestion."


def provider_response_empty():
    """Provider response empty.

    Inputs: none. Output: 'Provider response was empty.'.
    """
    return "Provider response was empty."


def provider_response_row_mismatch(received, expected):
    """Provider response row mismatch.

    Inputs: `received`, `expected`. Output: computed value.
    """
    return (
        "Provider response row count did not match the number of filenames "
        f"({received} received, {expected} expected)."
    )


def provider_response_invalid_format():
    """Provider response invalid format.

    Inputs: none. Output: 'Provider response format was invalid.'.
    """
    return "Provider response format was invalid."


def provider_required():
    """Provider required.

    Inputs: none. Output: 'Provider is required.'.
    """
    return "Provider is required."


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
    """Variable sets fetch failed.

    Inputs: none. Output: 'Unable to fetch saved variable sets.'.
    """
    return "Unable to fetch saved variable sets."


def variable_set_not_persisted():
    """Variable set not persisted.

    Inputs: none. Output: 'Variable set was not persisted to the database.'.
    """
    return "Variable set was not persisted to the database."


def variable_set_save_failed():
    """Variable set save failed.

    Inputs: none. Output: 'Could not save variable set.'.
    """
    return "Could not save variable set."


def variable_set_load_failed():
    """Variable set load failed.

    Inputs: none. Output: 'Unable to load variable set.'.
    """
    return "Unable to load variable set."


def variable_set_missing(set_name):
    """Variable set missing.

    Inputs: `set_name`. Output: computed value.
    """
    return f"Variable set '{set_name}' does not exist."


def variable_set_delete_unconfirmed():
    """Variable set delete unconfirmed.

    Inputs: none. Output: 'Variable set deletion could not be confirmed.'.
    """
    return "Variable set deletion could not be confirmed."


def variable_set_delete_failed():
    """Variable set delete failed.

    Inputs: none. Output: 'Unable to delete variable set.'.
    """
    return "Unable to delete variable set."


def unable_delete_plugin_annotations():
    """Unable delete plugin annotations.

    Inputs: none. Output: 'Unable to delete plugin annotations.'.
    """
    return "Unable to delete plugin annotations."


def unable_delete_annotations():
    """Unable delete annotations.

    Inputs: none. Output: 'Unable to delete annotations.'.
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
    """User settings not persisted.

    Inputs: none. Output: 'User settings were not persisted to the database.'.
    """
    return "User settings were not persisted to the database."


def user_settings_save_failed():
    """User settings save failed.

    Inputs: none. Output: 'Could not save user settings.'.
    """
    return "Could not save user settings."


def user_settings_delete_failed():
    """User settings delete failed.

    Inputs: none. Output: 'Unable to delete user settings.'.
    """
    return "Unable to delete user settings."


def variable_sets_delete_failed():
    """Variable sets delete failed.

    Inputs: none. Output: 'Unable to delete variable sets.'.
    """
    return "Unable to delete variable sets."


def ai_credentials_delete_failed():
    """AI credentials delete failed.

    Inputs: none. Output: 'Unable to delete AI credentials.'.
    """
    return "Unable to delete AI credentials."


def user_data_delete_failed():
    """User data delete failed.

    Inputs: none. Output: 'Unable to delete user data.'.
    """
    return "Unable to delete user data."


def unexpected_error():
    """Unexpected error.

    Inputs: none. Output: 'Unexpected error.'.
    """
    return "Unexpected error."


def rate_limit_exceeded(limit, window_seconds, time_str):
    """Rate limit exceeded.

    Inputs: `limit`, `window_seconds`, `time_str`. Output: computed value.
    """
    return (
        f"Rate limit exceeded: You have performed more than {limit} major actions in the last "
        f"{window_seconds} seconds. Please try again in {time_str}."
    )


def help_file_not_found(path):
    """Help file not found.

    Inputs: `path`. Output: computed value.
    """
    return f"Help file not found: {path}"
