from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class CrowdSecInstallationRegressionTests(unittest.TestCase):
    """Test cases for crowd sec installation regression tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set Up Class.

        Inputs: none. Output: None.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.crowdsec_entrypoint = (
            cls.repo_root / "docker" / "crowdsec-entrypoint.sh"
        ).read_text(encoding="utf-8")
        cls.installation_script = (
            cls.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        cls.crowdsec_restart_helper = (
            cls.repo_root / "installation" / "crowdsec_install_auto_restart.sh"
        )

    def test_console_enrollment_still_runs_when_only_capi_credentials_exist(
        self,
    ) -> None:
        """Verify console enrollment still runs when only capi credentials exist.

        Inputs: none. Output: None.
        """
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_true() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_install_enrollment_done_marker_path() {",
            "configure_console_enrollment\n\n# --- Wait for CrowdSec daemon to exit (container lifecycle) ----------------",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "etc" / "crowdsec"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "online_api_credentials.yaml").write_text(
                "already-enrolled\n", encoding="utf-8"
            )
            log_path = tmpdir_path / "cscli.log"

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_CONFIG_DIR="{config_dir}"
                CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR="{tmpdir_path / "data"}"
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="1"
                CROWDSEC_ENROLL_KEY="token-value"
                CROWDSEC_ENGINE_NAME="omero-host"
                CSCLI_LOG="{log_path}"
                cscli() {{
                    printf '%s\\n' "$*" >> "${{CSCLI_LOG}}"
                }}
                {helper_block}
                {enrollment_block}
                configure_console_enrollment
                """
            )

            self._run_bash(script)

            self.assertEqual(
                log_path.read_text(encoding="utf-8").strip(),
                "console enroll token-value --overwrite --name omero-host",
            )
            self.assertTrue(
                (tmpdir_path / "data" / ".console-enrollment-install.done").exists(),
                "First-install enrollment should persist the install-done marker even when CAPI credentials already exist.",
            )

    def test_console_enrollment_skips_reenroll_when_done_marker_exists(self) -> None:
        """Verify console enrollment skips reenroll when done marker exists.

        Inputs: none. Output: None.
        """
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_true() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_install_enrollment_done_marker_path() {",
            "configure_console_enrollment\n\n# --- Wait for CrowdSec daemon to exit (container lifecycle) ----------------",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "etc" / "crowdsec"
            config_dir.mkdir(parents=True, exist_ok=True)
            data_dir = tmpdir_path / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / ".console-enrollment-install.done").write_text(
                "", encoding="utf-8"
            )
            log_path = tmpdir_path / "cscli.log"

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_CONFIG_DIR="{config_dir}"
                CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR="{data_dir}"
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="1"
                CROWDSEC_ENROLL_KEY="first-install-token"
                CROWDSEC_ENGINE_NAME="omero-host"
                CSCLI_LOG="{log_path}"
                cscli() {{
                    printf '%s\\n' "$*" >> "${{CSCLI_LOG}}"
                }}
                {helper_block}
                {enrollment_block}
                configure_console_enrollment
                """
            )

            self._run_bash(script)

            self.assertFalse(
                log_path.exists(),
                "The install-done marker must suppress repeat console-enrollment attempts.",
            )
            self.assertTrue(
                (data_dir / ".console-enrollment-install.done").exists(),
                "The existing install-done marker must remain in place.",
            )

    def test_console_enrollment_uses_engine_name_on_first_install(self) -> None:
        """Verify console enrollment uses engine name on first install.

        Inputs: none. Output: None.
        """
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_true() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_install_enrollment_done_marker_path() {",
            "configure_console_enrollment\n\n# --- Wait for CrowdSec daemon to exit (container lifecycle) ----------------",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "etc" / "crowdsec"
            config_dir.mkdir(parents=True, exist_ok=True)
            log_path = tmpdir_path / "cscli.log"

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_CONFIG_DIR="{config_dir}"
                CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR="{tmpdir_path / "data"}"
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="1"
                CROWDSEC_ENROLL_KEY="sudo cscli console enroll first-install-token"
                CROWDSEC_ENGINE_NAME="omero-host"
                CSCLI_LOG="{log_path}"
                cscli() {{
                    printf '%s\\n' "$*" >> "${{CSCLI_LOG}}"
                }}
                {helper_block}
                {enrollment_block}
                configure_console_enrollment
                """
            )

            self._run_bash(script)

            self.assertEqual(
                log_path.read_text(encoding="utf-8").strip(),
                "console enroll first-install-token --overwrite --name omero-host",
            )
            self.assertTrue(
                (tmpdir_path / "data" / ".console-enrollment-install.done").exists(),
                "Successful first-install enrollment should persist the install-done marker.",
            )

    def test_console_enrollment_disables_when_key_is_placeholder(self) -> None:
        """Verify console enrollment disables when key is placeholder.

        Inputs: none. Output: None.
        """
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_true() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_install_enrollment_done_marker_path() {",
            "configure_console_enrollment\n\n# --- Wait for CrowdSec daemon to exit (container lifecycle) ----------------",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "etc" / "crowdsec"
            config_dir.mkdir(parents=True, exist_ok=True)
            log_path = tmpdir_path / "cscli.log"

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_CONFIG_DIR="{config_dir}"
                CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR="{tmpdir_path / "data"}"
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="1"
                legacy_placeholder_prefix="CHANGE"
                CROWDSEC_ENROLL_KEY="${{legacy_placeholder_prefix}}VALUE3"
                CROWDSEC_ENGINE_NAME="${{legacy_placeholder_prefix}}VALUE4"
                CSCLI_LOG="{log_path}"
                cscli() {{
                    printf '%s\\n' "$*" >> "${{CSCLI_LOG}}"
                }}
                {helper_block}
                {enrollment_block}
                configure_console_enrollment
                """
            )

            self._run_bash(script)

            self.assertEqual(
                log_path.read_text(encoding="utf-8").strip(),
                "console disable",
            )

    def test_console_enrollment_is_never_attempted_on_regular_restart_without_install_arm(
        self,
    ) -> None:
        """Verify console enrollment is never attempted on regular restart without install arm.

        Inputs: none. Output: None.
        """
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_true() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_install_enrollment_done_marker_path() {",
            "configure_console_enrollment\n\n# --- Wait for CrowdSec daemon to exit (container lifecycle) ----------------",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "etc" / "crowdsec"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "online_api_credentials.yaml").write_text(
                "url: https://api.crowdsec.net/\nlogin: seeded\npassword: seeded\n",
                encoding="utf-8",
            )
            log_path = tmpdir_path / "cscli.log"

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_CONFIG_DIR="{config_dir}"
                CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR="{tmpdir_path / "data"}"
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="0"
                CROWDSEC_ENROLL_KEY="first-install-token"
                CROWDSEC_ENGINE_NAME="omero-host"
                CSCLI_LOG="{log_path}"
                cscli() {{
                    printf '%s\\n' "$*" >> "${{CSCLI_LOG}}"
                }}
                {helper_block}
                {enrollment_block}
                configure_console_enrollment
                """
            )

            self._run_bash(script)

            self.assertFalse(
                log_path.exists(),
                "Regular CrowdSec restarts must not trigger console enrollment even when CAPI credentials already exist.",
            )

    def test_restart_helper_restarts_running_container_once_and_removes_marker(
        self,
    ) -> None:
        """Verify restart helper restarts running container once and removes marker.

        Inputs: none. Output: None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            bin_dir = tmpdir_path / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            log_path = tmpdir_path / "docker.log"
            marker_path = tmpdir_path / "pending.marker"
            marker_path.write_text("pending\n", encoding="utf-8")

            docker_script = bin_dir / "docker"
            docker_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    case "${{1:-}}" in
                        inspect)
                            if [ "${{2:-}}" = "--format" ]; then
                                printf '%s\\n' "${{DOCKER_RUNNING:-true}}"
                                exit 0
                            fi
                            exit 0
                            ;;
                        restart)
                            printf '%s\\n' "$*" >> "{log_path}"
                            exit 0
                            ;;
                    esac
                    exit 1
                    """
                ),
                encoding="utf-8",
            )
            docker_script.chmod(0o755)

            env = {
                "PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}",
                "CROWDSEC_AUTO_RESTART_MARKER": str(marker_path),
                "CROWDSEC_AUTO_RESTART_DELAY_SECONDS": "0",
                "CROWDSEC_AUTO_RESTART_CONTAINER_NAME": "crowdsec",
            }

            subprocess.run(
                [BASH_BIN, str(self.crowdsec_restart_helper)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            self.assertFalse(
                marker_path.exists(), "Helper must remove the one-shot marker."
            )
            self.assertEqual(
                log_path.read_text(encoding="utf-8").strip(), "restart crowdsec"
            )

    def test_restart_helper_skips_restart_when_container_is_not_running(self) -> None:
        """Verify restart helper skips restart when container is not running.

        Inputs: none. Output: None.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            bin_dir = tmpdir_path / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            log_path = tmpdir_path / "docker.log"
            marker_path = tmpdir_path / "pending.marker"
            marker_path.write_text("pending\n", encoding="utf-8")

            docker_script = bin_dir / "docker"
            docker_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    case "${{1:-}}" in
                        inspect)
                            if [ "${{2:-}}" = "--format" ]; then
                                printf '%s\\n' "${{DOCKER_RUNNING:-false}}"
                                exit 0
                            fi
                            exit 0
                            ;;
                        restart)
                            printf '%s\\n' "$*" >> "{log_path}"
                            exit 0
                            ;;
                    esac
                    exit 1
                    """
                ),
                encoding="utf-8",
            )
            docker_script.chmod(0o755)

            env = {
                "PATH": f"{bin_dir}:{Path('/usr/bin')}:{Path('/bin')}",
                "CROWDSEC_AUTO_RESTART_MARKER": str(marker_path),
                "CROWDSEC_AUTO_RESTART_DELAY_SECONDS": "0",
                "CROWDSEC_AUTO_RESTART_CONTAINER_NAME": "crowdsec",
                "DOCKER_RUNNING": "false",
            }

            subprocess.run(
                [BASH_BIN, str(self.crowdsec_restart_helper)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            self.assertFalse(
                marker_path.exists(), "Helper must clear stale one-shot markers."
            )
            self.assertFalse(
                log_path.exists(),
                "Stopped containers must not be restarted by the helper.",
            )

    def test_installation_arms_bootstrap_even_when_runtime_state_already_exists(
        self,
    ) -> None:
        """Verify installation arms bootstrap even when runtime state already exists.

        Inputs: none. Output: None.
        """
        install_block = self._slice_between(
            self.installation_script,
            "is_crowdsec_enabled() {",
            "load_installation_paths_env() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "crowdsec_config"
            config_dir.mkdir(parents=True, exist_ok=True)

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_ENROLL_KEY="real-token"
                CROWDSEC_CONFIG_PATH="{config_dir}"
                CROWDSEC_DB_PATH="{tmpdir_path / "crowdsec_db"}"
                CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=0
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL=0
                {install_block}
                prepare_crowdsec_install_bootstrap_enrollment
                printf 'before=%s,%s\\n' "${{CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}}" "${{CROWDSEC_INSTALL_BOOTSTRAP_ENROLL}}"
                cat > "{config_dir / "config.yaml"}" <<'EOF'
api:
  server:
    listen_uri: 127.0.0.1:8080
EOF
                prepare_crowdsec_install_bootstrap_enrollment
                printf 'after=%s,%s\\n' "${{CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}}" "${{CROWDSEC_INSTALL_BOOTSTRAP_ENROLL}}"
                """
            )

            result = self._run_bash(script)

            stdout_lines = result.stdout.strip().splitlines()
            self.assertEqual(stdout_lines[0], "before=1,1")
            self.assertIn("CrowdSec runtime state already exists", result.stdout)
            self.assertIn(
                "This installation run will still create a fresh CrowdSec dashboard enrollment request and schedule the install-only auto-restart.",
                result.stdout,
            )
            self.assertEqual(stdout_lines[-1], "after=1,1")

    def test_installation_reports_existing_crowdsec_runtime_state_in_transcript(
        self,
    ) -> None:
        """Verify installation reports existing crowdsec runtime state in transcript.

        Inputs: none. Output: None.
        """
        install_block = self._slice_between(
            self.installation_script,
            "is_crowdsec_enabled() {",
            "load_installation_paths_env() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "crowdsec_config"
            db_dir = tmpdir_path / "crowdsec_db"
            config_dir.mkdir(parents=True, exist_ok=True)
            db_dir.mkdir(parents=True, exist_ok=True)
            (db_dir / "crowdsec.db").write_text(
                "sqlite-placeholder\n", encoding="utf-8"
            )

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_ENROLL_KEY="real-token"
                CROWDSEC_CONFIG_PATH="{config_dir}"
                CROWDSEC_DB_PATH="{db_dir}"
                CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=0
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL=0
                {install_block}
                prepare_crowdsec_install_bootstrap_enrollment
                printf 'flags=%s,%s\\n' "${{CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}}" "${{CROWDSEC_INSTALL_BOOTSTRAP_ENROLL}}"
                """
            )

            result = self._run_bash(script)

            self.assertIn("CrowdSec runtime state already exists", result.stdout)
            self.assertIn(
                "This installation run will still create a fresh CrowdSec dashboard enrollment request and schedule the install-only auto-restart.",
                result.stdout,
            )
            self.assertIn("flags=1,1", result.stdout)

    def test_installation_clears_done_marker_before_rearming_enrollment(self) -> None:
        """Verify installation clears done marker before rearming enrollment.

        Inputs: none. Output: None.
        """
        install_block = self._slice_between(
            self.installation_script,
            "is_crowdsec_enabled() {",
            "load_installation_paths_env() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_dir = tmpdir_path / "crowdsec_config"
            db_dir = tmpdir_path / "crowdsec_db"
            marker_path = db_dir / ".console-enrollment-install.done"
            config_dir.mkdir(parents=True, exist_ok=True)
            db_dir.mkdir(parents=True, exist_ok=True)
            marker_path.write_text("done\n", encoding="utf-8")

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                CROWDSEC_ENROLL_KEY="real-token"
                CROWDSEC_CONFIG_PATH="{config_dir}"
                CROWDSEC_DB_PATH="{db_dir}"
                CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=0
                CROWDSEC_INSTALL_BOOTSTRAP_ENROLL=0
                {install_block}
                prepare_crowdsec_install_bootstrap_enrollment
                printf 'flags=%s,%s\\n' "${{CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}}" "${{CROWDSEC_INSTALL_BOOTSTRAP_ENROLL}}"
                if [ -f "{marker_path}" ]; then
                    echo "marker=present"
                else
                    echo "marker=removed"
                fi
                """
            )

            result = self._run_bash(script)

            self.assertIn(
                "Removed existing CrowdSec install enrollment marker so this installation run requests dashboard approval again.",
                result.stdout,
            )
            self.assertIn("flags=1,1", result.stdout)
            self.assertIn("marker=removed", result.stdout)

    @staticmethod
    def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
        """Bash.

        Inputs: `script`. Output: `subprocess.CompletedProcess[str]`.
        """
        return subprocess.run(
            [BASH_BIN, "-lc", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @staticmethod
    def _slice_between(content: str, start_marker: str, end_marker: str) -> str:
        """Slice between.

        Inputs: `content`, `start_marker`, `end_marker`. Output: `str`.
        """
        start = content.index(start_marker)
        end = content.index(end_marker, start)
        return content[start:end].rstrip()


if __name__ == "__main__":
    unittest.main()
