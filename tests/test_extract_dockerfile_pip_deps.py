"""Tests for tools/extract_dockerfile_pip_deps.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = REPO_ROOT / "tools" / "extract_dockerfile_pip_deps.py"
DOCKERFILE = REPO_ROOT / "docker" / "omero-web.Dockerfile"


def test_extractor_produces_sorted_unique_output():
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(DOCKERFILE)],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.strip().splitlines()
    assert len(lines) > 0, "Extractor produced no output"
    assert lines == sorted(set(lines)), "Output must be sorted and unique"


def test_extractor_includes_known_direct_dependencies():
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(DOCKERFILE)],
        capture_output=True,
        text=True,
        check=True,
    )
    packages = {
        line.split(">=")[0].split("==")[0].lower()
        for line in result.stdout.strip().splitlines()
    }
    for expected in ("matplotlib", "celery", "redis", "omero-py", "psycopg2-binary"):
        assert expected in packages, f"Expected {expected} in extracted packages"


def test_extractor_excludes_build_tooling():
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(DOCKERFILE)],
        capture_output=True,
        text=True,
        check=True,
    )
    packages = {
        line.split(">=")[0].split("==")[0].lower()
        for line in result.stdout.strip().splitlines()
    }
    for excluded in ("pip", "setuptools", "wheel"):
        assert excluded not in packages, f"{excluded} (build tooling) must be excluded"


def test_extractor_excludes_shell_variable_references():
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(DOCKERFILE)],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().splitlines():
        assert "${" not in line, f"Shell variable reference in output: {line}"
        assert "$(" not in line, f"Shell subcommand in output: {line}"


def test_extractor_fails_on_missing_file():
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), "/nonexistent/Dockerfile"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_extractor_fails_without_arguments():
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
