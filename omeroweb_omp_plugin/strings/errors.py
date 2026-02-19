def method_post_required():
    return "POST required"

def method_get_required():
    return "GET required"

def invalid_json_body():
    return "Invalid JSON body"

def missing_project_id():
    return "Missing project_id"

def missing_project_id_lower():
    return "missing project_id"

def missing_password():
    return "Missing password"

def missing_set_name():
    return "Missing set_name"

def omero_web_login_failed():
    return "OMERO.web login failed"

def no_images_found():
    return "No images found"

def map_annotations_still_present():
    return "Map annotations still present after delete."

def annotation_links_still_exist():
    return "Annotation links still exist; skipping delete."

def annotation_still_exists():
    return "Annotation still exists after delete."

def select_project_first():
    return "Select a project first."

def datasets_required():
    return "Please select one or more datasets."

def no_filenames_available():
    return "No filenames available in the selected datasets."

def no_data_to_process():
    return "No data to process is available in the selected dataset(s)."

def unable_to_determine_username():
    return "Unable to determine username."

def ai_api_key_required():
    return "Please add an API key for this provider in Settings."

def unable_to_process_filenames():
    return "Unable to process filenames. Try again or change your selections in this menu."

def filename_input_empty():
    return "The input field for filename parsing cannot be empty."

def invalid_variable_payload():
    return "Invalid variable payload."

def variable_names_empty():
    return "Variable names cannot be empty."

def variable_set_name_required():
    return "Please provide a name for this set."

def variable_set_already_exists():
    return (
        "A variable set with the same name already exists in database. "
        "Please rename or delete the existing set first."
    )

def variable_set_max_entries(max_sets):
    return (
        f"The maximum number of entries in the database is {max_sets}. "
        "Please delete a variable set first or check your user settings."
    )

def variable_set_dropdown_required():
    return "Please select a set of variables from the dropdown menu first."

def variable_set_empty_db():
    return "Your user database is empty. Please save some variables first."

def variable_set_not_found():
    return "Requested variable set was not found."

def invalid_user_settings_payload():
    return "Invalid user settings payload."

def unknown_job():
    return "unknown job"

def invalid_regex_pattern(detail):
    return f"Invalid regex pattern: {detail}"

def invalid_regex_pattern_title():
    return "Invalid regex pattern."

def wrong_password():
    return "Wrong password."

def validation_unavailable():
    return "Unable to validate credentials. Please try again later or contact the server administrator."

def provider_and_key_required():
    return "Provider and API key are required."

def api_key_empty():
    return "API key cannot be empty."

def connection_test_passed():
    return "Connection test passed."

def connection_test_failed_status(status):
    return f"Connection test failed with status {status}."

def connection_test_failed():
    return "Connection test failed. Please verify the API key."

def connection_test_not_supported(provider):
    return f"Connection testing is not supported for provider '{provider}'."


def provider_http_status(code):
    return f"Provider returned status {code}."

def provider_http_status_with_detail(code, detail):
    return f"Provider returned status {code}. {detail}"

def provider_http_retry_after(message, retry_after):
    return f"{message} Retry after {retry_after} seconds."

def provider_unreachable():
    return "Unable to reach the AI provider."

def provider_not_supported(provider):
    return f"Provider '{provider}' is not supported."

def provider_response_missing_regex():
    return "Provider response was missing the regex suggestion."

def provider_response_no_regex():
    return "Provider response did not include a regex suggestion."

def provider_response_empty():
    return "Provider response was empty."

def provider_response_row_mismatch(received, expected):
    return (
        "Provider response row count did not match the number of filenames "
        f"({received} received, {expected} expected)."
    )

def provider_response_invalid_format():
    return "Provider response format was invalid."

def provider_required():
    return "Provider is required."


def psycopg2_missing():
    return "psycopg2 is not installed. Please install psycopg2-binary in the OMERO.web environment."

def missing_db_credentials():
    return (
        "Database credentials (docker compose environment variables) are missing "
        "(OMP_DATA_USER/OMP_DATA_PASS)."
    )

def db_connection_failed():
    return "Could not connect to the database."

def variable_sets_fetch_failed():
    return "Unable to fetch saved variable sets."

def variable_set_not_persisted():
    return "Variable set was not persisted to the database."

def variable_set_save_failed():
    return "Could not save variable set."

def variable_set_load_failed():
    return "Unable to load variable set."

def variable_set_missing(set_name):
    return f"Variable set '{set_name}' does not exist."

def variable_set_delete_unconfirmed():
    return "Variable set deletion could not be confirmed."

def variable_set_delete_failed():
    return "Unable to delete variable set."

def ai_credentials_fetch_failed():
    return "Unable to fetch saved AI credentials."

def ai_credentials_save_failed():
    return "Could not save AI credentials."

def user_settings_not_persisted():
    return "User settings were not persisted to the database."

def user_settings_save_failed():
    return "Could not save user settings."

def user_settings_delete_failed():
    return "Unable to delete user settings."

def variable_sets_delete_failed():
    return "Unable to delete variable sets."

def ai_credentials_delete_failed():
    return "Unable to delete AI credentials."

def user_data_delete_failed():
    return "Unable to delete user data."

def unexpected_error():
    return "Unexpected error."

def rate_limit_exceeded(limit, window_seconds, time_str):
    return (
        f"Rate limit exceeded: You have performed more than {limit} major actions in the last "
        f"{window_seconds} seconds. Please try again in {time_str}."
    )

def help_file_not_found(path):
    return f"Help file not found: {path}"
