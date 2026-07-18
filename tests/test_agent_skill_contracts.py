"""Exhaustive contract and smoke tests for the repo-local agent skill surface."""

from __future__ import annotations

import re
import importlib.util
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

import yaml

from tools import agent_skill_provenance


ALLOWED_OPTIONAL_REPO_REFERENCES: frozenset[str] = frozenset(
    {"env/omero_secrets.env", "installation_paths.env"}
)
EXPECTED_SPLIT_TEST_SUITES: tuple[str, ...] = (
    "tests/",
    "omero_plugin_common/tests/",
    "omero_imaris_connector/tests/",
    "omeroweb_admin_tools/tests/",
    "omeroweb_omp_plugin/tests/",
    "omeroweb_import/tests/",
    "omeroweb_tools/tests/",
    "omero_web_zarr/tests/",
)
FORBIDDEN_GENERIC_UPSTREAM_PHRASES: tuple[str, ...] = (
    "~/.claude/",
    "Task(subagent_type",
    "resolve-library-id",
    "query-docs",
    "Context7",
    "researcher agent",
    "general-purpose",
)
KNOWN_REPO_PREFIXES: tuple[str, ...] = (
    ".agents/",
    ".github/",
    "docs/",
    "env/",
    "tests/",
    "tools/",
    "startup/",
    "monitoring/",
    "maintenance/",
    "installation/",
    "docker/",
    "omero_plugin_common/",
    "omeroweb_",
    "omero_web_zarr/",
    "third_party/",
)
KNOWN_EXACT_REPO_REFERENCES: frozenset[str] = frozenset(
    {
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "ARCHITECTURE.md",
        "LICENSE",
        "SECURITY.md",
        "docker-compose.yml",
        "installation_paths.env",
        "installation_paths_example.env",
        "supervisord.conf",
        "omero-web.config",
        "omero_imaris_connector/XTOmeroConnector.py",
    }
)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
CODE_TOKEN_RE = re.compile(r"[A-Za-z0-9_./*:-]+")


@dataclass(frozen=True)
class SmokeCheck:
    """A concrete command plus the skills it exercises in practice."""

    name: str
    command: tuple[str, ...]
    covers: frozenset[str]
    fallback_command: tuple[str, ...] | None = None


