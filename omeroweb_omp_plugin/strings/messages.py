def confirm_irreversible_action():
    """Confirm the irreversible action.

    Inputs: none. Output: `str`.
    """
    return "Are you absolutely sure? This action is irreversible."


def formatting_errors():
    """Return the formatting errors.

    Inputs: none. Output: `str`.
    """
    return "Formatting error(s). Please try again."


def user_settings_saved_db():
    """User settings saved DB.

    Inputs: none. Output: 'Saved user settings to database.'.
    """
    return "Saved user settings to database."


def user_settings_save_error():
    """Return the user settings save error.

    Inputs: none. Output: `str`.
    """
    return "Error saving user settings: {error}"


def user_settings_saved():
    """Return the user settings saved.

    Inputs: none. Output: `str`.
    """
    return "Saved user settings."


def unable_load_credentials():
    """Return the unable load credentials.

    Inputs: none. Output: `str`.
    """
    return "Unable to load saved credentials."


def ai_key_exists():
    """AI key exists.

    Inputs: none. Output: 'API key exists in database for the selected provider.'.
    """
    return "API key exists in database for the selected provider."


def ai_key_missing():
    """AI key missing.

    Inputs: none. Output: 'No API key saved yet for the selected provider.'.
    """
    return "No API key saved yet for the selected provider."


def select_project():
    """Select the project.

    Inputs: none. Output: `str`.
    """
    return "Please select a project."


def select_datasets():
    """Select the datasets.

    Inputs: none. Output: `str`.
    """
    return "Please select one or more datasets."


def no_data_to_process():
    """Return the no data to process.

    Inputs: none. Output: `str`.
    """
    return "No data to process is available in the selected datasets."


def filename_input_empty():
    """Return the filename input empty.

    Inputs: none. Output: `str`.
    """
    return "The input field for filename parsing cannot be empty."


def filename_input_duplicate():
    """Return the filename input duplicate.

    Inputs: none. Output: `str`.
    """
    return "The input field for filename parsing cannot contain duplicate characters."


def ai_regex_use_first():
    """AI regex use first.

    Inputs: none. Output: 'Please use the AI-assisted Regex expression method first, or
    choose another method.'.

    choose another method.'.
    """
    return "Please use the AI-assisted Regex expression method first, or choose another method."


def ai_parse_use_first():
    """AI parse use first.

    Inputs: none. Output: 'Please use the AI-assisted filename parsing method first, or
    choose another method.'.

    choose another method.'.
    """
    return "Please use the AI-assisted filename parsing method first, or choose another method."


def delete_data_failed():
    """Delete the data failed.

    Inputs: none. Output: `str`.
    """
    return "Unable to delete data."


def error_with_details():
    """Return the error with details.

    Inputs: none. Output: `str`.
    """
    return "ERROR: {error}"


def local_provider_ready():
    """Return the local provider ready.

    Inputs: none. Output: `str`.
    """
    return "Local provider selected. Ready to process."


def provider_key_ready():
    """Return the provider key ready.

    Inputs: none. Output: `str`.
    """
    return "API key exists in database for the selected provider. Ready to process."


def add_api_key_settings():
    """Add the API key settings.

    Inputs: none. Output: `str`.
    """
    return "Please add an API key for this provider in settings."


def choose_provider():
    """Return the choose provider.

    Inputs: none. Output: `str`.
    """
    return "Please choose a provider."


def api_key_empty():
    """Return the API key empty.

    Inputs: none. Output: `str`.
    """
    return "API key cannot be empty."


def testing_connection():
    """Return the testing connection.

    Inputs: none. Output: `str`.
    """
    return "Testing connection..."


def connection_test_passed():
    """Return the connection test passed.

    Inputs: none. Output: `str`.
    """
    return "Connection test passed."


def unable_test_api_key():
    """Return the unable test API key.

    Inputs: none. Output: `str`.
    """
    return "Unable to test API key."


def choose_provider_and_key():
    """Return the choose provider and key.

    Inputs: none. Output: `str`.
    """
    return "Please choose a provider and enter an API key."


def run_connection_test_first():
    """Return the prompt shown before saving an untested key.

    Inputs: none. Output: 'Please run the connection test before saving this API key.'.
    """
    return "Please run the connection test before saving this API key."


def saving_key():
    """Return the saving key.

    Inputs: none. Output: `str`.
    """
    return "Saving key..."


def api_key_saved_status():
    """Return the API key saved status.

    Inputs: none. Output: `str`.
    """
    return "API key saved."


