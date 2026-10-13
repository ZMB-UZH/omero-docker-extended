"""Explicit trust for monitoring clients, without changing unrelated HTTP calls."""

from __future__ import annotations

import os
import ssl
from urllib.parse import urlsplit


def request_options(url: str) -> dict:
    """Require HTTPS when managed trust is configured; never follow a downgrade.

    Legacy deployments without the TLS setting retain their existing platform
    verification. A configured but absent or unreadable bundle is an error in
    the HTTP client, never a reason to disable verification.

    Inputs: backend URL and managed CA setting. Output: verified request options.
    """
    authority = os.environ.get("ADMIN_TOOLS_TLS_CA_FILE", "").strip()
    if not authority:
        return {}
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "Managed monitoring backends require an HTTPS URL without credentials"
        )
    return {"verify": authority, "allow_redirects": False}


def connection_options(url: str) -> dict:
    """Inputs: backend URL. Output: fresh verified context, reloading renewed trust."""
    options = request_options(url)
    if not options:
        return {}
    context = ssl.create_default_context(cafile=options["verify"])
    context.minimum_version = max(
        context.minimum_version,
        ssl.TLSVersion.TLSv1_2,  # DevSkim: ignore DS440001 -- minimum only; preserves stricter platform policy
    )
    return {"context": context}
