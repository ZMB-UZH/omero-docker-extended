#!/usr/bin/env python3
"""Extract pip package names from a Dockerfile for license auditing.

Reads pip install lines from the given Dockerfile and prints one package
specifier per line.  Skips pip/setuptools/wheel (build tooling), tokens
that reference shell variables, and tokens that do not look like valid
Python package specifiers.

Usage:
    python3 tools/extract_dockerfile_pip_deps.py docker/omero-web.Dockerfile
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BUILD_TOOLING = {"pip", "setuptools", "wheel"}
_SHELL_VAR = re.compile(r"\$[{(]|\$\w")
# Match: pip install [flags...] <packages> terminated by ; or || or end-of-line
_PIP_INSTALL = re.compile(r"pip\s+install\s+(?:--\S+\s+)*(.+?)(?=\s*;\s|\s*\|\||\s*$)")
# Valid pip specifier: starts with letter, may contain [-_.], optional version
_VALID_PKG = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9._-]*(?:\[[-a-zA-Z0-9,._]+\])?(?:[><=!]+[a-zA-Z0-9.*_-]+)?$"
)


def extract(dockerfile: Path) -> list[str]:
    text = dockerfile.read_text(encoding="utf-8")
    # Join backslash-continued lines
    text = text.replace("\\\n", " ")
    packages: list[str] = []
    for line in text.splitlines():
        if "pip install" not in line:
            continue
        for match in _PIP_INSTALL.finditer(line):
            for token in match.group(1).split():
                token = token.strip("\"'")
                if not token or token.startswith("--"):
                    continue
                if _SHELL_VAR.search(token):
                    continue
                if not _VALID_PKG.match(token):
                    continue
                base_name = re.split(r"[><=!]", token)[0].lower()
                if base_name in _BUILD_TOOLING:
                    continue
                packages.append(token)
    return sorted(set(packages))


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <Dockerfile>", file=sys.stderr)
        sys.exit(1)
    dockerfile = Path(sys.argv[1])
    if not dockerfile.is_file():
        print(f"ERROR: {dockerfile} not found", file=sys.stderr)
        sys.exit(1)
    for pkg in extract(dockerfile):
        print(pkg)


if __name__ == "__main__":
    main()
