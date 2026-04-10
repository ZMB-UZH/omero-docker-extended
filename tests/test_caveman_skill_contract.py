"""Contract tests for the opt-in Caveman integration."""

from __future__ import annotations

import unittest
from pathlib import Path


class CavemanSkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_vendored_caveman_reference_exists(self) -> None:
        self.assertTrue(
            (self.repo_root / "third_party/caveman-v1.3.5/LICENSE").is_file()
        )
        self.assertTrue(
            (
                self.repo_root / "third_party/caveman-v1.3.5/skills/caveman/SKILL.md"
            ).is_file()
        )

    def test_active_caveman_skill_is_guarded_and_repo_specific(self) -> None:
        skill_text = self.read_text(".agents/skills/caveman/SKILL.md")
        self.assertIn("Use this skill only when the user explicitly asks", skill_text)
        self.assertIn("context-budget", skill_text)
        self.assertIn("Compression never outranks correctness", skill_text)
        self.assertIn("Drop compression and return to normal detail", skill_text)
        self.assertIn("third_party/caveman-v1.3.5/skills/caveman/SKILL.md", skill_text)

    def test_cross_agent_surfaces_present_caveman_as_opt_in(self) -> None:
        tracked_surfaces = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            "docs/reference/ai-agent-skills.md",
            "docs/reference/ai-agent-integrations.md",
        )
        for relative_path in tracked_surfaces:
            with self.subTest(relative_path=relative_path):
                text = self.read_text(relative_path)
                self.assertIn("caveman", text.lower())
                self.assertTrue(
                    "lower-token" in text.lower() or "lower token" in text.lower()
                )

    def test_repo_does_not_activate_upstream_caveman_runtime(self) -> None:
        integrations_text = self.read_text("docs/reference/ai-agent-integrations.md")
        self.assertIn("plugin auto-loading", integrations_text)
        self.assertIn("not activated in this repo", integrations_text)
        self.assertFalse((self.repo_root / ".codex-plugin").exists())
        self.assertNotIn("caveman", self.read_text(".claude/settings.json").lower())

    def test_readme_documents_opt_in_caveman_badge(self) -> None:
        readme_text = self.read_text("README.md")
        self.assertIn("[![Caveman](", readme_text)
        self.assertIn("https://github.com/JuliusBrussee/caveman", readme_text)


if __name__ == "__main__":
    unittest.main()
