# GitHub Copilot Instructions

Use [AGENTS.md](../AGENTS.md) as the universal project contract, including its pinned Karpathy agent baseline; use [docs/reference/ai-agent-context-routing.md](../docs/reference/ai-agent-context-routing.md) as the narrow-context router, and [docs/reference/ai-agent-skills.md](../docs/reference/ai-agent-skills.md) as the skill catalog.

## Single-session rule

- AI Agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule must not be bypassed except for the Codex Security exception below.
- Codex Security exception: multi-worker vulnerability scanning is on-demand only. Before opening or launching a Codex Security scan, pause and clearly ask the user to authorize the exact scan target, mode, and worker/subagent use.
- Continue only after explicit user approval or the Codex Security UI Start Scan handoff. Use the minimum required subagents only when the user explicitly asks for that workflow and the loaded security skill requires them; all edits, commits, pushes, releases, and reconciliation stay in the parent session.

## Core rules

- Start with `AGENTS.md`, then load the smallest correct task slice from the routing doc.
- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI Agent <>`; AI co-author trailers use `Co-authored-by: AI Agent` with no email; audits include anonymous contributors (`contributors?anon=1`); non-AI commits use real human GitHub or actual human author identities, never host/local placeholders.
- Develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch; resolve it dynamically and do not create feature branches, PR branches, temporary remote branches, or draft PRs for routine work.
- Before every release, pause for explicit confirmation of the exact GitHub release tag and Docker repository/tag; never infer or auto-increment a version. Require a version-matched human-readable `CHANGELOG.md` section, automated disclosure validation, and human public-safety review.
  Never publish credentials, personal or host-specific information, private infrastructure, findings, vulnerability mechanics, or exploit-enabling detail. Publish the same rendered notes through GitHub and the Docker carrier.
- Before deleting any pre-existing or persistent object, pause for fresh approval naming that single object and operation. Ask separately for every GitHub release, Git tag, Docker image/tag, branch, file tree, volume, backup, data object, or remote artifact; blanket, earlier, same-version, replace, or recreate permission never carries forward.
- Honor the routing doc's numeric caps before broadening context.
- Use repo-local skills from `.agents/skills/` when they match the task.
- CocoIndex: broad navigation has a mandatory `cocoindex-code` MCP check and uses `.agents/skills/cocoindex-code-search/` for semantic routing before exact `rg`; use direct `rg` first only for precise string, symbol, scanner-count, or already-small searches.
  State cold-index waits once; external cache/state stays under `AGENT_COCOINDEX_HOME`, outside `.cocoindex_code/`, text-decodable; `mcp-smoke` verifies MCP changes. For current edits run `index --allow-dirty-index` or `search --refresh "<query>"`; MCP search itself never refreshes and can return stale active-index text.
- If the user explicitly asks for lower-token replies, use the opt-in `caveman` skill. It is for internal AI communication only, never for repo docs, comments, docstrings, function descriptions, or user-facing copy.
- It changes reply style only, not routing, tool choice, verification scope, or uncertainty handling. Return to normal detail for destructive actions, security guidance, or unresolved ambiguity.
- Keep configuration environment-driven. Do not hard-code paths, credentials, hostnames, or ports.
- Do not create, edit, overwrite, delete, normalize, or print values from non-example deployment env files such as `env/omero_secrets.env` unless the user explicitly grants a one-off exception for that exact operation.
- Do not search for, create, restore, or edit `.deepsource.toml`; use `docs/operations/code-scanning.md` and `tools/scanner_inventory.py` for scanner counts. GitHub HTTPS Git needs a PAT/credential manager, never an account password; use `tools/git_push_with_pat.py`. If a GitHub PAT is missing, ask immediately and pause for input; continue only unrelated local work until GitHub auth is available.
- For functional OMERO/installation changes, live-test when appropriate or requested: reconcile dirty/stale live roots non-destructively, rebuild/inject/restart affected containers from the exact checkout, and test changed mechanisms before commit/push.
  After every push, confirm green GitHub workflows and no DeepSource count increase when auth and repository access are available.
  If DeepSource is skipped or unavailable because of credentials, subscription, repository access, or API availability, report it as skipped/unavailable and continue the remaining verification.
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
