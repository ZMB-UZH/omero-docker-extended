# AI Agent Integrations

This document defines the repository's complete cross-agent instruction surface.

The goal is to support the major documented instruction systems without changing runtime code, Docker behavior, or CI logic.

## Precedence

Apply guidance in this order:

1. `AGENTS.md`
2. `docs/reference/ai-agent-security-prevention-playbook.md`
3. `docs/reference/code-scanning-resolved-findings.md`
4. `docs/operations/code-scanning.md`
5. `docs/reference/ai-agent-skills.md` and `.agents/skills/`
6. harness-specific adapter files

Harness-specific files are additive. They must not override the repo's security read order, no-subagent rule, environment-driven configuration model, or split-pytest policy.

## Supported instruction surfaces

| Harness or surface | Files in this repo | Purpose |
| --- | --- | --- |
| Universal | `AGENTS.md`, `.agents/skills/`, `docs/reference/ai-agent-skills.md` | shared repo contract and reusable workflows |
| Claude Code | `CLAUDE.md` | Claude-specific session guidance |
| GitHub Copilot | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `.agents/skills/` | repo-wide and path-specific Copilot guidance |
| Cursor | `.cursor/rules/*.mdc`, `AGENTS.md`, `.agents/skills/` | rule-based Cursor context plus shared skills |
| Gemini CLI | `GEMINI.md` | project-level Gemini context file |

## ECC integration model

This repository does not run ECC's installer directly against the working tree.

Instead it uses:

- a pinned upstream snapshot under `third_party/ecc-v1.9.0/`
- repo-specific overlays in `.agents/skills/`
- native adapter files for each harness

This avoids importing ECC hooks, commands, multi-agent orchestration, or platform configs that would disturb the repo's existing workflows.

## What is intentionally imported

- engineering skills relevant to this repo: Python, Django, testing, verification, Docker, deployment, PostgreSQL, security, research, and context-budget control
- ECC provenance and license material for the selected upstream skills
- harness-specific adapters that route agents into the repo's existing docs and tests

## What is intentionally not imported

- ECC hook runtime
- ECC command shims
- ECC multi-agent orchestration and loop automation
- ECC MCP server configs
- unrelated domain skills such as business-content, media-generation, or social-distribution

## Token and speed guidance

The adapter set is designed to improve accuracy first, then reduce wasted context:

- route agents into `AGENTS.md` and the nearest domain doc before broad repo reads
- expose reusable workflows through `.agents/skills/`
- add path-specific Copilot and Cursor guidance so agents do not rediscover the same rules every time
- keep Gemini and Copilot adapter files concise so they do not bloat always-on context

## Maintenance rules

- Update `docs/index.md` when this surface changes.
- Update `docs/reference/ai-agent-upstream-sources.md` when the ECC snapshot or selected upstream skills change.
- For ECC-derived local skills, keep the repo overlay concise and point to the pinned upstream snapshot.
- Run `python3 tools/lint_docs_structure.py` and the AI-surface regression tests after changing any adapter or skill file.