def api_key_saved_db():
    """API key saved DB.

    Inputs: none. Output: 'API key saved to database.'.
    """
    return "API key saved to database."


def unable_save_api_key():
    """Return the unable save API key.

    Inputs: none. Output: `str`.
    """
    return "Unable to save API key."


def ai_modal_choose_provider():
    """AI modal choose provider.

    Inputs: none. Output: 'Please choose a provider.'.
    """
    return "Please choose a provider."


def ai_modal_add_key_selected():
    """AI modal add key selected.

    Inputs: none. Output: 'Please add an API key for the selected provider in
    settings.'.

    settings.'.
    """
    return "Please add an API key for the selected provider in settings."


def ai_modal_processing():
    """AI modal processing.

    Inputs: none. Output: 'Processing filenames...'.
    """
    return "Processing filenames..."


def ai_suggestion_fallback():
    """AI suggestion fallback.

    Inputs: none. Output: 'AI suggestion looked unreliable, so a heuristic regex was
    provided instead.'.

    provided instead.'.
    """
    return "AI suggestion looked unreliable, so a heuristic regex was provided instead."


def heuristic_regex_ready():
    """Return the heuristic regex ready.

    Inputs: none. Output: `str`.
    """
    return (
        "Heuristic regex suggestion ready. Please repeat processing if unsatisfactory."
    )


def regex_suggestion_ready():
    """Return the regex suggestion ready.

    Inputs: none. Output: `str`.
    """
    return "Regex suggestion ready. Please repeat processing if unsatisfactory."


def ai_suggestion_ready():
    """AI suggestion ready.

    Inputs: none. Output: 'AI suggestion ready. Please repeat processing if
    unsatisfactory.'.

    unsatisfactory.'.
    """
    return "AI suggestion ready. Please repeat processing if unsatisfactory."


def ai_process_failed():
    """AI process failed.

    Inputs: none. Output: 'Unable to process filenames. Please try again.'.
    """
    return "Unable to process filenames. Please try again."


def generate_regex_first():
    """Generate the regex first.

    Inputs: none. Output: `str`.
    """
    return "Generate a regex before transferring."


def no_datasets_found():
    """Return the no datasets found.

    Inputs: none. Output: `str`.
    """
    return 'No datasets found in project "{projectName}"'


def unable_load_datasets():
    """Return the unable load datasets.

    Inputs: none. Output: `str`.
    """
    return "Unable to load datasets. Refresh browser and try again."


def ai_models_loading():
    """AI models loading.

    Inputs: none. Output: 'Loading {provider} models...'.
    """
    return "Loading {provider} models..."


def ai_models_load_failed():
    """AI models load failed.

    Inputs: none. Output: 'Unable to load models. Please try again.'.
    """
    return "Unable to load models. Please try again."


def variable_parsing_capped():
    """Return the variable parsing capped.

    Inputs: none. Output: `str`.
    """
    return (
        "Variable parsing is capped at {maxParsedVariables}. "
        "Only the first {maxParsedVariables} variables will be parsed. "
        "Your filenames produced {maxVarsUncapped} variables. "
        "Consider checking your parsing method, filenames and user settings."
    )


def exit_edit_mode_first():
    """Return the exit edit mode first.

    Inputs: none. Output: `str`.
    """
    return "Please exit edit mode first."


def default_var_name():
    """Return the default var name.

    Inputs: none. Output: `str`.
    """
    return "rename"


def variable_names_spaces():
    """Return the variable names spaces.

    Inputs: none. Output: `str`.
    """
    return "Variable names cannot contain just empty spaces."


def variable_names_empty():
    """Return the variable names empty.

    Inputs: none. Output: `str`.
    """
    return "Variable names cannot be empty."


def variable_set_name_required():
    """Return the variable set name required.

    Inputs: none. Output: `str`.
    """
    return "Please provide a name for this variable set."


def variable_set_saved():
    """Return the variable set saved.

    Inputs: none. Output: `str`.
    """
    return 'Saved variable set "{setName}" to database.'


def variable_set_save_error():
    """Return the variable set save error.

    Inputs: none. Output: `str`.
    """
    return "Error saving variable set: {error}"


def variable_set_empty_db():
    """Variable set empty DB.

    Inputs: none. Output: 'Your user database is empty. Please save a variable set
    first.'.

    first.'.
    """
    return "Your user database is empty. Please save a variable set first."


def variable_set_select_required():
    """Return the variable set select required.

    Inputs: none. Output: `str`.
    """
    return "Please select a variable set from the dropdown menu."


def variable_set_loaded():
    """Return the variable set loaded.

    Inputs: none. Output: `str`.
    """
    return 'Loaded variable set "{setName}" from database.'


