"""Regression tests for interactive installer prompt handling."""

from __future__ import annotations

import errno
import os
import pty
import select
import signal
import stat
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class InstallationInteractivePromptRegressionTests(unittest.TestCase):
    """Exercise interactive installer prompts through a real PTY."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `InstallationInteractivePromptRegressionTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_path = cls.repo_root / "installation" / "installation_script.sh"
        cls.script_text = cls.script_path.read_text(encoding="utf-8")
        cls.validation_helpers = cls._extract_script_block(
            "is_non_negative_integer() {",
            "crowdsec_install_auto_restart_marker_path() {",
        )
        cls.prompt_functions = cls._extract_script_block(
            "is_valid_linux_path() {",
            "resolve_flatten_final_image_choice() {",
        )
        cls.build_functions = cls._extract_script_block(
            "resolve_buildx_inline_cache_setting() {",
            "resolve_buildx_local_cache_dir() {",
        )
        cls.cleanup_functions = cls._extract_script_block(
            "resolve_buildx_local_cache_dir() {",
            "compose_with_installation_env() {",
        )

    @classmethod
    def _extract_script_block(cls, start_marker: str, end_marker: str) -> str:
        """Extract the script block for `InstallationInteractivePromptRegressionTests`.

        Inputs: `start_marker` (str), `end_marker` (str). Output: `str`. Raises:
        AssertionError when validation or the called operation fails.
        """
        start = cls.script_text.find(start_marker)
        if start == -1:
            raise AssertionError(f"Unable to find script marker: {start_marker}")

        end = cls.script_text.find(end_marker, start)
        if end == -1:
            raise AssertionError(f"Unable to find script marker: {end_marker}")

        return cls.script_text[start:end]

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        """Write the executable for `InstallationInteractivePromptRegressionTests`.

        Inputs: `path` (Path) path, `content` (str). Output: None.
        """
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    @staticmethod
    def _build_harness(*blocks: str, body: str) -> str:
        """Build the harness for `InstallationInteractivePromptRegressionTests`.

        Inputs: `*blocks` (str), `body` (str). Output: `str`.
        """
        joined_blocks = "\n".join(
            [InstallationInteractivePromptRegressionTests.validation_helpers, *blocks]
        )
        return textwrap.dedent(
            f"""\
            #!/bin/bash
            set -euo pipefail
            install_transcript_record_line() {{
                :
            }}
            install_transcript_record_text() {{
                :
            }}
            INSTALLATION_AUTOMATION_MODE=0
            {joined_blocks}
            {body}
            """,
        )

    @staticmethod
    def _run_harness_with_pty(
        harness_path: Path,
        *,
        user_input: str,
        wait_for: str = "> ",
        timeout_seconds: float = 8.0,
    ) -> tuple[int, str]:
        """Harness with pty.

        Inputs: `harness_path` (Path), `user_input` (str), `wait_for` (str),
        `timeout_seconds` (float). Output: `tuple[int, str]`. Raises: AssertionError
        when validation or the called operation fails.
        """
        pid, fd = pty.fork()
        if pid == 0:
            completed = subprocess.run(
                [BASH_BIN, str(harness_path)],
                cwd=harness_path.parent,
                check=False,
            )
            os._exit(completed.returncode)

        output = bytearray()
        input_sent = False
        exit_status: int | None = None
        deadline = time.monotonic() + timeout_seconds

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    os.kill(pid, signal.SIGKILL)
                    _, status = os.waitpid(pid, 0)
                    decoded_output = output.decode("utf-8", errors="replace")
                    raise AssertionError(
                        f"Harness timed out waiting for completion.\nOutput so far:\n{decoded_output}",
                    )

                ready, _, _ = select.select([fd], [], [], min(0.1, remaining))
                if ready:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise

                    if not chunk:
                        break

                    output.extend(chunk)
                    if not input_sent and wait_for.encode() in output:
                        if user_input:
                            os.write(fd, user_input.encode("utf-8"))
                        input_sent = True

                pid_done, status = os.waitpid(pid, os.WNOHANG)
                if pid_done == pid:
                    exit_status = os.waitstatus_to_exitcode(status)
                    if not ready:
                        break

            if exit_status is None:
                _, status = os.waitpid(pid, 0)
                exit_status = os.waitstatus_to_exitcode(status)
        finally:
            os.close(fd)

        return exit_status, output.decode("utf-8", errors="replace")

    def test_delete_images_prompt_honors_yes_input(self) -> None:
        """Check delete images prompt honors yes input cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions in delete images prompt honors yes input.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                self._build_harness(
                    self.prompt_functions,
                    body=textwrap.dedent(
                        """\
                        DELETE_IMAGES_CHOICE=""
                        KEEP_IMAGES=1
                        resolve_delete_images_choice
                        printf 'KEEP_IMAGES=%s\n' "${KEEP_IMAGES}"
                        """,
                    ),
                ),
            )

            rc, output = self._run_harness_with_pty(harness_path, user_input="y\n")

            self.assertEqual(rc, 0, msg=output)
            self.assertIn("KEEP_IMAGES=0", output)

    def test_cache_prompt_honors_negative_input(self) -> None:
        """Verify cache prompt honors negative input.

        Inputs: repository fixtures. Output: fails on regressions in cache prompt honors negative input.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                self._build_harness(
                    self.prompt_functions,
                    body=textwrap.dedent(
                        """\
                        USE_BUILDX_COMPRESSED_BUILD=0
                        USE_CACHE_BUILD=1
                        resolve_cache_build_choice
                        printf 'USE_CACHE_BUILD=%s\n' "${USE_CACHE_BUILD}"
                        """,
                    ),
                ),
            )

            rc, output = self._run_harness_with_pty(harness_path, user_input="n\n")

            self.assertEqual(rc, 0, msg=output)
            self.assertIn("USE_CACHE_BUILD=0", output)

    def test_default_path_prompt_accepts_custom_path_after_negative_input(self) -> None:
        """Verify the default path prompt accepts custom path after negative input safety boundary.

        Inputs: repository fixtures. Output: fails on regressions when default path prompt accepts custom path after negative input accepts unsafe input.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                self._build_harness(
                    self.prompt_functions,
                    body=textwrap.dedent(
                        """\
                        result="$(resolve_path_with_default_prompt "/opt/omero" "OMERO installation path")"
                        printf 'RESULT=%s\n' "${result}"
                        """,
                    ),
                ),
            )

            rc, output = self._run_harness_with_pty(
                harness_path,
                user_input="n\n/srv/omero\n",
            )

            self.assertEqual(rc, 0, msg=output)
            self.assertIn("RESULT=/srv/omero", output)

    def test_interactive_no_cache_choice_prunes_and_uses_no_cache_compose_build(
        self,
    ) -> None:
        """Verify interactive no cache choice prunes and uses no cache compose build.

        Inputs: repository fixtures. Output: fails on regressions in interactive no cache choice prunes and uses no cache compose build.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bin_dir = temp_path / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            docker_log_path = temp_path / "docker.log"
            compose_log_path = temp_path / "compose.log"

            fake_docker_path = bin_dir / "docker"
            self._write_executable(
                fake_docker_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\\n' "$*" >> "{docker_log_path}"
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "--help" ]; then
                        exit 0
                    fi
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "-a" ] && [ "${{4:-}}" = "-f" ]; then
                        exit 0
                    fi
                    exit 0
                    """,
                ),
            )

            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                self._build_harness(
                    self.build_functions,
                    self.cleanup_functions,
                    self.prompt_functions,
                    body=textwrap.dedent(
                        f"""\
                        export PATH="{bin_dir}:$PATH"
                        compose_with_installation_env() {{
                            printf '%s\\n' "$*" >> "{compose_log_path}"
                        }}
                        USE_BUILDX_COMPRESSED_BUILD=0
                        USE_CACHE_BUILD=1
                        APPLY_SECURITY_HARDENING=0
                        ENABLE_VULNERABILITY_SCAN=0
                        DOCKER_BUILD_PROVENANCE=0
                        DOCKER_BUILD_FLATTEN_FINAL_IMAGE=0
                        OMERO_DROPBOX_VERSION=5.7.0
                        OMERO_CLI_ZARR_VERSION=0.8.0
                        OME_ZARR_PY_VERSION=0.16.0
                        BIOFORMATS2RAW_VERSION=0.11.0
                        BIOFORMATS_VERSION=8.5.0
                        OMERO_INSTALLATION_PATH="{temp_path}"
                        COMPOSE_FILE="{temp_path / "docker-compose.yml"}"
                        BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH="installation/docker_buildx_compressed_push.sh"
                        resolve_cache_build_choice
                        cleanup_local_build_cache_if_disabled
                        run_image_build
                        """,
                    ),
                ),
            )

            rc, output = self._run_harness_with_pty(harness_path, user_input="n\n")

            self.assertEqual(rc, 0, msg=output)
            self.assertIn(
                "Build cache is disabled; cleaning local build cache before rebuild...",
                output,
            )
            self.assertIn("Removed docker builder cache.", output)
            compose_log = compose_log_path.read_text(encoding="utf-8").strip()
            docker_log = docker_log_path.read_text(encoding="utf-8")
            self.assertIn(
                "--progress plain build --no-cache --provenance false",
                compose_log,
            )
            self.assertIn("builder prune --help", docker_log)
            self.assertIn("builder prune -a -f", docker_log)

    def test_interactive_no_cache_choice_prunes_buildx_cache_and_disables_buildx_cache_knobs(
        self,
    ) -> None:
        """Verify interactive no cache choice prunes buildx cache and disables buildx cache knobs.

        Inputs: repository fixtures. Output: fails on regressions in interactive no cache choice prunes buildx cache and disables buildx cache knobs.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bin_dir = temp_path / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            docker_log_path = temp_path / "docker.log"
            env_log_path = temp_path / "buildx-env.log"
            buildx_cache_dir = temp_path / "data" / "buildx_cache"
            buildx_cache_dir.mkdir(parents=True, exist_ok=True)
            (buildx_cache_dir / "marker.txt").write_text("cache", encoding="utf-8")

            fake_docker_path = bin_dir / "docker"
            self._write_executable(
                fake_docker_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\\n' "$*" >> "{docker_log_path}"
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "--help" ]; then
                        exit 0
                    fi
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "-a" ] && [ "${{4:-}}" = "-f" ]; then
                        exit 0
                    fi
                    exit 0
                    """,
                ),
            )

            helper_path = temp_path / "helper.sh"
            self._write_executable(
                helper_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    {{
                        printf 'DOCKER_BUILD_INLINE_CACHE=%s\\n' "${{DOCKER_BUILD_INLINE_CACHE:-}}"
                        printf 'DOCKER_BUILD_NO_CACHE=%s\\n' "${{DOCKER_BUILD_NO_CACHE:-}}"
                        printf 'DOCKER_BUILD_LOCAL_CACHE_ENABLED=%s\\n' "${{DOCKER_BUILD_LOCAL_CACHE_ENABLED:-}}"
                        printf 'DOCKER_BUILD_LOCAL_CACHE_MODE=%s\\n' "${{DOCKER_BUILD_LOCAL_CACHE_MODE:-}}"
                    }} > "{env_log_path}"
                    """,
                ),
            )

            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                self._build_harness(
                    self.build_functions,
                    self.cleanup_functions,
                    self.prompt_functions,
                    body=textwrap.dedent(
                        f"""\
                        export PATH="{bin_dir}:$PATH"
                        USE_BUILDX_COMPRESSED_BUILD=1
                        USE_CACHE_BUILD=1
                        APPLY_SECURITY_HARDENING=0
                        ENABLE_VULNERABILITY_SCAN=0
                        DOCKER_BUILD_PROVENANCE=0
                        DOCKER_BUILD_FLATTEN_FINAL_IMAGE=0
                        DOCKER_BUILD_LOCAL_CACHE_ENABLED=1
                        DOCKER_BUILD_LOCAL_CACHE_MODE=min
                        OMERO_DROPBOX_VERSION=5.7.0
                        OMERO_CLI_ZARR_VERSION=0.8.0
                        OME_ZARR_PY_VERSION=0.16.0
                        BIOFORMATS2RAW_VERSION=0.11.0
                        BIOFORMATS_VERSION=8.5.0
                        OMERO_INSTALLATION_PATH="{temp_path}"
                        OMERO_DATA_PATH="{temp_path / "data"}"
                        COMPOSE_FILE="{temp_path / "docker-compose.yml"}"
                        BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH="{helper_path.name}"
                        resolve_cache_build_choice
                        cleanup_local_build_cache_if_disabled
                        run_image_build
                        """,
                    ),
                ),
            )

            rc, output = self._run_harness_with_pty(harness_path, user_input="n\n")

            self.assertEqual(rc, 0, msg=output)
            self.assertIn("Removed docker builder cache.", output)
            self.assertIn("Removed Buildx local cache directory:", output)
            self.assertFalse(buildx_cache_dir.exists())
            env_log = env_log_path.read_text(encoding="utf-8")
            docker_log = docker_log_path.read_text(encoding="utf-8")
            self.assertIn("DOCKER_BUILD_INLINE_CACHE=0", env_log)
            self.assertIn("DOCKER_BUILD_NO_CACHE=1", env_log)
            self.assertIn("DOCKER_BUILD_LOCAL_CACHE_ENABLED=0", env_log)
            self.assertIn("DOCKER_BUILD_LOCAL_CACHE_MODE=min", env_log)
            self.assertIn("builder prune --help", docker_log)
            self.assertIn("builder prune -a -f", docker_log)


if __name__ == "__main__":
    unittest.main()
