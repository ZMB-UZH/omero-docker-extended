"""
OMERO helper utilities.

Common functions for extracting data from OMERO objects.
"""
import logging

logger = logging.getLogger(__name__)


def get_text(value_obj):
    """Extract text value from OMERO rtype objects."""
    try:
        return value_obj.getValue() if hasattr(value_obj, "getValue") else getattr(
            value_obj, "val", str(value_obj)
        )
    except Exception:
        return str(value_obj)


def get_id(obj):
    """Extract ID from OMERO object."""
    try:
        return obj._obj.id.val
    except (AttributeError, Exception):
        pass
    try:
        gid = obj.getId()
        return gid.getValue() if hasattr(gid, "getValue") else gid
    except (AttributeError, Exception):
        return None


def get_owner_id(obj):
    """Extract owner ID from OMERO object."""
    if obj is None:
        return None
    try:
        details = obj.getDetails()
        owner = details.getOwner() if details else None
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception:
        pass
    try:
        owner = obj.getOwner()
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception:
        pass
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
