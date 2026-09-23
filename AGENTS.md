# AGENTS guide

Mandatory baseline for every coding agent. Read once per revision; load only the
task-specific sections linked below. Adapters inherit this policy, not a copy.

## Safety and scope

- Work in one session. No background, delegated, or separate agent session.
  Codex Security scans are on-demand only: pause and clearly ask the user for
  the exact scan target, mode, and worker/subagent use. Continue only after
  explicit user approval or the Codex Security UI Start Scan handoff. Minimum
  required workers only; all edits, commits, pushes, releases, and reconciliation
  stay in the parent session.
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
- Resolve the current remote default branch; develop, commit, push, and verify
  there unless the user explicitly names another branch. No routine feature
  branches, PR branches, temporary remote branches, or draft PRs.
- AI-created/rewritten commits require author and committer `AI Agent <>` and
  only `Co-authored-by: AI Agent` trailers. Use command-scoped Git identity.
  Stop if the tool cannot preserve that identity.

## Mandatory efficiency

Lower-token operation is the default, without reducing reasoning or verification.

- CocoIndex Code is mandatory for broad semantic routing. Check the
  `cocoindex-code` MCP tool first; follow
  [cocoindex-code-search](.agents/skills/cocoindex-code-search/SKILL.md).
  Exact known symbols, strings, scanner counts, and already-small scopes use
  bounded `rg` directly. Confirm semantic hits against current source.
  Never silently trust a stale index or install/refresh one through MCP search.
- Apply [caveman](.agents/skills/caveman/SKILL.md) lite by default to internal AI
  communication: remove repetition, not reasoning or evidence. This is mandatory,
  not opt-in. Public text, code, commands, exact errors, and user replies stay
  normal prose and lossless. Expand normally for safety, approvals, ambiguity,
  incidents, and ordered procedures; required progress updates remain mandatory.
- Use the [context router](docs/reference/ai-agent-context-routing.md) only when
  the task location is unknown; load one matching skill, not the catalog.
  Follow its numeric caps, escalating with a stated reason when correctness
  needs more context. Never use a budget to skip required analysis or tests.
- Keep a verification ledger: command, relevant source/configuration/runtime
  identity, result, and evidence location; reuse fresh evidence. Retry failures
  only after changing a hypothesis/input. Run the full required matrix once on
  the stable final tree. Preserve raw logs and exit status; inspect complete
  failures, not only a truncated tail.
- Do not reread unchanged files, dump trees/logs, poll unchanged jobs, load
  upstream reference skills, or rediscover known tool schemas by default.
  Keep handoffs to decisions, changed files, evidence, risks, and next action.
  Never compress user requests or claim billing savings from byte counts.

## Before the matching action

Read only the required section of
[task contracts](docs/reference/ai-agent-task-contracts.md):

| Action | Required contract and next reference |
| --- | --- |
| Authorized Codex Security scan | Single-session rule; approved target/mode/workers only |
| Code/design decisions | Pinned Karpathy agent baseline; nearest implementation and tests |
| Paths, I/O, logging, HTTP, SQL, subprocesses, Docker, workflows, secrets or auth | Mandatory security read order: `regression_guard.py catalog`, `scan`, matching prevention/history sections |
| Deployment configuration, imports or test data | Configuration; tracked `*_example*` contracts |
| Live, Docker/Compose or sync | Runtime and sync; `docs/reference/ai-agent-runtime-playbook.md`; env `check` and `compose-guard` before Compose |
| Documentation or instruction edits | Documentation; `docs/reference/ai-agent-integrations.md` for adapters |
| Tests, commit or push | Verification; `.agents/skills/verification-loop/SKILL.md` |
| Git identity, branches, deletion or publication | AI commit identity; Default-branch development rule; Destructive operations and releases |
| Index/MCP maintenance | CocoIndex; `.agents/skills/cocoindex-code-search/SKILL.md` |

## Completion gate

- Preserve every required meaning and add objective regression checks before
  compacting instructions. Fewer lines must prove full functional parity and
  satisfy every repo rule. Do not weaken approvals, scanner scope, or tests.
- Before commit/push run
  `python3 tools/run_local_workflow_gates.py --setup --profile ci`.
  Scanner/action changes require `--profile all` with the exact engine.
  Run split pytest suites separately, never one monolithic process.
- Functional OMERO/install changes require fresh-code live verification when
  appropriate/requested, before commit/push. Agent-only edits do not justify
  rebuilding unchanged application images or restarting services.
- After every push, verify GitHub workflows and alert deltas for that exact
  commit. No suppression, scope reduction, or score manipulation to pass.
  Report untested areas and residual findings explicitly.
- Detailed skill catalog: `docs/reference/ai-agent-skills.md`; full docs hub:
  `docs/index.md`. Neither is a mandatory startup read.
