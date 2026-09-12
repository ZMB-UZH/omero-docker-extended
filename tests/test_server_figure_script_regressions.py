import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DOCKERFILE = REPO_ROOT / "docker" / "omero-server.Dockerfile"
SERVER_BOOTSTRAP = REPO_ROOT / "startup" / "10-server-bootstrap.sh"
BASH_BIN = shutil.which("bash") or "/bin/bash"
GIT_BIN = shutil.which("git") or "/usr/bin/git"


def _biop_fetch_commands() -> str:
    """Inputs: repository Dockerfile. Output: its actual dependency-fetch commands."""
    section = SERVER_DOCKERFILE.read_text(encoding="utf-8").split(
        "# Install BIOP OMERO script:", 1
    )[1]
    commands = section.split("RUN ", 1)[1].split("SCRIPT_SRC=", 1)[0]
    assert 'BIOP_SOURCE="$(mktemp -d)"' in commands
    return commands.replace("\\\n", "")


def _git(arguments, directory):
    """Inputs: Git arguments and fixture directory. Output: checked command stdout."""
    return subprocess.check_output(
        [GIT_BIN, "-c", "user.name=AI Agent", "-c", "user.email=", *arguments],
        cwd=directory,
        text=True,
    ).strip()


@pytest.fixture
def advanced_upstream(tmp_path):
    """Inputs: pytest temporary directory. Output: a real branch beyond its pinned commit."""
    source = tmp_path / "upstream"
    source.mkdir()
    _git(["init", "--initial-branch=main"], source)
    fixture = source / "fixture.txt"
    fixture.write_text("reviewed content\n", encoding="utf-8")
    _git(["add", "fixture.txt"], source)
    _git(["commit", "-m", "Reviewed fixture"], source)
    pinned = _git(["rev-parse", "HEAD"], source)
    fixture.write_text("new unreviewed content\n", encoding="utf-8")
    _git(["commit", "-am", "Advance fixture branch"], source)
    return source, pinned


def test_biop_fetch_preserves_pin_after_upstream_branch_advances(
    tmp_path, advanced_upstream
):
    """Inputs: a real advanced upstream. Output: exact pinned content, without branch fallback."""
    source, pinned = advanced_upstream
    commands = (
        _biop_fetch_commands() + '\n git -C "${BIOP_SOURCE}" show HEAD:fixture.txt\n'
    )
    result = subprocess.run(
        [BASH_BIN, "-c", commands],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TMPDIR": str(tmp_path),
            "BIOP_OMERO_SCRIPTS_REPO": source.as_uri(),
            "BIOP_OMERO_SCRIPTS_COMMIT": pinned,
            "BIOP_OMERO_SCRIPTS_REF": "nonexistent-reference",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("reviewed content\n")
    assert "new unreviewed content" not in result.stdout


@pytest.mark.parametrize("pin", ["", "main", "--upload-pack=invalid", "a" * 40])
def test_biop_fetch_rejects_invalid_or_missing_pin(tmp_path, advanced_upstream, pin):
    """Inputs: invalid or absent commit. Output: closed failure without fetching a branch."""
    source, _ = advanced_upstream
    result = subprocess.run(
        [BASH_BIN, "-c", _biop_fetch_commands()],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TMPDIR": str(tmp_path),
            "BIOP_OMERO_SCRIPTS_REPO": source.as_uri(),
            "BIOP_OMERO_SCRIPTS_COMMIT": pin,
            "BIOP_OMERO_SCRIPTS_REF": "main",
        },
    )
    assert result.returncode != 0
    assert not any(path.name == "fixture.txt" for path in tmp_path.glob("tmp.*/**/*"))


class ServerFigureScriptRegressionTests(unittest.TestCase):
    """Test cases for server figure script regression tests."""

    @classmethod
    def setUpClass(cls):
        """Prepare shared fixtures for `ServerFigureScriptRegressionTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.dockerfile = SERVER_DOCKERFILE.read_text(encoding="utf-8")
        cls.bootstrap = SERVER_BOOTSTRAP.read_text(encoding="utf-8")

    def test_server_image_bundles_figure_to_pdf_script(self):
        """Verify the server image bundles figure to pdf script execution contract.

        Inputs: repository fixtures. Output: fails on regressions in server image bundles figure to pdf script integration.
        """
        self.assertIn(
            'ARG OME_OMERO_FIGURE_REPO="https://github.com/ome/omero-figure.git"',
            self.dockerfile,
        )
        self.assertIn('ARG OME_OMERO_FIGURE_REF="7.4.1"', self.dockerfile)
        self.assertIn(
            "/opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py",
            self.dockerfile,
        )

    def test_biop_script_source_is_immutable_and_current(self):
        """Verify the installed BIOP script uses the reviewed source commit.

        Inputs: repository fixtures. Output: fails on a mutable or stale source pin.
        """
        biop_commit = "".join(("3dd78c7420f42bca4275", "75dfdc3acf9192d4f12d"))
        self.assertIn(f'ARG BIOP_OMERO_SCRIPTS_COMMIT="{biop_commit}"', self.dockerfile)
        self.assertIn(
            'if [[ "${actual_commit}" != "${BIOP_OMERO_SCRIPTS_COMMIT}" ]]',
            self.dockerfile,
        )

    def test_bootstrap_register_script_sync_skips_package_markers(self):
        """Verify the bootstrap register script sync skips package markers execution contract.

        Inputs: repository fixtures. Output: fails on regressions in bootstrap register script sync skips package markers integration.
        """
        self.assertIn(
            "if not file.endswith('.py') or file == '__init__.py':",
            self.bootstrap,
        )

    def test_bootstrap_requires_figure_version_env_var(self):
        """Verify bootstrap requires figure version env var.

        Inputs: repository fixtures. Output: fails on regressions in bootstrap requires figure version env var.
        """
        self.assertIn(
            'echo "ERROR: OMERO_FIGURE_VERSION must be set in env/omeroserver.env and must not be empty." >&2',
            self.bootstrap,
        )
        self.assertNotIn('figure_version="7.3.0"', self.bootstrap)

    def test_bootstrap_installs_figure_script_before_registration(self):
        """Verify the bootstrap installs figure script before registration execution contract.

        Inputs: repository fixtures. Output: fails on regressions in bootstrap installs figure script before registration integration.
        """
        self.assertRegex(
            self.bootstrap,
            re.compile(
                r"configure_script_python\n"
                r"\s*configure_ims_export_runtime_paths\n"
                r"\s*configure_import_runtime_paths\n"
                r"\s*ensure_certificate_sans\n"
                r"\s*cleanup_stale_repository_lock_files\n"
                r"\s*cleanup_rendering_caches\n"
                r"\s*toggle_zarr_pixel_buffer_plugin\n"
                r"\s*install_figure_script\n"
                r"\s*schedule_script_registration\n",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