def variable_set_load_error():
    """Return the variable set load error.

    Inputs: none. Output: `str`.
    """
    return "Error loading variable set: {error}"


def variable_set_deleted():
    """Return the variable set deleted.

    Inputs: none. Output: `str`.
    """
    return 'Deleted variable set "{setName}" from database.'


def variable_set_delete_error():
    """Return the variable set delete error.

    Inputs: none. Output: `str`.
    """
    return "Error deleting variable set: {error}"


def job_already_running():
    """Return the job already running.

    Inputs: none. Output: `str`.
    """
    return "Another job is already running. Please be patient."


def select_image_required():
    """Select the image required.

    Inputs: none. Output: `str`.
    """
    return "Select at least one image to apply changes."


def password_empty():
    """Return the password empty.

    Inputs: none. Output: `str`.
    """
    return "Password cannot be empty."


def min_variables_required():
    """Return the min variables required.

    Inputs: none. Output: `str`.
    """
    return "Please populate at least {count} variables and try again."


def variable_names_spaces_first():
    """Return the variable names spaces first.

    Inputs: none. Output: `str`.
    """
    return "Variable names for any of the first {count} variables cannot contain just empty spaces."


def variable_names_empty_first():
    """Return the variable names empty first.

    Inputs: none. Output: `str`.
    """
    return "Variable names for the first {count} variables cannot be empty."


def progress_start_save_job():
    """Return the progress start save job.

    Inputs: none. Output: `str`.
    """
    return 'Starting "Save filename metadata into key-value pairs" job…'


def progress_start_acq_job():
    """Return the progress start acq job.

    Inputs: none. Output: `str`.
    """
    return 'Starting "copy acquisition metadata into key-value pairs" job…'


def job_started_save():
    """Return the job started save.

    Inputs: none. Output: `str`.
    """
    return "Save filename metadata into key-value pairs job started for {totalImages} images..."


def job_started_acq():
    """Return the job started acq.

    Inputs: none. Output: `str`.
    """
    return "Copy acquisition metadata into key-value pairs job started for {totalImages} images..."


def progress_processed():
    """Return the progress processed.

    Inputs: none. Output: `str`.
    """
    return "Processed {done} of {total} images (unique IDs)."


def progress_completed():
    """Return the progress completed.

    Inputs: none. Output: `str`.
    """
    return "Completed. Processed {done} images (unique IDs)."


def delete_all_password_prompt():
    """Delete the all password prompt.

    Inputs: none. Output: `str`.
    """
    return "Enter your OMERO password to delete ALL key-value pairs:"


def delete_all_progress():
    """Delete the all progress.

    Inputs: none. Output: `str`.
    """
    return "Deleting ALL key-value pairs…"


def delete_all_job_label():
    """Delete the all job label.

    Inputs: none. Output: `str`.
    """
    return "Delete ALL key-value pairs"


def delete_plugin_password_prompt():
    """Delete the plugin password prompt.

    Inputs: none. Output: `str`.
    """
    return "Enter your OMERO password to delete ONLY plugin key-value pairs:"


def delete_plugin_progress():
    """Delete the plugin progress.

    Inputs: none. Output: `str`.
    """
    return "Deleting ONLY plugin key-value pairs…"


def delete_plugin_job_label():
    """Delete the plugin job label.

    Inputs: none. Output: `str`.
    """
    return "Delete ONLY plugin key-value pairs"


def job_started_for_images():
    """Return the job started for images.

    Inputs: none. Output: `str`.
    """
    return "{jobLabel} job started for {totalImages} images..."


def max_variables_reached():
    """Return the max variables reached.

    Inputs: none. Output: `str`.
    """
    return (
        "Maximum of {maxParsedVariables} variables allowed. Cannot add more "
        "variable name fields."
    )


def unable_load_variable_sets():
    """Return the unable load variable sets.

    Inputs: none. Output: `str`.
    """
    return "Unable to load variable sets."


def error_loading_variable_sets():
    """Return the error loading variable sets.

    Inputs: none. Output: `str`.
    """
    return "Error loading variable sets"


def variable_set_saved_response():
    """Return the variable set saved response.

    Inputs: none. Output: `str`.
    """
    return "Saved variable set."


def build_message_payload(names):
    """Build the message payload.

    Inputs: `names`. Output: `_build_payload` result.
    """
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
    """Return the index messages.

    Inputs: none. Output: `build_message_payload` result.
    """
    return build_message_payload(INDEX_MESSAGE_NAMES)
