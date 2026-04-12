"""Comprehensive regression checks for the repo-local agent skill surface."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import yaml


ALL_SKILLS: tuple[str, ...] = (
    "ai-regression-testing",
    "browser-fallback",
    "caveman",
    "compliance-and-rate-limit",
    "context-budget",
    "deployment-patterns",
    "django-patterns",
    "django-security",
    "django-verification",
    "docker-patterns",
    "docs-knowledge-maintainer",
    "documentation-lookup",
    "env-contract-reviewer",
    "frontend-preview",
    "omero-runtime-verifier",
    "plugin-regression-triager",
    "postgres-patterns",
    "python-patterns",
    "python-testing",
    "search-first",
    "security-finding-triager",
    "security-review",
    "site-extract",
    "source-audit",
    "tdd-workflow",
    "verification-loop",
    "web-discovery",
)

REPO_NATIVE_SKILLS: frozenset[str] = frozenset(
    {
        "browser-fallback",
        "caveman",
        "compliance-and-rate-limit",
        "docs-knowledge-maintainer",
        "env-contract-reviewer",
        "frontend-preview",
        "omero-runtime-verifier",
        "plugin-regression-triager",
        "site-extract",
        "source-audit",
        "security-finding-triager",
        "web-discovery",
    }
)

Concept = Union[str, tuple[str, ...]]


@dataclass(frozen=True)
class SkillScenario:
    """A realistic usage scenario plus the repo-specific cues it must expose."""

    scenario: str
    skill_phrases: tuple[Concept, ...]
    adapter_phrases: tuple[Concept, ...]


SKILL_SCENARIOS: dict[str, SkillScenario] = {
    "ai-regression-testing": SkillScenario(
        scenario=(
            "An AI-generated fix touched a startup script and a helper, and the "
            "reviewer wants narrow regression tests that catch partial fixes and "
            "path mismatches."
        ),
        skill_phrases=(
            "narrow contract tests",
            "split pytest lanes",
            "sandbox-path checks",
            ("path mismatches", "host-vs-container", "request-vs-service-account"),
        ),
        adapter_phrases=("regression", "fix"),
    ),
    "browser-fallback": SkillScenario(
        scenario=(
            "A release-note check depends on a JS-heavy docs page, so the agent "
            "needs a deterministic browser session only after direct fetch and "
            "bounded extraction fail."
        ),
        skill_phrases=(
            "direct fetch",
            "js-heavy",
            "stateful",
            "deterministic",
            "minimum reproducible navigation steps",
        ),
        adapter_phrases=("browser", "js-heavy"),
    ),
    "caveman": SkillScenario(
        scenario=(
            "A maintainer explicitly asks for lower-token replies but still needs "
            "the repo's safety rules, exact file references, and clear escalation "
            "back to normal detail when a risky step appears."
        ),
        skill_phrases=(
            "lower token usage",
            "user explicitly asks",
            "context-budget",
            "compression never outranks correctness",
            ("drop compression", "return to normal detail"),
            "destructive actions",
        ),
        adapter_phrases=("tokens", "terse"),
    ),
    "compliance-and-rate-limit": SkillScenario(
        scenario=(
            "A repeated multi-page docs check is starting to hit policy and load "
            "limits, so the agent must keep the collection cache-aware, paced, "
            "and non-evasive."
        ),
        skill_phrases=(
            "official APIs, feeds, sitemaps",
            "cache",
            "exponential backoff",
            ("no bypass", "no evasion"),
            "stop escalating",
        ),
        adapter_phrases=("cache-aware", "paced"),
    ),
    "context-budget": SkillScenario(
        scenario=(
            "A debugging session is getting too broad, too slow, and too token "
            "heavy, so the agent needs the smallest correct file and test set."
        ),
        skill_phrases=(
            "lower token usage",
            (
                "smallest correct context",
                "keep agent context small",
                "small and high-signal",
            ),
            ("search the narrow file set", "find the narrow file set"),
            "summarize long docs once",
            "open at most 4 task-specific files in the first pass",
            "run at most 2 refine loops",
        ),
        adapter_phrases=("context", "smallest correct"),
    ),
    "deployment-patterns": SkillScenario(
        scenario=(
            "An installation or update flow for the Dockerized OMERO platform is "
            "changing, and rollout safety plus env contracts must be preserved."
        ),
        skill_phrases=(
            "installation, update, rollout",
            "docker compose platform",
            "update safety",
            "deployment docs",
        ),
        adapter_phrases=("deployment", "update guidance"),
    ),
    "django-patterns": SkillScenario(
        scenario=(
            "A maintainer is refactoring an OMERO.web plugin view and template and "
            "needs to stay inside the repo's Django app boundaries."
        ),
        skill_phrases=(
            "omero.web plugin views",
            "each `omeroweb_*` plugin stays isolated",
            "views, services, templates, routing",
            "apps.py",
        ),
        adapter_phrases=("django", "plugin architecture"),
    ),
    "django-security": SkillScenario(
        scenario=(
            "A Django upload endpoint is being hardened and it must stop leaking "
            "internal exceptions while preserving OMERO permission boundaries."
        ),
        skill_phrases=(
            "do not leak raw exceptions",
            "uploads",
            "preserve omero permission checks",
            "json responses",
        ),
        adapter_phrases=("security", "permission boundaries"),
    ),
    "django-verification": SkillScenario(
        scenario=(
            "A change to an OMERO.web plugin needs the correct verification path, "
            "including split pytest and the documented fallback when Django is "
            "unavailable locally."
        ),
        skill_phrases=(
            "use this skill after django or omero.web changes",
            "split pytest",
            "fallback procedure",
            "plugin suite",
        ),
        adapter_phrases=("verify", "django"),
    ),
    "docker-patterns": SkillScenario(
        scenario=(
            "A Dockerfile and Compose change must preserve pinned images, health "
            "checks, and the repo's startup-script runtime contracts."
        ),
        skill_phrases=(
            "dockerfiles, `docker-compose.yml`, startup scripts",
            "do not introduce `:latest`",
            "security_opt: no-new-privileges:true",
            "runtime contracts",
        ),
        adapter_phrases=("docker", "compose"),
    ),
    "docs-knowledge-maintainer": SkillScenario(
        scenario=(
            "A behavior change affects topology and troubleshooting, so the right "
            "deep docs, index entries, and drift checks must all move together."
        ),
        skill_phrases=(
            "service topology or compose changes",
            "update `docs/index.md`",
            "root docs contradicting deep docs",
            "required verification",
        ),
        adapter_phrases=("docs", "drift checks"),
    ),
    "documentation-lookup": SkillScenario(
        scenario=(
            "A workflow or runtime question depends on current upstream behavior, "
            "so the answer must come from official docs and release notes instead "
            "of memory."
        ),
        skill_phrases=(
            "current official documentation",
            "official upstream docs",
            "exact versions or dates",
            "github actions version pinning",
        ),
        adapter_phrases=("current", "docs"),
    ),
    "site-extract": SkillScenario(
        scenario=(
            "A specific public status or release page is already known, and the "
            "agent only needs the smallest set of fields and dates from it."
        ),
        skill_phrases=(
            "known public page",
            "structured fields",
            "page title",
            "publish/update date",
            "browser-fallback",
        ),
        adapter_phrases=("extract", "public page"),
    ),
    "source-audit": SkillScenario(
        scenario=(
            "A recommendation about public-web evidence needs source weighting, "
            "dates, and a clean separation between confirmed facts and "
            "inference."
        ),
        skill_phrases=(
            "source type",
            "canonical URL",
            "independent second source",
            "confirmed facts",
            "unresolved uncertainty",
        ),
        adapter_phrases=("source quality", "inference"),
    ),
    "env-contract-reviewer": SkillScenario(
        scenario=(
            "A new environment variable is being added to startup logic and must be "
            "template-backed, typed, documented, and free of hard-coded defaults."
        ),
        skill_phrases=(
            "all configuration is environment-driven",
            "never hard-code paths",
            "env/*_example.env",
            "docs/deployment/configuration.md",
        ),
        adapter_phrases=("env", "config"),
    ),
    "frontend-preview": SkillScenario(
        scenario=(
            "An AI agent needs to visually validate HTML, CSS, or JavaScript changes "
            "in plugin templates without rebuilding the Docker container."
        ),
        skill_phrases=(
            "vite",
            "PLUGIN_ROOT",
            "django-template-strip",
        ),
        adapter_phrases=("preview", "vite"),
    ),
    "omero-runtime-verifier": SkillScenario(
        scenario=(
            "A live OMERO runtime issue needs Loki-first triage, container-local "
            "virtualenv discovery, and OMERO CLI usage through the service account."
        ),
        skill_phrases=(
            "loki/admin tools path first",
            "resolve the active runtime virtualenv",
            "use the service account",
            "never run omero cli as `root`",
        ),
        adapter_phrases=("runtime", "verify"),
    ),
    "plugin-regression-triager": SkillScenario(
        scenario=(
            "A change touched `omeroweb_import/` and root helper files, and the "
            "agent needs the narrowest correct split pytest lanes instead of one "
            "large combined run."
        ),
        skill_phrases=(
            "path-to-suite mapping",
            "narrowest correct verification set",
            "running one giant `pytest` command across all suites",
            "tests/ plus the affected plugin suite",
        ),
        adapter_phrases=("split pytest", "changed paths"),
    ),
    "postgres-patterns": SkillScenario(
        scenario=(
            "A database helper is changing and must respect the OMERO database, the "
            "plugin database, and maintenance behavior such as VACUUM or REINDEX."
        ),
        skill_phrases=(
            "two postgresql services",
            "keep sql parameterized",
            "vacuum",
            "reindex",
        ),
        adapter_phrases=("postgresql", "database"),
    ),
    "python-patterns": SkillScenario(
        scenario=(
            "A shared Python helper is being refactored and should stay aligned "
            "with `omero_plugin_common`, typed env loading, and the Ruff baseline."
        ),
        skill_phrases=(
            "`omero_plugin_common`",
            "environment-driven",
            "avoid installation-specific absolute paths",
            "ruff",
        ),
        adapter_phrases=("python", "helper"),
    ),
    "python-testing": SkillScenario(
        scenario=(
            "A Python fix needs the right regression approach, using split pytest "
            "when available and `py_compile` or `bash -n` only as explicit "
            "fallbacks."
        ),
        skill_phrases=(
            "split-pytest rule",
            "`python3 -m py_compile`",
            "`bash -n`",
            "never weaken tests",
        ),
        adapter_phrases=("testing", "split pytest"),
    ),
    "search-first": SkillScenario(
        scenario=(
            "Before adding a new integration or helper, the agent must search the "
            "repo, tests, and official upstream docs to decide whether to adopt, "
            "extend, or build custom logic."
        ),
        skill_phrases=(
            "search this repository first with `rg`",
            "official upstream docs and release notes",
            "adopt",
            "build custom",
        ),
        adapter_phrases=("research", "before writing"),
    ),
    "security-finding-triager": SkillScenario(
        scenario=(
            "A live code-scanning alert needs triage against the prevention "
            "playbook, historical resolved findings, and the live GitHub alert "
            "inventory before any code is changed."
        ),
        skill_phrases=(
            "mandatory read order",
            "refresh the live alert inventory from github",
            "fix the root cause",
            "do not guess that an alert is closed",
        ),
        adapter_phrases=("security finding", "triage"),
    ),
    "security-review": SkillScenario(
        scenario=(
            "A sensitive change involving uploads, SQL, and workflow behavior needs "
            "a security review before implementation, not a scanner-specific triage."
        ),
        skill_phrases=(
            "uploads, filesystem paths, sql, responses, subprocesses, docker, workflows, and secrets",
            "root-cause fixes",
            "name the regression tests",
            "refresh action pins",
        ),
        adapter_phrases=("security review", "sensitive"),
    ),
    "tdd-workflow": SkillScenario(
        scenario=(
            "A bug fix should land red-green-refactor style, with narrow tests and "
            "docs updates treated as part of done-ness."
        ),
        skill_phrases=(
            "tests first or tests alongside the fix",
            "relevant split pytest lane",
            "docs validation in the same change",
            "not treat a change as done",
        ),
        adapter_phrases=("tdd", ("tests", "test")),
    ),
    "verification-loop": SkillScenario(
        scenario=(
            "Before proposing a PR, the agent must report exactly what was checked: "
            "docs validation, Ruff, split pytest, fallback syntax checks, and any "
            "blocked coverage."
        ),
        skill_phrases=(
            "documentation structure",
            "python lint and formatting",
            "split pytest execution",
            "required reporting",
        ),
        adapter_phrases=("verify", "split-test"),
    ),
    "web-discovery": SkillScenario(
        scenario=(
            "A version-sensitive integration question needs current official docs, "
            "release notes, issue trackers, and broader community evidence "
            "without guessing."
        ),
        skill_phrases=(
            "current public-web research",
            "official docs, release notes, source repositories, standards pages, and issue trackers",
            "exact product names, versions, dates",
            "source-audit",
        ),
        adapter_phrases=("current", "public-web"),
    ),
}


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
        cls.skill_dirs = {
            path.name: path
            for path in sorted((cls.repo_root / ".agents" / "skills").iterdir())
            if path.is_dir()
        }

    def parse_frontmatter(self, skill_markdown: str) -> dict[str, object]:
        self.assertTrue(
            skill_markdown.startswith("---\n"), "Skill file is missing frontmatter"
        )
        _, frontmatter_text, _ = skill_markdown.split("---\n", 2)
        parsed = yaml.safe_load(frontmatter_text)
        self.assertIsInstance(parsed, dict, "Skill frontmatter must parse to a mapping")
        return parsed

    def load_skill(
        self, skill_name: str
    ) -> tuple[dict[str, object], str, dict[str, object]]:
        skill_dir = self.skill_dirs[skill_name]
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        adapter = yaml.safe_load(
            (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        return self.parse_frontmatter(skill_text), skill_text, adapter

    def normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.lower().replace("`", "")).strip()

    def assertNonEmptyString(self, value: object, msg: str) -> str:
        self.assertIsInstance(value, str, msg)
        self.assertNotEqual("", value.strip(), msg)
        return value

    def assertContainsAll(
        self, haystack: str, phrases: tuple[Concept, ...], msg: str
    ) -> None:
        normalized_haystack = self.normalize_text(haystack)
        missing: list[str] = []
        for phrase in phrases:
            alternatives = (phrase,) if isinstance(phrase, str) else phrase
            normalized_alternatives = tuple(
                self.normalize_text(alternative) for alternative in alternatives
            )
            if not any(
                alternative in normalized_haystack
                for alternative in normalized_alternatives
            ):
                missing.append(" | ".join(alternatives))
        if missing:
            self.fail(f"{msg}; missing phrases: {missing}")

    def test_catalog_doc_is_linked_from_agents_claude_and_index(self) -> None:
        self.assertIn("docs/reference/ai-agent-skills.md", self.agents_text)
        self.assertIn("docs/reference/ai-agent-skills.md", self.claude_text)
        self.assertIn("`reference/ai-agent-skills.md`", self.index_text)
        self.assertIn(".agents/skills/", self.catalog_text)

    def test_all_skill_directories_are_present_and_match_expected_inventory(
        self,
    ) -> None:
        self.assertEqual(set(ALL_SKILLS), set(self.skill_dirs))
        self.assertEqual(27, len(self.skill_dirs))
        self.assertEqual(set(ALL_SKILLS), set(SKILL_SCENARIOS))

    def test_every_skill_has_frontmatter_adapter_and_catalog_entry(self) -> None:
        for skill_name in ALL_SKILLS:
            with self.subTest(skill_name=skill_name):
                skill_dir = self.skill_dirs[skill_name]
                skill_file = skill_dir / "SKILL.md"
                adapter_file = skill_dir / "agents" / "openai.yaml"
                self.assertTrue(skill_file.is_file(), f"Missing SKILL.md: {skill_name}")
                self.assertTrue(
                    adapter_file.is_file(), f"Missing agents/openai.yaml: {skill_name}"
                )

                frontmatter, skill_text, adapter = self.load_skill(skill_name)
                name = self.assertNonEmptyString(
                    frontmatter.get("name"),
                    f"Skill frontmatter name must be a non-empty string: {skill_name}",
                )
                self.assertEqual(skill_name, name)
                self.assertNonEmptyString(
                    frontmatter.get("description"),
                    f"Skill description must be a non-empty string: {skill_name}",
                )
                self.assertNonEmptyString(
                    frontmatter.get("origin"),
                    f"Skill origin must be a non-empty string: {skill_name}",
                )
                self.assertGreaterEqual(skill_text.count("\n# "), 1)

                if skill_name in REPO_NATIVE_SKILLS:
                    self.assertNotIn("upstream", frontmatter)
                else:
                    upstream = self.assertNonEmptyString(
                        frontmatter.get("upstream"),
                        f"Adapted skill must declare a non-empty upstream path: {skill_name}",
                    )
                    self.assertTrue(
                        (self.repo_root / upstream).is_file(),
                        f"Missing upstream skill file for {skill_name}: {upstream}",
                    )
                    self.assertIn("## Upstream baseline", skill_text)

                self.assertIsInstance(adapter, dict)
                expected_implicit_policy = skill_name != "caveman"
                self.assertEqual(
                    expected_implicit_policy,
                    adapter.get("policy", {}).get("allow_implicit_invocation"),
                )
                interface = adapter.get("interface", {})
                self.assertIsInstance(interface, dict)
                self.assertNonEmptyString(
                    interface.get("display_name"),
                    f"Adapter display_name must be set: {skill_name}",
                )
                self.assertNonEmptyString(
                    interface.get("short_description"),
                    f"Adapter short_description must be set: {skill_name}",
                )
                self.assertNonEmptyString(
                    interface.get("default_prompt"),
                    f"Adapter default_prompt must be set: {skill_name}",
                )
                self.assertNonEmptyString(
                    interface.get("brand_color"),
                    f"Adapter brand_color must be set: {skill_name}",
                )

                self.assertIn(f"`{skill_name}`", self.catalog_text)
                self.assertIn(
                    f".agents/skills/{skill_name}/SKILL.md",
                    self.catalog_text,
                )

    def test_repo_native_skills_and_overlays_follow_expected_structure(self) -> None:
        for skill_name in ALL_SKILLS:
            frontmatter, skill_text, _ = self.load_skill(skill_name)
            with self.subTest(skill_name=skill_name):
                if skill_name in REPO_NATIVE_SKILLS:
                    self.assertIn(
                        "repo-local", str(frontmatter.get("origin", "")).lower()
                    )
                    self.assertNotIn("## Upstream baseline", skill_text)
                else:
                    self.assertIn("ecc", str(frontmatter.get("origin", "")).lower())
                    self.assertIn("third_party/ecc-v1.10.0/", skill_text)

    def test_each_skill_supports_a_realistic_repo_scenario(self) -> None:
        for skill_name, scenario in SKILL_SCENARIOS.items():
            with self.subTest(skill_name=skill_name, scenario=scenario.scenario):
                _, skill_text, adapter = self.load_skill(skill_name)
                self.assertContainsAll(
                    skill_text,
                    scenario.skill_phrases,
                    f"{skill_name} does not cover its expected repo scenario",
                )

                adapter_text = " ".join(
                    str(value)
                    for value in (
                        adapter.get("interface", {}).get("display_name"),
                        adapter.get("interface", {}).get("short_description"),
                        adapter.get("interface", {}).get("default_prompt"),
                    )
                )
                self.assertContainsAll(
                    adapter_text,
                    scenario.adapter_phrases,
                    f"{skill_name} adapter metadata does not advertise its scenario",
                )

    def test_security_and_verification_skills_point_to_repo_contracts(self) -> None:
        security_text = (
            self.skill_dirs["security-finding-triager"] / "SKILL.md"
        ).read_text(encoding="utf-8")
        verification_text = (
            self.skill_dirs["verification-loop"] / "SKILL.md"
        ).read_text(encoding="utf-8")
        runtime_text = (
            self.skill_dirs["omero-runtime-verifier"] / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "docs/reference/ai-agent-security-prevention-playbook.md",
            security_text,
        )
        self.assertIn("docs/operations/code-scanning.md", security_text)
        self.assertIn("split pytest", verification_text.lower())
        self.assertIn("never run omero cli as `root`", runtime_text.lower())

    def test_catalog_contains_exactly_the_expected_skill_paths(self) -> None:
        listed_paths = {
            match.group(1)
            for match in re.finditer(
                r"\.agents/skills/([^/]+)/SKILL\.md",
                self.catalog_text,
            )
        }
        self.assertEqual(set(ALL_SKILLS), listed_paths)


if __name__ == "__main__":
    unittest.main()
