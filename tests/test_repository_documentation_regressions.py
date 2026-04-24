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

    def test_code_scanning_runbook_records_current_root_security_state(
        self,
    ) -> None:
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        self.assertIn("GitHub reported **8 open alerts on `main`**", runbook_text)
        self.assertIn("`py/empty-except` (2)", runbook_text)
        self.assertIn("`py/exit-from-finally` (1)", runbook_text)
        self.assertIn("`py/multiple-definition` (1)", runbook_text)
        self.assertIn(
            "GitHub closed the Trivy `DS002`,",
            runbook_text,
        )
        self.assertIn("4 Scorecard alerts were repository-level", runbook_text)
        self.assertNotIn("should clear on the next workflow refresh", runbook_text)
        self.assertIn(
            "~~Add a `SECURITY.md` to the repository root.~~ **Done in-tree**",
            runbook_text,
        )

    def test_deepsource_repo_file_is_retired_from_agent_routing(self) -> None:
        expected_phrase = (
            "Do not search for, create, restore, or edit `.deepsource.toml`"
        )
        expected_runbook_phrase = "Do not look for `.deepsource.toml`"
        self.assertFalse(
            (self.repo_root / ".deepsource.toml").exists(),
            "DeepSource repo-file configuration must remain retired.",
        )
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        normalized_runbook_text = " ".join(runbook_text.split())
        self.assertIn(expected_phrase, " ".join(self.read_text("AGENTS.md").split()))
        for adapter_path in (
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
        ):
            self.assertIn(".deepsource.toml", self.read_text(adapter_path))
        self.assertIn(expected_phrase, normalized_runbook_text)
        self.assertIn(
            "GitHub PAT is not a DeepSource API credential", normalized_runbook_text
        )
        self.assertIn(
            "report the count as unavailable, not zero", normalized_runbook_text
        )
        self.assertIn("grouped issues from issue occurrences", normalized_runbook_text)
        self.assertIn("command -v gh", runbook_text)
        self.assertIn("gh run view <run-id> --log-failed", runbook_text)
        self.assertIn("tools/scanner_inventory.py github-code-scanning", runbook_text)
        self.assertIn("tools/scanner_inventory.py deepsource", runbook_text)
        self.assertIn("prompts without echo on a TTY", runbook_text)
        self.assertIn("Never paste PATs into command arguments", runbook_text)
        self.assertIn("newest supported version", runbook_text)
        self.assertIn("do not pin stale dates", runbook_text)
        self.assertNotIn('"X-GitHub-Api-Version": "2022-11-28"', runbook_text)
        self.assertNotIn("Authorization: Bearer $GITHUB_TOKEN", runbook_text)
        self.assertIn("branch=main", runbook_text)
        scanner_tool_text = self.read_text("tools/scanner_inventory.py")
        self.assertIn("getpass.getpass", scanner_tool_text)
        self.assertIn("https://api.github.com/versions", scanner_tool_text)
        self.assertIn(
            "GitHub versions request returned no supported versions", scanner_tool_text
        )
        self.assertIn('"X-GitHub-Api-Version": api_version', scanner_tool_text)
        self.assertIn("https://api.deepsource.com/graphql/", scanner_tool_text)
        self.assertIn("DeepSource API returned GraphQL errors", scanner_tool_text)
        self.assertIn("issueOccurrences(first: 1)", scanner_tool_text)
        self.assertIn("dependencyVulnerabilityOccurrences(first: 1)", scanner_tool_text)
        self.assertIn(
            expected_runbook_phrase,
            self.read_text(".agents/skills/security-finding-triager/SKILL.md"),
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
        self.assertEqual("root", self.services["redis-sysctl-init"].get("user"))
        self.assertEqual(
            ["sysctl-init"], self.services["redis-sysctl-init"].get("profiles")
        )
        self.assertIn("crowdsec", self.services)
        self.assertEqual(["crowdsec"], self.services["crowdsec"].get("profiles"))

        expected_phrases = [
            "21 Compose services",
            "19 long-running runtime containers by default",
            "20 when the profile-gated",
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
        self.assertIn("<title>Tools help</title>", template_text)
        self.assertIn("tools-help-screenshot", template_text)
        self.assertIn("Troubleshooting", template_text)
        self.assertNotIn("Open Enhanced search", template_text)

    def test_plugin_help_style_guide_is_agent_routed(self) -> None:
        guide_path = self.repo_root / "docs/reference/plugin-help-page-style-guide.md"
        self.assertTrue(guide_path.exists(), "Plugin help style guide is missing")

        guide_text = guide_path.read_text(encoding="utf-8")
        for phrase in [
            "use an `<a>` element, not a `<button>`",
            "the expanded state keeps the unrotated horizontal indicator",
            "crop rectangles consistently",
            "keep the full blue border",
            "no persisted state",
        ]:
            self.assertIn(phrase, guide_text)

        expected_references = {
            "AGENTS.md": "docs/reference/plugin-help-page-style-guide.md",
            "docs/index.md": "reference/plugin-help-page-style-guide.md",
            "docs/reference/ai-agent-context-routing.md": (
                "docs/reference/plugin-help-page-style-guide.md"
            ),
        }
        for relative_path, expected_reference in expected_references.items():
            self.assertIn(
                expected_reference,
                self.read_text(relative_path),
                f"{relative_path} does not route agents to the help-page guide.",
            )


if __name__ == "__main__":
    unittest.main()
