"""File and path utility functions for import plugin."""

import logging
from dataclasses import dataclass
from pathlib import Path

from omero_plugin_common.logging_utils import sanitize_log_value
from omero_plugin_common.tmp_utils import get_plugin_tmp_dir

logger = logging.getLogger(__name__)


@dataclass
class _DirectoryCache:
    """Represent directory cache."""

    upload_root: Path | None = None
    jobs_root: Path | None = None


_DIRECTORY_CACHE = _DirectoryCache()


def resolve_upload_root() -> Path:
    """Return the upload data directory under OMERO_TMP_PATH.

    Inputs: none. Output: `Path`.
    """
    return get_plugin_tmp_dir("data")


def resolve_jobs_root() -> Path:
    """Return the upload jobs directory under OMERO_TMP_PATH.

    Inputs: none. Output: `Path`.
    """
    return get_plugin_tmp_dir("jobs")


def ensure_parent_dir(path: Path) -> bool:
    """Ensure parent directory.

    Inputs: `path`. Output: `bool`.
    """
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


def initialize_directories() -> None:
    """Initialize upload and jobs directories.

    Inputs: none. Output: None.
    """
    if (
        _DIRECTORY_CACHE.upload_root is not None
        and _DIRECTORY_CACHE.jobs_root is not None
    ):
        return

    roots = (resolve_upload_root(), resolve_jobs_root())
    initialized_roots: list[Path] = []
    for root in roots:
        try:
            if not root.exists():
                root.mkdir(parents=True, exist_ok=True, mode=0o755)
            elif root.is_dir():
                root.chmod(0o755)
            else:
                logger.error(
                    "Upload directory path exists but is not a directory: %s",
                    sanitize_log_value(root),
                )
                return
            initialized_roots.append(root)
        except Exception as e:
            logger.error(
                "Failed to initialize directory %s: %s",
                sanitize_log_value(root),
                sanitize_log_value(e),
            )
            return

    _DIRECTORY_CACHE.upload_root, _DIRECTORY_CACHE.jobs_root = initialized_roots


def get_upload_root() -> Path:
    """Return upload root.

    Inputs: none. Output: `Path`. Raises on invalid or unavailable state.
    """
    if _DIRECTORY_CACHE.upload_root is None:
        initialize_directories()
    if _DIRECTORY_CACHE.upload_root is None:
        raise RuntimeError("Upload root was not initialized.")
    return _DIRECTORY_CACHE.upload_root


def get_jobs_root() -> Path:
    """Return jobs root.

    Inputs: none. Output: `Path`. Raises on invalid or unavailable state.
    """
    if _DIRECTORY_CACHE.jobs_root is None:
        initialize_directories()
    if _DIRECTORY_CACHE.jobs_root is None:
        raise RuntimeError("Jobs root was not initialized.")
    return _DIRECTORY_CACHE.jobs_root


def ensure_dir(path: Path) -> bool:
    """Ensure directory.

    Inputs: `path`. Output: `bool`.
    """
    try:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return path.is_dir()
    except Exception as e:
        logger.error(
            "Failed to create directory %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(e),
        )
        return False


def ensure_dir_with_permissions(path: Path, mode: int) -> bool:
    """Ensure directory with permissions.

    Inputs: `path`, `mode`. Output: `bool`.
    """
    try:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True, mode=mode)
        elif path.is_dir():
            path.chmod(mode)
        else:
            logger.error(
                "Managed directory path exists but is not a directory: %s",
                sanitize_log_value(path),
            )
            return False
        return True
    except Exception as e:
        logger.error(
            "Failed to create/chmod directory %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(e),
        )
        return False


def safe_relative_path(raw_name: str):
    """Sanitize filename to safe relative path.

    Inputs: `raw_name`. Output: computed value.
    """
    import re

    name = raw_name.strip()
    name = re.sub(r'[<>:"|?*]', "_", name)
    name = re.sub(r"\.\.", "_", name)
    name = name.lstrip("/\\")
    return name if name else "unnamed"


def is_within_root(path: Path, root: Path) -> bool:
    """Return whether within root.

    Inputs: `path`, `root`. Output: `bool`.
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_remove_tree(path: Path, root: Path):
    """Safely remove directory tree if within root.

    Inputs: `path`, `root`. Output: None.
    """
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
