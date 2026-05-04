def confirm_irreversible_action():
    """Confirm irreversible action.

    Inputs: none. Output: 'Are you absolutely sure? This action is irreversible.'.
    """
    return "Are you absolutely sure? This action is irreversible."


def formatting_errors():
    """Formatting errors.

    Inputs: none. Output: 'Formatting error(s). Please try again.'.
    """
    return "Formatting error(s). Please try again."


def user_settings_saved_db():
    """User settings saved DB.

    Inputs: none. Output: 'Saved user settings to database.'.
    """
    return "Saved user settings to database."


def user_settings_save_error():
    """User settings save error.

    Inputs: none. Output: 'Error saving user settings: {error}'.
    """
    return "Error saving user settings: {error}"


def user_settings_saved():
    """User settings saved.

    Inputs: none. Output: 'Saved user settings.'.
    """
    return "Saved user settings."


def unable_load_credentials():
    """Unable load credentials.

    Inputs: none. Output: 'Unable to load saved credentials.'.
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
    """Select project.

    Inputs: none. Output: 'Please select a project.'.
    """
    return "Please select a project."


def select_datasets():
    """Select datasets.

    Inputs: none. Output: 'Please select one or more datasets.'.
    """
    return "Please select one or more datasets."


def no_data_to_process():
    """No data to process.

    Inputs: none. Output: 'No data to process is available in the selected datasets.'.
    """
    return "No data to process is available in the selected datasets."


def filename_input_empty():
    """Filename input empty.

    Inputs: none. Output: 'The input field for filename parsing cannot be empty.'.
    """
    return "The input field for filename parsing cannot be empty."


def filename_input_duplicate():
    """Filename input duplicate.

    Inputs: none. Output: 'The input field for filename parsing cannot contain duplicate
    characters.'.

    characters.'.
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
    """Delete data failed.

    Inputs: none. Output: 'Unable to delete data.'.
    """
    return "Unable to delete data."


def error_with_details():
    """Error with details.

    Inputs: none. Output: 'ERROR: {error}'.
    """
    return "ERROR: {error}"


def local_provider_ready():
    """Local provider ready.

    Inputs: none. Output: 'Local provider selected. Ready to process.'.
    """
    return "Local provider selected. Ready to process."


def provider_key_ready():
    """Provider key ready.

    Inputs: none. Output: 'API key exists in database for the selected provider. Ready
    to process.'.

    to process.'.
    """
    return "API key exists in database for the selected provider. Ready to process."


def add_api_key_settings():
    """Add API key settings.

    Inputs: none. Output: 'Please add an API key for this provider in settings.'.
    """
    return "Please add an API key for this provider in settings."


def choose_provider():
    """Choose provider.

    Inputs: none. Output: 'Please choose a provider.'.
    """
    return "Please choose a provider."


def api_key_empty():
    """API key empty.

    Inputs: none. Output: 'API key cannot be empty.'.
    """
    return "API key cannot be empty."


def testing_connection():
    """Testing connection.

    Inputs: none. Output: 'Testing connection...'.
    """
    return "Testing connection..."


def connection_test_passed():
    """Connection test passed.

    Inputs: none. Output: 'Connection test passed.'.
    """
    return "Connection test passed."


def unable_test_api_key():
    """Unable test API key.

    Inputs: none. Output: 'Unable to test API key.'.
    """
    return "Unable to test API key."


def choose_provider_and_key():
    """Choose provider and key.

    Inputs: none. Output: 'Please choose a provider and enter an API key.'.
    """
    return "Please choose a provider and enter an API key."


def run_connection_test_first():
    """Return the prompt shown before saving an untested key.

    Inputs: none. Output: 'Please run the connection test before saving this API key.'.
    """
    return "Please run the connection test before saving this API key."


def saving_key():
    """Saving key.

    Inputs: none. Output: 'Saving key...'.
    """
    return "Saving key..."


def api_key_saved_status():
    """API key saved status.

    Inputs: none. Output: 'API key saved.'.
    """
    return "API key saved."


def api_key_saved_db():
    """API key saved DB.

    Inputs: none. Output: 'API key saved to database.'.
    """
    return "API key saved to database."


