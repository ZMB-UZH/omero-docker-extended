import json


def extract_error_details(error):
    if not error:
        return None
    try:
        raw = error.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="ignore").strip() or None
    if isinstance(payload, dict):
        info = payload.get("error") or payload.get("message")
        if isinstance(info, dict):
            message = info.get("message")
            if message:
                return message
        if isinstance(info, str):
            return info
    return None
