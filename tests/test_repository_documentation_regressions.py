"""Regression checks for repository-level documentation drift."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class RepositoryDocumentationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.compose_data = yaml.safe_load(
            (cls.repo_root / "docker-compose.yml").read_text(encoding="utf-8")
        )
        cls.services = cls.compose_data["services"]

    def read_text(self, relative_path: str) -> str:
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_root_security_policy_exists_and_points_to_canonical_docs(self) -> None:
        root_security = self.repo_root / "SECURITY.md"
        github_security = self.repo_root / ".github" / "SECURITY.md"
        self.assertTrue(
            root_security.exists(), "Repository root SECURITY.md is missing"
        )
        self.assertTrue(github_security.exists(), ".github/SECURITY.md is missing")
        root_text = root_security.read_text(encoding="utf-8")
        self.assertIn("docs/SECURITY.md", root_text)
        self.assertIn(
            "https://github.com/ZMB-UZH/omero-docker-extended/security/advisories/new",
            root_text,
        )
        self.assertIn(
            "https://github.com/ZMB-UZH/omero-docker-extended/blob/main/docs/SECURITY.md",
            github_security.read_text(encoding="utf-8"),
        )
        self.assertTrue((self.repo_root / "docs" / "SECURITY.md").exists())

    def test_code_scanning_runbook_records_root_security_fix_as_pending_refresh(
        self,
    ) -> None:
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        self.assertIn(
            "fixed in-tree now and should clear on the next workflow refresh",
            runbook_text,
        )
        self.assertIn(
            "~~Add a `SECURITY.md` to the repository root.~~ **Done in-tree**",
            runbook_text,
        )

    def test_explicit_manual_compose_examples_include_required_env_files(
        self,
    ) -> None:
        tracked_docs = [
            "CLAUDE.md",
            "docs/deployment/quickstart.md",
            "docs/product-specs/new-user-onboarding.md",
            "docs/references/docker-compose-llms.txt",
            "docs/troubleshooting/common.md",
        ]
        offenders: list[str] = []
        for relative_path in tracked_docs:
            for line_number, line in enumerate(
                self.read_text(relative_path).splitlines(), 1
            ):
                if (
                    "docker compose" in line
                    and "installation_paths.env" in line
                    and (
                        "omero_secrets.env" not in line or "omeroserver.env" not in line
                    )
                ):
                    offenders.append(f"{relative_path}:{line_number}:{line}")
        self.assertEqual(
            [],
            offenders,
            "Found stale compose examples without the full env contract:\n"
            + "\n".join(offenders),
        )

    def test_service_topology_docs_match_compose_terms(self) -> None:
        self.assertEqual(21, len(self.services))
        self.assertIn("redis-sysctl-init", self.services)
        self.assertEqual("no", str(self.services["redis-sysctl-init"].get("restart")))
        self.assertEqual(
            ["sysctl-init"], self.services["redis-sysctl-init"].get("profiles")
        )
        self.assertIn("crowdsec", self.services)
        self.assertEqual(["crowdsec"], self.services["crowdsec"].get("profiles"))

        expected_phrases = [
            "20 Compose services",
            "18 long-running runtime containers by default",
            "19 when the profile-gated",
            "crowdsec",
            "redis-sysctl-init",
        ]
        tracked_docs = [
            "README.md",
            "ARCHITECTURE.md",
            "AGENTS.md",
            "docs/references/docker-compose-llms.txt",
        ]
        for relative_path in tracked_docs:
            text = self.read_text(relative_path)
            for phrase in expected_phrases:
                self.assertIn(phrase, text, f"{relative_path} is missing: {phrase}")

    def test_plugin_help_pages_are_concise_user_help(self) -> None:
        expected_phrases = {
            "docs/help/omeroweb_omp_plugin_help.md": [
                "Select and Prepare",
                "Preview and Apply",
                "Apply metadata only when the preview matches the filenames.",
            ],
            "docs/help/omeroweb_import_help.md": [
                "Choose the target project.",
                "Upload and import are separate steps.",
                "Read the latest message before retrying.",
            ],
            "docs/help/omeroweb_admin_tools_help.md": [
                "Admin Tools is for OMERO administrators.",
                "Make one operational change at a time.",
                "Use Logs and Monitoring together to narrow the cause.",
            ],
        }
        runbook_terms = [
            "docker compose",
            "env/",
            "psycopg2",
            "container",
            "mounted",
            "supervisor",
            "Loki",
            "Prometheus reachability",
        ]
        for relative_path, phrases in expected_phrases.items():
            text = self.read_text(relative_path)
            nonempty_lines = [line for line in text.splitlines() if line.strip()]
            self.assertLessEqual(
                len(nonempty_lines),
                55,
                f"{relative_path} should stay compact end-user help.",
            )
            for phrase in phrases:
                self.assertIn(phrase, text, f"{relative_path} is missing: {phrase}")
            for term in runbook_terms:
                self.assertNotIn(
                    term,
                    text,
                    f"{relative_path} drifted into admin/runbook language: {term}",
                )

    def test_tools_help_is_canonical_html_help(self) -> None:
        stale_markdown = self.repo_root / "docs/help/omeroweb_tools_help.md"
        self.assertFalse(
            stale_markdown.exists(),
            "Enhanced search help should be the HTML template, not stale Markdown.",
        )

        docs_index = self.read_text("docs/index.md")
        template_text = self.read_text(
            "omeroweb_tools/templates/omeroweb_tools/help.html"
        )
        self.assertIn("omeroweb_tools/templates/omeroweb_tools/help.html", docs_index)
        self.assertIn("<title>Enhanced search help</title>", template_text)
        self.assertIn("tools-help-screenshot", template_text)
        self.assertIn("Troubleshooting", template_text)
        self.assertNotIn("Open Enhanced search", template_text)


if __name__ == "__main__":
    unittest.main()
