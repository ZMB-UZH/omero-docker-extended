"""Host-agnostic temporary artifact cleanup helpers.

This module is intentionally small and dependency-free. It is used by
plugins to remove their own temporary artifacts *immediately* after a
successful job, without relying on user clicks or view loads.

Longer-term cleanup is performed by the host-side systemd timer installed by
scripts/install-tmp-cleaner.sh. Specific paths may request a longer retention
window by writing a small marker that the host-side cleaner honors.
"""

import os
import tempfile
import time
from pathlib import Path


RETENTION_DIR_MARKER_NAME = ".omero-retain-until"
RETENTION_FILE_MARKER_SUFFIX = ".retain-until"


def is_within_root(path: Path, root: Path) -> bool:
    """Return True if *path* is contained within *root* after resolving symlinks."""
    try:
        root_resolved = root.resolve(strict=True)
        path_resolved = path.resolve(strict=False)
    except OSError:
        return False
    try:
        path_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def safe_remove_tree(path: Path, root: Path, *, follow_symlinks: bool = False) -> bool:
    """Safely delete a directory tree.

    Safety properties:
      - refuses to delete symlinks
      - refuses to delete anything outside *root*
      - refuses to traverse symlinked children

    Returns True on success, False otherwise.
    """
    if not path.exists():
        return True

    if path.is_symlink():
        return False

    if not is_within_root(path, root):
        return False

    # Pre-scan for symlinks to avoid following unexpected paths.
    try:
        for root_dir, dirnames, filenames in os.walk(path, followlinks=follow_symlinks):
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
        for root_dir, dirnames, filenames in os.walk(
            path, topdown=False, followlinks=follow_symlinks
        ):
            for name in filenames:
                try:
                    (Path(root_dir) / name).unlink()
                except OSError:
                    return False
            for name in dirnames:
                try:
                    (Path(root_dir) / name).rmdir()
                except OSError:
                    return False
        path.rmdir()
        return True
    except OSError:
        return False


def safe_remove_job_data(job_id: str, upload_root: Path) -> bool:
    """Remove the upload data directory for *job_id* under *upload_root*.

    This intentionally does *not* delete the job JSON file in the jobs folder.
    The UI may still need to show the final status and messages for a while.
    """
    job_dir = upload_root / job_id
    return safe_remove_tree(job_dir, upload_root)


def _retention_marker_path(path: Path) -> Path:
    if path.is_dir():
        return path / RETENTION_DIR_MARKER_NAME
    return path.parent / f".{path.name}{RETENTION_FILE_MARKER_SUFFIX}"


def _fsync_directory(path: Path) -> None:
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
    """Persist a deferred-cleanup marker for *path* under *root*."""
    try:
        ttl_seconds = int(ttl_seconds)
    except (TypeError, ValueError):
        return False
    if ttl_seconds < 1:
        return False

    if not path.exists():
        return True

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
