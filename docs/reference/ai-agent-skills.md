# AI Agent Skills

This document catalogs the repository's shared skill surface for AI agents.

The skills live under `.agents/skills/`. Harnesses that support skill discovery can load them directly. Harnesses that do not can still read the corresponding `SKILL.md` files manually.

ECC-derived overlays point back to the pinned upstream snapshot in `third_party/ecc-v1.10.0/`. Repo-native operational skills remain local-only.

## Precedence

Apply guidance in this order:

1. `AGENTS.md`
2. `docs/reference/ai-agent-context-routing.md`
3. `docs/reference/ai-agent-security-prevention-playbook.md`
4. the relevant skill in `.agents/skills/`
5. harness-specific files such as `CLAUDE.md`

The skill surface is additive. It must not override the repo's no-subagent rule, security read order, split-pytest policy, or environment-driven configuration model.

Opt-in compression skills are advisory only. They never override risk handling, safety warnings, exact dates, or clarity-first explanations.

## Repo-native operational skills

| Skill | Path | Use when | Key outcome |
| --- | --- | --- | --- |
| `search-first` | `.agents/skills/search-first/SKILL.md` | before adding helpers, integrations, wrappers, or dependencies | repo and upstream evidence are checked before coding |
| `documentation-lookup` | `.agents/skills/documentation-lookup/SKILL.md` | when a fact is version-sensitive or could have changed recently | answers are grounded in current official docs and releases |
| `web-discovery` | `.agents/skills/web-discovery/SKILL.md` | when current public-web discovery is needed across docs, releases, issues, or community sources | the search stays bounded and source-first instead of memory-driven |
| `site-extract` | `.agents/skills/site-extract/SKILL.md` | when a known public page needs structured extraction | extraction stays bounded, citation-ready, and easy to verify |
| `browser-fallback` | `.agents/skills/browser-fallback/SKILL.md` | when direct fetch is not enough because a page is JS-heavy or stateful | browser use stays deterministic and limited to real need |
| `source-audit` | `.agents/skills/source-audit/SKILL.md` | before giving advice or claims based on web research | final answers separate confirmed facts, inference, and open gaps |
| `compliance-and-rate-limit` | `.agents/skills/compliance-and-rate-limit/SKILL.md` | when repeated requests, crawling, or larger-scope extraction could create policy or load risk | collection stays cache-aware, paced, and non-evasive |
| `verification-loop` | `.agents/skills/verification-loop/SKILL.md` | after non-trivial changes and before PRs | verification states exactly what was checked and what was blocked |
| `caveman` | `.agents/skills/caveman/SKILL.md` | when the user explicitly asks for lower-token replies or terse mode in AI communication | output tokens drop without losing technical substance or safety |
| `docs-knowledge-maintainer` | `.agents/skills/docs-knowledge-maintainer/SKILL.md` | when behavior, env contracts, topology, or troubleshooting guidance changes | docs stay aligned with the code and routing model |
| `plugin-regression-triager` | `.agents/skills/plugin-regression-triager/SKILL.md` | when selecting the correct split pytest suites | the narrowest correct regression set is chosen |
| `omero-runtime-verifier` | `.agents/skills/omero-runtime-verifier/SKILL.md` | for live runtime debugging, service checks, or OMERO CLI work | runtime triage follows the documented safe procedure |
| `env-contract-reviewer` | `.agents/skills/env-contract-reviewer/SKILL.md` | when env files, config loaders, startup scripts, or compose wiring change | env-driven configuration stays template-backed and documented |
| `security-finding-triager` | `.agents/skills/security-finding-triager/SKILL.md` | for scanner findings or security-sensitive edits | fixes follow the live runbook and canonical prevention rules |
| `frontend-preview` | `.agents/skills/frontend-preview/SKILL.md` | previewing HTML/CSS/JS changes and adding narrow frontend regression checks without a Docker rebuild | visual validation plus pinned Vite/Vitest DOM or browser checks |

## ECC-derived engineering overlays

| Skill | Path | Use when | Key outcome |
| --- | --- | --- | --- |
| `python-patterns` | `.agents/skills/python-patterns/SKILL.md` | writing or refactoring Python helpers, services, or tooling | Python changes stay aligned with helper boundaries and env contracts |
| `python-testing` | `.agents/skills/python-testing/SKILL.md` | adding or choosing Python regression tests | the correct split pytest or fallback checks are selected |
| `django-patterns` | `.agents/skills/django-patterns/SKILL.md` | changing OMERO.web plugin views, routes, templates, or services | Django changes respect plugin boundaries and layout conventions |
| `django-security` | `.agents/skills/django-security/SKILL.md` | changing Django views, uploads, responses, or permissions | Django and OMERO.web boundaries are hardened correctly |
| `django-verification` | `.agents/skills/django-verification/SKILL.md` | verifying Django or OMERO.web changes | verification follows the repo's split-suite model |
| `docker-patterns` | `.agents/skills/docker-patterns/SKILL.md` | changing Dockerfiles, Compose, startup scripts, or service wiring | runtime changes keep the repo's pinning and hardening rules |
| `deployment-patterns` | `.agents/skills/deployment-patterns/SKILL.md` | changing installation, update, or rollout behavior | deployment changes preserve update safety and env contracts |
| `postgres-patterns` | `.agents/skills/postgres-patterns/SKILL.md` | changing SQL, persistence, indexes, or maintenance behavior | database changes respect the repo's dual-Postgres model |
| `security-review` | `.agents/skills/security-review/SKILL.md` | reviewing sensitive code or designs before implementation | security review follows the repo's boundary-focused rules |
| `tdd-workflow` | `.agents/skills/tdd-workflow/SKILL.md` | features, bug fixes, and refactors that need tests first | done-ness includes narrow tests and docs updates |
| `ai-regression-testing` | `.agents/skills/ai-regression-testing/SKILL.md` | validating AI-generated fixes for path mismatches or partial fixes | regressions are locked with narrow, explicit checks |
| `context-budget` | `.agents/skills/context-budget/SKILL.md` | reducing token usage and repeated repo rediscovery | agents stay faster by loading only the smallest correct context |

## Usage notes

- Start with `AGENTS.md` and `docs/reference/ai-agent-context-routing.md` to find the right domain docs.
- Use the nearest skill before falling back to a generic workflow.
- When a skill references live or version-sensitive behavior, verify with official upstream docs or releases.
- Never paste secrets, PATs, passwords, or internal-only URLs into external research tools.
- `caveman` is opt-in and available through the shared `.agents/skills/` catalog like every other skill. Use it only when the user asks for terseness or lower token usage, and drop it immediately if clarity or safety would suffer.
- `caveman` is limited to internal AI communication and prompting. Keep repository docs, comments, docstrings, function descriptions, commit messages, and user-facing text in normal prose.
- `caveman` changes reply style only. It never changes routing, tool use, verification scope, or the need to surface uncertainty clearly.
- The repo-local overlay intentionally stays narrower than upstream `v1.6.0`: no hooks, no plugin auto-loading, no `.codex` hook config, no natural-language auto-activation, no `CAVEMAN_DEFAULT_MODE` or `off` handling, no `caveman-help`, and no `/compress` context rewriting.

## Maintenance rules

- Keep skill files concise and repo-specific.
- Prefer routing to existing docs over copying long instructions into each skill.
- If a new recurring workflow appears, add a new skill only when the guidance cannot live cleanly in an existing doc.
