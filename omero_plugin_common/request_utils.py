"""Shared request utilities for OMERO web plugins."""
from __future__ import annotations

import json
from typing import Any, Optional, Tuple


def current_username(request, conn):
    """Resolve the current username from the OMERO connection or Django request."""
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception:
        pass

    try:
        return request.user.username
    except Exception:
        return None


def load_request_data(request):
    """Load request payload preferring JSON, falling back to POST form data."""
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return request.POST


def parse_json_body(request) -> Tuple[Optional[Any], Optional[Exception]]:
    """Parse JSON from request body, returning data and error if parsing fails."""
    try:
        raw_body = request.body.decode("utf-8")
    except Exception as exc:
        return None, exc
    try:
        return json.loads(raw_body), None
    except json.JSONDecodeError as exc:
        return None, exc
