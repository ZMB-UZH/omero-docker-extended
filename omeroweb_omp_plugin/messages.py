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
    return (
        "Please use the AI-assisted Regex expression routine first, or choose another method."
    )


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
    return "API key saved to the database."


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
    return "Heuristic regex suggestion ready."


def regex_suggestion_ready():
    return "Regex suggestion ready. Please repeat processing if unsatisfactory."


def ai_process_failed():
    return "Unable to process filenames. Please try again."


def generate_regex_first():
    return "Generate a regex before transferring."


def no_datasets_found():
    return 'No datasets found in project "{projectName}"'


def unable_load_datasets():
    return "Unable to load datasets. Please try again."


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
    return "Enter your Omero password to delete ALL key-value pairs:"


def delete_all_progress():
    return "Deleting ALL key-value pairs…"


def delete_all_job_label():
    return "Delete ALL key-value pairs"


def delete_plugin_password_prompt():
    return "Enter your Omero password to delete ONLY plugin key-value pairs:"


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


def index_messages():
    return {
        "confirmIrreversible": confirm_irreversible_action(),
        "formattingErrors": formatting_errors(),
        "userSettingsSavedDb": user_settings_saved_db(),
        "userSettingsSaveError": user_settings_save_error(),
        "unableLoadCredentials": unable_load_credentials(),
        "aiKeyExists": ai_key_exists(),
        "aiKeyMissing": ai_key_missing(),
        "selectProject": select_project(),
        "selectDatasets": select_datasets(),
        "noDataToProcess": no_data_to_process(),
        "filenameInputEmpty": filename_input_empty(),
        "filenameInputDuplicate": filename_input_duplicate(),
        "aiRegexUseFirst": ai_regex_use_first(),
        "deleteDataFailed": delete_data_failed(),
        "errorWithDetails": error_with_details(),
        "localProviderReady": local_provider_ready(),
        "providerKeyReady": provider_key_ready(),
        "addApiKeySettings": add_api_key_settings(),
        "chooseProvider": choose_provider(),
        "apiKeyEmpty": api_key_empty(),
        "testingConnection": testing_connection(),
        "connectionTestPassed": connection_test_passed(),
        "unableTestApiKey": unable_test_api_key(),
        "chooseProviderAndKey": choose_provider_and_key(),
        "runConnectionTestFirst": run_connection_test_first(),
        "savingKey": saving_key(),
        "apiKeySavedStatus": api_key_saved_status(),
        "apiKeySavedDb": api_key_saved_db(),
        "unableSaveApiKey": unable_save_api_key(),
        "aiModalChooseProvider": ai_modal_choose_provider(),
        "aiModalAddKeySelected": ai_modal_add_key_selected(),
        "aiModalProcessing": ai_modal_processing(),
        "aiSuggestionFallback": ai_suggestion_fallback(),
        "heuristicRegexReady": heuristic_regex_ready(),
        "regexSuggestionReady": regex_suggestion_ready(),
        "aiProcessFailed": ai_process_failed(),
        "generateRegexFirst": generate_regex_first(),
        "noDatasetsFound": no_datasets_found(),
        "unableLoadDatasets": unable_load_datasets(),
    }


def preview_messages():
    return {
        "confirmIrreversible": confirm_irreversible_action(),
        "variableParsingCapped": variable_parsing_capped(),
        "exitEditModeFirst": exit_edit_mode_first(),
        "defaultVarName": default_var_name(),
        "variableNamesSpaces": variable_names_spaces(),
        "variableNamesEmpty": variable_names_empty(),
        "variableSetNameRequired": variable_set_name_required(),
        "variableSetSaved": variable_set_saved(),
        "variableSetSaveError": variable_set_save_error(),
        "variableSetEmptyDb": variable_set_empty_db(),
        "variableSetSelectRequired": variable_set_select_required(),
        "variableSetLoaded": variable_set_loaded(),
        "variableSetLoadError": variable_set_load_error(),
        "variableSetDeleted": variable_set_deleted(),
        "variableSetDeleteError": variable_set_delete_error(),
        "jobAlreadyRunning": job_already_running(),
        "selectImageRequired": select_image_required(),
        "passwordEmpty": password_empty(),
        "errorWithDetails": error_with_details(),
        "minVariablesRequired": min_variables_required(),
        "variableNamesSpacesFirst": variable_names_spaces_first(),
        "variableNamesEmptyFirst": variable_names_empty_first(),
        "progressStartSaveJob": progress_start_save_job(),
        "progressStartAcqJob": progress_start_acq_job(),
        "jobStartedSave": job_started_save(),
        "jobStartedAcq": job_started_acq(),
        "progressProcessed": progress_processed(),
        "progressCompleted": progress_completed(),
        "deleteAllPasswordPrompt": delete_all_password_prompt(),
        "deleteAllProgress": delete_all_progress(),
        "deleteAllJobLabel": delete_all_job_label(),
        "deletePluginPasswordPrompt": delete_plugin_password_prompt(),
        "deletePluginProgress": delete_plugin_progress(),
        "deletePluginJobLabel": delete_plugin_job_label(),
        "jobStartedForImages": job_started_for_images(),
        "maxVariablesReached": max_variables_reached(),
        "unableLoadVariableSets": unable_load_variable_sets(),
        "errorLoadingVariableSets": error_loading_variable_sets(),
    }
