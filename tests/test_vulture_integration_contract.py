"""Contract tests for the Vulture dead-code workflow and scope runner."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from unittest import TestCase, main, mock

import yaml

from tools import vulture_check


class VultureIntegrationContractTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_python_style_doc_covers_vulture_workflow_and_local_runner(self) -> None:
        doc_text = self.read_text("docs/reference/python-style-and-linting.md")
        self.assertIn(".github/workflows/vulture.yml", doc_text)
        self.assertIn("python3 tools/vulture_check.py", doc_text)
        self.assertIn("dead-code gate", doc_text.lower())
        self.assertIn("tracked production Python files", doc_text)

    def test_vulture_requirements_are_hash_pinned(self) -> None:
        compiled = self.read_text(".github/requirements/vulture-ci.txt")
        self.assertIn("pip-compile", compiled)
        self.assertIn("vulture==2.16", compiled)
        self.assertIn("--generate-hashes", compiled)
        self.assertIn("--hash=sha256:", compiled)

    def test_vulture_workflow_is_pinned_and_uses_repo_runner(self) -> None:
        workflow = yaml.safe_load(self.read_text(".github/workflows/vulture.yml"))
        triggers = workflow[True]
        self.assertEqual(["main"], triggers["pull_request"]["branches"])
        self.assertEqual(["main"], triggers["push"]["branches"])
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("ubuntu-24.04", workflow["jobs"]["vulture"]["runs-on"])

        steps = workflow["jobs"]["vulture"]["steps"]
        uses_values = [step.get("uses") for step in steps if "uses" in step]
        run_values = [step.get("run") for step in steps if "run" in step]

        self.assertIn(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            uses_values,
        )
        self.assertIn(
            "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
            uses_values,
        )
        self.assertTrue(
            any(
                "python3 -m pip install --require-hashes --requirement .github/requirements/vulture-ci.txt"
                in value
                for value in run_values
            )
        )
        self.assertTrue(
            any("python3 tools/vulture_check.py" in value for value in run_values)
        )

    def test_scope_keeps_only_tracked_production_python_files(self) -> None:
        include = (
            "tools/vulture_check.py",
            "startup/50-config.py",
            "fuzzing/fuzz_filename_parser.py",
            "omeroweb_import/views/core_functions.py",
        )
        exclude = (
            "tests/test_vulture_integration_contract.py",
            "omeroweb_import/tests/test_core_function_helpers.py",
            "docs/conf.py",
            "third_party/caveman-v1.5.0/tools/helper.py",
            ".agents/skills/caveman/SKILL.md",
            ".github/scripts/helper.py",
            "omeroweb_import/conftest.py",
            "omeroweb_import/test_sem_edx.py",
            "omeroweb_import/sem_edx_test.py",
        )

        for relative_path in include:
            with self.subTest(relative_path=relative_path):
                self.assertTrue(
                    vulture_check.is_vulture_target(PurePosixPath(relative_path))
                )

        for relative_path in exclude:
            with self.subTest(relative_path=relative_path):
                self.assertFalse(
                    vulture_check.is_vulture_target(PurePosixPath(relative_path))
                )

    def test_list_vulture_targets_uses_git_ls_files_and_safe_directory(self) -> None:
        repo_root = self.repo_root
        tracked_files = "\n".join(
            [
                "tests/test_vulture_integration_contract.py",
                "tools/vulture_check.py",
                "omeroweb_import/views/core_functions.py",
                "omeroweb_import/tests/test_core_function_helpers.py",
                ".agents/skills/caveman/agents/openai.yaml",
            ]
        )
        with (
            mock.patch(
                "tools.vulture_check.resolve_required_executable",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "tools.vulture_check.subprocess.run",
                return_value=mock.Mock(stdout=tracked_files, returncode=0),
            ) as mocked_run,
        ):
            self.assertEqual(
                [
                    "tools/vulture_check.py",
                    "omeroweb_import/views/core_functions.py",
                ],
                vulture_check.list_vulture_targets(repo_root),
            )

        mocked_run.assert_called_once_with(
            [
                "/usr/bin/git",
                "-c",
                f"safe.directory={repo_root.resolve()}",
                "ls-files",
                "--",
                "*.py",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_build_vulture_command_uses_current_python_and_threshold(self) -> None:
        self.assertEqual(
            [
                vulture_check.sys.executable,
                "-m",
                "vulture",
                "--min-confidence",
                "100",
                "tools/vulture_check.py",
            ],
            vulture_check.build_vulture_command(
                ["tools/vulture_check.py"],
                min_confidence=100,
            ),
        )


if __name__ == "__main__":
    main()
