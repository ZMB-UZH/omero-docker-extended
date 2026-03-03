"""Host-agnostic temporary artifact cleanup helpers.

This module is intentionally small and dependency-free. It is used by
plugins to remove their own temporary artifacts *immediately* after a
successful job, without relying on user clicks or view loads.

Longer-term cleanup (e.g. deleting remnants older than 24h) is performed
by the host-side systemd timer installed by scripts/install-tmp-cleaner.sh.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


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
        for root_dir, dirnames, filenames in os.walk(path, topdown=False, followlinks=follow_symlinks):
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
