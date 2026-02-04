def confirm_irreversible_action():
    return "Are you absolutely sure? This action is irreversible."

def formatting_errors():
    return "Formatting error(s). Please try again."

def user_settings_saved_db():
    return "Saved user settings to database."

def user_settings_save_error():
    return "Error saving user settings: {error}"

def user_settings_saved():
    return "Saved user settings."

def unable_load_credentials():
    return "Unable to load saved credentials."

def ai_key_exists():
    return "API key exists in database for the selected provider."

def ai_key_missing():
    return "No API key saved yet for the selected provider."

def select_project():
    return "Please select a project."

def select_datasets():
    return "Please select one or more datasets."

def no_data_to_process():
    return "No data to process is available in the selected datasets."

def filename_input_empty():
    return "The input field for filename parsing cannot be empty."

def filename_input_duplicate():
    return "The input field for filename parsing cannot contain duplicate characters."

def ai_regex_use_first():
    return "Please use the AI-assisted Regex expression method first, or choose another method."

def ai_parse_use_first():
    return "Please use the AI-assisted filename parsing method first, or choose another method."

def delete_data_failed():
    return "Unable to delete data."

def error_with_details():
    return "ERROR: {error}"

def local_provider_ready():
    return "Local provider selected. Ready to process."

def provider_key_ready():
    return "API key exists in database for the selected provider. Ready to process."

def add_api_key_settings():
    return "Please add an API key for this provider in settings."

def choose_provider():
    return "Please choose a provider."

def api_key_empty():
    return "API key cannot be empty."

def testing_connection():
    return "Testing connection..."

def connection_test_passed():
    return "Connection test passed."

def unable_test_api_key():
    return "Unable to test API key."

def choose_provider_and_key():
    return "Please choose a provider and enter an API key."

def run_connection_test_first():
    return "Please run the connection test before saving this API key."

def saving_key():
    return "Saving key..."

def api_key_saved_status():
    return "API key saved."

def api_key_saved_db():
    return "API key saved to database."

def unable_save_api_key():
    return "Unable to save API key."

def ai_modal_choose_provider():
    return "Please choose a provider."

def ai_modal_add_key_selected():
    return "Please add an API key for the selected provider in settings."

def ai_modal_processing():
    return "Processing filenames..."

def ai_suggestion_fallback():
    return "AI suggestion looked unreliable, so a heuristic regex was provided instead."

def heuristic_regex_ready():
    return "Heuristic regex suggestion ready. Please repeat processing if unsatisfactory."

def regex_suggestion_ready():
    return "Regex suggestion ready. Please repeat processing if unsatisfactory."

def ai_suggestion_ready():
    return "AI suggestion ready. Please repeat processing if unsatisfactory."

def ai_process_failed():
    return "Unable to process filenames. Please try again."

def generate_regex_first():
    return "Generate a regex before transferring."

def no_datasets_found():
    return 'No datasets found in project "{projectName}"'

def unable_load_datasets():
    return "Unable to load datasets. Refresh browser and try again."

def ai_models_loading():
    return "Loading {provider} models..."

def ai_models_load_failed():
    return "Unable to load models. Please try again."


def variable_parsing_capped():
    return (
        "Variable parsing is capped at {maxParsedVariables}. "
        "Only the first {maxParsedVariables} variables will be parsed. "
        "Your filenames produced {maxVarsUncapped} variables. "
        "Consider checking your parsing method, filenames and user settings."
    )

def exit_edit_mode_first():
    return "Please exit edit mode first."

def default_var_name():
    return "rename"

def variable_names_spaces():
    return "Variable names cannot contain just empty spaces."

def variable_names_empty():
    return "Variable names cannot be empty."

def variable_set_name_required():
    return "Please provide a name for this variable set."

def variable_set_saved():
    return 'Saved variable set "{setName}" to database.'

def variable_set_save_error():
    return "Error saving variable set: {error}"

def variable_set_empty_db():
    return "Your user database is empty. Please save a variable set first."

def variable_set_select_required():
    return "Please select a variable set from the dropdown menu."

def variable_set_loaded():
    return 'Loaded variable set "{setName}" from database.'

def variable_set_load_error():
    return "Error loading variable set: {error}"

def variable_set_deleted():
    return 'Deleted variable set "{setName}" from database.'

def variable_set_delete_error():
    return "Error deleting variable set: {error}"

def job_already_running():
    return "Another job is already running. Please be patient."

def select_image_required():
    return "Select at least one image to apply changes."

def password_empty():
    return "Password cannot be empty."

