# Gemini CLI instructions

Use [AGENTS.md](AGENTS.md) as the universal contract and pinned Karpathy agent baseline,
[the routing guide](docs/reference/ai-agent-context-routing.md) for minimal
context, and [the skill catalog](docs/reference/ai-agent-skills.md) for reusable
workflows.

## Single-session rule

- AI Agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule must not be bypassed except for the Codex Security exception below.
- Codex Security exception: multi-worker vulnerability scanning is on-demand only. Before launching a Codex Security scan, pause and clearly ask the user to authorize the exact scan target, mode, and worker/subagent use. Continue only after explicit user approval or the Codex Security UI Start Scan handoff; all edits, commits, pushes, releases, and reconciliation stay in the parent session.

## Core rules

- Start with `AGENTS.md`, then the routing doc.
- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI Agent <>`; never use profile-mapped AI/tool emails; AI co-author trailers use `Co-authored-by: AI Agent` with no email; audits include anonymous contributors (`contributors?anon=1`).
- Non-AI commits use real human GitHub or actual human author identities, never host/local placeholders. Develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch; resolve it dynamically and do not create feature branches, PR branches, temporary remote branches, or draft PRs for routine work.
- Pause before every release and obtain explicit confirmation of the exact GitHub release tag and Docker repository/tag; never infer or auto-increment versions. Require a matching human-readable `CHANGELOG.md` section, automated disclosure validation, and human public-safety review.
  Never publish credentials, personal or host-specific information, private infrastructure, findings, vulnerability mechanics, or exploit-enabling detail. Publish the same notes through GitHub and the Docker carrier.
- Pause before deleting any pre-existing or persistent object. Each GitHub release, Git tag, Docker image/tag, branch, file tree, volume, backup, data object, or remote artifact needs fresh approval naming that one deletion; blanket, earlier, same-version, replace, or recreate permission never carries forward.
- Honor the routing doc's numeric caps before broadening scope and use `.agents/skills/` when a skill matches the task.
- CocoIndex: broad navigation has a mandatory `cocoindex-code` MCP check and uses `.agents/skills/cocoindex-code-search/` for semantic routing before exact `rg`; use direct `rg` first only for precise string, symbol, scanner-count, or already-small searches.
  State cold-index waits once; external cache/state stays under `AGENT_COCOINDEX_HOME`, outside `.cocoindex_code/`, text-decodable; `mcp-smoke` verifies MCP changes. For current edits run `index --allow-dirty-index` or `search --refresh "<query>"`; MCP search itself never refreshes and can return stale active-index text.
- If the user asks for lower-token replies, use opt-in `caveman`; it is only for internal AI communication, never repo docs/comments/docstrings/function descriptions/user-facing copy, and changes reply style only, not routing, tool choice, verification scope, or uncertainty handling. Fall back to normal detail when safety or clarity is at risk.
- Keep config environment-driven; never edit/normalize/print values from non-example deployment env files such as `env/omero_secrets.env` without an explicit one-off user exception; never use retired `.deepsource.toml`; use PAT/credential manager for GitHub HTTPS Git; ask immediately for missing GitHub credentials.
- Live-test functional OMERO/installation changes when appropriate or requested: reconcile dirty/stale live roots non-destructively, rebuild/inject/restart from the exact checkout before commit/push, then verify green GitHub workflows and no DeepSource count increase after pushes when auth and repository access are available.
  If DeepSource is skipped or unavailable because of credentials, subscription, repository access, or API availability, report it and continue the remaining verification.
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
