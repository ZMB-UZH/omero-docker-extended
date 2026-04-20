"""
File and path utility functions for import plugin.
"""

import logging
from pathlib import Path

from omero_plugin_common.logging_utils import sanitize_log_value
from omero_plugin_common.tmp_utils import get_plugin_tmp_dir

logger = logging.getLogger(__name__)

_UPLOAD_ROOT_CACHE: Path | None = None
_JOBS_ROOT_CACHE: Path | None = None


def resolve_upload_root() -> Path:
    """Return the upload data directory under OMERO_TMP_PATH."""
    return get_plugin_tmp_dir("data")


def resolve_jobs_root() -> Path:
    """Return the upload jobs directory under OMERO_TMP_PATH."""
    return get_plugin_tmp_dir("jobs")


def ensure_parent_dir(path: Path) -> bool:
    """Ensure parent directory exists with proper permissions."""
    try:
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        return True
    except Exception as e:
        logger.error(
            "Failed to create parent dir for %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(e),
        )
        return False


def initialize_directories():
    """Initialize upload and jobs directories."""
    global _UPLOAD_ROOT_CACHE, _JOBS_ROOT_CACHE

    if _UPLOAD_ROOT_CACHE is not None and _JOBS_ROOT_CACHE is not None:
        return

    upload_root = resolve_upload_root()
    jobs_root = resolve_jobs_root()

    for root in (upload_root, jobs_root):
        try:
            if not root.exists():
                root.mkdir(parents=True, exist_ok=True, mode=0o755)
            else:
                root.chmod(0o755)
        except Exception as e:
            logger.error(
                "Failed to initialize directory %s: %s",
                sanitize_log_value(root),
                sanitize_log_value(e),
            )

    _UPLOAD_ROOT_CACHE = upload_root
    _JOBS_ROOT_CACHE = jobs_root


def get_upload_root() -> Path:
    """Get cached upload root, initializing if needed."""
    global _UPLOAD_ROOT_CACHE
    if _UPLOAD_ROOT_CACHE is None:
        initialize_directories()
    if _UPLOAD_ROOT_CACHE is None:
        raise RuntimeError("Upload root was not initialized.")
    return _UPLOAD_ROOT_CACHE


def get_jobs_root() -> Path:
    """Get cached jobs root, initializing if needed."""
    global _JOBS_ROOT_CACHE
    if _JOBS_ROOT_CACHE is None:
        initialize_directories()
    if _JOBS_ROOT_CACHE is None:
        raise RuntimeError("Jobs root was not initialized.")
    return _JOBS_ROOT_CACHE


def ensure_dir(path: Path) -> bool:
    """Ensure directory exists."""
    try:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(
            "Failed to create directory %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(e),
        )
        return False


def ensure_dir_with_permissions(path: Path, mode: int) -> bool:
    """Ensure directory exists with specific permissions."""
    try:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True, mode=mode)
        else:
            path.chmod(mode)
        return True
    except Exception as e:
        logger.error(
            "Failed to create/chmod directory %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(e),
        )
        return False


def safe_relative_path(raw_name: str):
    """Sanitize filename to safe relative path."""
    import re

    name = raw_name.strip()
    name = re.sub(r'[<>:"|?*]', "_", name)
    name = re.sub(r"\.\.", "_", name)
    name = name.lstrip("/\\")
    return name if name else "unnamed"


def is_within_root(path: Path, root: Path) -> bool:
    """Check if path is within root directory."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_remove_tree(path: Path, root: Path):
    """Safely remove directory tree if within root."""
    import shutil

    if not is_within_root(path, root):
        logger.error(
            "Path %s is outside root %s",
            sanitize_log_value(path),
            sanitize_log_value(root),
        )
        return
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
    except Exception as e:
        logger.error(
            "Failed to remove %s: %s", sanitize_log_value(path), sanitize_log_value(e)
        )
