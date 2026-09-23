"""Tests for docs structure validation."""

from __future__ import annotations

import tempfile
import unittest
import json
from dataclasses import replace
from pathlib import Path

from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from tests.agent_instruction_helpers import read_instruction_contract

from tools.agent_context_policy import CONTEXT_SURFACE_CONTRACTS
from tools.lint_docs_structure import run_validations, validate_relative_markdown_links
from tools import lint_docs_structure
from tools.agent_context_policy import AGENT_ADAPTER_LINKS, TASK_CONTRACT_PATH


class ContextBudgetTests(unittest.TestCase):
    """Keep instruction budgets enforceable in the dependency-free docs job."""

    def test_byte_budget_is_not_a_line_or_character_count(self) -> None:
        """Count UTF-8 bytes, including whitespace, with normalized newlines.

        Inputs: boundary, Unicode, whitespace, and CRLF fixtures. Output: exact
        counts and budget rejection assertions.
        """
        contract = replace(
            CONTEXT_SURFACE_CONTRACTS["AGENTS.md"],
            required_tokens=(),
            max_nonempty_lines=10,
            max_utf8_bytes=8,
        )
        cases = [
            ("x" * 8, 8, False),
            ("x" * 9, 9, True),
            ("\u00e9" * 5, 10, True),
            ("x\r\nx", 3, False),
            (" " * 9, 9, True),
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                lint_docs_structure,
                "CONTEXT_SURFACE_CONTRACTS",
                {"AGENTS.md": contract},
            ),
        ):
            root = Path(directory)
            for text, expected_bytes, fails in cases:
                with self.subTest(text=text):
                    (root / "AGENTS.md").write_bytes(text.encode("utf-8"))
                    errors = lint_docs_structure.validate_context_surfaces(root)
                    self.assertEqual(bool(errors), fails)
                    self.assertEqual(
                        lint_docs_structure.context_size_report(root)["AGENTS.md"][
                            "utf8_bytes"
                        ],
                        expected_bytes,
                    )
                    if fails:
                        self.assertIn("UTF-8 context budget", errors[0].message)

    def test_context_report_is_json_and_preserves_validation_status(self) -> None:
        """Reporting must not turn a failed validation into success.

        Inputs: complete and missing repository fixtures. Output: parsed JSON
        and matching success/failure exit-status assertions.
        """
        with tempfile.TemporaryDirectory() as directory:
            for valid in (True, False):
                with self.subTest(valid=valid):
                    root = (
                        Path(__file__).resolve().parents[1]
                        if valid
                        else Path(directory)
                    )
                    output = StringIO()
                    with redirect_stdout(output):
                        status = lint_docs_structure.main(
                            ["--repo-root", str(root), "--context-report"]
                        )
                    report = json.loads(output.getvalue())
                    self.assertEqual(status, 0 if valid else 1)
                    self.assertEqual(bool(report["errors"]), not valid)
                    self.assertEqual(bool(report["surfaces"]), valid)

    def test_policy_inheritance_requires_real_links(self) -> None:
        """Only explicit links may inherit the canonical policy.

        Inputs: each adapter with missing, broken, and valid references.
        Output: failure assertions and retained-policy evidence.
        """
        for adapter, link in AGENT_ADAPTER_LINKS.items():
            with (
                self.subTest(adapter=adapter),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                path = root / adapter
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("No policy reference\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    AssertionError, "does not require AGENTS.md"
                ):
                    read_instruction_contract(root, adapter)
                path.write_text(
                    f"```markdown\n[AGENTS.md]({link})\n```\nmandatory shared policy\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    AssertionError, "does not require AGENTS.md"
                ):
                    read_instruction_contract(root, adapter)
                path.write_text(
                    f"Read [AGENTS.md]({link}): mandatory shared policy.\n",
                    encoding="utf-8",
                )
                (root / "AGENTS.md").write_text("No task contracts\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    AssertionError, "does not link its task contracts"
                ):
                    read_instruction_contract(root, adapter)
                (root / "AGENTS.md").write_text(
                    f"Read [task contracts]({TASK_CONTRACT_PATH}) at their triggers.\n",
                    encoding="utf-8",
                )
                with self.assertRaises(FileNotFoundError):
                    read_instruction_contract(root, adapter)
                policy = root / TASK_CONTRACT_PATH
                policy.parent.mkdir(parents=True, exist_ok=True)
                policy.write_text("Required policy sentinel\n", encoding="utf-8")
                self.assertIn(
                    "Required policy sentinel", read_instruction_contract(root, adapter)
                )

    def test_report_mode_rejects_a_real_over_budget_entrypoint(self) -> None:
        """Fail the real CLI path when a policy exceeds its byte ceiling.

        Inputs: repository policy with a deliberately insufficient budget.
        Output: nonzero status and a structured budget error, not success.
        """
        root = Path(__file__).resolve().parents[1]
        contract = replace(CONTEXT_SURFACE_CONTRACTS["AGENTS.md"], max_utf8_bytes=1)
        output = StringIO()
        with (
            patch.object(
                lint_docs_structure,
                "CONTEXT_SURFACE_CONTRACTS",
                {"AGENTS.md": contract},
            ),
            redirect_stdout(output),
        ):
            status = lint_docs_structure.main(
                ["--repo-root", str(root), "--context-report"]
            )
        self.assertEqual(status, 1)
        report = json.loads(output.getvalue())
        self.assertTrue(
            any("UTF-8 context budget" in error for error in report["errors"])
        )
        self.assertGreater(report["surfaces"]["AGENTS.md"]["utf8_bytes"], 1)


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

    def test_relative_link_validation_covers_first_party_documents(self) -> None:
        """Validate local links while ignoring external URLs, anchors, and code.

        Inputs: temporary repository fixtures. Output: verifies valid links pass
        and broken or repository-escaping links are reported.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            docs_dir = repo_root / "docs"
            docs_dir.mkdir()
            (repo_root / "README.md").write_text(
                "\n".join(
                    (
                        "[valid](docs/target.md#section)",
                        "[external](https://example.invalid/missing.md)",
                        "[anchor](#local-heading)",
                        "`[inline code](docs/missing-inline.md)`",
                        "```markdown",
                        "[fenced example](docs/missing-fenced.md)",
                        "```",
                        "[reference]: <docs/target.md>",
                    )
                ),
                encoding="utf-8",
            )
            (docs_dir / "target.md").write_text(
                "[broken](missing.md)\n[escape](../../outside.md)\n",
                encoding="utf-8",
            )

            errors = validate_relative_markdown_links(repo_root)

            self.assertEqual(
                sorted(error.message for error in errors),
                [
                    "docs/target.md has broken relative link: missing.md",
                    "docs/target.md has repository-escaping link: ../../outside.md",
                ],
            )


if __name__ == "__main__":
    unittest.main()
