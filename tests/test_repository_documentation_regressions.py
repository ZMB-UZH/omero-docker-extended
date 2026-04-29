"""Regression checks for repository-level documentation drift."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml


class RepositoryDocumentationRegressionTests(unittest.TestCase):
    """Regression tests for repository documentation contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load repository fixtures shared by documentation contract checks."""
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.compose_data = yaml.safe_load(
            (cls.repo_root / "docker-compose.yml").read_text(encoding="utf-8")
        )
        cls.services = cls.compose_data["services"]

    def read_text(self, relative_path: str) -> str:
        """Read a repository-relative UTF-8 text file for assertions."""
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def git_files(self, *patterns: str) -> list[str]:
        """Return repository paths that match the supplied git patterns."""
        git_path = shutil.which("git")
        self.assertIsNotNone(git_path)
        output = subprocess.check_output(
            [
                git_path,
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                *patterns,
            ],
            cwd=self.repo_root,
            text=True,
        )
        return [line for line in output.splitlines() if line]

    def git_file_count(self, *patterns: str) -> int:
        """Count repository paths that match the supplied git patterns."""
        return len(self.git_files(*patterns))

    def literal_assignment(self, relative_path: str, name: str) -> object:
        """Return a literal module-level assignment from a Python file."""
        module = ast.parse(self.read_text(relative_path))
        for node in module.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name
            ):
                return ast.literal_eval(node.value)
        raise AssertionError(f"{relative_path} is missing {name}")

    def test_root_security_policy_exists_and_points_to_canonical_docs(self) -> None:
        """Verify Root security policy exists and points to canonical docs."""
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

    def test_github_community_standard_files_exist(self) -> None:
        """Verify GitHub community standard files exist."""
        expected_paths = (
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            ".github/SECURITY.md",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/ISSUE_TEMPLATE/config.yml",
            ".github/pull_request_template.md",
        )
        for relative_path in expected_paths:
            with self.subTest(relative_path=relative_path):
                path = self.repo_root / relative_path
                self.assertTrue(path.is_file(), f"Missing {relative_path}")
                self.assertGreater(
                    len(path.read_text(encoding="utf-8").strip()),
                    0,
                    f"{relative_path} is empty",
                )

        code_of_conduct = self.read_text("CODE_OF_CONDUCT.md")
        contributing = self.read_text("CONTRIBUTING.md")
        issue_config = self.read_text(".github/ISSUE_TEMPLATE/config.yml")
        pr_template = self.read_text(".github/pull_request_template.md")

        self.assertIn("Reporting", code_of_conduct)
        self.assertIn("security/advisories/new", code_of_conduct)
        self.assertIn("tools/run_local_workflow_gates.py", contributing)
        self.assertIn("blank_issues_enabled: false", issue_config)
        self.assertIn("Security vulnerability", issue_config)
        self.assertIn("## Verification", pr_template)

    def test_docs_do_not_imply_multiple_project_maintainers(self) -> None:
        """Verify Docs do not imply multiple project maintainers."""
        plural_voice_patterns = {
            "plural pronoun": re.compile(
                r"\b(we|we're|we’ve|we've|we’ll|we'll|we’d|we'd|our|ours|"
                r"ourselves|us|let's|lets)\b",
                re.IGNORECASE,
            ),
            "plural maintainer role": re.compile(
                r"\b(maintainers|multi-maintainer|development team|team|"
                r"future developers)\b",
                re.IGNORECASE,
            ),
        }
        upstream_developer_url = re.compile(
            r"https://omero\.readthedocs\.io/.*/developers/"
        )
        mermaid_edge = re.compile(r"^\s*[A-Z][A-Z0-9]*\s*--?>")
        informal_singular = re.compile(
            r"\b(I'm|I’ve|I've|I’ll|I'll|I’d|I'd|me|my|mine|myself)\b|"
            r"(?<![-/])\bI\b(?![/\[])"
        )
        personal_voice_patterns = {
            **plural_voice_patterns,
            "informal singular": informal_singular,
        }
        checked_suffixes = {
            ".json",
            ".md",
            ".mdc",
            ".rst",
            ".txt",
            ".yaml",
            ".yml",
        }
        checked_names = {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md"}
        offenders: list[str] = []
        for relative_path in self.git_files():
            path = Path(relative_path)
            if path.parts and path.parts[0] == "third_party":
                continue
            if (
                path.suffix.lower() not in checked_suffixes
                and path.name not in checked_names
            ):
                continue
            text = self.read_text(relative_path)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if upstream_developer_url.search(line):
                    continue
                if mermaid_edge.search(line):
                    continue
                for pattern_name, pattern in personal_voice_patterns.items():
                    if pattern.search(line):
                        offenders.append(
                            f"{relative_path}:{line_number}: {pattern_name}: {line}"
                        )

        self.assertEqual([], offenders)

    def test_code_scanning_runbook_records_current_root_security_state(
        self,
    ) -> None:
        """Verify Code scanning runbook records current root security state."""
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        normalized_runbook_text = " ".join(runbook_text.split())
        self.assertIn(
            "GitHub reported **4 open alerts on the default branch",
            runbook_text,
        )
        self.assertIn("Last live API refresh: **2026-04-27**", runbook_text)
        self.assertIn("**3 grouped issues**", runbook_text)
        self.assertIn("**109 issue occurrences**", runbook_text)
        self.assertIn("**0 dependency vulnerability occurrences**", runbook_text)
        expected_scanner_snapshot_commit = "".join(
            (
                "00c9e9c7",
                "390f9181",
                "30cde53e",
                "e2923c56",
                "79de6718",
            )
        )
        self.assertIn(expected_scanner_snapshot_commit, runbook_text)
        self.assertIn("latest_commit_oid", runbook_text)
        self.assertIn(
            "GitHub closed the Trivy `DS002`,",
            runbook_text,
        )
        self.assertIn("CodeQL file-level findings in", runbook_text)
        self.assertIn("transient Semgrep", runbook_text)
        self.assertIn(
            "4 remaining GitHub alerts were repository-level",
            normalized_runbook_text,
        )
        self.assertIn("`SH-3015` shell portability finding", normalized_runbook_text)
        self.assertNotIn("should clear on the next workflow refresh", runbook_text)
        self.assertIn(
            "~~Add a `SECURITY.md` to the repository root.~~ **Done in-tree**",
            runbook_text,
        )

        resolved_text = self.read_text(
            "docs/reference/code-scanning-resolved-findings.md"
        )
        self.assertIn(
            "Live GitHub code scanning showed only repository-level", resolved_text
        )
        self.assertIn("historical 2026-03-31 snapshot", resolved_text)
        self.assertNotIn("remain open", resolved_text)

    def test_docs_match_supervisord_program_topology(self) -> None:
        """Verify Docs match supervisord program topology."""
        supervisord_text = self.read_text("supervisord.conf")
        programs = sorted(re.findall(r"^\[program:([^\]]+)\]", supervisord_text, re.M))
        self.assertEqual(
            [
                "imaris-celery-worker",
                "omero-web",
                "storage-quota-reconcile-loop",
                "tools-celery-worker",
            ],
            programs,
        )

        expected_phrases = {
            "AGENTS.md": "storage-quota reconciliation loop under `supervisord`",
            "ARCHITECTURE.md": "The `omeroweb` container runs four processes via supervisord",
            "docs/RELIABILITY.md": "The `omeroweb` container runs four processes via supervisord",
            "docs/architecture/system-overview.md": "as four supervised processes",
            "docs/references/docker-compose-llms.txt": "storage-quota reconciliation loop via supervisord",
        }
        for relative_path, phrase in expected_phrases.items():
            with self.subTest(relative_path=relative_path):
                self.assertIn(phrase, self.read_text(relative_path))

    def test_docs_planning_uses_default_branch_change_records(self) -> None:
        """Verify Docs planning uses default branch change records."""
        planning_paths = (
            "docs/PLANS.md",
            "docs/index.md",
            "docs/PRODUCT_SENSE.md",
            "docs/QUALITY_SCORE.md",
            "docs/design-docs/core-beliefs.md",
            "docs/exec-plans/tech-debt-tracker.md",
            "docs/exec-plans/completed/README.md",
        )
        stale_tokens = (
            "single PR",
            "multi-PR",
            "PR-level",
            "pull request description",
            "PR link",
            "reference it in the PR",
            "before merge",
        )
        for relative_path in planning_paths:
            text = self.read_text(relative_path)
            with self.subTest(relative_path=relative_path):
                for token in stale_tokens:
                    self.assertNotIn(token, text)

        for relative_path in (
            "docs/PLANS.md",
            "docs/index.md",
            "docs/PRODUCT_SENSE.md",
            "docs/design-docs/core-beliefs.md",
        ):
            with self.subTest(default_branch_path=relative_path):
                self.assertIn("default-branch", self.read_text(relative_path))

    def test_completed_knowledge_base_plan_is_not_active(self) -> None:
        """Verify Completed knowledge base plan is not active."""
        active_plan = (
            self.repo_root / "docs/exec-plans/active/knowledge-base-bootstrap.md"
        )
        completed_plan = (
            self.repo_root / "docs/exec-plans/completed/knowledge-base-bootstrap.md"
        )
        self.assertFalse(active_plan.exists())
        self.assertTrue(completed_plan.exists())
        self.assertIn(
            "completed docs knowledge-base bootstrap outcomes",
            self.read_text("docs/index.md"),
        )
        completed_text = completed_plan.read_text(encoding="utf-8")
        self.assertIn("Status: completed.", completed_text)
        self.assertIn("tools/lint_docs_structure.py", completed_text)

    def test_quality_docs_reflect_current_plugin_test_baseline(self) -> None:
        """Verify Quality docs reflect current plugin test baseline."""
        quality_text = self.read_text("docs/QUALITY_SCORE.md")
        tracker_text = self.read_text("docs/exec-plans/tech-debt-tracker.md")
        backlog_text = self.read_text(
            "docs/exec-plans/active/repo-improvements-and-fixes-backlog.md"
        )
        self.assertIn("broad OMP/Import regression suites", quality_text)
        self.assertIn("deployment/live integration", quality_text)
        self.assertNotIn("limited unit test coverage for OMP and Import", quality_text)
        self.assertNotIn("Add unit test coverage for OMP", tracker_text)
        self.assertNotIn("Add unit test coverage for Import", tracker_text)
        self.assertIn("OMP has 19", backlog_text)
        self.assertIn("Import has 37", backlog_text)
        self.assertIn("33,000 test-source lines", backlog_text)

    def test_generated_schema_docs_match_plugin_data_stores(self) -> None:
        """Verify Generated schema docs match plugin data stores."""
        schema_text = self.read_text("docs/generated/db-schema.md")
        self.assertIn("OMP, Import, and Tools enhanced search", schema_text)
        self.assertIn("omeroweb_tools/services/enhanced_search_store.py", schema_text)
        self.assertIn("Enhanced-search sync state", schema_text)
        self.assertNotIn("OMP and Upload", schema_text)

        for relative_path in (
            "omeroweb_omp_plugin/services/data_store.py",
            "omeroweb_import/services/data_store.py",
            "omeroweb_tools/services/enhanced_search_store.py",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertIn(
                    "CREATE TABLE IF NOT EXISTS", self.read_text(relative_path)
                )

    def test_ollama_and_ai_provider_docs_match_code_and_compose(self) -> None:
        """Verify Ollama and AI provider docs match code and compose."""
        compose_text = self.read_text("docker-compose.yml")
        provider_options = self.literal_assignment(
            "omeroweb_omp_plugin/services/ai_providers.py",
            "AI_PROVIDER_OPTIONS",
        )
        self.assertIsInstance(provider_options, list)
        provider_labels = [option["label"] for option in provider_options]
        self.assertEqual(
            ["Local", "Groq", "Gemini", "Claude", "Perplexity", "xAI", "Cohere"],
            provider_labels,
        )
        self.assertIn('image: "ollama/ollama:0.21.0"', compose_text)
        self.assertIn(
            '_OLLAMA_PORT = "11434"', self.read_text("omeroweb_omp_plugin/constants.py")
        )

        expected_provider_text = "Local/Ollama, Groq, Gemini, Claude, Perplexity, xAI"
        for relative_path in (
            "README.md",
            "docs/architecture/system-overview.md",
            "docs/deployment/configuration.md",
            "docs/plugins/omp-plugin.md",
            "docs/plugins/omp-plugin-workflow.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertIn(expected_provider_text, self.read_text(relative_path))

        expected_ollama_docs = {
            "README.md": "ollama/ollama:0.21.0",
            "docs/architecture/system-overview.md": "### Local AI inference (`ollama`)",
            "docs/reference/service-endpoints.md": "ollama:11434",
            "docs/references/docker-compose-llms.txt": "Ollama 0.21.0",
            "env/omeroweb_example.env": "OMP_OLLAMA_MODEL=qwen2.5:3b",
        }
        for relative_path, phrase in expected_ollama_docs.items():
            with self.subTest(ollama_path=relative_path):
                self.assertIn(phrase, self.read_text(relative_path))

    def test_doc_compaction_requires_objective_meaning_preservation(self) -> None:
        """Verify Doc compaction requires objective meaning preservation."""
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
        """Verify Agent instructions close proven retry loops after verification."""
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

    def test_agent_instructions_require_fresh_code_live_runtime_verification(
        self,
    ) -> None:
        """Verify Agent instructions require fresh code live runtime verification."""
        runtime_text = self.read_text("docs/reference/ai-agent-runtime-playbook.md")
        verifier_text = self.read_text(".agents/skills/omero-runtime-verifier/SKILL.md")
        verification_text = self.read_text(".agents/skills/verification-loop/SKILL.md")

        self.assertIn("fresh-code live verification before commit/push", runtime_text)
        self.assertIn("exact checkout under test", runtime_text)
        self.assertIn("not a reason to skip live verification", runtime_text)
        self.assertIn("preserve unrelated dirty work non-destructively", runtime_text)
        self.assertIn("changed mechanisms end to end", runtime_text)
        self.assertIn("rebuild/inject/restart affected containers", verifier_text)
        self.assertIn("exact checkout before testing", verifier_text)
        self.assertIn("Do not treat stale or dirty live state", verification_text)
        for adapter_path in (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
        ):
            with self.subTest(adapter_path=adapter_path):
                adapter_text = " ".join(self.read_text(adapter_path).split())
                self.assertIn("exact", adapter_text)
                self.assertIn("before commit/push", adapter_text)
                self.assertIn("dirty", adapter_text)
                self.assertIn("rebuild", adapter_text)

    def test_deepsource_repo_file_is_retired_from_agent_routing(self) -> None:
        """Verify Deepsource repo file is retired from agent routing."""
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
        self.assertIn("non-TTY agent shells", runbook_text)
        self.assertIn("short-lived `GITHUB_TOKEN`", runbook_text)
        self.assertIn("Never paste PATs into command arguments", runbook_text)
        self.assertIn("GitHub HTTPS Git operations require a PAT", runbook_text)
        self.assertIn(
            'tools/git_push_with_pat.py origin "HEAD:${default_branch}"',
            runbook_text,
        )
        self.assertIn("temp files", runbook_text)
        self.assertIn("newest supported version", runbook_text)
        self.assertIn("do not pin stale dates", runbook_text)
        self.assertNotIn('"X-GitHub-Api-Version": "2022-11-28"', runbook_text)
        self.assertNotIn("Authorization: Bearer $GITHUB_TOKEN", runbook_text)
        self.assertIn('--branch "${default_branch}"', runbook_text)
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
        """Verify CodeQL file count coverage is explained."""
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        normalized_runbook_text = " ".join(runbook_text.split())
        workflow_text = self.read_text(".github/workflows/security-code-scanning.yml")

        self.assertIn("CodeQL File-Count Coverage", runbook_text)
        py_count = self.git_file_count("*.py")
        pyi_count = self.git_file_count("*.pyi")
        total_python_count = py_count + pyi_count
        self.assertIn(
            f"{py_count} tracked `.py` implementation files "
            f"and {pyi_count} tracked `.pyi` type stubs",
            normalized_runbook_text,
        )
        self.assertIn(
            f"`{py_count}/{total_python_count}` CodeQL count",
            normalized_runbook_text,
        )
        self.assertIn("earlier `310/343` UI count", normalized_runbook_text)
        self.assertIn("8 tracked JS-family files", normalized_runbook_text)
        self.assertIn(".agents/skills/frontend-preview/agents/", runbook_text)
        self.assertIn("6 application/test JS files", runbook_text)
        self.assertIn("Audit — explain CodeQL language candidates", workflow_text)
        self.assertIn("git ls-files '*.py'", workflow_text)
        self.assertIn("git ls-files '*.pyi'", workflow_text)
        self.assertIn("git ls-files '*.js' '*.jsx' '*.mjs'", workflow_text)

    def test_python_acceleration_doc_counts_match_current_tree(self) -> None:
        """Verify Python acceleration doc counts match current tree."""
        doc_text = self.read_text("docs/design-docs/python-acceleration-options.md")
        production_paths = self.git_files(
            "*.py",
            ":!:tests/*",
            ":!:*/tests/*",
            ":!:third_party/*",
            ":!:.agents/*",
        )
        test_paths = self.git_files("tests/*.py", "*/tests/*.py")

        production_lines = sum(
            len(self.read_text(path).splitlines()) for path in production_paths
        )
        test_lines = sum(len(self.read_text(path).splitlines()) for path in test_paths)

        self.assertIn(f"Production Python files: `{len(production_paths)}`", doc_text)
        self.assertIn(f"Production Python lines: `{production_lines:,}`", doc_text)
        self.assertIn(f"Test Python files: `{len(test_paths)}`", doc_text)
        self.assertIn(f"Test Python lines: `{test_lines:,}`", doc_text)

        for relative_path in (
            "omeroweb_import/views/core_functions.py",
            "omeroweb_admin_tools/views/index_view.py",
            "omero_web_zarr/utils.py",
            "omeroweb_imaris_connector/imaris_service.py",
            "omeroweb_omp_plugin/views/index_view.py",
            "omeroweb_import/services/omero/sem_edx_parser.py",
            "omeroweb_import/services/ome_zarr_support.py",
        ):
            with self.subTest(relative_path=relative_path):
                line_count = len(self.read_text(relative_path).splitlines())
                self.assertIn(f"`{relative_path}`: `{line_count:,}` lines", doc_text)

    def test_agent_instructions_require_current_default_branch_development(
        self,
    ) -> None:
        """Verify Agent instructions require current default branch development."""
        entrypoints = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".cursor/rules/00-omero-core.mdc",
            "docs/reference/ai-agent-runtime-playbook.md",
            "docs/reference/ai-agent-integrations.md",
        )
        for path in entrypoints:
            with self.subTest(path=path):
                text = " ".join(self.read_text(path).split())
                self.assertIn("current remote default branch", text)
                self.assertIn("unless the user explicitly names another branch", text)
                self.assertRegex(
                    text,
                    r"([Dd]o not|never|must not) create feature branches, PR branches",
                )
                self.assertIn("draft PRs", text)

        agents_text = self.read_text("AGENTS.md")
        runtime_text = self.read_text("docs/reference/ai-agent-runtime-playbook.md")
        runbook_text = self.read_text("docs/operations/code-scanning.md")
        self.assertIn("never hard-code `main`", agents_text)
        self.assertIn("temporary remote branches", agents_text)
        self.assertIn(
            'tools/git_push_with_pat.py origin "HEAD:${default_branch}"',
            runtime_text,
        )
        self.assertNotIn("tools/git_push_with_pat.py origin main", runbook_text)
        self.assertNotIn("--branch main", runbook_text)
        self.assertIn(
            "current-remote-default-branch development rule",
            self.read_text("docs/reference/ai-agent-integrations.md"),
        )

    def test_markdownlint_command_is_pinned(self) -> None:
        """Verify Markdownlint command is pinned."""
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
        """Verify Missing host pytest dependencies route to workflow venv."""
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
        """Verify Explicit manual compose examples include required env files."""
        tracked_docs = [
            "README.md",
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

    def test_quickstart_missing_dot_env_exports_full_compose_contract(self) -> None:
        """Verify Quickstart missing dot env exports full compose contract."""
        quickstart = self.read_text("docs/deployment/quickstart.md")
        for env_file in (
            "installation_paths.env",
            "env/omero_secrets.env",
            "env/omeroserver.env",
            "env/omeroweb.env",
            "env/omero-celery.env",
            "env/grafana.env",
        ):
            self.assertIn(f"source {env_file}", quickstart)

    def test_onboarding_creates_required_runtime_env_files(self) -> None:
        """Verify Onboarding creates required runtime env files."""
        onboarding = self.read_text("docs/product-specs/new-user-onboarding.md")
        for template, runtime in (
            ("installation_paths_example.env", "installation_paths.env"),
            ("env/omeroserver_example.env", "env/omeroserver.env"),
            ("env/omeroweb_example.env", "env/omeroweb.env"),
            ("env/omero-celery_example.env", "env/omero-celery.env"),
            ("env/grafana_example.env", "env/grafana.env"),
            ("env/omero_secrets_example.env", "env/omero_secrets.env"),
        ):
            self.assertIn(f"cp {template} {runtime}", onboarding)

    def test_import_plugin_docs_match_current_temp_and_upload_env_contract(
        self,
    ) -> None:
        """Verify Import plugin docs match current temp and upload env contract."""
        import_doc = self.read_text("docs/plugins/import-plugin.md")
        import_core = self.read_text("omeroweb_import/views/core_functions.py")
        file_helpers = self.read_text("omeroweb_import/utils/file_helpers.py")

        self.assertIn(
            'UPLOAD_CONCURRENCY_ENV = "OMERO_WEB_UPLOAD_CONCURRENCY"',
            import_core,
        )
        self.assertIn(
            'UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"', import_core
        )
        self.assertIn('return get_plugin_tmp_dir("data")', file_helpers)
        self.assertIn('return get_plugin_tmp_dir("jobs")', file_helpers)

        self.assertIn("`OMERO_WEB_UPLOAD_CONCURRENCY`", import_doc)
        self.assertIn("`OMERO_WEB_UPLOAD_BATCH_FILES`", import_doc)
        self.assertIn("derived from `OMERO_TMP_PATH`", import_doc)
        self.assertIn("`data/.omero-cli-home`", import_doc)
        self.assertIn("not a plugin override", import_doc)
        self.assertNotIn("`UPLOAD_CONCURRENT_LIMIT`", import_doc)
        self.assertNotIn("`UPLOAD_BATCH_SIZE`", import_doc)
        self.assertNotIn("${OMERO_IMPORT_PATH}/.omero-cli-home", import_doc)

    def test_frontend_docs_cover_current_template_packages(self) -> None:
        """Verify Frontend docs cover current template packages."""
        frontend_text = self.read_text("docs/FRONTEND.md")
        self.assertIn("<plugin_package>/templates/<plugin_package>/", frontend_text)
        self.assertIn("OMERO.web Zarr", frontend_text)
        self.assertIn("image_preview.html", frontend_text)
        self.assertIn("right_plugin.preview.js.html", frontend_text)
        for relative_path in (
            "omeroweb_omp_plugin/templates/omeroweb_omp_plugin/index.html",
            "omeroweb_import/templates/omeroweb_import/index.html",
            "omeroweb_tools/templates/omeroweb_tools/enhanced_search.html",
            "omeroweb_admin_tools/templates/omeroweb_admin_tools/index.html",
            "omero_web_zarr/templates/omero_web_zarr/image_preview.html",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((self.repo_root / relative_path).exists())

    def test_service_topology_docs_match_compose_terms(self) -> None:
        """Verify Service topology docs match compose terms."""
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

    def test_service_endpoint_health_table_covers_compose_healthchecks(self) -> None:
        """Verify Service endpoint health table covers compose healthchecks."""
        endpoint_text = self.read_text("docs/reference/service-endpoints.md")
        expected_services = sorted(
            service_name
            for service_name, service_config in self.services.items()
            if "healthcheck" in service_config
        )
        self.assertNotIn("redis-sysctl-init", expected_services)
        for service_name in expected_services:
            with self.subTest(service_name=service_name):
                self.assertIn(f"`{service_name}`", endpoint_text)

    def test_monitoring_docs_match_prometheus_probe_counts(self) -> None:
        """Verify Monitoring docs match prometheus probe counts."""
        prometheus_data = yaml.safe_load(
            (self.repo_root / "monitoring/prometheus/prometheus.yml").read_text(
                encoding="utf-8"
            )
        )
        scrape_configs = prometheus_data["scrape_configs"]
        scrape_configs_by_name = {
            config["job_name"]: config for config in scrape_configs
        }
        direct_jobs = [
            config
            for config in scrape_configs
            if config["job_name"] not in {"blackbox_http", "blackbox_tcp"}
        ]
        blackbox_http = scrape_configs_by_name["blackbox_http"]
        blackbox_tcp = scrape_configs_by_name["blackbox_tcp"]
        http_targets = blackbox_http["static_configs"][0]["targets"]
        tcp_targets = blackbox_tcp["static_configs"][0]["targets"]
        self.assertEqual(10, len(direct_jobs))
        self.assertEqual(13, len(http_targets))
        self.assertEqual(5, len(tcp_targets))

        expected_phrases = {
            "README.md": "Prometheus** scrapes 10 direct metric targets",
            "ARCHITECTURE.md": "Prometheus scrapes 10 direct metric targets",
            "docs/architecture/system-overview.md": "scrapes 10 direct metric targets",
            "docs/operations/monitoring.md": "13 HTTP probe targets",
            "docs/references/docker-compose-llms.txt": "10 direct targets",
        }
        for relative_path, phrase in expected_phrases.items():
            with self.subTest(relative_path=relative_path):
                self.assertIn(phrase, self.read_text(relative_path))

    def test_plugin_help_pages_are_concise_user_help(self) -> None:
        """Verify Plugin help pages are concise user help."""
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
        """Verify Tools help is canonical HTML help."""
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
        """Verify Plugin help style guide is agent routed."""
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
