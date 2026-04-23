"""Contract tests for Ruff configuration and CI wiring."""

from __future__ import annotations

from iter_test_helpers import next_or_fail

import tomllib
import unittest
from pathlib import Path

import yaml


class RuffIntegrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_readme_has_ruff_badge_in_top_row(self) -> None:
        readme_text = self.read_text("README.md")
        self.assertIn(
            "[![License](",
            readme_text,
        )
        self.assertLess(
            readme_text.index("[![License]("),
            readme_text.index("[![tests]("),
        )
        self.assertIn(
            "[![Codecov](",
            readme_text,
        )
        self.assertIn(
            "[![Ruff](",
            readme_text,
        )
        self.assertIn(
            "[![Vulture](",
            readme_text,
        )
        self.assertLess(
            readme_text.index("[![Ruff]("),
            readme_text.index("[![Vulture]("),
        )

    def test_docs_index_links_to_python_style_reference(self) -> None:
        index_text = self.read_text("docs/index.md")
        doc_text = self.read_text("docs/reference/python-style-and-linting.md")
        self.assertIn(
            "reference/python-style-and-linting.md",
            index_text,
        )
        self.assertIn(".github/workflows/ruff.yml", doc_text)
        self.assertIn("0.15.11", doc_text)
        self.assertIn("pre-commit install", doc_text)
        self.assertIn("ruff format .", doc_text)

    def test_agents_document_ruff_commands(self) -> None:
        agents_text = self.read_text("AGENTS.md")
        self.assertIn(
            "Use Ruff as the canonical Python formatter and lint gate.", agents_text
        )
        self.assertIn("ruff check .", agents_text)
        self.assertIn("ruff format --check .", agents_text)
        self.assertIn(
            "If the active host exposes Ruff only as a Python module",
            agents_text,
        )
        self.assertIn("python3 -m ruff check .", agents_text)
        self.assertIn("python3 -m ruff format --check .", agents_text)

    def test_ruff_config_is_pinned_and_repo_specific(self) -> None:
        config = tomllib.loads(self.read_text(".ruff.toml"))
        self.assertEqual("==0.15.11", config["required-version"])
        self.assertEqual("py39", config["target-version"])
        self.assertEqual(["F", "E7", "E9"], config["lint"]["select"])
        self.assertEqual({}, config["lint"].get("per-file-ignores", {}))

    def test_pre_commit_uses_pinned_ruff_hooks(self) -> None:
        config = yaml.safe_load(self.read_text(".pre-commit-config.yaml"))
        self.assertEqual(1, len(config["repos"]))
        repo = config["repos"][0]
        self.assertEqual("https://github.com/astral-sh/ruff-pre-commit", repo["repo"])
        self.assertEqual("v0.15.11", repo["rev"])
        hooks = {hook["id"]: hook for hook in repo["hooks"]}
        self.assertEqual(["--fix"], hooks["ruff-check"]["args"])
        self.assertEqual(["python", "pyi"], hooks["ruff-check"]["types_or"])
        self.assertEqual(["python", "pyi"], hooks["ruff-format"]["types_or"])

    def test_ruff_workflow_is_pinned_and_runs_on_main_only(self) -> None:
        workflow = yaml.safe_load(self.read_text(".github/workflows/ruff.yml"))
        # yaml.safe_load parses the YAML key `on:` as boolean True
        triggers = workflow[True]
        self.assertEqual(["main"], triggers["pull_request"]["branches"])
        self.assertEqual(["main"], triggers["push"]["branches"])
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("ubuntu-24.04", workflow["jobs"]["ruff"]["runs-on"])

        steps = workflow["jobs"]["ruff"]["steps"]
        uses_values = [step.get("uses") for step in steps if "uses" in step]
        run_values = [step.get("run") for step in steps if "run" in step]

        self.assertIn(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            uses_values,
        )
        self.assertIn(
            "astral-sh/ruff-action@0ce1b0bf8b818ef400413f810f8a11cdbda0034b",
            uses_values,
        )
        self.assertIn("ruff check .", run_values)
        self.assertIn("ruff format --check .", run_values)

        install_step = next_or_fail(
            step for step in steps if step.get("name") == "Install Ruff"
        )
        self.assertEqual("0.15.11", install_step["with"]["version"])
        self.assertEqual("--version", install_step["with"]["args"])


if __name__ == "__main__":
    unittest.main()