def unable_save_api_key():
    """Unable save API key.

    Inputs: none. Output: 'Unable to save API key.'.
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
    """Heuristic regex ready.

    Inputs: none. Output: 'Heuristic regex suggestion ready. Please repeat processing if
    unsatisfactory.'.

    unsatisfactory.'.
    """
    return (
        "Heuristic regex suggestion ready. Please repeat processing if unsatisfactory."
    )


def regex_suggestion_ready():
    """Regex suggestion ready.

    Inputs: none. Output: 'Regex suggestion ready. Please repeat processing if
    unsatisfactory.'.

    unsatisfactory.'.
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
    """Generate regex first.

    Inputs: none. Output: 'Generate a regex before transferring.'.
    """
    return "Generate a regex before transferring."


def no_datasets_found():
    """No datasets found.

    Inputs: none. Output: 'No datasets found in project "{projectName}"'.
    """
    return 'No datasets found in project "{projectName}"'


def unable_load_datasets():
    """Unable load datasets.

    Inputs: none. Output: 'Unable to load datasets. Refresh browser and try again.'.
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
    """Variable parsing capped.

    Inputs: none. Output: 'Variable parsing is capped at {maxParsedVariables}. Only the
    first {maxParsedVariables} variables will be parsed. Your filenames produced
    {maxVarsUncapped} variables. Consider checking your parsing method, filenames and
    user settings.'.

    first {maxParsedVariables} variables will be parsed. Your filenames produced
    {maxVarsUncapped} variables. Consider checking your parsing method, filenames and
    user settings.'.
    """
    return (
        "Variable parsing is capped at {maxParsedVariables}. "
        "Only the first {maxParsedVariables} variables will be parsed. "
        "Your filenames produced {maxVarsUncapped} variables. "
        "Consider checking your parsing method, filenames and user settings."
    )


def exit_edit_mode_first():
    """Exit edit mode first.

    Inputs: none. Output: 'Please exit edit mode first.'.
    """
    return "Please exit edit mode first."


def default_var_name():
    """Default var name.

    Inputs: none. Output: 'rename'.
    """
    return "rename"


def variable_names_spaces():
    """Variable names spaces.

    Inputs: none. Output: 'Variable names cannot contain just empty spaces.'.
    """
    return "Variable names cannot contain just empty spaces."


def variable_names_empty():
    """Variable names empty.

    Inputs: none. Output: 'Variable names cannot be empty.'.
    """
    return "Variable names cannot be empty."


def variable_set_name_required():
    """Variable set name required.

    Inputs: none. Output: 'Please provide a name for this variable set.'.
    """
    return "Please provide a name for this variable set."


def variable_set_saved():
    """Variable set saved.

    Inputs: none. Output: 'Saved variable set "{setName}" to database.'.
    """
    return 'Saved variable set "{setName}" to database.'


def variable_set_save_error():
    """Variable set save error.

    Inputs: none. Output: 'Error saving variable set: {error}'.
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
    """Variable set select required.

    Inputs: none. Output: 'Please select a variable set from the dropdown menu.'.
    """
    return "Please select a variable set from the dropdown menu."


def variable_set_loaded():
    """Variable set loaded.

    Inputs: none. Output: 'Loaded variable set "{setName}" from database.'.
    """
    return 'Loaded variable set "{setName}" from database.'


def variable_set_load_error():
    """Variable set load error.

    Inputs: none. Output: 'Error loading variable set: {error}'.
    """
    return "Error loading variable set: {error}"


def variable_set_deleted():
    """Variable set deleted.

    Inputs: none. Output: 'Deleted variable set "{setName}" from database.'.
    """
    return 'Deleted variable set "{setName}" from database.'


def variable_set_delete_error():
    """Variable set delete error.

    Inputs: none. Output: 'Error deleting variable set: {error}'.
    """
    return "Error deleting variable set: {error}"


def job_already_running():
    """Job already running.

    Inputs: none. Output: 'Another job is already running. Please be patient.'.
    """
    return "Another job is already running. Please be patient."


def select_image_required():
    """Select image required.

    Inputs: none. Output: 'Select at least one image to apply changes.'.
    """
    return "Select at least one image to apply changes."


def password_empty():
    """Password empty.

    Inputs: none. Output: 'Password cannot be empty.'.
    """
    return "Password cannot be empty."


def min_variables_required():
    """Min variables required.

    Inputs: none. Output: 'Please populate at least {count} variables and try again.'.
    """
    return "Please populate at least {count} variables and try again."


