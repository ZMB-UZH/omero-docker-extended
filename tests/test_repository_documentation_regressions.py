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
        normalized_runbook_text = " ".join(runbook_text.split())
        self.assertIn("GitHub reported **4 open alerts on `main`**", runbook_text)
        self.assertIn("**11 grouped issues**", runbook_text)
        self.assertIn("**291 issue occurrences**", runbook_text)
        self.assertIn("**0 dependency vulnerability occurrences**", runbook_text)
        self.assertIn("latest_commit_oid", runbook_text)
        self.assertIn(
            "GitHub closed the Trivy `DS002`,",
            runbook_text,
        )
        self.assertIn("CodeQL file-level findings in", runbook_text)
        self.assertIn("transient Semgrep", runbook_text)
        self.assertIn(
            "4 remaining alerts were repository-level", normalized_runbook_text
        )
        self.assertNotIn("should clear on the next workflow refresh", runbook_text)
        self.assertIn(
            "~~Add a `SECURITY.md` to the repository root.~~ **Done in-tree**",
            runbook_text,
        )

    def test_doc_compaction_requires_objective_meaning_preservation(self) -> None:
        agents_text = self.read_text("AGENTS.md")
        runtime_text = self.read_text("docs/reference/ai-agent-runtime-playbook.md")
        docs_skill_text = self.read_text(
            ".agents/skills/docs-knowledge-maintainer/SKILL.md"
        )

        self.assertIn("preserve every required meaning", agents_text)
        self.assertIn("objective regression checks", agents_text)
        self.assertIn("If a line-count budget must change", runtime_text)
        self.assertIn("explicit phrase or behavior invariants", runtime_text)
        self.assertIn("Less is more", runtime_text)
        self.assertIn("prove full functional parity", agents_text)
        self.assertIn("satisfy every repo rule", agents_text)
        self.assertIn("fewer lines can prove full functional parity", docs_skill_text)
        for adapter_path in (
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
        ):
            with self.subTest(adapter_path=adapter_path):
                adapter_text = " ".join(self.read_text(adapter_path).split())
                self.assertIn("fewer lines", adapter_text)
                self.assertRegex(adapter_text, r"(parity|full parity)")
        self.assertIn("compact rewrites", docs_skill_text)
        self.assertIn("dropping required meaning", docs_skill_text)

    def test_agent_instructions_close_proven_retry_loops_after_verification(
        self,
    ) -> None:
        agents_text = self.read_text("AGENTS.md")
        runtime_text = self.read_text("docs/reference/ai-agent-runtime-playbook.md")
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        docs_skill_text = self.read_text(
            ".agents/skills/docs-knowledge-maintainer/SKILL.md"
        )

        self.assertIn("proven avoidable retry/error loop", agents_text)
        self.assertIn("only after the correct workflow is verified", agents_text)
        self.assertIn("repo instruction, runbook, script, or helper", runtime_text)
        self.assertIn("establish the correct workflow end to end", runtime_text)
        self.assertIn("regression coverage", runtime_text)
        self.assertIn("documented scanner command or helper", runbook_text)
        self.assertIn("correct scanner workflow end to end", runbook_text)
        self.assertIn("proven avoidable retry/error loop", docs_skill_text)

        adapter_paths = (
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
        )
        for adapter_path in adapter_paths:
            with self.subTest(adapter_path=adapter_path):
                adapter_text = " ".join(self.read_text(adapter_path).split())
                self.assertIn("proven bad instructions/tools", adapter_text)
                self.assertIn("correct workflow", adapter_text)

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
        normalized_agents_text = " ".join(self.read_text("AGENTS.md").split())
        self.assertIn(
            "do not search for, create, restore, or edit",
            normalized_agents_text.lower(),
        )
        self.assertIn("`.deepsource.toml`", normalized_agents_text)
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
            "ask the user for the exact credential immediately",
            normalized_runbook_text,
        )
        self.assertIn("Do not keep retrying", runbook_text)
        self.assertIn("confirm all GitHub workflows are green", runbook_text)
        self.assertIn("compare grouped issues plus issue occurrences", runbook_text)
        self.assertIn("If either count increased", runbook_text)
        self.assertIn(
            "report the count as unavailable, not zero", normalized_runbook_text
        )
        self.assertIn("grouped issues from issue occurrences", normalized_runbook_text)
        self.assertIn("latest_commit_oid", normalized_runbook_text)
        self.assertIn("lagged snapshot", normalized_runbook_text)
        self.assertIn("command -v gh", runbook_text)
        self.assertIn("gh run view <run-id> --log-failed", runbook_text)
        self.assertIn("tools/scanner_inventory.py github-code-scanning", runbook_text)
        self.assertIn("tools/scanner_inventory.py deepsource", runbook_text)
        self.assertIn("tools/scanner_inventory.py deepsource-issues", runbook_text)
        self.assertIn("prompts without echo on a TTY", runbook_text)
        self.assertIn("Never paste PATs into command arguments", runbook_text)
        self.assertIn("GitHub HTTPS Git operations require a PAT", runbook_text)
        self.assertIn("tools/git_push_with_pat.py origin main", runbook_text)
        self.assertIn("temp files", runbook_text)
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
        self.assertIn("occurrences(first: $occurrenceLimit)", scanner_tool_text)
        git_push_tool_text = self.read_text("tools/git_push_with_pat.py")
        self.assertIn("getpass.getpass", git_push_tool_text)
        self.assertIn("GIT_ASKPASS", git_push_tool_text)
        self.assertIn("GIT_PAT_SOCKET", git_push_tool_text)
        self.assertNotIn("GIT_PAT_FILE", git_push_tool_text)
        self.assertNotIn("write_text(token", git_push_tool_text)
        self.assertIn("credential.https://github.com.helper=", git_push_tool_text)
        self.assertIn("GIT_TERMINAL_PROMPT", git_push_tool_text)
        self.assertIn(
            expected_runbook_phrase,
            self.read_text(".agents/skills/security-finding-triager/SKILL.md"),
        )
        expected_auth_phrase = "ask immediately and pause for input"
        for adapter_path in (
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
        ):
            adapter_text = self.read_text(adapter_path)
            normalized_adapter_text = " ".join(adapter_text.split())
            self.assertIn(".deepsource.toml", adapter_text)
            self.assertIn("ask immediately", normalized_adapter_text)
            self.assertIn("credential", normalized_adapter_text)
            self.assertIn("PAT", normalized_adapter_text)
            self.assertIn("GitHub workflows", normalized_adapter_text)
            self.assertIn("DeepSource", normalized_adapter_text)
            self.assertRegex(
                normalized_adapter_text,
                r"(did not increase|no DeepSource count increase)",
            )
        self.assertIn(expected_auth_phrase, self.read_text("CLAUDE.md"))
        self.assertIn(
            expected_auth_phrase,
            self.read_text(".github/copilot-instructions.md"),
        )
        self.assertIn("GitHub PAT", normalized_agents_text)
        self.assertIn(
            "GitHub HTTPS Git operations require a PAT", normalized_agents_text
        )
        self.assertIn("DeepSource API key", normalized_agents_text)
        self.assertIn("needed and unavailable", normalized_agents_text)
        self.assertIn("ask immediately and pause", normalized_agents_text)
        self.assertIn("do not retry auth failures", normalized_agents_text)
        self.assertIn(
            "After every push, verify GitHub workflows are green",
            self.read_text("AGENTS.md"),
        )
        self.assertIn(
            "issue occurrences for the pushed commit", self.read_text("AGENTS.md")
        )
        self.assertIn(
            "ask for it immediately and pause",
            self.read_text(".agents/skills/security-finding-triager/SKILL.md"),
        )
        self.assertIn(
            "tools/git_push_with_pat.py",
            self.read_text(".agents/skills/security-finding-triager/SKILL.md"),
        )
        self.assertIn(
            "against the pre-push baseline",
            self.read_text(".agents/skills/security-finding-triager/SKILL.md"),
        )
        prevention_text = self.read_text(
            "docs/reference/ai-agent-security-prevention-playbook.md"
        )
        self.assertIn("confirm GitHub workflows are green", prevention_text)
        self.assertIn("compare grouped issues plus issue occurrences", prevention_text)
        self.assertIn("against the pre-push baseline", prevention_text)

    def test_codeql_file_count_coverage_is_explained(self) -> None:
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        normalized_runbook_text = " ".join(runbook_text.split())
        workflow_text = self.read_text(".github/workflows/security-code-scanning.yml")

        self.assertIn("CodeQL File-Count Coverage", runbook_text)
        self.assertIn(
            "310 tracked `.py` implementation files and 33 tracked `.pyi` type stubs",
            normalized_runbook_text,
        )
        self.assertIn("`310/343` CodeQL count", normalized_runbook_text)
        self.assertIn("8 tracked JS-family files", normalized_runbook_text)
        self.assertIn(".agents/skills/frontend-preview/agents/", runbook_text)
        self.assertIn("6 application/test JS files", runbook_text)
        self.assertIn("Audit — explain CodeQL language candidates", workflow_text)
        self.assertIn("git ls-files '*.py'", workflow_text)
        self.assertIn("git ls-files '*.pyi'", workflow_text)
        self.assertIn("git ls-files '*.js' '*.jsx' '*.mjs'", workflow_text)

    def test_markdownlint_command_is_node18_compatible(self) -> None:
        expected = "npx --yes markdownlint-cli2@0.17.2"
        self.assertIn(expected, self.read_text("AGENTS.md"))
        self.assertIn(
            expected,
            self.read_text("docs/reference/plugin-help-page-style-guide.md"),
        )
        self.assertIn(
            expected,
            self.read_text("docs/reference/ai-agent-integrations.md"),
        )

    def test_missing_host_pytest_dependencies_route_to_workflow_venv(self) -> None:
        troubleshooting_text = self.read_text("docs/troubleshooting/common.md")
        normalized_troubleshooting_text = " ".join(troubleshooting_text.split())

        self.assertIn(
            "lacks Django or optional test dependencies", troubleshooting_text
        )
        self.assertIn(
            "python3 tools/run_local_workflow_gates.py --setup-only",
            troubleshooting_text,
        )
        self.assertIn("LOCAL_WORKFLOW_GATE_VENV", troubleshooting_text)
        self.assertIn("numpy", troubleshooting_text)
        self.assertIn("numcodecs", troubleshooting_text)
        self.assertIn("matplotlib", troubleshooting_text)
        self.assertIn(
            "Use the OMERO.web runtime interpreter only for installed-container or live-runtime verification",
            normalized_troubleshooting_text,
        )
        self.assertNotIn(
            "Prefer the OMERO.web runtime interpreter for full pytest runs.",
            troubleshooting_text,
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