def min_variables_required():
    return "Please populate at least {count} variables and try again."

def variable_names_spaces_first():
    return (
        "Variable names for any of the first {count} variables cannot contain just empty spaces."
    )

def variable_names_empty_first():
    return "Variable names for the first {count} variables cannot be empty."

def progress_start_save_job():
    return 'Starting "Save filename metadata into key-value pairs" job…'

def progress_start_acq_job():
    return 'Starting "copy acquisition metadata into key-value pairs" job…'

def job_started_save():
    return "Save filename metadata into key-value pairs job started for {totalImages} images..."

def job_started_acq():
    return "Copy acquisition metadata into key-value pairs job started for {totalImages} images..."

def progress_processed():
    return "Processed {done} of {total} images (unique IDs)."

def progress_completed():
    return "Completed. Processed {done} images (unique IDs)."

def delete_all_password_prompt():
    return "Enter your OMERO password to delete ALL key-value pairs:"

def delete_all_progress():
    return "Deleting ALL key-value pairs…"

def delete_all_job_label():
    return "Delete ALL key-value pairs"

def delete_plugin_password_prompt():
    return "Enter your OMERO password to delete ONLY plugin key-value pairs:"

def delete_plugin_progress():
    return "Deleting ONLY plugin key-value pairs…"

def delete_plugin_job_label():
    return "Delete ONLY plugin key-value pairs"

def job_started_for_images():
    return "{jobLabel} job started for {totalImages} images..."

def max_variables_reached():
    return "Maximum of {maxParsedVariables} variables allowed. Cannot add more variable name fields."

def unable_load_variable_sets():
    return "Unable to load variable sets."

def error_loading_variable_sets():
    return "Error loading variable sets"

def variable_set_saved_response():
    return "Saved variable set."

def build_message_payload(names):
    from omero_plugin_common.string_utils import build_message_payload as _build_payload

    return _build_payload(names, globals())


INDEX_MESSAGE_NAMES = (
    "confirm_irreversible_action",
    "formatting_errors",
    "user_settings_saved_db",
    "user_settings_save_error",
    "unable_load_credentials",
    "ai_key_exists",
    "ai_key_missing",
    "select_project",
    "select_datasets",
    "no_data_to_process",
    "filename_input_empty",
    "filename_input_duplicate",
    "ai_regex_use_first",
    "ai_parse_use_first",
    "delete_data_failed",
    "error_with_details",
    "local_provider_ready",
    "provider_key_ready",
    "add_api_key_settings",
    "choose_provider",
    "api_key_empty",
    "testing_connection",
    "connection_test_passed",
    "unable_test_api_key",
    "choose_provider_and_key",
    "run_connection_test_first",
    "saving_key",
    "api_key_saved_status",
    "api_key_saved_db",
    "unable_save_api_key",
    "ai_modal_choose_provider",
    "ai_modal_add_key_selected",
    "ai_modal_processing",
    "ai_suggestion_fallback",
    "heuristic_regex_ready",
    "regex_suggestion_ready",
    "ai_suggestion_ready",
    "ai_process_failed",
    "generate_regex_first",
    "no_datasets_found",
    "unable_load_datasets",
    "ai_models_loading",
    "ai_models_load_failed",
)


PREVIEW_MESSAGE_NAMES = (
    "confirm_irreversible_action",
    "variable_parsing_capped",
    "exit_edit_mode_first",
    "default_var_name",
    "variable_names_spaces",
    "variable_names_empty",
    "variable_set_name_required",
    "variable_set_saved",
    "variable_set_save_error",
    "variable_set_empty_db",
    "variable_set_select_required",
    "variable_set_loaded",
    "variable_set_load_error",
    "variable_set_deleted",
    "variable_set_delete_error",
    "job_already_running",
    "select_image_required",
    "password_empty",
    "error_with_details",
    "min_variables_required",
    "variable_names_spaces_first",
    "variable_names_empty_first",
    "progress_start_save_job",
    "progress_start_acq_job",
    "job_started_save",
    "job_started_acq",
    "progress_processed",
    "progress_completed",
    "delete_all_password_prompt",
    "delete_all_progress",
    "delete_all_job_label",
    "delete_plugin_password_prompt",
    "delete_plugin_progress",
    "delete_plugin_job_label",
    "job_started_for_images",
    "max_variables_reached",
    "unable_load_variable_sets",
    "error_loading_variable_sets",
)


def index_messages():
    return build_message_payload(INDEX_MESSAGE_NAMES)
