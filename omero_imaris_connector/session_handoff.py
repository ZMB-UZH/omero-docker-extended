"""Short-lived local session-key handoff for Imaris Celery workers."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path

from .config import get_connector_tmp_dir

_HANDOFF_DIR = "session-handoff"
_HANDOFF_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_DIR_MODE = stat.S_IRWXU
_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR


def _validate_handoff_ref(ref: str) -> str:
    """Validate and return a single safe handoff reference component.

    Inputs: candidate handoff reference. Output: validated reference string.
    """
    value = str(ref or "").strip()
    if not _HANDOFF_FILE_RE.fullmatch(value):
        raise ValueError("Invalid Imaris export session handoff reference.")
    return value


def _handoff_dir() -> Path:
    """Return the secure handoff directory, creating it when needed.

    Inputs: none. Output: private handoff directory path.
    """
    path = get_connector_tmp_dir(_HANDOFF_DIR, create=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError("Invalid Imaris export session handoff directory.")
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise RuntimeError(
            "Cannot inspect Imaris export session handoff directory."
        ) from exc
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise RuntimeError("Imaris export session handoff directory is too permissive.")
    return path


def _handoff_path(ref: str) -> Path:
    """Return the path for a validated handoff reference.

    Inputs: handoff reference. Output: path to the corresponding handoff file.
    """
    return _handoff_dir() / _validate_handoff_ref(ref)


def store_export_session_key(
    ref: str,
    session_key: str,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """Store a session key in a local one-time handoff file.

    Inputs: handoff reference, OMERO session key, optional TTL. Output: reference.
    """
    if not session_key:
        raise ValueError("OMERO session key is required for Imaris export handoff.")
    value = _validate_handoff_ref(ref)
    timeout = int(ttl_seconds or _DEFAULT_TTL_SECONDS)
    if timeout <= 0:
        timeout = _DEFAULT_TTL_SECONDS
    payload = {
        "session_key": str(session_key),
        "expires_at": time.time() + timeout,
    }
    path = _handoff_path(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        delete_export_session_key(value)
        raise
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass
    return value


def pop_export_session_key(ref: str | None) -> str | None:
    """Read and remove a session key handoff file.

    Inputs: handoff reference. Output: session key or None when absent/expired.
    """
    if not ref:
        return None
    path = _handoff_path(ref)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    if not isinstance(payload, dict):
        return None
    try:
        expires_at = float(payload.get("expires_at", 0))
    except (TypeError, ValueError):
        return None
    if expires_at < time.time():
        return None
    session_key = payload.get("session_key")
    return str(session_key) if session_key else None


def delete_export_session_key(ref: str | None) -> None:
    """Remove an unused session-key handoff file.

    Inputs: handoff reference or None. Output: None.
    """
    if not ref:
        return
    try:
        _handoff_path(ref).unlink()
    except FileNotFoundError:
        return
