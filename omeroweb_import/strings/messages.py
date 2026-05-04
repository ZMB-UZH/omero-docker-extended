def imported_file(path):
    """Imported file.

    Inputs: `path`. Output: computed value.
    """
    return f"Import success: {path}"


def job_error_with_path(path, detail):
    """Job error with path.

    Inputs: `path`, `detail`. Output: computed value.
    """
    if detail:
        return f"Import failure: {path} - {detail}"
    return f"Import failure: {path}"


def skipped_non_importable(path):
    """Skipped non importable.

    Inputs: `path`. Output: computed value.
    """
    return f"Auto-skipped (not an importable image): {path}"


def skipped_incompatible(path):
    """Skipped incompatible.

    Inputs: `path`. Output: computed value.
    """
    return f"Auto-skipped (incompatible format): {path}"


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


def special_method_settings_saved_db():
    """Special method settings saved DB.

    Inputs: none. Output: 'Saved special method user settings to database.'.
    """
    return "Saved special method user settings to database."


def user_settings_save_error():
    """User settings save error.

    Inputs: none. Output: 'Error saving user settings: {error}'.
    """
    return "Error saving user settings: {error}"


def special_method_settings_save_error():
    """Special method settings save error.

    Inputs: none. Output: 'Error saving special method settings: {error}'.
    """
    return "Error saving special method settings: {error}"


def special_method_settings_load_error():
    """Special method settings load error.

    Inputs: none. Output: 'Error loading special method settings: {error}'.
    """
    return "Error loading special method settings: {error}"


def user_settings_saved():
    """User settings saved.

    Inputs: none. Output: 'Saved user settings.'.
    """
    return "Saved user settings."


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
    "special_method_settings_saved_db",
    "special_method_settings_save_error",
    "special_method_settings_load_error",
)


def index_messages():
    """Index messages.

    Inputs: none. Output: `build_message_payload` result.
    """
    return build_message_payload(INDEX_MESSAGE_NAMES)
