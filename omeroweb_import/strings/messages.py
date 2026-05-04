def imported_file(path):
    """Return the imported file.

    Inputs: `path` path. Output: imported file result.
    """
    return f"Import success: {path}"


def job_error_with_path(path, detail):
    """Return the job error with path.

    Inputs: `path` path, `detail`. Output: `Path` or path text.
    """
    if detail:
        return f"Import failure: {path} - {detail}"
    return f"Import failure: {path}"


def skipped_non_importable(path):
    """Return the skipped non importable.

    Inputs: `path` path. Output: skipped non importable result.
    """
    return f"Auto-skipped (not an importable image): {path}"


def skipped_incompatible(path):
    """Return the skipped incompatible.

    Inputs: `path` path. Output: skipped incompatible result.
    """
    return f"Auto-skipped (incompatible format): {path}"


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


def special_method_settings_saved_db():
    """Special method settings saved DB.

    Inputs: none. Output: 'Saved special method user settings to database.'.
    """
    return "Saved special method user settings to database."


def user_settings_save_error():
    """Return the user settings save error.

    Inputs: none. Output: `str`.
    """
    return "Error saving user settings: {error}"


def special_method_settings_save_error():
    """Return the special method settings save error.

    Inputs: none. Output: `str`.
    """
    return "Error saving special method settings: {error}"


def special_method_settings_load_error():
    """Return the special method settings load error.

    Inputs: none. Output: `str`.
    """
    return "Error loading special method settings: {error}"


def user_settings_saved():
    """Return the user settings saved.

    Inputs: none. Output: `str`.
    """
    return "Saved user settings."


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
    "special_method_settings_saved_db",
    "special_method_settings_save_error",
    "special_method_settings_load_error",
)


def index_messages():
    """Return the index messages.

    Inputs: none. Output: `build_message_payload` result.
    """
    return build_message_payload(INDEX_MESSAGE_NAMES)
