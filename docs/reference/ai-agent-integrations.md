# AI Agent Integrations

This document defines the repository's complete cross-agent instruction surface.

The goal is to support the major documented instruction systems without changing runtime code, Docker behavior, or CI logic.

## Precedence

Apply guidance in this order:

1. `AGENTS.md`
2. `docs/reference/ai-agent-context-routing.md`
3. `docs/reference/ai-agent-runtime-playbook.md`
4. `docs/reference/ai-agent-security-prevention-playbook.md`
5. `docs/reference/code-scanning-resolved-findings.md`
6. `docs/operations/code-scanning.md`
7. `docs/reference/ai-agent-skills.md` and `.agents/skills/`
8. harness-specific adapter files

Harness-specific files are additive. They must not override the repo's security read order, no-subagent rule, environment-driven configuration model, or split-pytest policy.

## Supported instruction surfaces

| Harness or surface | Files in this repo | Purpose |
| --- | --- | --- |
| Universal | `AGENTS.md`, `docs/reference/ai-agent-context-routing.md`, `docs/reference/ai-agent-runtime-playbook.md`, `.agents/skills/`, `docs/reference/ai-agent-skills.md` | shared repo contract, narrow routing, deep runtime procedure, and reusable workflows |
| Claude Code | `CLAUDE.md` | Claude-specific session guidance |
| GitHub Copilot | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `.agents/skills/` | repo-wide and path-specific Copilot guidance |
| Cursor | `.cursor/rules/*.mdc`, `AGENTS.md`, `.agents/skills/` | rule-based Cursor context plus shared skills |
| Gemini CLI | `GEMINI.md` | project-level Gemini context file |

## ECC integration model

This repository does not run ECC's installer directly against the working tree.

Instead it uses:

- a pinned upstream snapshot under `third_party/ecc-v1.10.0/`
- repo-specific overlays in `.agents/skills/`
- native adapter files for each harness

This avoids importing ECC hooks, commands, multi-agent orchestration, or platform configs that would disturb the repo's existing workflows.

## caveman integration model

This repository also carries an opt-in `caveman` communication overlay:

- vendored upstream prompt reference material under `third_party/caveman-v1.5.0/`
- a repo-local overlay at `.agents/skills/caveman/`
- small adapter reminders in `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and `.github/copilot-instructions.md`

Compression stays opt-in and quality-first:

- use `context-budget` to reduce input/context cost first
- use `caveman` only when the user explicitly asks for lower-token replies
- start at lite compression in this repo and return to normal detail whenever safety, sequencing, or ambiguity matters
- keep `caveman` limited to internal AI communication and prompting; repository docs, comments, docstrings, function descriptions, commit messages, and user-facing text stay in normal prose
- keep routing, tool use, verification scope, and uncertainty handling identical to normal mode

Upstream `caveman` `v1.5.0` adds configurable default-mode resolution (`CAVEMAN_DEFAULT_MODE` / `~/.config/caveman/config.json`), `off`, and `caveman-help`. This repo does not import those activation or configuration surfaces.

The upstream `caveman` hooks, plugin auto-loading, and compression-tool context rewriting are not activated in this repo.

## What is intentionally imported

- engineering skills relevant to this repo: Python, Django, testing, verification, Docker, deployment, PostgreSQL, security, research, and context-budget control
- the opt-in `caveman` overlay for lower-token replies when the user explicitly requests terseness
- ECC provenance and license material for the selected upstream skills
- harness-specific adapters that route agents into the repo's existing docs and tests

## What is intentionally not imported

- ECC hook runtime
- ECC command shims
- ECC multi-agent orchestration and loop automation
- ECC MCP server configs
- `caveman` hook runtime, plugin auto-loading, default-mode config resolution, `off`, `caveman-help`, and `/compress` context-rewrite automation
- unrelated domain skills such as business-content, media-generation, or social-distribution

## Token and speed guidance

The adapter set is designed to improve accuracy first, then reduce wasted context:

- route agents into `AGENTS.md`, `docs/reference/ai-agent-context-routing.md`, and the nearest domain doc before broad repo reads
- keep the routing doc's numeric caps CI-validated so first-pass reads, refine loops, and escalation stay bounded
- expose reusable workflows through `.agents/skills/`
- prefer `context-budget` for input reduction and the opt-in `caveman` overlay for output reduction
- add path-specific Copilot and Cursor guidance so agents do not rediscover the same rules every time
- keep `AGENTS.md`, Claude, Gemini, Copilot, and Cursor core rules concise so they do not bloat always-on context

## Claude Code hooks

`.claude/settings.json` defines PostToolUse and PreToolUse hooks that automate rules from `AGENTS.md`:

| Event | Matcher | Action | Rule enforced |
| --- | --- | --- | --- |
| PostToolUse | Write\|Edit | Run `ruff check --fix` and `ruff format` on edited `.py` files | Ruff is the canonical Python formatter and lint gate |
| PostToolUse | Write\|Edit | Run `npx markdownlint-cli2` on edited `.md` files | Validate Markdown to prevent CI super-linter failures |
| PreToolUse | Bash | Run `python3 tools/env_safety_guard.py check` before `docker compose` commands | Verify deployment env files are intact before compose operations |

These hooks are Claude Code-specific (other harnesses do not support hooks). The underlying rules are documented in `AGENTS.md` so all agents follow them regardless of automation.

## Maintenance rules

- Add new skills once in `.agents/skills/` and once in `docs/reference/ai-agent-skills.md`. Supported harnesses inherit new skills through the shared catalog; do not duplicate per-skill instructions into every harness adapter.
- Update `docs/index.md` when this surface changes.
- Update `docs/reference/ai-agent-upstream-sources.md` when the ECC snapshot, vendored `caveman` prompt references, or selected upstream skills change.
- For ECC-derived local skills, keep the repo overlay concise and point to the pinned upstream snapshot.
- Run `python3 tools/lint_docs_structure.py` and the AI-surface regression tests after changing any adapter or skill file.
