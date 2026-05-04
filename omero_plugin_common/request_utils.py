"""Shared request utilities for OMERO web plugins."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Tuple

from .logging_utils import sanitize_log_value


logger = logging.getLogger(__name__)


def current_username(request, conn):
    """Return current username.

    Inputs: `request` Django request, `conn` OMERO gateway connection. Output:
    `username`.
    """
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception as exc:
        logger.debug(
            "Failed to resolve username from OMERO connection: %s",
            sanitize_log_value(exc),
        )

    try:
        return request.user.username
    except Exception:
        return None


def load_request_data(request):
    """Load the request data.

    Inputs: `request` Django request. Output: `loads` result.
    """
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return request.POST


def parse_json_body(request) -> Tuple[Optional[Any], Optional[str]]:
    """Parse and validate the json body input.

    Inputs: `request` Django request. Output: `Tuple[Optional[Any], Optional[str]]`.
    """
    try:
        raw_body = request.body.decode("utf-8")
    except Exception:
        return None, "Request body is not valid UTF-8."
    try:
        return json.loads(raw_body), None
    except json.JSONDecodeError:
        return None, "Request body is not valid JSON."
