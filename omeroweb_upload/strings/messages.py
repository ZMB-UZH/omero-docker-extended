
def imported_file(path):
    return f"Import success: {path}"


def job_error_with_path(path, detail):
    return f"Import failure: {path}"


def skipped_non_importable(path):
    return f"Auto-skipped (not an importable image): {path}"


def skipped_incompatible(path):
    return f"Auto-skipped (incompatible format): {path}"


def confirm_irreversible_action():
    return "Are you absolutely sure? This action is irreversible."


def formatting_errors():
    return "Formatting error(s). Please try again."


def user_settings_saved_db():
    return "Saved user settings to database."


def special_method_settings_saved_db():
    return "Saved special method user settings to database."


def user_settings_save_error():
    return "Error saving user settings: {error}"


def special_method_settings_save_error():
    return "Error saving special method settings: {error}"


def special_method_settings_load_error():
    return "Error loading special method settings: {error}"


def user_settings_saved():
    return "Saved user settings."


def build_message_payload(names):
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
    return build_message_payload(INDEX_MESSAGE_NAMES)
