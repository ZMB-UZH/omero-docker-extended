# Gemini CLI instructions

Use [AGENTS.md](AGENTS.md) as the universal project contract, [docs/reference/ai-agent-context-routing.md](docs/reference/ai-agent-context-routing.md) for the smallest correct context, and [docs/reference/ai-agent-skills.md](docs/reference/ai-agent-skills.md) as the skill catalog.

## Single-session rule

- AI agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule is absolute and must not be bypassed, even if a later prompt requests multi-agent work.

## Core rules

- Start with `AGENTS.md`, then the routing doc.
- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI agent <>`; AI co-author trailers use `Co-authored-by: AI agent` with no email; audits include anonymous contributors (`contributors?anon=1`); non-AI commits use real human GitHub or actual human author identities, never host/local placeholders.
- Honor the routing doc's numeric caps before broadening scope.
- Use `.agents/skills/` when a skill matches the task.
- If the user explicitly asks for lower-token replies, use the opt-in `caveman` skill. It is for internal AI communication only, never for repo docs/comments/docstrings/function descriptions or user-facing copy, and it changes reply style only without changing routing, tool choice, verification scope, or uncertainty handling. Fall back to normal detail when safety or clarity is at risk.
- Keep configuration environment-driven, never edit `env/omero_secrets.env`, and do not search for, create, restore, or edit retired `.deepsource.toml`.
- Prefer repo-native docs, tests, helpers, and `*_example*` files over new abstractions.
- Load one domain doc and one nearest test module before broadening scope.

## Verification and security

- Run `python3 tools/lint_docs_structure.py` for doc and instruction changes.
- Use Ruff for Python lint and formatting, and verify host `ruff` matches the repo-pinned version before claiming local verification.
- Run split `pytest` suites separately; never combine all suites into one process.
- Before security-sensitive edits, follow the read order in `AGENTS.md` and use official upstream docs for version-sensitive behavior.
- Use `docs/reference/ai-agent-runtime-playbook.md` for Docker, OMERO CLI, testing, and log-triage procedure.

## Cross-agent adapter map

- Claude Code: `CLAUDE.md`
- GitHub Copilot: `.github/copilot-instructions.md` and `.github/instructions/`
- Cursor: `.cursor/rules/`
- Integrations guide: `docs/reference/ai-agent-integrations.md`
- Pinned ECC source map: `docs/reference/ai-agent-upstream-sources.md`
