from __future__ import annotations

import importlib.util
import io
import json
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

    def test_main_keep_going_runs_all_gates_and_preserves_failures(self) -> None:
        """Collect independent failures without hiding them behind later success.

        Inputs: failing and passing gates. Output: all run, both errors retained.
        """
        first = unittest.mock.Mock(side_effect=self.tool.GateError("first failed"))
        middle = unittest.mock.Mock()
        last = unittest.mock.Mock(side_effect=self.tool.GateError("last failed"))
        with (
            unittest.mock.patch.dict(self.tool.PROFILES, {"ci": (first, middle, last)}),
            unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as errors,
        ):
            result = self.tool.main(["--profile", "ci", "--keep-going"])
        self.assertEqual(result, 1)
        for runner in (first, middle, last):
            runner.assert_called_once()
        self.assertIn("first failed", errors.getvalue())
        self.assertIn("last failed", errors.getvalue())
        self.assertNotIn("Local workflow gates passed", output.getvalue())

    def test_main_remains_fail_fast_without_keep_going(self) -> None:
        """Preserve the default early-stop policy.

        Inputs: a failed first gate. Output: nonzero status without later calls.
        """
        first = unittest.mock.Mock(side_effect=self.tool.GateError("first failed"))
        last = unittest.mock.Mock()
        with (
            unittest.mock.patch.dict(self.tool.PROFILES, {"ci": (first, last)}),
            unittest.mock.patch("sys.stdout", new_callable=io.StringIO),
            unittest.mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(self.tool.main(["--profile", "ci"]), 1)
        first.assert_called_once()
        last.assert_not_called()

    def test_main_does_not_run_gates_after_failed_setup(self) -> None:
        """A broken tool environment is not an independent gate failure.

        Inputs: failed setup with keep-going. Output: no verification runs.
        """
        runner = unittest.mock.Mock()
        with (
            unittest.mock.patch.dict(self.tool.PROFILES, {"ci": (runner,)}),
            unittest.mock.patch.object(
                self.tool,
                "_install_python_workflow_dependencies",
                side_effect=self.tool.GateError("setup failed"),
            ),
            unittest.mock.patch("sys.stdout", new_callable=io.StringIO),
            unittest.mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(
                self.tool.main(["--profile", "ci", "--setup", "--keep-going"]), 1
            )
        runner.assert_not_called()

    def test_main_success_with_keep_going_is_reported_once(self) -> None:
        """An all-pass profile succeeds after every selected gate runs.

        Inputs: two successful gates. Output: zero status and one success summary.
        """
        first, last = unittest.mock.Mock(), unittest.mock.Mock()
        with (
            unittest.mock.patch.dict(self.tool.PROFILES, {"ci": (first, last)}),
            unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as errors,
        ):
            self.assertEqual(self.tool.main(["--profile", "ci", "--keep-going"]), 0)
        first.assert_called_once()
        last.assert_called_once()
        self.assertEqual(output.getvalue().count("Local workflow gates passed."), 1)
        self.assertEqual(errors.getvalue(), "")

    def test_scan_discovery_covers_all_first_party_locations(self) -> None:
        """Keep tools, hooks and future packages in scope.

        Inputs: a Git fixture with tracked, new and ignored files. Output: exact inventories.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            subprocess.run(
                [self.tool._require_executable("git"), "init", "-q", str(root)],
                check=True,
            )
            production = (
                "omero_alpha/__init__.py",
                "omeroweb_without_init/task.py",
                "tools/build.py",
                "startup/bootstrap.py",
                "monitoring/exporter.py",
                "docker/check.py",
                "scripts/agent.py",
                "env/validate.py",
                ".agents/hooks/check.py",
                ".github/helpers/ci.py",
                "root script.py",
            )
            tests = ("conftest.py", "omero_alpha/tests/check.py", "tests/root.py")
            dockerfiles = (
                "Dockerfile",
                "docker/server.Dockerfile",
                ".agents/build/Dockerfile.ci",
            )
            for relative in (
                production
                + tests
                + dockerfiles
                + (
                    "third_party/vendor.py",
                    "third_party/Dockerfile",
                    ".cache/generated.py",
                )
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            (root / ".gitignore").write_text(".cache/\n", encoding="utf-8")
            subprocess.run(
                [self.tool._require_executable("git"), "add", "--", "omero_alpha"],
                cwd=root,
                check=True,
            )
            targets = self.tool.discover_bandit_targets(root)
            self.assertEqual(
                tuple(sorted("./" + p for p in production)), targets.production_files
            )
            self.assertEqual(tuple(sorted("./" + p for p in tests)), targets.test_files)
            self.assertEqual(
                tuple(sorted(dockerfiles)), self.tool.discover_dockerfiles(root)
            )
            self.assertFalse(set(targets.production_files) & set(targets.test_files))

    def test_scan_discovery_rejects_source_symlinks(self) -> None:
        """Reject aliased sources. Inputs: temporary symlink. Output: fail-closed discovery."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.py"
            source.write_text("", encoding="utf-8")
            link = root / "alias.py"
            link.symlink_to(source)
            with (
                unittest.mock.patch.object(
                    self.tool, "tracked_source_paths", return_value=("alias.py",)
                ),
                self.assertRaisesRegex(self.tool.GateError, "regular in-repository"),
            ):
                self.tool.discover_bandit_targets(root)
            link.unlink()
            self.assertFalse(self.tool._regular_source_file(root, "alias.py"))

    def test_bandit_gate_uses_same_skip_policy_as_security_workflow(self) -> None:
        """Verify the bandit gate uses same skip policy as security workflow execution contract.

        Inputs: repository fixtures. Output: fails on regressions when bandit gate uses same skip policy as security workflow accepts unsafe input.
        """
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "security-code-scanning.yml"
        ).read_text(encoding="utf-8")
        tool_text = TOOL_PATH.read_text(encoding="utf-8")

        self.assertIn("python3 tools/run_local_workflow_gates.py", workflow_text)
        self.assertIn("--profile bandit", workflow_text)
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
                "discover_bandit_targets",
                return_value=self.tool.BanditTargets(
                    ("./tools/source.py",), ("./tests/source.py",)
                ),
            ),
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

    def test_scanner_report_rejects_partial_analysis(self) -> None:
        """Reject false clean reports. Inputs: SARIF fixtures. Output: explicit failures."""
        invalid = [
            [],
            {},
            {"runs": []},
            {"runs": [None]},
            {"runs": [{"results": {}}]},
            {"runs": [{"results": [None]}]},
            {"runs": [{"invocations": {}}]},
            {"runs": [{"invocations": [None]}]},
            {"runs": [{"invocations": [{"executionSuccessful": False}]}]},
        ]
        for key in ("toolConfigurationNotifications", "toolExecutionNotifications"):
            for notices in (
                {},
                [None],
                [{"level": "error", "message": {"text": "syntax error"}}],
            ):
                invalid.append(
                    {"runs": [{"results": [], "invocations": [{key: notices}]}]}
                )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.sarif"
            for document in invalid:
                with self.subTest(document=document):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(self.tool.GateError):
                        self.tool._sarif_result_count(path)
            path.write_text(
                json.dumps(
                    {
                        "runs": [
                            {
                                "results": [{"ruleId": "example"}],
                                "invocations": [
                                    {
                                        "executionSuccessful": True,
                                        "toolExecutionNotifications": [
                                            {"level": "note"}
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(1, self.tool._sarif_result_count(path))

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
            self.tool.PROFILES["ci"]
            + (
                self.tool.run_hadolint,
                self.tool.run_devskim,
                self.tool.run_super_linter,
                self.tool.run_redis,
                self.tool.run_deployment,
            ),
            self.tool.PROFILES["all"],
        )

    def test_redis_container_gate_is_explicit_and_mandatory_in_hosted_tests(
        self,
    ) -> None:
        """Inputs: gate and hosted workflow. Output: lifecycle checks cannot be silently skipped."""
        context = self.tool.GateContext(
            REPO_ROOT, REPO_ROOT / ".cache", REPO_ROOT / ".venv", sys.executable, False
        )
        with unittest.mock.patch.object(self.tool, "_run") as run:
            self.tool.run_redis(context)
        command = run.call_args.args[0]
        self.assertIn("tests/container_redis_persistence.py", command)
        self.assertEqual(command[:3], (sys.executable, "-m", "pytest"))
        self.assertEqual(self.tool.PROFILES["redis"], (self.tool.run_redis,))
        self.assertIn(
            "--profile redis", (REPO_ROOT / ".github/workflows/tests.yml").read_text()
        )

    def test_deployment_gate_runs_the_hosted_contract_in_an_isolated_copy(self) -> None:
        """Inputs: local gate. Output: the actual hosted Compose/Buildx check is mandatory in all."""
        context = self.tool.GateContext(
            REPO_ROOT, REPO_ROOT / ".cache", REPO_ROOT / ".venv", sys.executable, False
        )
        with unittest.mock.patch.object(self.tool, "_run") as run:
            self.tool.run_deployment(context)
        command = run.call_args.args[0]
        self.assertIn("tests/container_deployment_contracts.py", command)
        self.assertEqual(command[:3], (sys.executable, "-m", "pytest"))
        self.assertEqual(self.tool.PROFILES["deployment"], (self.tool.run_deployment,))
        self.assertIn(self.tool.run_deployment, self.tool.PROFILES["all"])

    def test_hadolint_gate_uses_compatible_pinned_engine(self) -> None:
        """Verify the local Hadolint gate pins the workflow-compatible engine.

        Inputs: local gate and workflow sources. Output: asserts immutable compatible pins.
        """

        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "security-code-scanning.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "hadolint/hadolint-action@2332a7b74a6de0dda2e2221d575162eba76ba5e5",
            workflow_text,
        )
        self.assertIn("v2.14.0", self.tool.HADOLINT_IMAGE)
        self.assertRegex(self.tool.HADOLINT_IMAGE, r"@sha256:[0-9a-f]{64}$")

    def test_hadolint_gate_fails_when_scanner_reports_results(self) -> None:
        """Verify the local Hadolint gate rejects scanner findings.

        Inputs: mocked Docker execution and temporary repository. Output: asserts a failed gate result.
        """

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            (repo_root / "docker").mkdir()
            (repo_root / "docker" / "example.Dockerfile").write_text(
                "FROM example:1\n", encoding="utf-8"
            )
            (repo_root / "example.Dockerfile").write_text(
                "FROM another:2\n", encoding="utf-8"
            )
            context = self.tool.GateContext(
                repo_root=repo_root,
                artifact_dir=repo_root / ".cache",
                tool_venv=repo_root / ".venv",
                python="/usr/bin/python3",
                keep_going=False,
            )
            sarif = '{"runs":[{"results":[{"ruleId":"DL0001"}]}]}'

            with (
                unittest.mock.patch.object(
                    self.tool, "_require_executable", return_value="/usr/bin/docker"
                ),
                unittest.mock.patch.object(
                    self.tool,
                    "discover_dockerfiles",
                    return_value=("docker/example.Dockerfile", "example.Dockerfile"),
                ),
                unittest.mock.patch.object(
                    self.tool.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=(), returncode=0, stdout=sarif, stderr=""
                    ),
                ) as run,
                self.assertRaisesRegex(self.tool.GateError, "Hadolint findings"),
            ):
                self.tool.run_hadolint(context)

            command = run.call_args.args[0]
            self.assertEqual(
                "hadolint", command[command.index(self.tool.HADOLINT_IMAGE) + 1]
            )
            for relative in ("docker/example.Dockerfile", "example.Dockerfile"):
                self.assertEqual(
                    sarif,
                    (
                        context.artifact_dir / "hadolint" / f"{relative}.sarif"
                    ).read_text(),
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
            coverage_paths: list[Path] = []

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
                _ = (cwd, check)
                if env and "COVERAGE_FILE" in env and "pytest" in command:
                    coverage_paths.append(Path(env["COVERAGE_FILE"]))
                elif label.startswith("coverage "):
                    self.assertEqual(
                        Path(env["COVERAGE_FILE"]).parent, coverage_paths[0].parent
                    )
                calls.append((label, tuple(command)))
                return subprocess.CompletedProcess(command, 0)

            with unittest.mock.patch.object(self.tool, "_run", side_effect=record_run):
                self.tool.run_tests(context)

            self.assertTrue((repo_root / ".coverage.root").exists())
            self.assertTrue((repo_root / ".coverage.common").exists())
            self.assertEqual((repo_root / ".coverage").read_text(), "stale")
            self.assertFalse((repo_root / "coverage.xml").exists())
            self.assertTrue((repo_root / ".coverage.unrelated").exists())

        combine_command = next(
            (command for label, command in calls if label == "coverage combine"),
            (),
        )
        self.assertTrue(combine_command, "coverage combine command was not recorded")
        self.assertEqual(len(coverage_paths), 8)
        self.assertEqual(len({path.parent for path in coverage_paths}), 1)
        self.assertEqual(coverage_paths[0].name, ".coverage.root")
        self.assertEqual(coverage_paths[-1].name, ".coverage.zarr")
        self.assertTrue(coverage_paths[0].parent.is_relative_to(context.artifact_dir))
        self.assertEqual(combine_command[-1], str(coverage_paths[0].parent))
        self.assertIn("--keep", combine_command)
        self.assertNotIn(".coverage.unrelated", combine_command)

    def test_super_linter_image_matches_workflow_pin(self) -> None:
        """Verify the super linter image matches workflow pin execution contract.

        Inputs: repository fixtures. Output: fails on regressions in super linter image matches workflow pin integration.
        """
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "super-linter.yml"
        ).read_text(encoding="utf-8")

        image_matches = re.findall(
            r"ghcr\.io/super-linter/super-linter:v9\.0\.0@sha256:[0-9a-f]{64}",
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
            r"(^|/)third_party/(ecc-v2\.0\.0|caveman-v2\.2\.0)/",
            environment["FILTER_REGEX_EXCLUDE"],
        )

    def test_setup_reads_ruff_version_from_repo_config(self) -> None:
        """Verify setup reads ruff version from repo config.

        Inputs: repository fixtures. Output: fails on regressions in setup reads ruff version from repo config.
        """
        self.assertEqual("0.17.2", self.tool._read_required_ruff_version(REPO_ROOT))

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
