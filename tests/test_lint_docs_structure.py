"""Tests for docs structure validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.agent_context_policy import CONTEXT_SURFACE_CONTRACTS
from tools.lint_docs_structure import run_validations


class DocsStructureLintTests(unittest.TestCase):
    """Coverage for docs lint helper."""

    def test_validation_passes_for_project_repository(self) -> None:
        """Verify validation passes for project repository.

        Inputs: repository fixtures. Output: fails on regressions in validation passes for project repository.
        """
        repo_root: Path = Path(__file__).resolve().parents[1]
        errors = run_validations(repo_root)
        self.assertEqual(errors, [])

    def test_validation_fails_when_index_is_missing(self) -> None:
        """Confirm validation fails when index is missing exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in validation fails when index is missing.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
            errors = run_validations(repo_root)
            self.assertTrue(any("docs/index.md" in err.message for err in errors))

    def test_validation_flags_bloated_or_unrouted_agent_surfaces(self) -> None:
        """Verify validation flags bloated or unrouted agent surfaces.

        Inputs: repository fixtures. Output: fails on regressions in validation flags bloated or unrouted agent surfaces.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)

            for rel_path in (
                "AGENTS.md",
                "ARCHITECTURE.md",
                "CLAUDE.md",
                "GEMINI.md",
                "docs/index.md",
                "docs/DESIGN.md",
                "docs/FRONTEND.md",
                "docs/PLANS.md",
                "docs/PRODUCT_SENSE.md",
                "docs/QUALITY_SCORE.md",
                "docs/RELIABILITY.md",
                "docs/SECURITY.md",
                "docs/reference/ai-agent-context-routing.md",
                "docs/reference/ai-agent-runtime-playbook.md",
                "docs/reference/ai-agent-skills.md",
                ".agents/skills/context-budget/SKILL.md",
                "docs/design-docs/index.md",
                "docs/design-docs/core-beliefs.md",
                "docs/exec-plans/tech-debt-tracker.md",
                "docs/exec-plans/completed/knowledge-base-bootstrap.md",
                "docs/exec-plans/completed/README.md",
                "docs/generated/db-schema.md",
                "docs/product-specs/index.md",
                "docs/product-specs/new-user-onboarding.md",
                "docs/references/design-system-reference-llms.txt",
                "docs/references/docker-compose-llms.txt",
                ".github/copilot-instructions.md",
                ".cursor/rules/00-omero-core.mdc",
            ):
                path = repo_root / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8")

            index_tokens = "\n".join(
                [
                    "`DESIGN.md`",
                    "`FRONTEND.md`",
                    "`PLANS.md`",
                    "`PRODUCT_SENSE.md`",
                    "`QUALITY_SCORE.md`",
                    "`RELIABILITY.md`",
                    "`SECURITY.md`",
                    "`reference/ai-agent-context-routing.md`",
                    "`reference/ai-agent-skills.md`",
                    "`design-docs/index.md`",
                    "`exec-plans/tech-debt-tracker.md`",
                    "`product-specs/index.md`",
                ]
            )
            (repo_root / "docs" / "index.md").write_text(index_tokens, encoding="utf-8")

            bloated_agents = "\n".join(
                ["docs/reference/ai-agent-skills.md"]
                * (CONTEXT_SURFACE_CONTRACTS["AGENTS.md"].max_nonempty_lines + 5)
            )
            (repo_root / "AGENTS.md").write_text(bloated_agents, encoding="utf-8")

            errors = run_validations(repo_root)

            self.assertTrue(
                any(
                    "AGENTS.md exceeds compactness budget" in err.message
                    for err in errors
                )
            )
            self.assertTrue(
                any(
                    "CLAUDE.md missing required routing token" in err.message
                    for err in errors
                )
            )
            self.assertTrue(
                any(
                    "docs/reference/ai-agent-context-routing.md missing required routing token"
                    in err.message
                    for err in errors
                )
            )


if __name__ == "__main__":
    unittest.main()
