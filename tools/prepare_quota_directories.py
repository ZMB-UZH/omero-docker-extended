#!/usr/bin/env python3
"""Prepare host quota metadata directories without following child symlinks."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import sys
from typing import Iterator


LOGGER = logging.getLogger(__name__)


@contextmanager
def directory(path: Path | str, *, parent_fd: int | None = None) -> Iterator[int]:
    """Inputs: operator root or relative child. Output: owned directory handle.

    Only the operator-selected root may be an alias. Metadata children are
    created privately when absent and never opened through symbolic links.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if parent_fd is not None:
        try:
            os.mkdir(path, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            LOGGER.debug("Validating existing quota metadata directory")
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, dir_fd=parent_fd)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def prepare(data_root: Path, web_gid: int) -> None:
    """Apply the runtime permission model to the two metadata directories only.

    Inputs: trusted operator data root and resolved web GID. Output: secure
    directories; existing files and application data remain unchanged.
    """
    if not 0 <= web_gid < 2**32 - 1:
        raise ValueError("The runtime group must be a valid nonnegative GID.")
    with (
        directory(data_root) as root,
        directory(".admin-tools", parent_fd=root) as admin,
        directory("quota", parent_fd=admin) as quota,
    ):
        os.fchown(admin, 0, web_gid)
        # Only the service group writes state; sticky ownership protects root files.
        # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        os.fchmod(admin, 0o1770)  # nosec B103
        os.fchown(quota, 0, 0)
        # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        os.fchmod(quota, 0o700)
        for parent, name, descriptor in (
            (root, ".admin-tools", admin),
            (admin, "quota", quota),
        ):
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            expected = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != (
                expected.st_dev,
                expected.st_ino,
            ):
                raise ValueError("Quota metadata changed during permission setup.")


def main(argv: list[str] | None = None) -> int:
    """Run the Linux installer helper and fail closed on permission errors.

    Inputs: data root and numeric runtime GID arguments. Output: process status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("web_gid", type=int)
    args = parser.parse_args(argv)
    try:
        prepare(args.data_root, args.web_gid)
    except (OSError, ValueError) as exc:
        print(f"ERROR: Quota directory preparation failed: {exc}", file=sys.stderr)
        return 1
    print("Quota metadata directory permissions verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
