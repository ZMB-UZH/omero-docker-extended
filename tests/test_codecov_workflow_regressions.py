"""Regression checks for the coverage workflow and its pinned CI dependencies."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class CodecovWorkflowRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        workflow_path = cls.repo_root / ".github" / "workflows" / "tests.yml"
        cls.workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        cls.steps = cls.workflow["jobs"]["test-with-coverage"]["steps"]
        cls.requirements_path = cls.repo_root / "requirements-tests.txt"

    def _step(self, name: str) -> dict:
        for step in self.steps:
            if step.get("name") == name:
                return step
        self.fail(f"Workflow step not found: {name}")

    def test_tests_workflow_can_refresh_codecov_from_manual_dispatch_on_default_branch(self) -> None:
        upload_if = self._step("Upload coverage to Codecov")["if"]
        validate_if = self._step("Validate Codecov token")["if"]

        self.assertIn("workflow_dispatch", upload_if)
        self.assertIn("workflow_dispatch", validate_if)
        self.assertIn("github.event.repository.default_branch", upload_if)
        self.assertIn("github.event.repository.default_branch", validate_if)

    def test_tests_workflow_installs_pinned_requirements_file(self) -> None:
        install_run = self._step("Install dependencies")["run"]
        self.assertIn("python3 -m pip install -r requirements-tests.txt", install_run)
        self.assertTrue(self.requirements_path.exists(), "Pinned test requirements file is missing")

    def test_tests_requirements_are_version_pinned(self) -> None:
        pinned_lines = [
            line.strip()
            for line in self.requirements_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(pinned_lines, "requirements-tests.txt is empty")
        self.assertTrue(all("==" in line for line in pinned_lines), pinned_lines)
        self.assertIn("ome-zarr==0.14.0", pinned_lines)
        self.assertIn("zarr==3.1.6", pinned_lines)

    def test_tests_workflow_publishes_coverage_summary_and_artifacts(self) -> None:
        report_run = self._step("Combine coverage and generate report")["run"]
        artifact_step = self._step("Upload coverage artifacts")
        artifact_link_step = self._step("Publish coverage artifact link")

        self.assertIn("No split coverage data files were produced", report_run)
        self.assertIn("python3 -m coverage json", report_run)
        self.assertIn("python3 -m coverage html", report_run)
        self.assertIn("tee coverage-report.txt", report_run)
        self.assertIn("tools/coverage_summary.py", report_run)
        self.assertIn("coverage-summary.md", report_run)
        self.assertIn("GITHUB_STEP_SUMMARY", report_run)
        self.assertEqual("actions/upload-artifact@v4", artifact_step["uses"])
        self.assertEqual("upload_coverage_artifacts", artifact_step["id"])
        self.assertIn("coverage.json", artifact_step["with"]["path"])
        self.assertIn("coverage-report.txt", artifact_step["with"]["path"])
        self.assertIn("coverage-summary.md", artifact_step["with"]["path"])
        self.assertIn("coverage-html/", artifact_step["with"]["path"])
        self.assertEqual("error", artifact_step["with"]["if-no-files-found"])
        self.assertIn("artifact-url", artifact_link_step["run"])
        self.assertIn("GITHUB_STEP_SUMMARY", artifact_link_step["run"])


if __name__ == "__main__":
    unittest.main()
