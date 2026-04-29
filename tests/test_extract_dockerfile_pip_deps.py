"""Tests for tools/extract_dockerfile_pip_deps.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import textwrap

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = REPO_ROOT / "tools" / "extract_dockerfile_pip_deps.py"
DOCKERFILE = REPO_ROOT / "docker" / "omero-web.Dockerfile"


def test_extractor_produces_sorted_unique_output():
    """Verify test extractor produces sorted unique output."""
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
    """Verify test extractor includes known direct dependen behavior."""
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


def test_omeroweb_runtime_pins_psycopg2_binary_to_monitored_requirement():
    """Verify test omeroweb runtime pins psycopg2 binary to behavior."""
    requirement_prefix = "psycopg2-binary>="
    monitored_version = None
    requirements_path = REPO_ROOT / "omeroweb_omp_plugin" / "requirements.txt"
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(requirement_prefix):
            monitored_version = line.removeprefix(requirement_prefix).strip()
            break

    assert monitored_version, "OMP plugin requirements must monitor psycopg2-binary"

    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(DOCKERFILE)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert f"psycopg2-binary=={monitored_version}" in result.stdout.splitlines()


def test_extractor_excludes_build_tooling():
    """Verify test extractor excludes build tooling."""
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
    """Verify test extractor excludes shell variable refere behavior."""
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(DOCKERFILE)],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().splitlines():
        assert "${" not in line, f"Shell variable reference in output: {line}"
        assert "$(" not in line, f"Shell subcommand in output: {line}"


def test_extractor_accepts_common_version_specifiers(tmp_path):
    """Verify test extractor accepts common version specifiers."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        textwrap.dedent(
            """
            FROM python:3.14.4
            RUN python -m pip install --no-cache-dir \\
                "example~=1.2" \\
                "another>=1,<2" \\
                "package[extra]==3.4.5" \\
                "pip~=26.0" \\
                "${DYNAMIC_PACKAGE}"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), str(dockerfile)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.splitlines() == [
        "another>=1,<2",
        "example~=1.2",
        "package[extra]==3.4.5",
    ]


def test_extractor_fails_on_missing_file():
    """Verify test extractor fails on missing file."""
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), "/nonexistent/Dockerfile"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode != 0


def test_extractor_fails_without_arguments():
    """Verify test extractor fails without arguments."""
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode != 0
