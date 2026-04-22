from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "run_local_workflow_gates.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("run_local_workflow_gates", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load local workflow gate tool.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LocalWorkflowGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = _load_tool()

    def test_bandit_discovery_matches_workflow_package_convention(self) -> None:
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
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "security-code-scanning.yml"
        ).read_text(encoding="utf-8")
        tool_text = TOOL_PATH.read_text(encoding="utf-8")

        self.assertIn('--skip "B603,B404"', workflow_text)
        self.assertIn('--skip "B101,B106,B603,B404"', workflow_text)
        self.assertIn('"B603,B404"', tool_text)
        self.assertIn('"B101,B106,B603,B404"', tool_text)

    def test_bandit_gate_fails_when_scanner_reports_results(self) -> None:
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
        ):
            with self.assertRaisesRegex(
                self.tool.GateError,
                r"Bandit test scan produced 1 result",
            ):
                self.tool.run_bandit(context)

    def test_ci_profile_matches_locally_reproducible_workflow_set(self) -> None:
        self.assertEqual(
            (
                self.tool.run_docs,
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
                del cwd, env, check
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
            command for label, command in calls if label == "coverage combine"
        )
        self.assertIn(".coverage.root", combine_command)
        self.assertIn(".coverage.zarr", combine_command)
        self.assertNotIn(".coverage.unrelated", combine_command)

    def test_super_linter_image_matches_workflow_pin(self) -> None:
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / "super-linter.yml"
        ).read_text(encoding="utf-8")

        image_matches = re.findall(
            r"ghcr\.io/super-linter/super-linter:v8\.6\.0@sha256:[0-9a-f]{64}",
            workflow_text,
        )
        self.assertEqual(1, len(set(image_matches)))
        self.assertEqual(
            image_matches[0], self.tool._read_super_linter_image(REPO_ROOT)
        )

    def test_setup_reads_ruff_version_from_repo_config(self) -> None:
        self.assertEqual("0.15.10", self.tool._read_required_ruff_version(REPO_ROOT))

    def test_default_branch_prefers_remote_head_metadata_over_stale_symbolic_ref(
        self,
    ) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run(
            command: tuple[str, ...],
            *,
            cwd: Path,
            check: bool,
            text: bool,
            capture_output: bool,
        ) -> subprocess.CompletedProcess[str]:
            del cwd, check, text, capture_output
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
