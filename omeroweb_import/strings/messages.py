def imported_file(path):
    """Handle imported file."""
    return f"Import success: {path}"


def job_error_with_path(path, detail):
    """Handle job error with path."""
    if detail:
        return f"Import failure: {path} - {detail}"
    return f"Import failure: {path}"


def skipped_non_importable(path):
    """Handle skipped non importable."""
    return f"Auto-skipped (not an importable image): {path}"


def skipped_incompatible(path):
    """Handle skipped incompatible."""
    return f"Auto-skipped (incompatible format): {path}"


def confirm_irreversible_action():
    """Handle confirm irreversible action."""
    return "Are you absolutely sure? This action is irreversible."


def formatting_errors():
    """Build formatting errors."""
    return "Formatting error(s). Please try again."


def user_settings_saved_db():
    """Handle user settings saved database."""
    return "Saved user settings to database."


def special_method_settings_saved_db():
    """Handle special method settings saved database."""
    return "Saved special method user settings to database."


def user_settings_save_error():
    """Handle user settings save error."""
    return "Error saving user settings: {error}"


def special_method_settings_save_error():
    """Handle special method settings save error."""
    return "Error saving special method settings: {error}"


def special_method_settings_load_error():
    """Handle special method settings load error."""
    return "Error loading special method settings: {error}"


def user_settings_saved():
    """Handle user settings saved."""
    return "Saved user settings."


def build_message_payload(names):
    """Build build message payload."""
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
    """Handle index messages."""
    return build_message_payload(INDEX_MESSAGE_NAMES)
