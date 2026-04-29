"""
OMERO helper utilities.

Common functions for extracting data from OMERO objects.
"""

import logging

from .logging_utils import sanitize_log_value

logger = logging.getLogger(__name__)


def _value_or_raw(value):
    """Handle value or raw."""
    return value.getValue() if hasattr(value, "getValue") else value


def _call_or_none(obj, method_name: str):
    """Handle call or none."""
    method = getattr(obj, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def _owner_candidates(obj):
    """Handle owner candidates."""
    details = _call_or_none(obj, "getDetails")
    details_owner = _call_or_none(details, "getOwner") if details is not None else None
    method_owner = _call_or_none(obj, "getOwner")
    owners = []
    seen_ids = set()
    for owner in (details_owner, method_owner):
        if owner is not None and id(owner) not in seen_ids:
            owners.append(owner)
            seen_ids.add(id(owner))
    return tuple(owners)


def _owner_from_details_or_method(obj):
    """Handle owner from details or method."""
    return next(iter(_owner_candidates(obj)), None)


def _safe_debug(message: str, *values) -> None:
    """Handle safe debug."""
    logger.debug(message, *(sanitize_log_value(value) for value in values))


def get_text(value_obj):
    """Extract text value from OMERO rtype objects."""
    try:
        return (
            _value_or_raw(value_obj)
            if hasattr(value_obj, "getValue")
            else value_obj.val
        )
    except Exception:
        return str(value_obj)


def get_id(obj):
    """Extract ID from OMERO object."""
    try:
        model_obj = getattr(obj, "_obj", None)
        if model_obj is not None:
            return model_obj.id.val
    except Exception as exc:
        _safe_debug("Falling back to getId() after internal ID lookup failed: %s", exc)
    try:
        return _value_or_raw(obj.getId())
    except Exception:
        return None


def get_owner_id(obj):
    """Extract owner ID from OMERO object."""
    if obj is None:
        return None
    for owner in _owner_candidates(obj):
        try:
            return _value_or_raw(owner.getId())
        except Exception as exc:
            _safe_debug("Failed to resolve owner ID: %s", exc)
    return None


def is_owned_by_user(obj, owner_id):
    """Check if object is owned by specified user."""
    if owner_id is None:
        return True
    obj_owner_id = get_owner_id(obj)
    if obj_owner_id is None:
        return False
    try:
        return int(obj_owner_id) == int(owner_id)
    except Exception:
        return False


def _current_user_id(conn):
    """Handle current user identifier."""
    try:
        user = conn.getUser()
        if user is not None:
            return _value_or_raw(user.getId())
    except Exception:
        return None
    return None


def _get_owner_username(obj):
    """Handle get owner username."""
    if obj is None:
        return ""
    for owner in _owner_candidates(obj):
        for attr in ("getOmeName", "getName", "getFirstName"):
            try:
                if hasattr(owner, attr):
                    value = get_text(getattr(owner, attr)())
                    if value:
                        return value
            except Exception as exc:
                _safe_debug("Failed to get owner name via %s: %s", attr, exc)
                continue
        owner_id = get_id(owner)
        if owner_id is not None:
            return str(owner_id)
    return ""


def _has_read_write_permissions(obj):
    """Handle has read write permissions."""
    if obj is None:
        return False
    for attr in ("canEdit", "canWrite"):
        checker = getattr(obj, attr, None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception as exc:
                _safe_debug("Permission check via %s failed: %s", attr, exc)
                continue
    try:
        details = obj.getDetails()
        permissions = details.getPermissions() if details else None
        if permissions:
            return bool(permissions.isRead() and permissions.isWrite())
    except Exception:
        return False
    return False
