import json


def _extract_message_from_payload(payload):
    if isinstance(payload, dict):
        info = payload.get("error") or payload.get("message")
        if isinstance(info, dict):
            message = info.get("message")
            if message:
                return message
        if isinstance(info, str):
            return info
    return None


def _extract_message_from_response(response):
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        text = getattr(response, "text", "")
        return str(text or "").strip() or None
    detail = _extract_message_from_payload(payload)
    if detail:
        return detail
    if isinstance(payload, str):
        return payload.strip() or None
    return None


def extract_error_details(error):
    if not error:
        return None
    response = getattr(error, "response", None)
    if response is not None:
        return _extract_message_from_response(response)
    if (
        hasattr(error, "json")
        or hasattr(error, "text")
        or hasattr(error, "status_code")
    ):
        return _extract_message_from_response(error)
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
    return _extract_message_from_payload(payload)
