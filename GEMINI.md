# Gemini CLI instructions

Use [AGENTS.md](AGENTS.md) as the universal project contract, [docs/reference/ai-agent-context-routing.md](docs/reference/ai-agent-context-routing.md) for the smallest correct context, and [docs/reference/ai-agent-skills.md](docs/reference/ai-agent-skills.md) as the skill catalog.

## Core rules

- Start with `AGENTS.md`, then the routing doc.
- Honor the routing doc's numeric caps before broadening scope.
- Use `.agents/skills/` when a skill matches the task.
- If the user explicitly asks for lower-token replies, use the opt-in `caveman` skill and fall back to normal detail when safety or clarity is at risk.
- Keep configuration environment-driven and never edit `env/omero_secrets.env`.
- Do not use background agents or subagents unless the user explicitly asks for them.
- Prefer repo-native docs, tests, helpers, and `*_example*` files over new abstractions.
- Load one domain doc and one nearest test module before broadening scope.

## Verification and security

- Run `python3 tools/lint_docs_structure.py` for doc and instruction changes.
- Use Ruff for Python lint and formatting.
- Run split `pytest` suites separately; never combine all suites into one process.
- Before security-sensitive edits, follow the read order in `AGENTS.md` and use official upstream docs for version-sensitive behavior.
- Use `docs/reference/ai-agent-runtime-playbook.md` for Docker, OMERO CLI, testing, and log-triage procedure.

## Cross-agent adapter map

- Claude Code: `CLAUDE.md`
- GitHub Copilot: `.github/copilot-instructions.md` and `.github/instructions/`
- Cursor: `.cursor/rules/`
- Integrations guide: `docs/reference/ai-agent-integrations.md`
- Pinned ECC source map: `docs/reference/ai-agent-upstream-sources.md`
