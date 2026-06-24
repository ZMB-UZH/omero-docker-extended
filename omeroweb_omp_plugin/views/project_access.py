"""Project access checks shared by destructive OMP views."""

from __future__ import annotations

from ..services.core import get_id
from ..strings import errors as error_messages
from .index_view import _get_accessible_project

_DESTRUCTIVE_PROJECT_ACCESS = frozenset({"owned", "read_write"})


def _current_user_id(conn):
    """Return the current OMERO user id from a gateway connection.

    Inputs: OMERO gateway connection. Output: user id or None.
    """
    try:
        return get_id(conn.getUser())
    except Exception:
        return None


def require_destructive_project_access(conn, project_id):
    """Return project access validation for destructive annotation operations.

    Inputs: OMERO gateway connection and project id. Output: `(ok, error)`.
    """
    user_id = _current_user_id(conn)
    project, access = _get_accessible_project(conn, project_id, user_id)
    if project is None or access not in _DESTRUCTIVE_PROJECT_ACCESS:
        return False, error_messages.project_write_access_required()
    return True, None
