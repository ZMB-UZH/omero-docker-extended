from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "run_local_workflow_gates.py"


def _load_tool():
    """Load the tool.

    Inputs: none. Output: `module`. Raises: RuntimeError for the exercised failure path.
    """
    spec = importlib.util.spec_from_file_location("run_local_workflow_gates", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load local workflow gate tool.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LocalWorkflowGateTests(unittest.TestCase):
    """Test cases for local workflow gate tests."""

    def setUp(self) -> None:
        """Set the up for `LocalWorkflowGateTests`.

        Inputs: unittest supplies the instance. Output: prepares isolated fixtures for one check.
        """
        self.tool = _load_tool()

    def test_bandit_discovery_matches_workflow_package_convention(self) -> None:
        """Verify the bandit discovery matches workflow package convention execution contract.

        Inputs: repository fixtures. Output: fails on regressions in bandit discovery matches workflow package convention integration.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            for package in (
                "omero_alpha",
                "omero_web_zarr",
                "omeroweb_beta",
                "omeroweb_without_init",
            ):
                (repo_root / package).mkdir()
            for package in ("omero_alpha", "omero_web_zarr", "omeroweb_beta"):
                (repo_root / package / "__init__.py").write_text("", encoding="utf-8")
            (repo_root / "omero_alpha" / "tests").mkdir()
            (repo_root / "omeroweb_beta" / "test").mkdir()
            (repo_root / "tests").mkdir()

            targets = self.tool.discover_bandit_targets(repo_root)

        self.assertEqual(
            ("omero_alpha", "omero_web_zarr", "omeroweb_beta"),
            targets.scan_dirs,
        )
        self.assertEqual(
            ("omero_alpha/tests", "omeroweb_beta/test"),
            targets.package_test_dirs,
        )
        self.assertEqual(
            ("omero_alpha/tests", "omeroweb_beta/test", "tests"),
            targets.test_dirs,
        )
        self.assertEqual("omero_alpha/tests,omeroweb_beta/test", targets.exclude_csv)

    def test_bandit_gate_uses_same_skip_policy_as_security_workflow(self) -> None:
        """Verify the bandit gate uses same skip policy as security workflow execution contract.

        Inputs: repository fixtures. Output: fails on regressions when bandit gate uses same skip policy as security workflow accepts unsafe input.
        """
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "security-code-scanning.yml"
        ).read_text(encoding="utf-8")
        tool_text = TOOL_PATH.read_text(encoding="utf-8")

        self.assertIn('--skip "B603,B404"', workflow_text)
        self.assertIn('--skip "B101,B106,B603,B404"', workflow_text)
        self.assertIn('"B603,B404"', tool_text)
        self.assertIn('"B101,B106,B603,B404"', tool_text)

    def test_bandit_gate_fails_when_scanner_reports_results(self) -> None:
        """Confirm bandit gate fails when scanner reports results exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in bandit gate fails when scanner reports results.
        """
        context = self.tool.GateContext(
            repo_root=REPO_ROOT,
            artifact_dir=REPO_ROOT / ".cache" / "test-local-workflow-gate",
            tool_venv=REPO_ROOT / ".cache" / "test-local-workflow-gate" / "venv",
            python="/usr/bin/python3",
            keep_going=False,
        )

        with (
            unittest.mock.patch.object(
                self.tool, "_require_executable", return_value="/bin/true"
            ),
            unittest.mock.patch.object(self.tool, "_run"),
            unittest.mock.patch.object(
                self.tool,
                "_sarif_result_count",
                side_effect=[0, 1],
            ),
            self.assertRaisesRegex(
                self.tool.GateError,
                r"Bandit test scan produced 1 result",
            ),
        ):
            self.tool.run_bandit(context)

    def test_ci_profile_matches_locally_reproducible_workflow_set(self) -> None:
        """Verify the ci profile matches locally reproducible workflow set execution contract.

        Inputs: repository fixtures. Output: fails on regressions in ci profile matches locally reproducible workflow set integration.
        """
        self.assertEqual(
            (
                self.tool.run_docs,
                self.tool.run_regression_guard,
                self.tool.run_ruff,
                self.tool.run_mypy,
                self.tool.run_vulture,
                self.tool.run_tests,
                self.tool.run_bandit,
            ),
            self.tool.PROFILES["ci"],
        )
        self.assertEqual(
            self.tool.PROFILES["ci"] + (self.tool.run_super_linter,),
            self.tool.PROFILES["all"],
        )

    def test_test_gate_uses_clean_explicit_coverage_files(self) -> None:
        """Verify the local pytest gate writes explicit fresh coverage files.

        Inputs: repository fixtures. Output: fails on regressions in coverage file
        isolation for local workflow gates.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            for stale_file in (
                ".coverage.root",
                ".coverage.common",
                ".coverage",
                "coverage.xml",
                ".coverage.unrelated",
            ):
                (repo_root / stale_file).write_text("stale", encoding="utf-8")

            context = self.tool.GateContext(
                repo_root=repo_root,
                artifact_dir=repo_root / ".cache" / "local-workflow-gate",
                tool_venv=repo_root / ".cache" / "local-workflow-gate" / "venv",
                python="/usr/bin/python3",
                keep_going=False,
            )
            calls: list[tuple[str, tuple[str, ...]]] = []

            def record_run(
                command: tuple[str, ...],
                *,
                cwd: Path,
                env: dict[str, str] | None = None,
                label: str,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                """Record the run for `LocalWorkflowGateTests`.

                Inputs: `command` (tuple[str, ...]), `cwd` (Path) working directory,
                `env` (dict[str, str] | None) environment mapping, `label` (str),
                `check` (bool). Output: `subprocess.CompletedProcess[str]`.
                """
                _ = (cwd, env, check)
                calls.append((label, tuple(command)))
                return subprocess.CompletedProcess(command, 0)

            with unittest.mock.patch.object(self.tool, "_run", side_effect=record_run):
                self.tool.run_tests(context)

            self.assertFalse((repo_root / ".coverage.root").exists())
            self.assertFalse((repo_root / ".coverage.common").exists())
            self.assertFalse((repo_root / ".coverage").exists())
            self.assertFalse((repo_root / "coverage.xml").exists())
            self.assertTrue((repo_root / ".coverage.unrelated").exists())

        combine_command = next(
            (command for label, command in calls if label == "coverage combine"),
            (),
        )
        self.assertTrue(combine_command, "coverage combine command was not recorded")
        self.assertIn(".coverage.root", combine_command)
        self.assertIn(".coverage.zarr", combine_command)
        self.assertNotIn(".coverage.unrelated", combine_command)

    def test_super_linter_image_matches_workflow_pin(self) -> None:
        """Verify the super linter image matches workflow pin execution contract.

        Inputs: repository fixtures. Output: fails on regressions in super linter image matches workflow pin integration.
        """
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "super-linter.yml"
        ).read_text(encoding="utf-8")

        image_matches = re.findall(
            r"ghcr\.io/super-linter/super-linter:v8\.7\.0@sha256:[0-9a-f]{64}",
            workflow_text,
        )
        self.assertEqual(1, len(set(image_matches)))
        self.assertEqual(
            image_matches[0], self.tool._read_super_linter_image(REPO_ROOT)
        )

    def test_super_linter_gate_mirrors_workflow_lint_scope(self) -> None:
        """Verify the local Super-Linter gate mirrors the workflow lint scope.

        Inputs: mocked Docker execution and repository fixtures. Output: verifies
        Bash validation and current vendor exclusions reach the container.
        """
        context = self.tool.GateContext(
            repo_root=REPO_ROOT,
            artifact_dir=REPO_ROOT / ".cache" / "test-local-workflow-gate",
            tool_venv=REPO_ROOT / ".cache" / "test-local-workflow-gate" / "venv",
            python="/usr/bin/python3",
            keep_going=False,
        )

        with (
            unittest.mock.patch.object(
                self.tool, "_require_executable", return_value="/usr/bin/docker"
            ),
            unittest.mock.patch.object(
                self.tool, "_default_branch", return_value="main"
            ),
            unittest.mock.patch.object(
                self.tool,
                "_read_super_linter_image",
                return_value="ghcr.io/super-linter/super-linter:test",
            ),
            unittest.mock.patch.object(self.tool, "_run") as run,
        ):
            self.tool.run_super_linter(context)

        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertIn("VALIDATE_BASH", command)
        self.assertEqual("true", environment["VALIDATE_BASH"])
        self.assertEqual(
            r"(^|/)third_party/(ecc-v2\.0\.0|caveman-v1\.9\.1)/",
            environment["FILTER_REGEX_EXCLUDE"],
        )

    def test_setup_reads_ruff_version_from_repo_config(self) -> None:
        """Verify setup reads ruff version from repo config.

        Inputs: repository fixtures. Output: fails on regressions in setup reads ruff version from repo config.
        """
        self.assertEqual("0.15.22", self.tool._read_required_ruff_version(REPO_ROOT))

    def test_default_branch_prefers_remote_head_metadata_over_stale_symbolic_ref(
        self,
    ) -> None:
        """Verify default branch prefers remote head metadata over stale symbolic ref.

        Inputs: repository fixtures. Output: fails on regressions in default branch prefers remote head metadata over stale symbolic ref.
        """
        commands: list[tuple[str, ...]] = []

        def fake_run(
            command: tuple[str, ...],
            *,
            cwd: Path,
            check: bool,
            text: bool,
            capture_output: bool,
        ) -> subprocess.CompletedProcess[str]:
            """Simulate run so the surrounding test controls that dependency.

            Inputs: `command` (tuple[str, ...]), `cwd` (Path) working directory, `check`
            (bool), `text` (bool), `capture_output` (bool). Output:
            `subprocess.CompletedProcess[str]`.
            """
            _ = (cwd, check, text, capture_output)
            args = tuple(command[1:])
            commands.append(args)
            if args == (
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ):
                return subprocess.CompletedProcess(command, 0, stdout="upstream/main\n")
            if args == ("remote",):
                return subprocess.CompletedProcess(command, 0, stdout="upstream\n")
            if args == ("remote", "show", "upstream"):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="* remote upstream\n  HEAD branch: main\n",
                )
            if args[:3] == ("symbolic-ref", "--quiet", "--short"):
                return subprocess.CompletedProcess(command, 0, stdout="upstream/test\n")
            return subprocess.CompletedProcess(command, 1, stdout="")

        with (
            unittest.mock.patch.dict(self.tool.os.environ, {}, clear=True),
            unittest.mock.patch.object(
                self.tool, "_require_executable", return_value="/bin/git"
            ),
            unittest.mock.patch.object(
                self.tool.subprocess, "run", side_effect=fake_run
            ),
        ):
            branch = self.tool._default_branch(REPO_ROOT)

        self.assertEqual("main", branch)
        self.assertNotIn(
            ("symbolic-ref", "--quiet", "--short", "refs/remotes/upstream/HEAD"),
            commands,
        )

    def test_agent_and_runbook_document_local_gate_without_claiming_full_parity(
        self,
    ) -> None:
        """Verify agent and runbook document local gate without claiming full parity.

        Inputs: repository fixtures. Output: fails on regressions in agent and runbook document local gate without claiming full parity.
        """
        agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        runbook_text = (
            REPO_ROOT / "docs" / "operations" / "code-scanning.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "python3 tools/run_local_workflow_gates.py --setup --profile ci",
            agents_text,
        )
        self.assertIn("locally reproducible", runbook_text)
        self.assertIn("GitHub-only", runbook_text)


if __name__ == "__main__":
    unittest.main()
