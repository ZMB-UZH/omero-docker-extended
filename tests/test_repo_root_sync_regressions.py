from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


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
        cls.helper_path = cls.repo_root / "startup" / "repo_root_sync_helper.py"
        cls.helper_script = cls.helper_path.read_text(encoding="utf-8")

    def test_helper_plan_uses_only_configured_shared_prefix_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "ManagedRepository"
            (managed_root / "users_legacy" / "alice").mkdir(parents=True)
            (managed_root / ".omero").mkdir(parents=True)
            (managed_root / "codex-zarr-20260322live" / "alice").mkdir(parents=True)

            result = self._run_helper(
                "plan",
                "--managed-root",
                str(managed_root),
                "--repo-template",
                "%group%/%user%/%year%-%month%-%day%/%time%",
                "--install-groups",
                "users_private:private,users_read:read-only",
                "--ldap-config",
                "true",
                "--ldap-group",
                "users_ldap",
            )

        self.assertEqual(
            ["users_private", "users_read", "users_ldap"],
            result.stdout.strip().splitlines(),
        )

    def test_helper_plan_stops_before_volatile_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "ManagedRepository"
            (managed_root / "users_private" / "2025" / "alice").mkdir(parents=True)

            result = self._run_helper(
                "plan",
                "--managed-root",
                str(managed_root),
                "--repo-template",
                "%group%/%year%/%user%/%time%",
                "--install-groups",
                "users_private:private",
            )

        self.assertEqual(["users_private"], result.stdout.strip().splitlines())

    def test_helper_plan_handles_literal_shared_prefix_without_group_token(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "ManagedRepository"
            managed_root.mkdir(parents=True)

            result = self._run_helper(
                "plan",
                "--managed-root",
                str(managed_root),
                "--repo-template",
                "shared/%user%/%time%",
            )

        self.assertEqual(["shared"], result.stdout.strip().splitlines())

    def test_helper_plan_does_not_infer_group_prefixes_from_repository_contents(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "ManagedRepository"
            (managed_root / "users_private" / "alice").mkdir(parents=True)
            (managed_root / "guest").mkdir(parents=True)

            result = self._run_helper(
                "plan",
                "--managed-root",
                str(managed_root),
                "--repo-template",
                "%group%/%user%/%year%-%month%-%day%/%time%",
                "--install-groups",
                "",
                "--ldap-config",
                "false",
                "--ldap-group",
                "",
            )

        self.assertEqual("", result.stdout.strip())

    def test_helper_plan_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "ManagedRepository"
            (managed_root / "users_private" / "alice").mkdir(parents=True)
            before_paths = sorted(
                str(path.relative_to(managed_root))
                for path in managed_root.rglob("*")
                if path.is_dir()
            )

            self._run_helper(
                "plan",
                "--managed-root",
                str(managed_root),
                "--repo-template",
                "%group%/%user%/%year%-%month%-%day%/%time%",
                "--install-groups",
                "users_private:private",
            )

            after_paths = sorted(
                str(path.relative_to(managed_root))
                for path in managed_root.rglob("*")
                if path.is_dir()
            )

        self.assertEqual(before_paths, after_paths)

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
            "repo_root_sync_stable_prefix_depth() {",
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
                REPO_ROOT_DIR="{self.repo_root}"
                CONFIG_omero_fs_repo_path="shared/%user%/%time%"
                OMERO_SERVER_VAR_PATH="{server_var_dir}"
                OMERO_REPO_ROOT_BOOTSTRAP_RETRIES=1
                OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS=1
                {function_text}
                wait_for_repo_root_sync_ready 100
                """
            )

            self._run_bash(script)

    def test_installation_wait_skips_when_no_stable_shared_prefix(self) -> None:
        function_text = self._slice_function(
            self.installation_script,
            "repo_root_sync_stable_prefix_depth() {",
            "stop_old_installation_containers() {",
        )
        script = textwrap.dedent(
            f"""\
            set -euo pipefail
            START_CONTAINERS=1
            ROOTPASS=secret
            REPO_ROOT_DIR="{self.repo_root}"
            CONFIG_omero_fs_repo_path="%user%/%year%/%time%"
            OMERO_SERVER_VAR_PATH="/tmp/unused"
            {function_text}
            wait_for_repo_root_sync_ready 100
            """
        )

        result = self._run_bash(script)

        self.assertIn(
            "Skipping managed-repository shared-prefix readiness wait", result.stdout
        )

    def test_repo_root_bootstrap_retries_lookup_before_marking_failure(self) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "repo_root_sync_stable_prefix_depth() {",
            "schedule_repo_root_sync() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            status_file = Path(tmpdir) / "repo-root-sync.status"
            lookup_state_file = Path(tmpdir) / "lookup-count"
            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                TMPDIR="{tmpdir}"
                OMERO_CLI_USER=omero-server
                REPO_ROOT_SYNC_HELPER=/bin/true
                SERVER_VAR_DIR="{tmpdir}"
                REPO_ROOT_SYNC_STATUS_FILE="{status_file}"
                OMERO_REPO_ROOT_BOOTSTRAP_RETRIES=1
                OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS=1
                printf '0\\n' > "{lookup_state_file}"

                run_omero() {{
                    if [[ "${{1}}" == "-C" ]]; then
                        return 0
                    fi
                    if [[ "${{1}}" == "fs" && "${{2}}" == "mkdir" ]]; then
                        return 0
                    fi
                    if [[ "${{1}}" == "chown" ]]; then
                        return 0
                    fi
                    echo "unexpected run_omero call: $*" >&2
                    return 1
                }}

                resolve_server_venv_python() {{
                    printf '%s\\n' /bin/true
                }}

                expected_managed_repository_root() {{
                    printf '%s\\n' /OMERO/ManagedRepository
                }}

                verify_managed_repository_runtime_safety() {{
                    return 0
                }}

                runuser() {{
                    if printf '%s\\n' "$*" | grep -q ' plan '; then
                        printf '%s\\n' users_ldap
                        return 0
                    fi
                    local lookup_calls
                    lookup_calls="$(cat "{lookup_state_file}")"
                    lookup_calls=$((lookup_calls + 1))
                    printf '%s\\n' "${{lookup_calls}}" > "{lookup_state_file}"
                    if [[ "${{lookup_calls}}" -eq 1 ]]; then
                        printf '%s\\n' MISSING
                        return 0
                    fi
                    printf '%s\\n' FOUND\\|42\\|root\\|repo-1
                }}

                {function_text}
                run_repo_root_bootstrap_once secret
                printf 'lookup_calls=%s\\n' "$(cat "{lookup_state_file}")"
                cat "{status_file}"
                """
            )

            result = self._run_bash(script)

        self.assertIn("lookup_calls=2", result.stdout)
        self.assertIn("status=ok", result.stdout)
        self.assertIn("failed_prefix_count=0", result.stdout)

    def test_repo_root_bootstrap_lookup_is_repo_aware(self) -> None:
        self.assertIn('target_repo_uuid = ""', self.helper_script)
        self.assertIn("sharedResources().repositories()", self.helper_script)
        self.assertIn(
            "repo_description_path(description) != expected_managed_dir",
            self.helper_script,
        )
        self.assertIn(
            "obj.getPath() == parent_path and obj.getRepo() == target_repo_uuid",
            self.helper_script,
        )

    def test_validate_managed_repository_configuration_rejects_relative_path(
        self,
    ) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "normalize_dir_path() {",
            "validate_binary_repository_cleanse_configuration() {",
        )
        script = textwrap.dedent(
            """\
            set -euo pipefail
            OMERO_DIR=/OMERO
            SERVER_HOME=/tmp/omero-server/OMERO.server
            CONFIG_omero_managed_dir=ManagedRepository
            trim_whitespace() {
                printf "%s" "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
            }
            """
            + function_text
            + """
            validate_managed_repository_configuration
            """
        )

        result = subprocess.run(
            [BASH_BIN, "-lc", script],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("absolute path", result.stderr)

    def test_validate_managed_repository_configuration_rejects_image_local_repo(
        self,
    ) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "normalize_dir_path() {",
            "validate_binary_repository_cleanse_configuration() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            server_home = Path(tmpdir) / "server" / "OMERO.server"
            unexpected_root = (
                Path(tmpdir)
                / "server"
                / "OMERO.server-5.6.17-ice36"
                / "ManagedRepository"
            )
            omero_dir = Path(tmpdir) / "OMERO"
            server_home.mkdir(parents=True, exist_ok=True)
            unexpected_root.mkdir(parents=True, exist_ok=True)
            omero_dir.mkdir(parents=True, exist_ok=True)

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                OMERO_DIR="{omero_dir}"
                SERVER_HOME="{server_home}"
                CONFIG_omero_managed_dir="{omero_dir}/ManagedRepository"
                trim_whitespace() {{
                    printf "%s" "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
                }}
                {function_text}
                validate_managed_repository_configuration
                """
            )

            result = subprocess.run(
                [BASH_BIN, "-lc", script],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected image-local managed repository", result.stderr)

    def _run_bash(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH_BIN, "-lc", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _run_helper(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.helper_path), *args],
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
