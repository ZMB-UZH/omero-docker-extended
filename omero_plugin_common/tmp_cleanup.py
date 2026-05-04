"""Host-agnostic temporary artifact cleanup helpers."""

import os
import shutil
import tempfile
import time
from pathlib import Path


RETENTION_DIR_MARKER_NAME = ".omero-retain-until"
RETENTION_FILE_MARKER_SUFFIX = ".retain-until"


def _resolve_existing(path: Path) -> Path | None:
    """Resolve the existing.

    Inputs: `path` (Path) path. Output: `Path | None`.
    """
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _resolve_child_candidate(path: Path) -> Path | None:
    """Resolve the child candidate.

    Inputs: `path` (Path) path. Output: `Path | None`.
    """
    if path.exists() or path.is_symlink():
        return _resolve_existing(path)
    parent = _resolve_existing(path.parent)
    if parent is None:
        return None
    return parent / path.name


def _is_safe_path_component(value: str) -> bool:
    """Return whether safe path component.

    Inputs: `value`. Output: `bool`.
    """
    return (
        value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
    )


def is_within_root(path: Path, root: Path) -> bool:
    """Return True if *path* is contained within *root* after resolving symlinks.

    Inputs: `path`, `root`. Output: `bool`.
    """
    root_resolved = _resolve_existing(root)
    path_resolved = _resolve_child_candidate(path)
    if root_resolved is None or path_resolved is None:
        return False
    try:
        path_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def safe_remove_tree(path: Path, root: Path) -> bool:
    """Safely delete a directory tree under *root*.

    Inputs: `path`, `root`. Output: `bool`.
    """
    if not path.exists():
        return is_within_root(path, root)

    root_resolved = _resolve_existing(root)
    path_resolved = _resolve_existing(path)
    if root_resolved is None or path_resolved is None or path_resolved == root_resolved:
        return False

    if path.is_symlink():
        return False

    if not is_within_root(path, root):
        return False

    # Pre-scan for symlinks to avoid following unexpected paths.
    try:
        for root_dir, dirnames, filenames in os.walk(path, followlinks=False):
            for name in dirnames:
                candidate = Path(root_dir) / name
                if candidate.is_symlink():
                    return False
            for name in filenames:
                candidate = Path(root_dir) / name
                if candidate.is_symlink():
                    return False
    except OSError:
        return False

    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def safe_remove_job_data(job_id: str, upload_root: Path) -> bool:
    """Return safe remove job data.

    Inputs: `job_id`, `upload_root`. Output: `bool`.
    """
    if not _is_safe_path_component(str(job_id)):
        return False
    job_dir = upload_root / job_id
    return safe_remove_tree(job_dir, upload_root)


def _retention_marker_path(path: Path) -> Path:
    """Return the retention marker path.

    Inputs: `path` (Path) path. Output: `Path`.
    """
    if path.is_dir():
        return path / RETENTION_DIR_MARKER_NAME
    return path.parent / f".{path.name}{RETENTION_FILE_MARKER_SUFFIX}"


def _fsync_directory(path: Path) -> None:
    """Flush directory metadata after atomic filesystem updates.

    Inputs: `path` (Path) path. Output: None.
    """
    try:
        dir_fd = os.open(path, os.O_DIRECTORY)
    except (AttributeError, OSError):
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def safe_mark_path_for_deferred_cleanup(
    path: Path,
    root: Path,
    *,
    ttl_seconds: int,
    now: float | None = None,
) -> bool:
    """Persist a deferred-cleanup marker for *path* under *root*.

    Inputs: `path`, `root`, `ttl_seconds`, `now`. Output: `bool`.
    """
    try:
        ttl_seconds = int(ttl_seconds)
    except (TypeError, ValueError):
        return False
    if ttl_seconds < 1:
        return False

    if not path.exists():
        return is_within_root(path, root)

    if path.is_symlink():
        return False

    if not is_within_root(path, root):
        return False

    marker_path = _retention_marker_path(path)
    if not is_within_root(marker_path, root):
        return False

    expires_at = int((time.time() if now is None else now) + ttl_seconds)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=marker_path.parent,
            prefix=f".{marker_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(f"{expires_at}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, marker_path)
        _fsync_directory(marker_path.parent)
        tmp_path = None
        return True
    except OSError:
        return False
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