SMOKE_CHECKS: tuple[SmokeCheck, ...] = (
    SmokeCheck(
        name="docs-lint-structure",
        command=("python3", "tools/lint_docs_structure.py"),
        covers=frozenset({"docs-knowledge-maintainer", "verification-loop"}),
    ),
    SmokeCheck(
        name="skill-catalog-and-badge-contracts",
        command=(
            "python3",
            "-m",
            "unittest",
            "-v",
            "tests.test_agent_skill_catalog",
            "tests.test_caveman_skill_contract",
            "tests.test_agent_skill_provenance",
            "tests.test_readme_badges",
            "tests.test_lint_docs_structure",
        ),
        covers=frozenset(
            {
                "ai-regression-testing",
                "browser-fallback",
                "caveman",
                "cocoindex-code-search",
                "compliance-and-rate-limit",
                "context-budget",
                "documentation-lookup",
                "docs-knowledge-maintainer",
                "frontend-preview",
                "site-extract",
                "source-audit",
                "search-first",
                "tdd-workflow",
                "verification-loop",
                "web-discovery",
            }
        ),
    ),
    SmokeCheck(
        name="repository-documentation-regressions",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "tests/test_repository_documentation_regressions.py",
        ),
        covers=frozenset(
            {
                "deployment-patterns",
                "docs-knowledge-maintainer",
                "documentation-lookup",
                "env-contract-reviewer",
                "search-first",
            }
        ),
    ),
    SmokeCheck(
        name="workflow-and-compose-contracts",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "tests/test_build_workflow_integration_contract.py",
            "tests/test_docker_healthcheck_contracts.py",
            "tests/test_ruff_integration_contract.py",
            "tests/test_vulture_integration_contract.py",
        ),
        covers=frozenset(
            {
                "deployment-patterns",
                "docker-patterns",
                "env-contract-reviewer",
                "postgres-patterns",
                "security-review",
                "verification-loop",
            }
        ),
    ),
    SmokeCheck(
        name="security-contracts",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "tests/test_security_delta_guard.py",
            "tests/test_security_hardening_contracts.py",
            "tests/test_admin_tools_security_regressions.py",
        ),
        covers=frozenset(
            {
                "django-security",
                "omero-runtime-verifier",
                "security-finding-triager",
                "security-review",
            }
        ),
    ),
    SmokeCheck(
        name="shared-python-contracts",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "omero_plugin_common/tests/test_env_utils_additional.py",
            "omero_plugin_common/tests/test_helper_modules.py",
            "omero_plugin_common/tests/test_logging_utils.py",
        ),
        covers=frozenset(
            {
                "ai-regression-testing",
                "env-contract-reviewer",
                "python-patterns",
                "python-testing",
            }
        ),
    ),
    SmokeCheck(
        name="process-helper-boundary-contracts",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "omero_plugin_common/tests/test_process_utils.py",
        ),
        covers=frozenset(
            {
                "ai-regression-testing",
                "python-patterns",
                "python-testing",
                "verification-loop",
            }
        ),
    ),
    SmokeCheck(
        name="installation-env-parser-regressions",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "tests/test_installation_env_parsing_regressions.py",
        ),
        covers=frozenset(
            {
                "deployment-patterns",
                "env-contract-reviewer",
                "security-review",
                "verification-loop",
            }
        ),
    ),
    SmokeCheck(
        name="plugin-suite-contracts",
        command=(
            "python3",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-W",
            "error",
            "omeroweb_import/tests/test_cli_runtime_env.py",
            "omeroweb_import/tests/test_security_hardening.py",
            "omeroweb_tools/tests/test_tools_module_contracts.py",
            "omeroweb_omp_plugin/tests/test_log_sanitization.py",
            "omeroweb_admin_tools/tests/test_log_query.py",
            "omero_imaris_connector/tests/test_security_regressions.py",
        ),
        covers=frozenset(
            {
                "ai-regression-testing",
                "django-patterns",
                "django-security",
                "django-verification",
                "omero-runtime-verifier",
                "plugin-regression-triager",
            }
        ),
        fallback_command=(
            "python3",
            "tools/run_agent_skill_smoke.py",
            "plugin-suite-fallback",
        ),
    ),
)


