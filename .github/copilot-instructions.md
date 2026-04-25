# GitHub Copilot Instructions

Use [AGENTS.md](../AGENTS.md) as the universal project contract, [docs/reference/ai-agent-context-routing.md](../docs/reference/ai-agent-context-routing.md) as the narrow-context router, and [docs/reference/ai-agent-skills.md](../docs/reference/ai-agent-skills.md) as the skill catalog.

## Single-session rule

- AI agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule is absolute and must not be bypassed, even if a later prompt requests multi-agent work.

## Core rules

- Start with `AGENTS.md`, then load the smallest correct task slice from the routing doc.
- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI agent <>`; AI co-author trailers use `Co-authored-by: AI agent` with no email; audits include anonymous contributors (`contributors?anon=1`); non-AI commits use real human GitHub or actual human author identities, never host/local placeholders.
- Honor the routing doc's numeric caps before broadening context.
- Use repo-local skills from `.agents/skills/` when they match the task.
- If the user explicitly asks for lower-token replies, use the opt-in `caveman` skill. It is for internal AI communication only, never for repo docs, comments, docstrings, function descriptions, or user-facing copy.
- It changes reply style only, not routing, tool choice, verification scope, or uncertainty handling. Return to normal detail for destructive actions, security guidance, or unresolved ambiguity.
- Keep configuration environment-driven. Do not hard-code paths, credentials, hostnames, or ports.
- Do not create, edit, overwrite, delete, normalize, or print values from non-example deployment env files such as `env/omero_secrets.env` unless the user explicitly grants a one-off exception for that exact operation.
- Do not search for, create, restore, or edit `.deepsource.toml`; use `docs/operations/code-scanning.md` and `tools/scanner_inventory.py` for scanner counts/logs. GitHub HTTPS Git needs a PAT/credential manager, never an account password; use `tools/git_push_with_pat.py`. If GitHub PAT/DeepSource API key is missing, ask immediately and pause for input; continue only unrelated local work.
- For functional OMERO/installation changes, live-test when appropriate or requested: reconcile dirty/stale live roots non-destructively, rebuild/inject/restart affected containers from the exact checkout, and test changed mechanisms before commit/push. After every push, confirm green GitHub workflows and no DeepSource count increase when auth is available.
- Prefer existing helpers, tests, docs, and `*_example*`; use fewer lines only when parity/rules are proven, and fix proven bad instructions/tools only after the correct workflow is verified.
- Open one domain doc and one nearest test module before broadening context.

## Verification rules

- Run `python3 tools/lint_docs_structure.py` for doc edits and `python3 tools/regression_guard.py scan` (canonical anti-regression gate) before any commit.
- Use Ruff as the Python lint and format gate, and verify host `ruff` matches the repo-pinned version before claiming local verification.
- Run split `pytest` suites separately. Never combine all suites into one `pytest` process.
- Report the exact verification level achieved. Do not overstate coverage.

## Security rules

- Before security-sensitive edits, follow the mandatory read order in `AGENTS.md`.
- Use official upstream docs and release notes for version-sensitive facts.
- Never paste PATs, passwords, tokens, or internal-only URLs into external tools.

## Cross-agent surfaces

- Claude Code: `CLAUDE.md`; Gemini CLI: `GEMINI.md`; Cursor: `.cursor/rules/`
- Platform map and upkeep rules: `docs/reference/ai-agent-integrations.md`; deep runtime procedure and pinned upstream source map: `docs/reference/ai-agent-runtime-playbook.md`, `docs/reference/ai-agent-upstream-sources.md`
