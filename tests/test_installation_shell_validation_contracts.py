"""Contracts for portable installer shell validation helpers."""

from __future__ import annotations

import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class InstallationShellValidationContractTests(unittest.TestCase):
    """Test cases for installation shell validation contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Store set up class."""
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_text = (
            cls.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        cls.validation_helpers = cls._extract_script_block(
            "is_non_negative_integer() {",
            "crowdsec_install_auto_restart_marker_path() {",
            cls.script_text,
        )
        cls.group_validation_helpers = cls._extract_script_block(
            "normalize_omero_install_group_list() {",
            "create_omero_groups_from_list() {",
            cls.script_text,
        )

    @staticmethod
    def _extract_script_block(
        start_marker: str, end_marker: str, source_text: str
    ) -> str:
        """Handle extract script block."""
        start = source_text.find(start_marker)
        if start == -1:
            raise AssertionError(f"Unable to find script marker: {start_marker}")

        end = source_text.find(end_marker, start)
        if end == -1:
            raise AssertionError(f"Unable to find script marker: {end_marker}")

        return source_text[start:end]

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        """Handle write executable."""
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run_harness(self, script_text: str) -> subprocess.CompletedProcess[str]:
        """Handle run harness."""
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

    def test_installer_avoids_bash_regex_operator(self) -> None:
        """Verify test installer avoids bash regex operator."""
        self.assertNotRegex(self.script_text, r"\[\[\s+[^\n]*=~")
        self.assertIn("is_non_negative_integer()", self.script_text)
        self.assertIn("is_positive_integer()", self.script_text)
        self.assertIn("is_shell_variable_name()", self.script_text)
        self.assertIn("is_omero_group_name()", self.script_text)

    def test_shell_validation_helpers_accept_only_expected_values(self) -> None:
        """Verify test shell validation helpers accept only exp behavior."""
        result = self._run_harness(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -euo pipefail

                {self.validation_helpers}

                expect_success() {{
                    local helper="$1"
                    shift
                    if ! "${{helper}}" "$@"; then
                        echo "expected success: ${{helper}} $*" >&2
                        exit 1
                    fi
                }}

                expect_failure() {{
                    local helper="$1"
                    shift
                    if "${{helper}}" "$@"; then
                        echo "expected failure: ${{helper}} $*" >&2
                        exit 1
                    fi
                }}

                expect_success is_non_negative_integer 0
                expect_success is_non_negative_integer 00042
                expect_failure is_non_negative_integer ""
                expect_failure is_non_negative_integer -1
                expect_failure is_non_negative_integer 1.0
                expect_failure is_non_negative_integer " 1"
                expect_failure is_non_negative_integer "1 "
                expect_failure is_non_negative_integer 1a

                expect_success is_positive_integer 1
                expect_success is_positive_integer 0007
                expect_failure is_positive_integer 0
                expect_failure is_positive_integer 000
                expect_failure is_positive_integer -1

                expect_success is_shell_variable_name _
                expect_success is_shell_variable_name _name_1
                expect_success is_shell_variable_name NAME1
                expect_failure is_shell_variable_name ""
                expect_failure is_shell_variable_name 1NAME
                expect_failure is_shell_variable_name NAME-1
                expect_failure is_shell_variable_name NAME.1

                expect_success is_omero_group_name team-1.alpha_beta
                expect_failure is_omero_group_name ""
                expect_failure is_omero_group_name team/name
                expect_failure is_omero_group_name team:name
                expect_failure is_omero_group_name "team name"

                unset CROWDSEC_ENROLL_KEY || true
                expect_failure is_crowdsec_enabled
                legacy_placeholder_prefix=CHANGE
                CROWDSEC_ENROLL_KEY="${{legacy_placeholder_prefix}}VALUE2" expect_failure is_crowdsec_enabled
                CROWDSEC_ENROLL_KEY="${{legacy_placeholder_prefix}}VALUE3" expect_failure is_crowdsec_enabled
                CROWDSEC_ENROLL_KEY=real-token expect_success is_crowdsec_enabled
                """
            )
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_group_list_validator_uses_same_name_contract(self) -> None:
        """Verify test group list validator uses same name cont behavior."""
        result = self._run_harness(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -euo pipefail

                {self.validation_helpers}
                {self.group_validation_helpers}

                expect_success() {{
                    if ! "$@"; then
                        echo "expected success: $*" >&2
                        exit 1
                    fi
                }}

                expect_failure() {{
                    if "$@"; then
                        echo "expected failure: $*" >&2
                        exit 1
                    fi
                }}

                expect_success validate_omero_install_group_list ""
                expect_success validate_omero_install_group_list "team-1.alpha_beta:read-annotate,qa:private"
                expect_failure validate_omero_install_group_list "team/name:private"
                expect_failure validate_omero_install_group_list "team:name:private"
                expect_failure validate_omero_install_group_list "team"
                expect_failure validate_omero_install_group_list "team:admin"
                """
            )
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
