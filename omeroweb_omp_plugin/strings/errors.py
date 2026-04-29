def method_post_required():
    """Handle method post required."""
    return "POST required"


def method_get_required():
    """Handle method get required."""
    return "GET required"


def invalid_json_body():
    """Handle invalid JSON body."""
    return "Invalid JSON body"


def missing_project_id():
    """Handle missing project identifier."""
    return "Missing project_id"


def missing_project_id_lower():
    """Handle missing project identifier lower."""
    return "missing project_id"


def missing_password():
    """Handle missing password."""
    return "Missing password"


def missing_set_name():
    """Handle missing set name."""
    return "Missing set_name"


def omero_web_login_failed():
    """Handle OMERO web login failed."""
    return "OMERO.web login failed"


def no_images_found():
    """Handle no images found."""
    return "No images found"


def map_annotations_still_present():
    """Handle map annotations still present."""
    return "Map annotations still present after delete."


def annotation_links_still_exist():
    """Handle annotation links still exist."""
    return "Annotation links still exist; skipping delete."


def annotation_still_exists():
    """Handle annotation still exists."""
    return "Annotation still exists after delete."


def select_project_first():
    """Handle select project first."""
    return "Select a project first."


def datasets_required():
    """Handle datasets required."""
    return "Please select one or more datasets."


def no_filenames_available():
    """Handle no filenames available."""
    return "No filenames available in the selected datasets."


def no_filenames_provided():
    """Handle no filenames provided."""
    return "No filenames were provided."


def no_data_to_process():
    """Handle no data to process."""
    return "No data to process is available in the selected dataset(s)."


def unable_to_determine_username():
    """Handle unable to determine username."""
    return "Unable to determine username."


def ai_api_key_required():
    """Handle ai API key required."""
    return "Please add an API key for this provider in Settings."


def unable_to_process_filenames():
    """Handle unable to process filenames."""
    return (
        "Unable to process filenames. Try again or change your selections in this menu."
    )


def filename_input_empty():
    """Handle filename input empty."""
    return "The input field for filename parsing cannot be empty."


def invalid_variable_payload():
    """Handle invalid variable payload."""
    return "Invalid variable payload."


def variable_names_empty():
    """Handle variable names empty."""
    return "Variable names cannot be empty."


def variable_set_name_required():
    """Handle variable set name required."""
    return "Please provide a name for this set."


def variable_set_already_exists():
    """Handle variable set already exists."""
    return (
        "A variable set with the same name already exists in database. "
        "Please rename or delete the existing set first."
    )


def variable_set_max_entries(max_sets):
    """Handle variable set max entries."""
    return (
        f"The maximum number of entries in the database is {max_sets}. "
        "Please delete a variable set first or check your user settings."
    )


def variable_set_dropdown_required():
    """Handle variable set dropdown required."""
    return "Please select a set of variables from the dropdown menu first."


def variable_set_empty_db():
    """Handle variable set empty database."""
    return "Your user database is empty. Please save some variables first."


def variable_set_not_found():
    """Handle variable set not found."""
    return "Requested variable set was not found."


def invalid_user_settings_payload():
    """Handle invalid user settings payload."""
    return "Invalid user settings payload."


def unknown_job():
    """Handle unknown job."""
    return "unknown job"


def invalid_regex_pattern(_detail=None):
    """Handle invalid regex pattern."""
    return "Invalid regex pattern."


def invalid_ai_parsing_data():
    """Handle invalid ai parsing data."""
    return "Invalid AI parsing data."


def ai_parsing_data_missing():
    """Handle ai parsing data missing."""
    return "AI parsing data is missing. Please run the AI-assisted filename parsing routine first."


def invalid_regex_pattern_title():
    """Handle invalid regex pattern title."""
    return "Invalid regex pattern."


def wrong_password():
    """Handle wrong password."""
    return "Wrong password."


def validation_unavailable():
    """Handle validation unavailable."""
    return "Unable to validate credentials. Please try again later or contact the server administrator."


def provider_and_key_required():
    """Handle provider and key required."""
    return "Provider and API key are required."


def api_key_empty():
    """Handle API key empty."""
    return "API key cannot be empty."


def connection_test_passed():
    """Handle connection test passed."""
    return "Connection test passed."


def connection_test_failed_status(status):
    """Handle connection test failed status."""
    return f"Connection test failed with status {status}."


