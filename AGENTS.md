# AGENTS guide

Mandatory for every AI agent. Read once per revision; load triggered docs.

## Safety

- Work in one session. No background, delegated, or separate agent session.
  Codex Security scans are on-demand only: pause and clearly ask the user for
  the exact target, mode, and worker/subagent use. Continue only after
  explicit user approval or the Codex Security UI Start Scan handoff. Minimum
  required workers only; edits, commits, pushes, releases, and reconciliation
  remain in the parent session.
- Pause before every deletion of a pre-existing or persistent object. Require
  fresh approval naming exactly one object and one deletion, including replacements,
  containers, images, tags, releases, volumes, files, backups, and data.
  Blanket, earlier, or same-version permission never carries forward.
- Before every release, confirm exact GitHub and Docker tags and public notes.
  Never infer or auto-increment versions. Require a matching `CHANGELOG.md`,
  automated disclosure validation, and human public-safety review. Never publish
  credentials, personal/host information, private infrastructure, findings,
  vulnerability mechanics, or exploit-enabling detail.
- Configuration is environment-driven and host/installation-agnostic. Never
  hard-code deployment paths, credentials, endpoints, ports, or live object IDs.
  Preserve user data and unrelated changes. Non-example deployment env files
  are operator-owned: never edit, overwrite, delete, normalize, or print their
  values without explicit one-off authorization for that exact operation.
- Learn from verified past failures: inspect history before changing a failed
  mechanism and retain regression tests for its cause. Session/authentication
  must pass the runtime playbook's session-regression gate.
- Resolve the current remote default branch; work, commit, push, and verify there
  unless the user names another branch. No routine feature/PR branches, temporary
  remote branches, or draft PRs.
- Use the official GitHub connector for commits and pushes; verify its account
  and repository permission. Use GitHub defaults: no identity overrides or
  AI co-author trailers. If unavailable, stop publication; no CLI/PAT fallback.

## Mandatory efficiency

Mandatory lower-token tools; no silent skips.

- Before edits run `python3 tools/agent_preflight.py begin --query "<task>"`.
  Add `--research-url "<source>"` for web research. It loads Caveman, executes
  CocoIndex/Crawl4AI, and saves private receipts. Run `check` before commit.
  Diagnose failures; restore tooling before dependent work. Never substitute.
- [Crawl4AI](.agents/skills/crawl4ai-research/SKILL.md) must read web research
  sources. Search tools discover URLs; registry/account APIs retain their roles.
  No snippets-only research or silent fallback.

- CocoIndex Code is mandatory for broad semantic routing. After preflight check
  `cocoindex-code` MCP tool first; follow
  [cocoindex-code-search](.agents/skills/cocoindex-code-search/SKILL.md).
  Confirm hits in source; exact symbols, strings, counts, and small scopes use `rg`.
  Never silently trust a stale index or install/refresh one through MCP search.
- Apply [caveman](.agents/skills/caveman/SKILL.md) lite for internal AI, not opt-in: remove repetition,
  never reasoning or evidence. Public text, code, commands, errors and replies
  stay normal prose and lossless. Expand for safety, approvals, ambiguity, incidents and ordered
  procedures; required progress updates remain mandatory.
- Use the [context router](docs/reference/ai-agent-context-routing.md) only when
  the location is unknown; load one skill, not the catalog. Follow its numeric caps;
  explain escalation. Never use a budget to skip required analysis or tests.
- Keep a verification ledger: command, relevant source/configuration/runtime
  identity, result, and evidence; reuse fresh evidence. Retry only changed inputs or
  hypotheses. Run the full matrix once on the stable final tree. Preserve
  logs and exit status; inspect complete failures, not just tails.
- Avoid needless rereads, tree/log dumps, unchanged polling, upstream references
  and schema rediscovery. Handoffs retain decisions, changed files, evidence,
  risks and next action. Never compress user requests or equate bytes with billing.

## Before the matching action

Read matching [task contracts](docs/reference/ai-agent-task-contracts.md):

| Action | Required contract and next reference |
| --- | --- |
| Authorized Codex Security scan | Single-session rule; approved target/mode/workers only |
| Code/design decisions | Pinned Karpathy agent baseline; nearest implementation and tests |
| Paths, I/O, logging, HTTP, SQL, subprocesses, Docker, workflows, secrets or auth | Mandatory security read order: `regression_guard.py catalog`, `scan`, matching prevention/history sections |
| Deployment configuration, imports or test data | Configuration; tracked `*_example*` contracts |
| Live, Docker/Compose or sync | Runtime and sync; `docs/reference/ai-agent-runtime-playbook.md`; env `check` and `compose-guard` before Compose |
| Docs/instructions | Documentation; `docs/reference/ai-agent-integrations.md` for adapters |
| Tests, commit or push | Verification; `.agents/skills/verification-loop/SKILL.md` |
| Identity, branches, deletion, publication | GitHub publication; Default-branch development rule; Destructive operations and releases |
| Index/MCP maintenance | CocoIndex contract and skill above |

## Completion gate

- Preserve required meaning when compacting instructions; prove full functional
  parity with objective regression checks. Never weaken approvals, scanner scope,
  tests, or other repo rules.
- Before commit/push run
  `python3 tools/run_local_workflow_gates.py --setup --profile ci`.
  Scanner/action changes require `--profile all` with the exact engine.
  Run split pytest suites separately, never one monolithic process.
- Verify functional OMERO/install changes live before commit/push when requested
  or appropriate. Agent-only edits do not justify application rebuilds or restarts.
- After every push, verify GitHub workflows and alert deltas for that exact
  commit. No suppression, scope reduction, or score manipulation to pass.
  Report untested areas and residual findings explicitly.
- With every release, complete the runtime playbook's registry cleanup reconciliation.
- Catalog: `docs/reference/ai-agent-skills.md`; hub: `docs/index.md`.
  Neither is a mandatory startup read.
