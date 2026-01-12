
def imported_file(path):
    return f"Imported {path}"


def job_error_with_path(path, detail):
    return f"{path}: {detail}"


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


def _snake_to_camel(name):
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def build_message_payload(names):
    payload = {}
    for name in names:
        if name == "confirm_irreversible_action":
            key = "confirmIrreversible"
        else:
            key = _snake_to_camel(name)
        payload[key] = globals()[name]()
    return payload


INDEX_MESSAGE_NAMES = (
    "confirm_irreversible_action",
    "formatting_errors",
    "user_settings_saved_db",
    "user_settings_save_error",
)


def index_messages():
    return build_message_payload(INDEX_MESSAGE_NAMES)