def connection_test_failed():
    """Handle connection test failed."""
    return "Connection test failed. Please verify the API key."


def connection_test_not_supported(provider):
    """Handle connection test not supported."""
    return f"Connection testing is not supported for provider '{provider}'."


def provider_http_status(code):
    """Handle provider HTTP status."""
    return f"Provider returned status {code}."


def provider_http_status_with_detail(code, detail):
    """Handle provider HTTP status with detail."""
    return f"Provider returned status {code}. {detail}"


def provider_http_retry_after(message, retry_after):
    """Handle provider HTTP retry after."""
    return f"{message} Retry after {retry_after} seconds."


def provider_unreachable():
    """Handle provider unreachable."""
    return "Unable to reach the AI provider."


def provider_not_supported(provider):
    """Handle provider not supported."""
    return f"Provider '{provider}' is not supported."


def provider_response_missing_regex():
    """Handle provider response missing regex."""
    return "Provider response was missing the regex suggestion."


def provider_response_no_regex():
    """Handle provider response no regex."""
    return "Provider response did not include a regex suggestion."


def provider_response_empty():
    """Handle provider response empty."""
    return "Provider response was empty."


def provider_response_row_mismatch(received, expected):
    """Handle provider response row mismatch."""
    return (
        "Provider response row count did not match the number of filenames "
        f"({received} received, {expected} expected)."
    )


def provider_response_invalid_format():
    """Handle provider response invalid format."""
    return "Provider response format was invalid."


def provider_required():
    """Handle provider required."""
    return "Provider is required."


def psycopg2_missing():
    """Handle psycopg2 missing."""
    return "psycopg2 is not installed. Please install psycopg2-binary in the OMERO.web environment."


def missing_db_credentials():
    """Handle missing database credentials."""
    return (
        "Database credentials (docker compose environment variables) are missing "
        "(OMP_DATA_USER/OMP_DATA_PASS)."
    )


def db_connection_failed():
    """Handle database connection failed."""
    return "Could not connect to the database."


def variable_sets_fetch_failed():
    """Handle variable sets fetch failed."""
    return "Unable to fetch saved variable sets."


def variable_set_not_persisted():
    """Handle variable set not persisted."""
    return "Variable set was not persisted to the database."


def variable_set_save_failed():
    """Handle variable set save failed."""
    return "Could not save variable set."


def variable_set_load_failed():
    """Handle variable set load failed."""
    return "Unable to load variable set."


def variable_set_missing(set_name):
    """Handle variable set missing."""
    return f"Variable set '{set_name}' does not exist."


def variable_set_delete_unconfirmed():
    """Handle variable set delete unconfirmed."""
    return "Variable set deletion could not be confirmed."


def variable_set_delete_failed():
    """Handle variable set delete failed."""
    return "Unable to delete variable set."


def unable_delete_plugin_annotations():
    """Handle unable delete plugin annotations."""
    return "Unable to delete plugin annotations."


def unable_delete_annotations():
    """Handle unable delete annotations."""
    return "Unable to delete annotations."


def ai_credentials_fetch_failed():
    """Handle ai credentials fetch failed."""
    return "Unable to fetch saved AI credentials."


def ai_credentials_save_failed():
    """Handle ai credentials save failed."""
    return "Could not save AI credentials."


def user_settings_not_persisted():
    """Handle user settings not persisted."""
    return "User settings were not persisted to the database."


def user_settings_save_failed():
    """Handle user settings save failed."""
    return "Could not save user settings."


def user_settings_delete_failed():
    """Handle user settings delete failed."""
    return "Unable to delete user settings."


def variable_sets_delete_failed():
    """Handle variable sets delete failed."""
    return "Unable to delete variable sets."


def ai_credentials_delete_failed():
    """Handle ai credentials delete failed."""
    return "Unable to delete AI credentials."


def user_data_delete_failed():
    """Handle user data delete failed."""
    return "Unable to delete user data."


def unexpected_error():
    """Handle unexpected error."""
    return "Unexpected error."


def rate_limit_exceeded(limit, window_seconds, time_str):
    """Handle rate limit exceeded."""
    return (
        f"Rate limit exceeded: You have performed more than {limit} major actions in the last "
        f"{window_seconds} seconds. Please try again in {time_str}."
    )


def help_file_not_found(path):
    """Handle help file not found."""
    return f"Help file not found: {path}"
