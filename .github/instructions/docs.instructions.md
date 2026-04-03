---
applyTo: "**/*.md"
---

# Documentation and instruction-surface instructions

- Keep root docs limited to `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `CLAUDE.md`, and `GEMINI.md`.
- Keep all other project documentation under `docs/`.
- Update `docs/index.md` when adding new docs.
- Keep cross-agent instruction files aligned with `AGENTS.md`, `docs/reference/ai-agent-skills.md`, and `docs/reference/ai-agent-integrations.md`.
- Run `python3 tools/lint_docs_structure.py` and the AI-surface regression tests after doc or instruction changes.
