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
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_path = cls.repo_root / "installation" / "installation_script.sh"
        cls.script_text = cls.script_path.read_text(encoding="utf-8")
        cls.helper_text = (
            cls.repo_root / "installation" / "env_assignment_utils.sh"
        ).read_text(encoding="utf-8")
        cls.env_loader_block = cls._extract_script_block(
            "load_installation_paths_env() {",
            "bootstrap_env_files_from_examples() {",
            cls.script_text,
        )
        cls.resolver_block = cls._extract_script_block(
            "resolve_env_assignment_value() {",
            None,
            cls.helper_text,
        )
        cls.collector_block = cls._extract_script_block(
            "collect_bootstrap_sentinel_names() {",
            "bootstrap_installation_checkout_if_missing() {",
            cls.script_text,
        )

    @classmethod
    def _extract_script_block(
        cls, start_marker: str, end_marker: str | None, source_text: str
    ) -> str:
        start = source_text.find(start_marker)
        if start == -1:
            raise AssertionError(f"Unable to find script marker: {start_marker}")

        if end_marker is None:
            return source_text[start:]

        end = source_text.find(end_marker, start)
        if end == -1:
            raise AssertionError(f"Unable to find script marker: {end_marker}")

        return source_text[start:end]

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run_harness(self, script_text: str) -> subprocess.CompletedProcess[str]:
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
                    {self.resolver_block}
                    {self.env_loader_block}
                    load_installation_paths_env "{env_file}"
                    """
                )
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker_file.exists())
            self.assertIn("Refusing unsafe value", result.stderr)

    def test_installation_script_no_longer_re_evaluates_env_lines(self) -> None:
        self.assertNotIn('eval "${env_line}"', self.script_text)
        self.assertNotIn('eval "${env_key}', self.script_text)
        self.assertNotIn('eval "${env_line}"', self.helper_text)


if __name__ == "__main__":
    unittest.main()
