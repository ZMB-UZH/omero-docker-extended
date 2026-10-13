#!/usr/bin/env python3
"""Prepare host quota metadata directories without following child symlinks."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import sys


def prepare(data_root: Path, web_gid: int) -> None:
    """Apply the runtime permission model to the two metadata directories only.

    Inputs: trusted operator data root and resolved web GID. Output: secure
    directories; existing files and application data remain unchanged.
    """
    if not 0 <= web_gid < 2**32 - 1:
        raise ValueError("The runtime group must be a valid nonnegative GID.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    with ExitStack() as opened:
        # The operator may select a symlinked data root. Untrusted children
        # below that root are opened relative to descriptors with NOFOLLOW.
        root = os.open(data_root, flags)
        opened.callback(os.close, root)
        parent = root
        directories = []
        bindings = []
        for name in (".admin-tools", "quota"):
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            descriptor = os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent)
            opened.callback(os.close, descriptor)
            directories.append(descriptor)
            bindings.append((parent, name, descriptor))
            parent = descriptor
        admin, quota = directories
        os.fchown(admin, 0, web_gid)
        # Only the service group writes state; sticky ownership protects root files.
        os.fchmod(admin, 0o1770)  # nosec B103
        os.fchown(quota, 0, 0)
        os.fchmod(quota, 0o700)
        for parent, name, descriptor in bindings:
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
