from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class RepoRootSyncRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.installation_script = (
            cls.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        cls.server_bootstrap_script = (
            cls.repo_root / "startup" / "10-server-bootstrap.sh"
        ).read_text(encoding="utf-8")

    def test_collect_repo_root_bootstrap_paths_unions_runtime_and_configured_groups(self) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "trim_whitespace() {",
            "resolve_cli_home() {",
        )
        script = textwrap.dedent(
            f"""\
            set -euo pipefail
            {function_text}
            CONFIG_omero_fs_repo_path="%group%/%user%/%year%-%month%-%day%/%time%"
            OMERO_INSTALL_GROUP_LIST="users_private:private,users_read:read-only"
            collect_repo_root_bootstrap_paths users_ldap users_collaboration
            """
        )

        result = self._run_bash(script)
        emitted_paths = result.stdout.strip().splitlines()

        self.assertIn("users_ldap", emitted_paths)
        self.assertIn("users_collaboration", emitted_paths)
        self.assertIn("users_private", emitted_paths)
        self.assertIn("users_read", emitted_paths)

    def test_write_repo_root_sync_status_records_expected_fields(self) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "write_repo_root_sync_status() {",
            "run_repo_root_bootstrap_once() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            status_file = Path(tmpdir) / "repo-root-sync.status"
            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                SERVER_VAR_DIR="{tmpdir}"
                REPO_ROOT_SYNC_STATUS_FILE="{status_file}"
                {function_text}
                write_repo_root_sync_status ok 123 4 2 0
                cat "{status_file}"
                """
            )

            result = self._run_bash(script)

        self.assertIn("status=ok", result.stdout)
        self.assertIn("last_success_epoch=123", result.stdout)
        self.assertIn("inspected_prefix_count=4", result.stdout)
        self.assertIn("normalized_prefix_count=2", result.stdout)
        self.assertIn("failed_prefix_count=0", result.stdout)

    def test_installation_wait_accepts_current_repo_root_sync_status(self) -> None:
        function_text = self._slice_function(
            self.installation_script,
            "wait_for_repo_root_sync_ready() {",
            "stop_old_installation_containers() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            server_var_dir = Path(tmpdir) / "server-var"
            server_var_dir.mkdir(parents=True, exist_ok=True)
            status_file = server_var_dir / "repo-root-sync.status"
            status_file.write_text(
                textwrap.dedent(
                    """\
                    status=ok
                    last_success_epoch=200
                    inspected_prefix_count=1
                    normalized_prefix_count=1
                    failed_prefix_count=0
                    """
                ),
                encoding="utf-8",
            )
            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                START_CONTAINERS=1
                ROOTPASS=secret
                CONFIG_omero_fs_repo_path="%group%/%user%/%year%-%month%-%day%/%time%"
                OMERO_SERVER_VAR_PATH="{server_var_dir}"
                OMERO_REPO_ROOT_BOOTSTRAP_RETRIES=1
                OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS=1
                {function_text}
                wait_for_repo_root_sync_ready 100
                """
            )

            self._run_bash(script)

    def _run_bash(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-lc", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _slice_function(self, content: str, start_marker: str, end_marker: str) -> str:
        start = content.index(start_marker)
        end = content.index(end_marker, start)
        return content[start:end].rstrip()


if __name__ == "__main__":
    unittest.main()
