"""Contract tests for the opt-in caveman integration."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class CavemanSkillContractTests(unittest.TestCase):
    """Test cases for caveman skill contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Store set up class."""
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        """Return read text."""
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_vendored_caveman_reference_exists(self) -> None:
        """Verify test vendored caveman reference exists."""
        self.assertTrue(
            (self.repo_root / "third_party/caveman-v1.6.0/LICENSE").is_file()
        )
        self.assertTrue(
            (
                self.repo_root / "third_party/caveman-v1.6.0/skills/caveman/SKILL.md"
            ).is_file()
        )
        self.assertFalse(
            (self.repo_root / "third_party/caveman-v1.6.0/README.md").exists()
        )

    def test_active_caveman_skill_is_guarded_and_repo_specific(self) -> None:
        """Verify test active caveman skill is guarded and repo behavior."""
        skill_text = self.read_text(".agents/skills/caveman/SKILL.md")
        self.assertIn("Use this skill only when the user explicitly asks", skill_text)
        self.assertIn("context-budget", skill_text)
        self.assertIn("changes response style only", skill_text)
        self.assertIn("must not change context selection", skill_text)
        self.assertIn("Compression never outranks correctness", skill_text)
        self.assertIn("Drop compression and return to normal detail", skill_text)
        self.assertIn("internal AI reply/prompting only", skill_text)
        self.assertIn("Never use caveman prose", skill_text)
        self.assertIn("CAVEMAN_DEFAULT_MODE", skill_text)
        self.assertIn("caveman-help", skill_text)
        self.assertIn("All supported agents", skill_text)
        self.assertIn(".codex", skill_text)
        self.assertIn("natural-language auto-activation", skill_text)
        self.assertIn("third_party/caveman-v1.6.0/skills/caveman/SKILL.md", skill_text)

    def test_caveman_adapter_disables_implicit_invocation(self) -> None:
        """Verify test caveman adapter disables implicit invoca behavior."""
        adapter = yaml.safe_load(
            self.read_text(".agents/skills/caveman/agents/openai.yaml")
        )
        self.assertEqual(False, adapter["policy"]["allow_implicit_invocation"])
        self.assertIn(
            "explicitly asks",
            adapter["interface"]["default_prompt"],
        )
        self.assertIn("normal prose", adapter["interface"]["default_prompt"])
        self.assertIn("across agents", adapter["interface"]["default_prompt"])

    def test_cross_agent_surfaces_present_caveman_as_opt_in(self) -> None:
        """Verify test cross agent surfaces present caveman as behavior."""
        tracked_surfaces = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            "docs/reference/ai-agent-skills.md",
            "docs/reference/ai-agent-integrations.md",
            "docs/reference/ai-agent-upstream-sources.md",
        )
        for relative_path in tracked_surfaces:
            with self.subTest(relative_path=relative_path):
                text = self.read_text(relative_path)
                text_lower = text.lower()
                self.assertIn("caveman", text_lower)
                self.assertTrue(
                    "lower-token" in text_lower or "lower token" in text_lower
                )
                self.assertTrue(
                    "style only" in text_lower
                    or "reply style only" in text_lower
                    or "routing" in text_lower
                    or "tool choice" in text_lower
                    or "verification scope" in text_lower
                )

    def test_supported_agent_adapters_route_to_shared_skill_catalog(self) -> None:
        """Verify test supported agent adapters route to shared behavior."""
        tracked_surfaces = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
        )
        for relative_path in tracked_surfaces:
            with self.subTest(relative_path=relative_path):
                text = self.read_text(relative_path)
                self.assertIn(".agents/skills", text)
                self.assertTrue(
                    "docs/reference/ai-agent-skills.md" in text or "AGENTS.md" in text
                )

    def test_public_docs_keep_caveman_prompt_only(self) -> None:
        """Verify test public docs keep caveman prompt only."""
        tracked_docs = (
            "README.md",
            "AGENTS.md",
            "docs/reference/ai-agent-skills.md",
            "docs/reference/ai-agent-integrations.md",
            "docs/reference/ai-agent-upstream-sources.md",
        )
        for relative_path in tracked_docs:
            with self.subTest(relative_path=relative_path):
                text_lower = self.read_text(relative_path).lower()
                self.assertIn("caveman", text_lower)
                self.assertTrue(
                    "internal ai" in text_lower
                    or "internal ai communication" in text_lower
                )
                self.assertTrue(
                    "normal prose" in text_lower
                    or "standard prose" in text_lower
                    or "never rewrite" in text_lower
                    or "user-facing copy" in text_lower
                )

    def test_repo_does_not_activate_upstream_caveman_runtime(self) -> None:
        """Verify test repo does not activate upstream caveman behavior."""
        integrations_text = self.read_text("docs/reference/ai-agent-integrations.md")
        self.assertIn("shared `.agents/skills/` catalog", integrations_text)
        self.assertIn("do not make it Codex-only", integrations_text)
        self.assertIn(".codex` hook config", integrations_text)
        self.assertIn("plugin auto-loading", integrations_text)
        self.assertIn("not activated in this repo", integrations_text)
        self.assertIn("verification scope", integrations_text)
        self.assertFalse((self.repo_root / ".codex-plugin").exists())
        self.assertFalse((self.repo_root / ".codex" / "hooks.json").exists())
        self.assertFalse((self.repo_root / ".codex" / "config.toml").exists())
        self.assertNotIn("caveman", self.read_text(".claude/settings.json").lower())

    def test_upstream_reference_records_latest_reviewed_release(self) -> None:
        """Verify test upstream reference records latest review behavior."""
        upstream_text = self.read_text("docs/reference/ai-agent-upstream-sources.md")
        reviewed_caveman_commit = "".join(
            (
                "c2ed24b3e5d412cd0c251",
                "97b2bc9af587621fd99",
            )
        )
        self.assertIn("Reviewed release notes: `v1.5.1` and `v1.6.0`", upstream_text)
        self.assertIn("caveman release tag: `v1.6.0`", upstream_text)
        self.assertIn(reviewed_caveman_commit, upstream_text)
        self.assertIn("third_party/caveman-v1.6.0/", upstream_text)

    def test_readme_documents_opt_in_caveman_badge(self) -> None:
        """Verify test readme documents opt in caveman badge."""
        readme_text = self.read_text("README.md")
        self.assertIn("[![caveman](", readme_text)
        self.assertIn(
            "https://img.shields.io/static/v1?label=&message=caveman&color=555"
            "&logo=github&logoColor=white",
            readme_text,
        )
        self.assertNotIn(
            "https://img.shields.io/badge/caveman-555?logo=github&labelColor=555",
            readme_text,
        )
        self.assertNotIn("https://img.shields.io/badge/caveman-555", readme_text)
        self.assertIn("https://github.com/JuliusBrussee/caveman", readme_text)
        self.assertIn(
            "https://github.com/forrestchang/andrej-karpathy-skills", readme_text
        )


if __name__ == "__main__":
    unittest.main()
