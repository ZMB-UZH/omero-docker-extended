"""Regression checks for Node 24-ready GitHub Actions runtime usage."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class GitHubActionsRuntimeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow_dir = repo_root / ".github" / "workflows"
        cls.tests_workflow = yaml.safe_load((workflow_dir / "tests.yml").read_text(encoding="utf-8"))
        cls.docs_workflow = yaml.safe_load(
            (workflow_dir / "docs-knowledge-base.yml").read_text(encoding="utf-8")
        )
        cls.security_workflow = yaml.safe_load(
            (workflow_dir / "security-code-scanning.yml").read_text(encoding="utf-8")
        )

    def _step(self, workflow: dict, job_name: str, step_name: str) -> dict:
        for step in workflow["jobs"][job_name]["steps"]:
            if step.get("name") == step_name:
                return step
        self.fail(f"Workflow step not found: {job_name}/{step_name}")

    def _all_uses(self, workflow: dict) -> list[str]:
        uses = []
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    uses.append(step["uses"])
        return uses

    def test_tests_workflow_uses_node24_ready_action_majors(self) -> None:
        self.assertEqual(
            "actions/checkout@v6",
            self._step(self.tests_workflow, "test-with-coverage", "Checkout")["uses"],
        )
        self.assertEqual(
            "actions/setup-python@v6",
            self._step(self.tests_workflow, "test-with-coverage", "Setup Python")["uses"],
        )
        self.assertEqual(
            "actions/upload-artifact@v7",
            self._step(self.tests_workflow, "test-with-coverage", "Upload coverage artifacts")["uses"],
        )

    def test_docs_and_security_workflows_use_node24_ready_checkout_and_python_setup(self) -> None:
        self.assertEqual(
            "actions/checkout@v6",
            self._step(self.docs_workflow, "docs-validation", "Checkout")["uses"],
        )
        self.assertEqual(
            "actions/setup-python@v6",
            self._step(self.docs_workflow, "docs-validation", "Setup Python")["uses"],
        )

        security_uses = self._all_uses(self.security_workflow)
        checkout_steps = [uses for uses in security_uses if uses.startswith("actions/checkout@")]
        setup_steps = [uses for uses in security_uses if uses.startswith("actions/setup-python@")]
        self.assertTrue(checkout_steps)
        self.assertTrue(setup_steps)
        self.assertEqual({"actions/checkout@v6"}, set(checkout_steps))
        self.assertEqual({"actions/setup-python@v6"}, set(setup_steps))

    def test_no_workflow_keeps_node20_only_action_majors(self) -> None:
        all_uses = (
            self._all_uses(self.tests_workflow)
            + self._all_uses(self.docs_workflow)
            + self._all_uses(self.security_workflow)
        )

        self.assertNotIn("actions/checkout@v4", all_uses)
        self.assertNotIn("actions/setup-python@v5", all_uses)
        self.assertNotIn("actions/upload-artifact@v4", all_uses)


if __name__ == "__main__":
    unittest.main()
