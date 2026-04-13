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
        "github_pull_project_bash_example",
        "supervisord.conf",
        "omero-web.config",
        "XTOmeroConnector.py",
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
            "omeroweb_omp_plugin/tests/test_log_sanitization.py",
            "omeroweb_admin_tools/tests/test_log_query.py",
            "omeroweb_imaris_connector/tests/test_security_regressions.py",
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
    @classmethod
    def setUpClass(cls) -> None:
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
        if not skill_text.startswith("---\n"):
            raise AssertionError("Skill file is missing frontmatter")
        _, frontmatter_text, _ = skill_text.split("---\n", 2)
        parsed = yaml.safe_load(frontmatter_text)
        if not isinstance(parsed, dict):
            raise AssertionError("Skill frontmatter must parse to a mapping")
        return parsed

    @staticmethod
    def _normalize_repo_reference(token: str) -> str:
        normalized = token.strip().strip("'\"").rstrip(".,:;)")
        if normalized.endswith("/"):
            return normalized
        return normalized

    @classmethod
    def extract_repo_references(cls, text: str) -> set[str]:
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
        command = smoke_check.command
        if (
            smoke_check.fallback_command is not None
            and not cls._host_python_has_django()
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
            text=True,
            timeout=600,
        )
        cls._command_cache[resolved_command] = completed
        return completed

    @staticmethod
    def _resolve_smoke_command(command: tuple[str, ...]) -> tuple[str, ...]:
        if not command or command[0] != "python3":
            return command
        return (sys.executable, *command[1:])

    @staticmethod
    def _host_python_has_django() -> bool:
        return importlib.util.find_spec("django") is not None

    def test_upstream_sources_doc_matches_adapted_skill_frontmatter(self) -> None:
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
        for skill_name, skill_text in self.skill_texts.items():
            with self.subTest(skill_name=skill_name):
                combined_text = f"{skill_text}\n{self.adapter_texts[skill_name]}"
                for phrase in FORBIDDEN_GENERIC_UPSTREAM_PHRASES:
                    self.assertNotIn(
                        phrase,
                        combined_text,
                        f"{skill_name} still contains upstream-only generic harness text: {phrase}",
                    )

    def test_agent_surfaces_use_only_valid_repo_references(self) -> None:
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
        settings_text = (self.repo_root / ".claude" / "settings.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("/home/itservice/.local/bin/ruff", settings_text)
        self.assertNotIn("/opt/omero/tools/env_safety_guard.py", settings_text)
        self.assertIn("python3 -m ruff check --fix --quiet", settings_text)
        self.assertIn("python3 -m ruff format --quiet", settings_text)
        self.assertIn("git rev-parse --show-toplevel", settings_text)
        self.assertIn("tools/env_safety_guard.py", settings_text)

    def test_agent_surfaces_avoid_host_specific_clone_paths(self) -> None:
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
        expected_skills = set(self.skill_dirs)
        covered_skills: set[str] = set()
        for smoke_check in SMOKE_CHECKS:
            covered_skills.update(smoke_check.covers)
        self.assertEqual(expected_skills, covered_skills)

    def test_smoke_commands_pass(self) -> None:
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
