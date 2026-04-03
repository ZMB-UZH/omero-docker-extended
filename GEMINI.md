# Gemini CLI instructions

Use [AGENTS.md](AGENTS.md) as the universal project contract and [docs/reference/ai-agent-skills.md](docs/reference/ai-agent-skills.md) as the skill catalog.

## Core rules

- Start with `AGENTS.md`.
- Use `.agents/skills/` when a skill matches the task.
- Keep configuration environment-driven and never edit `env/omero_secrets.env`.
- Do not use background agents or subagents unless the user explicitly asks for them.
- Prefer repo-native docs, tests, helpers, and `*_example*` files over new abstractions.

## Verification and security

- Run `python3 tools/lint_docs_structure.py` for doc and instruction changes.
- Use Ruff for Python lint and formatting.
- Run split `pytest` suites separately; never combine all suites into one process.
- Before security-sensitive edits, follow the read order in `AGENTS.md` and use official upstream docs for version-sensitive behavior.

## Cross-agent adapter map

- Claude Code: `CLAUDE.md`
- GitHub Copilot: `.github/copilot-instructions.md` and `.github/instructions/`
- Cursor: `.cursor/rules/`
- Integrations guide: `docs/reference/ai-agent-integrations.md`
- Pinned ECC source map: `docs/reference/ai-agent-upstream-sources.md`
