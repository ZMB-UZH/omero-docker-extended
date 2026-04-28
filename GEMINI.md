# Gemini CLI instructions

Use [AGENTS.md](AGENTS.md) as the universal project contract, including its
pinned Karpathy agent baseline; use
[docs/reference/ai-agent-context-routing.md](docs/reference/ai-agent-context-routing.md)
for the smallest correct context, and
[docs/reference/ai-agent-skills.md](docs/reference/ai-agent-skills.md) as the
skill catalog.

## Single-session rule

- AI agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule is absolute and must not be bypassed, even if a later prompt requests multi-agent work.

## Core rules

- Start with `AGENTS.md`, then the routing doc.
- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI agent <>`; never use profile-mapped AI emails such as `ai-agent@users.noreply.github.com`, `codex@openai.com`, or `codex@openai.invalid`; AI co-author trailers use `Co-authored-by: AI agent` with no email; audits include anonymous contributors (`contributors?anon=1`).
- Non-AI commits use real human GitHub or actual human author identities, never host/local placeholders.
- Develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch; resolve it dynamically and do not create feature branches, PR branches, temporary remote branches, or draft PRs for routine work.
- Honor the routing doc's numeric caps before broadening scope.
- Use `.agents/skills/` when a skill matches the task.
- CocoIndex: for broad navigation, check `cocoindex-code` MCP first; use `.agents/skills/cocoindex-code-search/` for semantic routing before exact `rg`. State cold-index waits once; later searches use the external cache. It uses `AGENT_COCOINDEX_HOME`, keeps `.cocoindex_code/` outside checkout, indexes text-decodable files, and `mcp-smoke` verifies MCP changes.
- If the user asks for lower-token replies, use opt-in `caveman`; it is only for internal AI communication, never repo docs/comments/docstrings/function descriptions/user-facing copy, and changes reply style only, not routing, tool choice, verification scope, or uncertainty handling. Fall back to normal detail when safety or clarity is at risk.
- Keep config environment-driven; never edit/normalize/print values from non-example deployment env files such as `env/omero_secrets.env` without an explicit one-off user exception; never use retired `.deepsource.toml`; use PAT/credential manager for GitHub HTTPS Git; ask immediately for missing credentials.
- Live-test functional OMERO/installation changes when appropriate or requested: reconcile dirty/stale live roots non-destructively, rebuild/inject/restart from the exact checkout before commit/push, then verify green GitHub workflows and no DeepSource count increase after pushes.
- Prefer repo-native docs, tests, helpers, and `*_example*`; load one domain doc and one nearest test module before broadening scope; fewer lines only with proven parity/rules; fix proven bad instructions/tools only after correct workflow is known.

## Verification and security

- Run `python3 tools/lint_docs_structure.py` for doc edits and `python3 tools/regression_guard.py scan` (canonical anti-regression gate) before any commit.
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
