# AI Agent Skills

This document catalogs the repository's shared skill surface for AI agents.

The skills live under `.agents/skills/`. Harnesses that support skill discovery can load them directly. Harnesses that do not can still read the corresponding `SKILL.md` files manually.

## Precedence

Apply guidance in this order:

1. `AGENTS.md`
2. `docs/reference/ai-agent-security-prevention-playbook.md`
3. the relevant skill in `.agents/skills/`
4. harness-specific files such as `CLAUDE.md`

The skill surface is additive. It must not override the repo's no-subagent rule, security read order, split-pytest policy, or environment-driven configuration model.

## Shared skills

| Skill | Path | Use when | Key outcome |
| --- | --- | --- | --- |
| `search-first` | `.agents/skills/search-first/SKILL.md` | before adding helpers, integrations, wrappers, or dependencies | repo and upstream evidence are checked before coding |
| `documentation-lookup` | `.agents/skills/documentation-lookup/SKILL.md` | when a fact is version-sensitive or could have changed recently | answers are grounded in current official docs and releases |
| `verification-loop` | `.agents/skills/verification-loop/SKILL.md` | after non-trivial changes and before PRs | verification states exactly what was checked and what was blocked |
| `docs-knowledge-maintainer` | `.agents/skills/docs-knowledge-maintainer/SKILL.md` | when behavior, env contracts, topology, or troubleshooting guidance changes | docs stay aligned with the code and routing model |
| `plugin-regression-triager` | `.agents/skills/plugin-regression-triager/SKILL.md` | when selecting the correct split pytest suites | the narrowest correct regression set is chosen |
| `omero-runtime-verifier` | `.agents/skills/omero-runtime-verifier/SKILL.md` | for live runtime debugging, service checks, or OMERO CLI work | runtime triage follows the documented safe procedure |
| `env-contract-reviewer` | `.agents/skills/env-contract-reviewer/SKILL.md` | when env files, config loaders, startup scripts, or compose wiring change | env-driven configuration stays template-backed and documented |
| `security-finding-triager` | `.agents/skills/security-finding-triager/SKILL.md` | for scanner findings or security-sensitive edits | fixes follow the live runbook and canonical prevention rules |

## Usage notes

- Start with `AGENTS.md` to find the right domain docs.
- Use the nearest skill before falling back to a generic workflow.
- When a skill references live or version-sensitive behavior, verify with official upstream docs or releases.
- Never paste secrets, PATs, passwords, or internal-only URLs into external research tools.

## Maintenance rules

- Keep skill files concise and repo-specific.
- Prefer routing to existing docs over copying long instructions into each skill.
- If a new recurring workflow appears, add a new skill only when the guidance cannot live cleanly in an existing doc.