class AgentSkillContractTests(unittest.TestCase):
    """Test cases for agent skill contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `AgentSkillContractTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.skill_dirs = {
            path.name: path
            for path in sorted((cls.repo_root / ".agents" / "skills").iterdir())
            if path.is_dir()
        }
        cls.skill_texts = {
            name: (path / "SKILL.md").read_text(encoding="utf-8")
            for name, path in cls.skill_dirs.items()
        }
        cls.adapter_texts = {
            name: (path / "agents" / "openai.yaml").read_text(encoding="utf-8")
            for name, path in cls.skill_dirs.items()
        }
        cls.frontmatters = {
            name: cls.parse_frontmatter(text) for name, text in cls.skill_texts.items()
        }
        cls.upstream_sources = agent_skill_provenance.load_upstream_sources(
            cls.repo_root
        )
        cls._command_cache: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}

    COMPACT_SKILL_LINE_BUDGETS: dict[str, int] = {
        "ai-regression-testing": 24,
        "caveman": 24,
        "context-budget": 32,
        "env-contract-reviewer": 44,
        "plugin-regression-triager": 41,
        "search-first": 41,
        "security-review": 24,
        "verification-loop": 82,
    }

    @staticmethod
    def parse_frontmatter(skill_text: str) -> dict[str, object]:
        """Parse and validate the frontmatter input.

        Inputs: `skill_text` (str). Output: `dict[str, object]`. Raises: AssertionError
        when validation or the called operation fails.
        """
        if not skill_text.startswith("---\n"):
            raise AssertionError("Skill file is missing frontmatter")
        _, frontmatter_text, _ = skill_text.split("---\n", 2)
        parsed = yaml.safe_load(frontmatter_text)
        if not isinstance(parsed, dict):
            raise AssertionError("Skill frontmatter must parse to a mapping")
        return parsed

    @staticmethod
    def _normalize_repo_reference(token: str) -> str:
        """Normalize the repo reference for `AgentSkillContractTests`.

        Inputs: `token` (str). Output: `str`.
        """
        normalized = token.strip().strip("'\"").rstrip(".,:;)")
        if normalized.endswith("/"):
            return normalized
        return normalized

    @classmethod
    def extract_repo_references(cls, text: str) -> set[str]:
        """Return extract repo references.

        Inputs: `text`. Output: `set[str]`.
        """
        references: set[str] = set()
        for span in INLINE_CODE_RE.findall(text):
            if "://" in span:
                continue
            for token in CODE_TOKEN_RE.findall(span):
                normalized = cls._normalize_repo_reference(token)
                if not normalized or normalized.startswith("/"):
                    continue
                if normalized in {"omeroweb_", "omeroweb_*"}:
                    continue
                if normalized in KNOWN_EXACT_REPO_REFERENCES or normalized.startswith(
                    KNOWN_REPO_PREFIXES
                ):
                    references.add(normalized)
        return references

    @classmethod
    def assert_repo_reference_exists(cls, reference: str) -> None:
        """Assert the repo reference exists for `AgentSkillContractTests`.

        Inputs: `reference` (str). Output: None. Raises: AssertionError when validation or the called operation fails.
        """
        if reference in ALLOWED_OPTIONAL_REPO_REFERENCES:
            return
        if "*" in reference:
            matches = list(cls.repo_root.glob(reference))
            if matches:
                return
            raise AssertionError(f"Glob reference does not match anything: {reference}")
        if (cls.repo_root / reference).exists():
            return
        raise AssertionError(f"Repository reference does not exist: {reference}")

    @classmethod
    def run_smoke_command(
        cls, smoke_check: SmokeCheck
    ) -> subprocess.CompletedProcess[str]:
        """One configured skill smoke command.

        Inputs: `smoke_check`. Output: `subprocess.CompletedProcess[str]`.
        """
        command = smoke_check.command
        if (
            smoke_check.fallback_command is not None
            and not cls._host_python_has_plugin_runtime()
        ):
            command = smoke_check.fallback_command
        resolved_command = cls._resolve_smoke_command(command)
        cached = cls._command_cache.get(resolved_command)
        if cached is not None:
            return cached
        completed = subprocess.run(
            resolved_command,
            cwd=cls.repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=600,
        )
        cls._command_cache[resolved_command] = completed
        return completed

    @staticmethod
    def _resolve_smoke_command(command: tuple[str, ...]) -> tuple[str, ...]:
        """Resolve the smoke command for `AgentSkillContractTests`.

        Inputs: `command` (tuple[str, ...]). Output: `tuple[str, ...]`.
        """
        if not command or command[0] != "python3":
            return command
        return (sys.executable, *command[1:])

    @staticmethod
    def _host_python_has_plugin_runtime() -> bool:
        """Return the host python has plugin runtime for `AgentSkillContractTests`.

        Inputs: none. Output: `bool`.
        """
        for module_name in ("django", "omeroweb"):
            try:
                if importlib.util.find_spec(module_name) is None:
                    return False
            except (ImportError, ValueError):
                return False
        return True

    def test_upstream_sources_doc_matches_adapted_skill_frontmatter(self) -> None:
        """Verify upstream sources doc matches adapted skill frontmatter.

        Inputs: repository fixtures. Output: fails on regressions in upstream sources doc matches adapted skill frontmatter.
        """
        adapted_skill_names = {
            name
            for name, frontmatter in self.frontmatters.items()
            if "upstream" in frontmatter
        }
        self.assertEqual(
            set(self.upstream_sources.skill_vendor_paths),
            adapted_skill_names,
        )
        for skill_name in sorted(adapted_skill_names):
            with self.subTest(skill_name=skill_name):
                self.assertEqual(
                    self.upstream_sources.skill_vendor_paths[skill_name],
                    self.frontmatters[skill_name]["upstream"],
                )

    def test_adapted_overlays_are_smaller_than_vendored_upstream_sources(self) -> None:
        """Verify adapted overlays are smaller than vendored upstream sources.

        Inputs: repository fixtures. Output: fails on regressions in adapted overlays are smaller than vendored upstream sources.
        """
        for skill_name, frontmatter in self.frontmatters.items():
            upstream_path = frontmatter.get("upstream")
            if not isinstance(upstream_path, str):
                continue
            with self.subTest(skill_name=skill_name):
                local_lines = [
                    line
                    for line in self.skill_texts[skill_name].splitlines()
                    if line.strip()
                ]
                upstream_lines = [
                    line
                    for line in (self.repo_root / upstream_path)
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line.strip()
                ]
                self.assertLess(
                    len(local_lines),
                    len(upstream_lines),
                    f"{skill_name} overlay should be slimmer than its vendored upstream baseline",
                )

    def test_high_frequency_skills_stay_compact(self) -> None:
        """Verify high frequency skills stay compact.

        Inputs: repository fixtures. Output: fails on regressions in high frequency skills stay compact.
        """
        for skill_name, max_nonempty_lines in self.COMPACT_SKILL_LINE_BUDGETS.items():
            with self.subTest(skill_name=skill_name):
                local_lines = [
                    line
                    for line in self.skill_texts[skill_name].splitlines()
                    if line.strip()
                ]
                self.assertLessEqual(
                    len(local_lines),
                    max_nonempty_lines,
                    f"{skill_name} should stay compact to control context cost",
                )

    def test_active_skills_do_not_retain_generic_upstream_harness_instructions(
        self,
    ) -> None:
        """Verify active skills do not retain generic upstream harness instructions.

        Inputs: repository fixtures. Output: fails on regressions in active skills do not retain generic upstream harness instructions.
        """
        for skill_name, skill_text in self.skill_texts.items():
            with self.subTest(skill_name=skill_name):
                combined_text = f"{skill_text}\n{self.adapter_texts[skill_name]}"
                for phrase in FORBIDDEN_GENERIC_UPSTREAM_PHRASES:
                    self.assertNotIn(
                        phrase,
                        combined_text,
                        f"{skill_name} still contains upstream-only generic harness text: {phrase}",
                    )

    def test_tdd_workflow_disables_implicit_checkpoint_commits(self) -> None:
        """Verify TDD workflow disables upstream checkpoint commits by default.

        Inputs: repository fixtures. Output: fails on regressions in the TDD Git boundary.
        """
        skill_text = self.skill_texts["tdd-workflow"]
        adapter_text = self.adapter_texts["tdd-workflow"]

        self.assertIn("checkpoint-commit guidance is disabled", skill_text)
        self.assertIn("unless", skill_text)
        self.assertIn("explicitly asks for Git staging", skill_text)
        self.assertIn("TDD checkpoints should be recorded in notes", skill_text)
        self.assertIn("allow_implicit_invocation: true", adapter_text)

    def test_agent_surfaces_use_only_valid_repo_references(self) -> None:
        """Verify agent surfaces use only valid repo references.

        Inputs: repository fixtures. Output: fails on regressions in agent surfaces use only valid repo references.
        """
        surfaces = {
            "AGENTS.md": (self.repo_root / "AGENTS.md").read_text(encoding="utf-8"),
            "docs/reference/ai-agent-skills.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-skills.md"
            ).read_text(encoding="utf-8"),
            "docs/reference/ai-agent-integrations.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-integrations.md"
            ).read_text(encoding="utf-8"),
            "docs/reference/ai-agent-upstream-sources.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-upstream-sources.md"
            ).read_text(encoding="utf-8"),
            **{
                f".agents/skills/{name}/SKILL.md": text
                for name, text in self.skill_texts.items()
            },
        }

        for surface_name, surface_text in surfaces.items():
            with self.subTest(surface=surface_name):
                references = self.extract_repo_references(surface_text)
                self.assertTrue(
                    references,
                    f"{surface_name} should expose at least one repository reference",
                )
                for reference in sorted(references):
                    self.assert_repo_reference_exists(reference)

    def test_claude_hooks_use_portable_repo_local_commands(self) -> None:
        """Verify claude hooks use portable repo local commands.

        Inputs: repository fixtures. Output: fails on regressions in claude hooks use portable repo local commands.
        """
        settings_text = (self.repo_root / ".claude" / "settings.json").read_text(
            encoding="utf-8"
        )
        pinned_markdownlint = "npx --yes markdownlint-cli2@0.23.1"
        self.assertNotIn("/home/itservice/.local/bin/ruff", settings_text)
        self.assertNotIn("/opt/omero/tools/env_safety_guard.py", settings_text)
        self.assertNotIn("npx markdownlint-cli2", settings_text)
        self.assertIn("command -v ruff", settings_text)
        self.assertIn("ruff check --fix --quiet", settings_text)
        self.assertIn("ruff format --quiet", settings_text)
        self.assertIn("python3 -m ruff --version", settings_text)
        self.assertIn(pinned_markdownlint, settings_text)
        self.assertIn("git rev-parse --show-toplevel", settings_text)
        self.assertIn("tools/env_safety_guard.py", settings_text)

    def test_root_test_stubs_support_importlib_discovery(self) -> None:
        """Verify root test stubs support importlib discovery.

        Inputs: repository fixtures. Output: fails on regressions in root test stubs support importlib discovery.
        """
        for module_name in (
            "celery",
            "celery.states",
            "omero",
            "omero.gateway",
            "omeroweb",
            "omeroweb.webclient",
            "omeroweb.webgateway.views",
        ):
            with self.subTest(module=module_name):
                try:
                    spec = importlib.util.find_spec(module_name)
                except ValueError as exc:
                    self.fail(
                        f"{module_name} test stub has invalid import metadata: {exc}"
                    )
                self.assertIsNotNone(spec)
                self.assertEqual(module_name, spec.name)

    def test_agent_split_test_surfaces_cover_every_repo_suite(self) -> None:
        """Verify agent split test surfaces cover every repo suite.

        Inputs: repository fixtures. Output: fails on regressions in agent split test surfaces cover every repo suite.
        """
        discovered = {"tests/"}
        discovered.update(
            f"{path.relative_to(self.repo_root).as_posix()}/"
            for path in self.repo_root.glob("*/tests")
            if path.is_dir()
        )
        self.assertEqual(set(EXPECTED_SPLIT_TEST_SUITES), discovered)

        surfaces = {
            "AGENTS.md": (self.repo_root / "AGENTS.md").read_text(encoding="utf-8"),
            "CLAUDE.md": (self.repo_root / "CLAUDE.md").read_text(encoding="utf-8"),
            "docs/reference/ai-agent-context-routing.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-context-routing.md"
            ).read_text(encoding="utf-8"),
            "docs/reference/ai-agent-runtime-playbook.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-runtime-playbook.md"
            ).read_text(encoding="utf-8"),
            ".agents/skills/plugin-regression-triager/SKILL.md": self.skill_texts[
                "plugin-regression-triager"
            ],
            ".agents/skills/verification-loop/SKILL.md": self.skill_texts[
                "verification-loop"
            ],
        }
        for surface_name, surface_text in surfaces.items():
            with self.subTest(surface=surface_name):
                for suite in EXPECTED_SPLIT_TEST_SUITES:
                    self.assertIn(suite, surface_text)

    def test_agent_surfaces_enforce_release_and_deletion_governance(self) -> None:
        """Verify every agent surface carries public-release safety policy.

        Inputs: agent and workflow instruction fixtures. Output: no policy drift.
        """
        relative_paths = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".github/copilot-instructions.md",
            ".github/instructions/workflows.instructions.md",
            ".cursor/rules/00-omero-core.mdc",
            ".cursor/rules/30-workflows-security.mdc",
            ".agents/skills/deployment-patterns/SKILL.md",
            ".agents/skills/docker-patterns/SKILL.md",
            "docs/reference/ai-agent-runtime-playbook.md",
        )
        required_tokens = (
            "CHANGELOG.md",
            "automated disclosure",
            "human public-safety review",
            "credentials",
            "private infrastructure",
            "vulnerability mechanics",
            "exploit-enabling detail",
        )
        for relative_path in relative_paths:
            text = (self.repo_root / relative_path).read_text(encoding="utf-8")
            normalized_text = " ".join(text.lower().split())
            with self.subTest(relative_path=relative_path):
                for token in required_tokens:
                    self.assertIn(token.lower(), normalized_text)
                self.assertIn("exact", normalized_text)
                self.assertRegex(normalized_text, r"(?:pause|explicit)")
                self.assertRegex(normalized_text, r"(?:never infer|auto-increment)")
                self.assertIn("delet", normalized_text)
                self.assertIn("fresh", normalized_text)
                self.assertRegex(normalized_text, r"carr(?:y|ies) forward")

    def test_agent_surfaces_avoid_host_specific_clone_paths(self) -> None:
        """Verify agent surfaces avoid host specific clone paths.

        Inputs: repository fixtures. Output: fails on regressions in agent surfaces avoid host specific clone paths.
        """
        surfaces = {
            ".claude/settings.json": (
                self.repo_root / ".claude" / "settings.json"
            ).read_text(encoding="utf-8"),
            "CLAUDE.md": (self.repo_root / "CLAUDE.md").read_text(encoding="utf-8"),
            "GEMINI.md": (self.repo_root / "GEMINI.md").read_text(encoding="utf-8"),
            "docs/reference/ai-agent-integrations.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-integrations.md"
            ).read_text(encoding="utf-8"),
            "docs/reference/ai-agent-skills.md": (
                self.repo_root / "docs" / "reference" / "ai-agent-skills.md"
            ).read_text(encoding="utf-8"),
            ".github/copilot-instructions.md": (
                self.repo_root / ".github" / "copilot-instructions.md"
            ).read_text(encoding="utf-8"),
            **{
                str(path.relative_to(self.repo_root)): path.read_text(encoding="utf-8")
                for path in sorted(
                    (self.repo_root / ".github" / "instructions").glob(
                        "*.instructions.md"
                    )
                )
            },
            **{
                str(path.relative_to(self.repo_root)): path.read_text(encoding="utf-8")
                for path in sorted((self.repo_root / ".cursor" / "rules").glob("*.mdc"))
            },
            **{
                f".agents/skills/{name}/SKILL.md": text
                for name, text in self.skill_texts.items()
            },
            **{
                f".agents/skills/{name}/agents/openai.yaml": text
                for name, text in self.adapter_texts.items()
            },
        }
        for surface_name, surface_text in surfaces.items():
            with self.subTest(surface=surface_name):
                self.assertNotIn("/opt/omero/", surface_text)
                self.assertNotIn("/home/itservice/", surface_text)

    def test_smoke_command_coverage_spans_every_skill(self) -> None:
        """Verify the smoke command coverage spans every skill execution contract.

        Inputs: repository fixtures. Output: fails on regressions in smoke command coverage spans every skill integration.
        """
        expected_skills = set(self.skill_dirs)
        covered_skills: set[str] = set()
        for smoke_check in SMOKE_CHECKS:
            covered_skills.update(smoke_check.covers)
        self.assertEqual(expected_skills, covered_skills)

    def test_smoke_commands_pass(self) -> None:
        """Verify smoke commands pass.

        Inputs: repository fixtures. Output: fails on regressions in smoke commands pass.
        """
        for smoke_check in SMOKE_CHECKS:
            with self.subTest(
                smoke_check=smoke_check.name,
                covers=sorted(smoke_check.covers),
            ):
                completed = self.run_smoke_command(smoke_check)
                self.assertEqual(
                    0,
                    completed.returncode,
                    "\n".join(
                        [
                            f"Smoke check failed: {smoke_check.name}",
                            f"Command: {' '.join(smoke_check.command)}",
                            f"Covers: {', '.join(sorted(smoke_check.covers))}",
                            "",
                            "STDOUT:",
                            completed.stdout,
                            "",
                            "STDERR:",
                            completed.stderr,
                        ]
                    ),
                )


if __name__ == "__main__":
    unittest.main()
