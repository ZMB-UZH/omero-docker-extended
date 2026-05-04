"""Contract tests for Mypy static type-checking CI wiring."""

from __future__ import annotations

from iter_test_helpers import next_or_fail

import configparser
from pathlib import Path, PurePosixPath
from unittest import TestCase, main, mock

import yaml

from tools import mypy_check


class MypyIntegrationContractTests(TestCase):
    """Test cases for mypy integration contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set Up Class.

        Inputs: none. Output: None.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        """Return read text.

        Inputs: `relative_path`. Output: `str`.
        """
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_python_style_doc_covers_mypy_workflow_and_local_runner(self) -> None:
        """Verify python style doc covers mypy workflow and local runner.

        Inputs: none. Output: None.
        """
        doc_text = self.read_text("docs/reference/python-style-and-linting.md")
        self.assertIn(".github/workflows/mypy.yml", doc_text)
        self.assertIn("python3 tools/mypy_check.py", doc_text)
        self.assertIn("static type-check gate", doc_text.lower())
        self.assertIn("tracked production Python files", doc_text)

    def test_mypy_config_enables_meaningful_repo_checks(self) -> None:
        """Verify mypy config enables meaningful repo checks.

        Inputs: none. Output: None.
        """
        config = configparser.ConfigParser()
        config.read_string(self.read_text("mypy.ini"))
        mypy_config = config["mypy"]

        self.assertEqual("typings", mypy_config["mypy_path"])
        self.assertNotIn("python_version", mypy_config)
        self.assertNotIn("ignore_missing_imports", mypy_config)
        self.assertEqual("True", mypy_config["warn_unused_configs"])
        self.assertEqual("True", mypy_config["check_untyped_defs"])
        self.assertEqual("True", mypy_config["no_implicit_optional"])
        self.assertEqual("True", mypy_config["strict_equality"])
        self.assertEqual("True", mypy_config["warn_redundant_casts"])
        self.assertEqual("True", mypy_config["warn_unused_ignores"])
        self.assertEqual("True", mypy_config["warn_unreachable"])

    def test_mypy_requirements_are_hash_pinned(self) -> None:
        """Verify mypy requirements are hash pinned.

        Inputs: none. Output: None.
        """
        source = self.read_text(".github/requirements/mypy-ci.in")
        compiled = self.read_text(".github/requirements/mypy-ci.txt")

        self.assertIn("mypy==1.20.2", source)
        self.assertIn("pip-compile", compiled)
        self.assertIn("mypy==1.20.2", compiled)
        self.assertIn("django-stubs==6.0.3", compiled)
        self.assertIn("types-requests==2.33.0.20260408", compiled)
        self.assertIn("types-atheris==3.0.0.20260408", compiled)
        self.assertIn("types-psycopg2==2.9.21.20260408", compiled)
        self.assertIn("--generate-hashes", compiled)
        self.assertIn("--hash=sha256:", compiled)

    def test_runtime_only_type_stubs_are_scoped_to_typings_directory(self) -> None:
        """Verify runtime only type stubs are scoped to typings directory.

        Inputs: none. Output: None.
        """
        required_stub_paths = (
            "typings/omero/__init__.pyi",
            "typings/omero/gateway.pyi",
            "typings/omeroweb/decorators.pyi",
            "typings/celery/__init__.pyi",
            "typings/ome_zarr/reader.pyi",
        )

        for relative_path in required_stub_paths:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((self.repo_root / relative_path).is_file())

    def test_mypy_workflow_is_pinned_and_uses_repo_runner(self) -> None:
        """Verify mypy workflow is pinned and uses repo runner.

        Inputs: none. Output: None.
        """
        workflow = yaml.safe_load(self.read_text(".github/workflows/mypy.yml"))
        triggers = workflow[True]
        self.assertNotIn("pull_request", triggers)
        self.assertIn("push", triggers)
        self.assertIsNone(triggers["push"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(
            "github.ref_name == github.event.repository.default_branch",
            workflow["jobs"]["mypy"]["if"],
        )
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("ubuntu-24.04", workflow["jobs"]["mypy"]["runs-on"])

        steps = workflow["jobs"]["mypy"]["steps"]
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
        setup_step = next_or_fail(
            step for step in steps if step.get("name") == "Setup Python"
        )
        self.assertEqual("3.14.4", setup_step["with"]["python-version"])
        self.assertEqual("pip", setup_step["with"]["cache"])
        cache_dependency_paths = setup_step["with"][
            "cache-dependency-path"
        ].splitlines()
        self.assertEqual(
            [".github/requirements/tests-ci.txt", ".github/requirements/mypy-ci.txt"],
            cache_dependency_paths,
        )
        self.assertTrue(
            any(
                "python3 -m pip install --require-hashes --requirement .github/requirements/tests-ci.txt"
                in value
                for value in run_values
            )
        )
        self.assertTrue(
            any(
                "python3 -m pip install --require-hashes --requirement .github/requirements/mypy-ci.txt"
                in value
                for value in run_values
            )
        )
        self.assertTrue(
            any("python3 tools/mypy_check.py" in value for value in run_values)
        )

    def test_scope_keeps_only_tracked_production_python_files(self) -> None:
        """Verify scope keeps only tracked production python files.

        Inputs: none. Output: None.
        """
        include = (
            "tools/mypy_check.py",
            "startup/50-config.py",
            "fuzzing/fuzz_filename_parser.py",
            "omeroweb_import/views/core_functions.py",
        )
        exclude = (
            "tests/test_mypy_integration_contract.py",
            "omeroweb_import/tests/test_core_function_helpers.py",
            "docs/conf.py",
            "third_party/caveman-v1.6.0/tools/helper.py",
            ".agents/skills/caveman/agents/openai.yaml",
            ".github/scripts/helper.py",
            "omeroweb_import/conftest.py",
            "omeroweb_import/test_sem_edx.py",
            "omeroweb_import/sem_edx_test.py",
        )

        for relative_path in include:
            with self.subTest(relative_path=relative_path):
                self.assertTrue(mypy_check.is_mypy_target(PurePosixPath(relative_path)))

        for relative_path in exclude:
            with self.subTest(relative_path=relative_path):
                self.assertFalse(
                    mypy_check.is_mypy_target(PurePosixPath(relative_path))
                )

    def test_list_mypy_targets_uses_git_ls_files_and_safe_directory(self) -> None:
        """Verify list mypy targets uses git ls files and safe directory.

        Inputs: none. Output: None.
        """
        repo_root = self.repo_root
        tracked_files = "\n".join(
            [
                "tests/test_mypy_integration_contract.py",
                "tools/mypy_check.py",
                "omeroweb_import/views/core_functions.py",
                "omeroweb_import/tests/test_core_function_helpers.py",
                ".agents/skills/caveman/agents/openai.yaml",
            ]
        )
        with (
            mock.patch(
                "tools.mypy_check.resolve_required_executable",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "tools.mypy_check.subprocess.run",
                return_value=mock.Mock(stdout=tracked_files, returncode=0),
            ) as mocked_run,
        ):
            self.assertEqual(
                [
                    "tools/mypy_check.py",
                    "omeroweb_import/views/core_functions.py",
                ],
                mypy_check.list_mypy_targets(repo_root),
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

    def test_build_mypy_command_uses_current_python_and_config(self) -> None:
        """Verify build mypy command uses current python and config.

        Inputs: none. Output: None.
        """
        self.assertEqual(
            [
                mypy_check.sys.executable,
                "-m",
                "mypy",
                "--config-file",
                "mypy.ini",
                "tools/mypy_check.py",
            ],
            mypy_check.build_mypy_command(
                ["tools/mypy_check.py"],
                config_file="mypy.ini",
            ),
        )


if __name__ == "__main__":
    main()