def variable_names_spaces_first():
    """Variable names spaces first.

    Inputs: none. Output: 'Variable names for any of the first {count} variables cannot
    contain just empty spaces.'.

    contain just empty spaces.'.
    """
    return "Variable names for any of the first {count} variables cannot contain just empty spaces."


def variable_names_empty_first():
    """Variable names empty first.

    Inputs: none. Output: 'Variable names for the first {count} variables cannot be
    empty.'.

    empty.'.
    """
    return "Variable names for the first {count} variables cannot be empty."


def progress_start_save_job():
    """Progress start save job.

    Inputs: none. Output: 'Starting "Save filename metadata into key-value pairs" job…'.
    """
    return 'Starting "Save filename metadata into key-value pairs" job…'


def progress_start_acq_job():
    """Progress start acq job.

    Inputs: none. Output: 'Starting "copy acquisition metadata into key-value pairs"
    job…'.

    job…'.
    """
    return 'Starting "copy acquisition metadata into key-value pairs" job…'


def job_started_save():
    """Job started save.

    Inputs: none. Output: 'Save filename metadata into key-value pairs job started for
    {totalImages} images...'.

    {totalImages} images...'.
    """
    return "Save filename metadata into key-value pairs job started for {totalImages} images..."


def job_started_acq():
    """Job started acq.

    Inputs: none. Output: 'Copy acquisition metadata into key-value pairs job started
    for {totalImages} images...'.

    for {totalImages} images...'.
    """
    return "Copy acquisition metadata into key-value pairs job started for {totalImages} images..."


def progress_processed():
    """Progress processed.

    Inputs: none. Output: 'Processed {done} of {total} images (unique IDs).'.
    """
    return "Processed {done} of {total} images (unique IDs)."


def progress_completed():
    """Progress completed.

    Inputs: none. Output: 'Completed. Processed {done} images (unique IDs).'.
    """
    return "Completed. Processed {done} images (unique IDs)."


def delete_all_password_prompt():
    """Delete all password prompt.

    Inputs: none. Output: 'Enter your OMERO password to delete ALL key-value pairs:'.
    """
    return "Enter your OMERO password to delete ALL key-value pairs:"


def delete_all_progress():
    """Delete all progress.

    Inputs: none. Output: 'Deleting ALL key-value pairs…'.
    """
    return "Deleting ALL key-value pairs…"


def delete_all_job_label():
    """Delete all job label.

    Inputs: none. Output: 'Delete ALL key-value pairs'.
    """
    return "Delete ALL key-value pairs"


def delete_plugin_password_prompt():
    """Delete plugin password prompt.

    Inputs: none. Output: 'Enter your OMERO password to delete ONLY plugin key-value
    pairs:'.

    pairs:'.
    """
    return "Enter your OMERO password to delete ONLY plugin key-value pairs:"


def delete_plugin_progress():
    """Delete plugin progress.

    Inputs: none. Output: 'Deleting ONLY plugin key-value pairs…'.
    """
    return "Deleting ONLY plugin key-value pairs…"


def delete_plugin_job_label():
    """Delete plugin job label.

    Inputs: none. Output: 'Delete ONLY plugin key-value pairs'.
    """
    return "Delete ONLY plugin key-value pairs"


def job_started_for_images():
    """Job started for images.

    Inputs: none. Output: '{jobLabel} job started for {totalImages} images...'.
    """
    return "{jobLabel} job started for {totalImages} images..."


def max_variables_reached():
    """Max variables reached.

    Inputs: none. Output: 'Maximum of {maxParsedVariables} variables allowed. Cannot add
    more variable name fields.'.

    more variable name fields.'.
    """
    return (
        "Maximum of {maxParsedVariables} variables allowed. Cannot add more "
        "variable name fields."
    )


def unable_load_variable_sets():
    """Unable load variable sets.

    Inputs: none. Output: 'Unable to load variable sets.'.
    """
    return "Unable to load variable sets."


def error_loading_variable_sets():
    """Error loading variable sets.

    Inputs: none. Output: 'Error loading variable sets'.
    """
    return "Error loading variable sets"


def variable_set_saved_response():
    """Variable set saved response.

    Inputs: none. Output: 'Saved variable set.'.
    """
    return "Saved variable set."


def build_message_payload(names):
    """Message payload.

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
    """Index messages.

    Inputs: none. Output: `build_message_payload` result.
    """
    return build_message_payload(INDEX_MESSAGE_NAMES)
