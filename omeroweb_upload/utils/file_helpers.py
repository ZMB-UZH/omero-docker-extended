"""
File and path utility functions for upload management.
"""
import os
import stat
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Constants
UPLOAD_ROOT_ENV = "OMERO_WEB_UPLOAD_DIR"
DEFAULT_UPLOAD_ROOT = "/tmp/omero-upload-tmp"
JOBS_DIR_ENV = "OMERO_WEB_UPLOAD_JOBS_DIR"
DEFAULT_JOBS_DIR = "/tmp/omero_web_upload_jobs"

_UPLOAD_ROOT_CACHE = None
_JOBS_ROOT_CACHE = None
_DIRS_INITIALIZED = False


def resolve_upload_root() -> Path:
    """Resolve upload root directory from environment."""
    upload_root_str = os.environ.get(UPLOAD_ROOT_ENV, DEFAULT_UPLOAD_ROOT)
    return Path(upload_root_str).resolve()


def resolve_jobs_root() -> Path:
    """Resolve jobs root directory from environment."""
    jobs_root_str = os.environ.get(JOBS_DIR_ENV, DEFAULT_JOBS_DIR)
    return Path(jobs_root_str).resolve()


def ensure_parent_dir(path: Path) -> bool:
    """Ensure parent directory exists with proper permissions."""
    try:
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        return True
    except Exception as e:
        logger.error(f"Failed to create parent dir for {path}: {e}")
        return False


def initialize_directories():
    """Initialize upload and jobs directories."""
    global _UPLOAD_ROOT_CACHE, _JOBS_ROOT_CACHE, _DIRS_INITIALIZED
    
    if _DIRS_INITIALIZED:
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
            logger.error(f"Failed to initialize directory {root}: {e}")
    
    _UPLOAD_ROOT_CACHE = upload_root
    _JOBS_ROOT_CACHE = jobs_root
    _DIRS_INITIALIZED = True


def get_upload_root() -> Path:
    """Get cached upload root, initializing if needed."""
    global _UPLOAD_ROOT_CACHE
    if _UPLOAD_ROOT_CACHE is None:
        initialize_directories()
    return _UPLOAD_ROOT_CACHE


def get_jobs_root() -> Path:
    """Get cached jobs root, initializing if needed."""
    global _JOBS_ROOT_CACHE
    if _JOBS_ROOT_CACHE is None:
        initialize_directories()
    return _JOBS_ROOT_CACHE


def ensure_dir(path: Path) -> bool:
    """Ensure directory exists."""
    try:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
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
        logger.error(f"Failed to create/chmod directory {path}: {e}")
        return False


def safe_relative_path(raw_name: str):
    """Sanitize filename to safe relative path."""
    import re
    name = raw_name.strip()
    name = re.sub(r'[<>:"|?*]', '_', name)
    name = re.sub(r'\.\.', '_', name)
    name = name.lstrip('/\\')
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
        logger.error(f"Path {path} is outside root {root}")
        return
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
    except Exception as e:
        logger.error(f"Failed to remove {path}: {e}")
