from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class CrowdSecInstallationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    def test_console_enrollment_skips_reenroll_when_credentials_exist(self) -> None:
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_placeholder_value() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_console_credentials_path() {",
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

            self.assertFalse(log_path.exists(), "Existing credentials must suppress re-enrollment.")

    def test_console_enrollment_uses_engine_name_on_first_install(self) -> None:
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_placeholder_value() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_console_credentials_path() {",
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
                "console enroll first-install-token --name omero-host",
            )

    def test_console_enrollment_disables_when_key_is_placeholder(self) -> None:
        helper_block = self._slice_between(
            self.crowdsec_entrypoint,
            "is_placeholder_value() {",
            "# ---------------------------------------------------------------------------\n# Firewall backend detection",
        )
        enrollment_block = self._slice_between(
            self.crowdsec_entrypoint,
            "crowdsec_console_credentials_path() {",
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
                CROWDSEC_ENROLL_KEY="CHANGEVALUE3"
                CROWDSEC_ENGINE_NAME="CHANGEVALUE4"
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

    def test_restart_helper_restarts_running_container_once_and_removes_marker(self) -> None:
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
                ["bash", str(self.crowdsec_restart_helper)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            self.assertFalse(marker_path.exists(), "Helper must remove the one-shot marker.")
            self.assertEqual(log_path.read_text(encoding="utf-8").strip(), "restart crowdsec")

    def test_restart_helper_skips_restart_when_container_is_not_running(self) -> None:
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
                ["bash", str(self.crowdsec_restart_helper)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            self.assertFalse(marker_path.exists(), "Helper must clear stale one-shot markers.")
            self.assertFalse(log_path.exists(), "Stopped containers must not be restarted by the helper.")

    def test_installation_snapshots_missing_credentials_before_first_start(self) -> None:
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
                CROWDSEC_DB_PATH="{tmpdir_path / 'crowdsec_db'}"
                CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=0
                {install_block}
                mark_crowdsec_install_auto_restart_requirement
                printf 'before=%s\\n' "${{CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}}"
                : > "{config_dir / 'online_api_credentials.yaml'}"
                printf 'after=%s\\n' "${{CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}}"
                """
            )

            result = self._run_bash(script)

            self.assertEqual(result.stdout.strip().splitlines(), ["before=1", "after=1"])

    def _run_bash(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-lc", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _slice_between(self, content: str, start_marker: str, end_marker: str) -> str:
        start = content.index(start_marker)
        end = content.index(end_marker, start)
        return content[start:end].rstrip()


if __name__ == "__main__":
    unittest.main()
