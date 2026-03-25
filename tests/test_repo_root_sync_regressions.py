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

    def test_repo_root_bootstrap_retries_lookup_before_marking_failure(self) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "run_repo_root_bootstrap_once() {",
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
                OMERO_REPO_ROOT_BOOTSTRAP_RETRIES=1
                OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS=0
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

                list_repo_root_bootstrap_groups() {{
                    printf '%s\\n' users_ldap
                }}

                collect_repo_root_bootstrap_paths() {{
                    printf '%s\\n' users_ldap
                }}

                resolve_server_venv_python() {{
                    printf '%s\\n' /bin/true
                }}

                resolve_cli_home() {{
                    printf '%s\\n' /tmp
                }}

                expected_managed_repository_root() {{
                    printf '%s\\n' /OMERO/ManagedRepository
                }}

                verify_managed_repository_runtime_safety() {{
                    return 0
                }}

                write_repo_root_sync_status() {{
                    printf 'status=%s\\nlast_success_epoch=%s\\ninspected_prefix_count=%s\\nnormalized_prefix_count=%s\\nfailed_prefix_count=%s\\n' \
                        "$1" "$2" "$3" "$4" "$5" > "{status_file}"
                }}

                runuser() {{
                    local lookup_calls
                    lookup_calls="$(cat "{lookup_state_file}")"
                    lookup_calls=$((lookup_calls + 1))
                    printf '%s\\n' "${{lookup_calls}}" > "{lookup_state_file}"
                    if [[ "${{lookup_calls}}" -eq 1 ]]; then
                        printf '%s\\n' MISSING
                        return 0
                    fi
                    printf '%s\\n' FOUND\\|42\\|root
                }}

                chown() {{ :; }}
                chmod() {{ :; }}

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
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "run_repo_root_bootstrap_once() {",
            "schedule_repo_root_sync() {",
        )

        self.assertIn('target_repo_uuid = ""', function_text)
        self.assertIn("sharedResources().repositories()", function_text)
        self.assertIn("repo_description_path(description) != expected_managed_dir", function_text)
        self.assertIn('obj.getPath() == parent_path and obj.getRepo() == target_repo_uuid', function_text)
        self.assertIn('"${managed_repo_root}"', function_text)

    def test_validate_managed_repository_configuration_rejects_relative_path(self) -> None:
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
            """ + function_text + """
            validate_managed_repository_configuration
            """
        )

        result = subprocess.run(
            ["bash", "-lc", script],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("absolute path", result.stderr)

    def test_validate_managed_repository_configuration_rejects_image_local_repo(self) -> None:
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "normalize_dir_path() {",
            "validate_binary_repository_cleanse_configuration() {",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            server_home = Path(tmpdir) / "server" / "OMERO.server"
            unexpected_root = Path(tmpdir) / "server" / "OMERO.server-5.6.17-ice36" / "ManagedRepository"
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
                ["bash", "-lc", script],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected image-local managed repository", result.stderr)

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
