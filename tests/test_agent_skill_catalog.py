"""Regression checks for the repo-local agent skill surface."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REQUIRED_SKILLS: tuple[str, ...] = (
    "search-first",
    "documentation-lookup",
    "verification-loop",
    "docs-knowledge-maintainer",
    "plugin-regression-triager",
    "omero-runtime-verifier",
    "env-contract-reviewer",
    "security-finding-triager",
)


class AgentSkillCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.catalog_text = (
            cls.repo_root / "docs" / "reference" / "ai-agent-skills.md"
        ).read_text(encoding="utf-8")
        cls.agents_text = (cls.repo_root / "AGENTS.md").read_text(encoding="utf-8")
        cls.claude_text = (cls.repo_root / "CLAUDE.md").read_text(encoding="utf-8")
        cls.index_text = (cls.repo_root / "docs" / "index.md").read_text(
            encoding="utf-8"
        )

    def parse_frontmatter(self, skill_markdown: str) -> dict[str, object]:
        self.assertTrue(
            skill_markdown.startswith("---\n"), "Skill file is missing frontmatter"
        )
        _, frontmatter_text, _ = skill_markdown.split("---\n", 2)
        parsed = yaml.safe_load(frontmatter_text)
        self.assertIsInstance(parsed, dict, "Skill frontmatter must parse to a mapping")
        return parsed

    def test_catalog_doc_is_linked_from_agents_claude_and_index(self) -> None:
        self.assertIn("docs/reference/ai-agent-skills.md", self.agents_text)
        self.assertIn("docs/reference/ai-agent-skills.md", self.claude_text)
        self.assertIn("`reference/ai-agent-skills.md`", self.index_text)
        self.assertIn(".agents/skills/", self.catalog_text)

    def test_required_skill_directories_exist_with_metadata(self) -> None:
        for skill_name in REQUIRED_SKILLS:
            skill_dir = self.repo_root / ".agents" / "skills" / skill_name
            skill_file = skill_dir / "SKILL.md"
            metadata_file = skill_dir / "agents" / "openai.yaml"

            self.assertTrue(
                skill_dir.is_dir(), f"Missing skill directory: {skill_name}"
            )
            self.assertTrue(skill_file.is_file(), f"Missing SKILL.md: {skill_name}")
            self.assertTrue(
                metadata_file.is_file(), f"Missing agents/openai.yaml: {skill_name}"
            )

            frontmatter = self.parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            self.assertEqual(skill_name, frontmatter.get("name"))
            self.assertTrue(frontmatter.get("description"))
            self.assertTrue(frontmatter.get("origin"))

            metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
            self.assertEqual(
                True,
                metadata.get("policy", {}).get("allow_implicit_invocation"),
            )
            self.assertTrue(metadata.get("interface", {}).get("display_name"))
            self.assertTrue(metadata.get("interface", {}).get("short_description"))
            self.assertTrue(metadata.get("interface", {}).get("default_prompt"))

    def test_catalog_lists_every_required_skill_path(self) -> None:
        for skill_name in REQUIRED_SKILLS:
            self.assertIn(f"`{skill_name}`", self.catalog_text)
            self.assertIn(
                f".agents/skills/{skill_name}/SKILL.md",
                self.catalog_text,
            )

    def test_security_and_verification_skills_point_to_repo_contracts(self) -> None:
        security_text = (
            self.repo_root
            / ".agents"
            / "skills"
            / "security-finding-triager"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        verification_text = (
            self.repo_root / ".agents" / "skills" / "verification-loop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        runtime_text = (
            self.repo_root
            / ".agents"
            / "skills"
            / "omero-runtime-verifier"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "docs/reference/ai-agent-security-prevention-playbook.md",
            security_text,
        )
        self.assertIn("docs/operations/code-scanning.md", security_text)
        self.assertIn("split pytest", verification_text.lower())
        self.assertIn("Never run OMERO CLI as `root`", runtime_text)


if __name__ == "__main__":
    unittest.main()
