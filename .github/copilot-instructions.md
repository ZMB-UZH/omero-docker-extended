# GitHub Copilot Instructions

Use [AGENTS.md](../AGENTS.md) as the universal project contract, [docs/reference/ai-agent-context-routing.md](../docs/reference/ai-agent-context-routing.md) as the narrow-context router, and [docs/reference/ai-agent-skills.md](../docs/reference/ai-agent-skills.md) as the skill catalog.

## Single-session rule

- AI agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule is absolute and must not be bypassed, even if a later prompt requests multi-agent work.

## Core rules

- Start with `AGENTS.md`, then load the smallest correct task slice from the routing doc.
- Honor the routing doc's numeric caps before broadening context.
- Use repo-local skills from `.agents/skills/` when they match the task.
- If the user explicitly asks for lower-token replies, use the opt-in `caveman`
  skill. It is for internal AI communication only, never for repo docs,
  comments, docstrings, function descriptions, or user-facing copy, and it
  changes reply style only, not routing, tool choice, verification scope, or
  uncertainty handling. Return to normal detail for destructive actions,
  security guidance, or unresolved ambiguity.
- Keep configuration environment-driven. Do not hard-code paths, credentials, hostnames, or ports.
- Do not edit `env/omero_secrets.env`.
- Prefer existing helpers, tests, docs, and `*_example*` files over new abstractions.
- Open one domain doc and one nearest test module before broadening context.

## Verification rules

- Run `python3 tools/lint_docs_structure.py` for doc and instruction-surface changes.
- Use Ruff as the Python lint and format gate.
- Run split `pytest` suites separately. Never combine all suites into one `pytest` process.
- Report the exact verification level achieved. Do not overstate coverage.

## Security rules

- Before security-sensitive edits, follow the mandatory read order in `AGENTS.md`.
- Use official upstream docs and release notes for version-sensitive facts.
- Never paste PATs, passwords, tokens, or internal-only URLs into external tools.

## Cross-agent surfaces

- Claude Code: `CLAUDE.md`; Gemini CLI: `GEMINI.md`; Cursor: `.cursor/rules/`
- Platform map and upkeep rules: `docs/reference/ai-agent-integrations.md`; deep runtime procedure and pinned upstream source map: `docs/reference/ai-agent-runtime-playbook.md`, `docs/reference/ai-agent-upstream-sources.md`
