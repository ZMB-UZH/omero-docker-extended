"""Regression tests for safe installation env parsing."""

from __future__ import annotations

import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class InstallationEnvParsingRegressionTests(unittest.TestCase):
    """Test cases for installation env parsing regression tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `InstallationEnvParsingRegressionTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_path = cls.repo_root / "installation" / "installation_script.sh"
        cls.script_text = cls.script_path.read_text(encoding="utf-8")
        cls.helper_text = (
            cls.repo_root / "installation" / "env_assignment_utils.sh"
        ).read_text(encoding="utf-8")
        cls.validation_helpers = cls._extract_script_block(
            "is_non_negative_integer() {",
            "crowdsec_install_auto_restart_marker_path() {",
            cls.script_text,
        )
        cls.env_loader_block = cls._extract_script_block(
            "load_installation_paths_env() {",
            "bootstrap_env_files_from_examples() {",
            cls.script_text,
        )
        cls.env_assignment_reader_block = cls._extract_script_block(
            "read_env_assignment_from_file() {",
            "# Load secrets environment.",
            cls.script_text,
        )
        cls.dot_env_renderer_block = cls._extract_script_block(
            "render_compose_dot_env_template_assignments() {",
            "# Derive compose project name.",
            cls.script_text,
        )
        cls.resolver_block = cls._extract_script_block(
            "_env_assignment_is_name_start_char() {",
            None,
            cls.helper_text,
        )
        cls.collector_block = cls._extract_script_block(
            "collect_bootstrap_sentinel_names() {",
            "bootstrap_installation_checkout_if_missing() {",
            cls.script_text,
        )
        cls.installation_paths_writer_block = cls._extract_script_block(
            "quote_installation_env_value() {",
            "# Validate path is preparable.",
            cls.script_text,
        )

    @classmethod
    def _extract_script_block(
        cls, start_marker: str, end_marker: str | None, source_text: str
    ) -> str:
        """Extract the script block for `InstallationEnvParsingRegressionTests`.

        Inputs: `start_marker` (str), `end_marker` (str | None), `source_text` (str).
        Output: `str`. Raises: AssertionError when validation or external operations
        fail.
        """
        start = source_text.find(start_marker)
        if start == -1:
            raise AssertionError(f"Unable to find script marker: {start_marker}")

        if end_marker is None:
            return source_text[start:]

        end = source_text.find(end_marker, start)
        if end == -1:
            raise AssertionError(f"Unable to find script marker: {end_marker}")

        return source_text[start:end]

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        """Write the executable for `InstallationEnvParsingRegressionTests`.

        Inputs: `path` (Path) path, `content` (str). Output: None.
        """
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run_harness(self, script_text: str) -> subprocess.CompletedProcess[str]:
        """Run the harness for `InstallationEnvParsingRegressionTests`.

        Inputs: `script_text` (str). Output: `subprocess.CompletedProcess[str]`.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            harness_path = temp_path / "run.sh"
            self._write_executable(harness_path, script_text)
            return subprocess.run(
                [BASH_BIN, str(harness_path)],
                check=False,
                text=True,
                capture_output=True,
                cwd=temp_path,
            )

    def test_installation_env_loader_resolves_safe_variable_references(self) -> None:
        """Verify installation env loader resolves safe variable references.

        Inputs: repository fixtures. Output: fails on regressions in installation env loader resolves safe variable references.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / "installation_paths.env"
            env_file.write_text(
                textwrap.dedent(
                    """\
                    OMERO_INSTALLATION_PATH=/opt/omero
                    OMERO_DATABASE_PATH=${OMERO_INSTALLATION_PATH}/postgresdb/omero_database
                    OMERO_DATA_PATH=/srv/omero/data
                    OMERO_USER_DATA_PATH=${OMERO_DATA_PATH}/user
                    OMERO_WEB_VAR_PATH=${REPO_ROOT_DIR}/runtime/web_var
                    """
                ),
                encoding="utf-8",
            )

            result = self._run_harness(
                textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    set -euo pipefail
                    REPO_ROOT_DIR="/srv/repo"
                    {self.validation_helpers}
                    {self.resolver_block}
                    {self.env_loader_block}
                    {self.collector_block}
                    load_installation_paths_env "{env_file}"
                    printf 'DB=%s\\n' "${{OMERO_DATABASE_PATH}}"
                    printf 'USER=%s\\n' "${{OMERO_USER_DATA_PATH}}"
                    printf 'WEBVAR=%s\\n' "${{OMERO_WEB_VAR_PATH}}"
                    printf 'SENTINELS=%s\\n' "$(collect_bootstrap_sentinel_names | tr '\\n' ',' )"
                    printf 'REPO_DIRS=%s\\n' "$(collect_repo_data_dir_names | tr '\\n' ',' )"
                    """
                )
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("DB=/opt/omero/postgresdb/omero_database", result.stdout)
            self.assertIn("USER=/srv/omero/data/user", result.stdout)
            self.assertIn("WEBVAR=/srv/repo/runtime/web_var", result.stdout)
            self.assertIn(
                "SENTINELS=data,omero_database,postgresdb,user,web_var,",
                result.stdout,
            )
            self.assertIn("REPO_DIRS=runtime,", result.stdout)

    def test_installation_env_loader_rejects_command_substitution_without_executing_it(
        self,
    ) -> None:
        """Confirm installation env loader rejects command substitution without executing it is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in installation env loader rejects command substitution without executing it integration.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / "installation_paths.env"
            marker_file = temp_path / "should-not-exist"
            env_file.write_text(
                f'OMERO_INSTALLATION_PATH=$(touch "{marker_file}")\n',
                encoding="utf-8",
            )

            result = self._run_harness(
                textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    set -euo pipefail
                    {self.validation_helpers}
                    {self.resolver_block}
                    {self.env_loader_block}
                    load_installation_paths_env "{env_file}"
                    """
                )
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker_file.exists())
            self.assertIn("Refusing unsafe value", result.stderr)

    def test_installation_env_loader_rejects_invalid_variable_names(self) -> None:
        """Confirm installation env loader rejects invalid variable names is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in installation env loader rejects invalid variable names.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / "installation_paths.env"
            env_file.write_text("OMERO-DATA-PATH=/srv/omero\n", encoding="utf-8")

            result = self._run_harness(
                textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    set -euo pipefail
                    {self.validation_helpers}
                    {self.resolver_block}
                    {self.env_loader_block}
                    load_installation_paths_env "{env_file}"
                    """
                )
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid environment variable name", result.stderr)

    def test_installation_paths_writer_quotes_shell_sourced_paths(self) -> None:
        """Verify generated installation paths cannot execute shell metacharacters.

        Inputs: repository fixtures. Output: fails on generated env quoting
        regressions.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / "installation_paths.env"
            marker_file = temp_path / "should-not-exist"
            result = self._run_harness(
                textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    set -euo pipefail
                    {self.installation_paths_writer_block}
                    OMERO_INSTALLATION_PATH="/tmp/omero; touch {marker_file}"
                    OMERO_DATABASE_PATH="${{OMERO_INSTALLATION_PATH}}/postgresdb/omero_database"
                    OMERO_PLUGIN_DATABASE_PATH="${{OMERO_INSTALLATION_PATH}}/postgresdb/plugin_database"
                    OMERO_DATA_PATH="/tmp/omero data; touch {marker_file}"
                    OMERO_TMP_PATH="/tmp/omero tmp; touch {marker_file}"
                    OMERO_DATA_DIR="${{OMERO_DATA_PATH}}/OMERO"
                    OMERO_USER_DATA_PATH="${{OMERO_DATA_PATH}}/omero_user_data"
                    OMERO_IMPORT_PATH="${{OMERO_TMP_PATH}}/omeroweb-import"
                    OMERO_SERVER_VAR_PATH="${{OMERO_DATA_PATH}}/omero_server_var"
                    OMERO_WEB_VAR_PATH="${{OMERO_DATA_PATH}}/omero_web_var"
                    OMERO_SERVER_LOGS_PATH="${{OMERO_DATA_PATH}}/omero_server_logs"
                    OMERO_WEB_LOGS_PATH="${{OMERO_DATA_PATH}}/omero_web_logs"
                    OMERO_WEB_SUPERVISOR_LOGS_PATH="${{OMERO_DATA_PATH}}/omero_web_supervisor_logs"
                    PROMETHEUS_DATA_PATH="${{OMERO_DATA_PATH}}/prometheus_data"
                    GRAFANA_DATA_PATH="${{OMERO_DATA_PATH}}/grafana_data"
                    PORTAINER_DATA_PATH="${{OMERO_DATA_PATH}}/portainer_data"
                    LOKI_DATA_PATH="${{OMERO_DATA_PATH}}/loki_data"
                    ALLOY_DATA_PATH="${{OMERO_DATA_PATH}}/alloy_data"
                    PG_MAINTENANCE_DATA_PATH="${{OMERO_DATA_PATH}}/pg_maintenance_data"
                    BUILDX_DATA_PATH="${{OMERO_DATA_PATH}}/buildx_cache"
                    NODE_EXPORTER_TEXTFILE_PATH="${{OMERO_DATA_PATH}}/node_exporter_textfile"
                    CROWDSEC_DB_PATH="${{OMERO_DATA_PATH}}/crowdsec_db"
                    CROWDSEC_CONFIG_PATH="${{OMERO_DATA_PATH}}/crowdsec_config"
                    write_installation_paths_env "{env_file}"
                    verify_installation_paths_env_content "{env_file}"
                    . "{env_file}"
                    printf 'INSTALL=%s\\n' "${{OMERO_INSTALLATION_PATH}}"
                    printf 'USER_DATA=%s\\n' "${{OMERO_USER_DATA_PATH}}"
                    test ! -e "{marker_file}"
                    """
                )
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertFalse(marker_file.exists())
            self.assertIn(f"INSTALL=/tmp/omero; touch {marker_file}", result.stdout)
            self.assertIn(
                f"USER_DATA=/tmp/omero data; touch {marker_file}/omero_user_data",
                result.stdout,
            )

    def test_env_assignment_resolver_expands_safe_references_without_eval(
        self,
    ) -> None:
        """Verify env assignment resolver expands safe references without eval.

        Inputs: repository fixtures. Output: fails on regressions in env assignment resolver expands safe references without eval.
        """
        result = self._run_harness(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -euo pipefail
                {self.resolver_block}
                BASE_PATH=/srv/omero
                CHILD_NAME=data
                printf 'DOUBLE=%s\\n' "$(resolve_env_assignment_value '"$BASE_PATH/${{CHILD_NAME}}/files"')"
                printf 'BARE=%s\\n' "$(resolve_env_assignment_value '$BASE_PATH/$CHILD_NAME/files')"
                printf 'SINGLE=%s\\n' "$(resolve_env_assignment_value "'\\$BASE_PATH/\\${{CHILD_NAME}}'")"
                """
            )
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DOUBLE=/srv/omero/data/files", result.stdout)
        self.assertIn("BARE=/srv/omero/data/files", result.stdout)
        self.assertIn("SINGLE=$BASE_PATH/${CHILD_NAME}", result.stdout)

    def test_env_assignment_resolver_rejects_unsupported_parameter_expansion(
        self,
    ) -> None:
        """Confirm env assignment resolver rejects unsupported parameter expansion is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in env assignment resolver rejects unsupported parameter expansion.
        """
        result = self._run_harness(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -euo pipefail
                {self.resolver_block}
                BASE_PATH=/srv/omero
                resolve_env_assignment_value '${{BASE_PATH:-/fallback}}'
                """
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported parameter expansion", result.stderr)

    def test_dot_env_renderer_refreshes_empty_template_backed_values(self) -> None:
        """Verify dot env renderer refreshes empty template backed values.

        Inputs: synthetic generated .env and tracked template. Output: fails on regressions in generated .env refresh.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dot_env_path = temp_path / ".env"
            template_path = temp_path / ".env_example"
            dot_env_path.write_text(
                textwrap.dedent(
                    """\
                    REDIS_SAVE_POLICY=
                    REDIS_APPENDONLY=
                    REDIS_MAXMEMORY=1gb
                    REDIS_MAXMEMORY_POLICY=
                    REDIS_DATA_TMPFS_SIZE=
                    """
                ),
                encoding="utf-8",
            )
            template_path.write_text(
                textwrap.dedent(
                    """\
                    REDIS_SAVE_POLICY=
                    REDIS_APPENDONLY=no
                    REDIS_MAXMEMORY=512mb
                    REDIS_MAXMEMORY_POLICY=allkeys-lru
                    REDIS_DATA_TMPFS_SIZE=512m
                    """
                ),
                encoding="utf-8",
            )

            result = self._run_harness(
                textwrap.dedent(
                    f"""\
                    #!/bin/bash
                    set -euo pipefail
                    {self.validation_helpers}
                    {self.resolver_block}
                    {self.env_assignment_reader_block}
                    {self.dot_env_renderer_block}
                    render_compose_dot_env_template_assignments "{dot_env_path}" "{template_path}"
                    """
                )
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("REDIS_SAVE_POLICY=\n", result.stdout)
            self.assertIn("REDIS_APPENDONLY=no\n", result.stdout)
            self.assertIn("REDIS_MAXMEMORY=1gb\n", result.stdout)
            self.assertIn("REDIS_MAXMEMORY_POLICY=allkeys-lru\n", result.stdout)
            self.assertIn("REDIS_DATA_TMPFS_SIZE=512m\n", result.stdout)

    def test_installation_script_no_longer_re_evaluates_env_lines(self) -> None:
        """Verify the installation script no longer re evaluates env lines execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script no longer re evaluates env lines integration.
        """
        self.assertNotIn('eval "${env_line}"', self.script_text)
        self.assertNotIn('eval "${env_key}', self.script_text)
        self.assertNotIn('eval "${env_line}"', self.helper_text)
        self.assertNotIn("BASH_REMATCH", self.helper_text)


if __name__ == "__main__":
    unittest.main()
