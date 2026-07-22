# AGENTS guide

Repository entrypoint for coding agents. Keep it small: load only the smallest correct context for the current task, then stop expanding.

## Pinned Karpathy agent baseline

Adapted from <https://github.com/forrestchang/andrej-karpathy-skills> at `2c606141936f1eeef17fa3043a72095b4765b9c2`.
Apply this agent-neutral baseline before repo-specific rules without weakening
single-session, identity, configuration, security, live-verification, or workflow requirements.

- Think before coding: state assumptions, surface ambiguity and tradeoffs, and
  ask when uncertainty would otherwise become a guess.
- Simplicity first: solve the requested problem with the minimum maintainable
  code; avoid speculative features, abstractions, configurability, or new
  defensive branches that repo contracts prove unnecessary.
- Compact and efficient code matters, not just lower token usage. Prefer
  shorter, clearer implementations that preserve behavior; do not trade away
  security, environment safety, live-verification evidence, or OMERO runtime
  correctness for fewer lines.
- Surgical changes: touch only what the task requires and preserve local
  contracts. Match existing style only when it is already clear, efficient,
  and consistent; otherwise improve style only where the task gives evidence
  and scope to do so. Clean up only orphans created by your change and mention
  unrelated debt instead of editing it.
- Goal-driven execution: turn work into verifiable success criteria, reproduce
  bugs with a test or concrete failing check when practical, loop until the
  relevant checks pass, and report the exact verification performed.
- Treat upstream `EXAMPLES.md` as optional maintenance rationale only. Do not
  load or import it by default or let it override repository rules.

## AI commit identity

- AI Agents that create, amend, merge, cherry-pick, squash, rebase, or rewrite commits must use `AI Agent <>` for author and committer, and any AI co-author trailer must be `Co-authored-by: AI Agent` with no email. Use command-scoped config such as `git -c user.name='AI Agent' -c user.email= commit ...`; never reuse human, host, GitHub, previous-commit, or global identity.
- If a tool cannot produce the empty email field shown as `<>`, or would insert a named AI tool, host, local account, fake address, vendor identity, or profile-mapped AI/tool address, stop before committing. Human contributors are not required to use the AI identity.
- Identity audits must check authors, committers, `Co-authored-by` trailers, and GitHub anonymous contributors (`contributors?anon=1`) from fresh branch-head fetches; report PR-head refs separately. Non-AI commit identities must be real human GitHub identities or actual human author names with real email addresses, never host/local placeholders or fake emails.

## Single-session rule

- AI Agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule must not be bypassed except for the Codex Security exception below.
- Codex Security exception: multi-worker vulnerability scanning is on-demand only. Before opening or launching a Codex Security scan, pause and clearly ask the user to authorize the exact scan target, mode, and worker/subagent use.
- Continue only after explicit user approval or the Codex Security UI Start Scan handoff. Use minimum required subagents only when the user explicitly asks for that workflow and the loaded security skill requires them; all edits, commits, pushes, releases, and reconciliation stay in the parent session.

## Default-branch development rule

- AI Agents must develop, commit, push, and verify on the repository's current remote default branch unless the user explicitly names another branch. Resolve it from the remote, for example with `git remote show origin` or `git symbolic-ref refs/remotes/origin/HEAD`, and never hard-code `main` in agent workflow decisions.
- Do not create feature branches, PR branches, temporary remote branches, or draft PRs for routine coding, verification, workflow checks, or scanner checks. If one is created accidentally, move the work back to the resolved default branch, delete the temporary branch, close any PR, and continue there.

## Destructive operations and releases

- Pause before every deletion of a pre-existing or persistent object and ask for fresh, explicit user approval naming exactly one object and one deletion operation. Separate approval is required for each file or directory tree, branch, Git tag, GitHub release, Docker image or tag, container, volume, backup, data object, and local or remote artifact.
- Approval never carries forward. Blanket or "full" permission, an earlier deletion approval, a replace/recreate request, and approval for the same version or object in an earlier run do not authorize a later deletion. Do not start a command, script, or workflow capable of the deletion until that exact approval has been received.
- Before every release, pause and ask the user to provide or confirm the exact GitHub release tag and the exact Docker repository/tag. Never infer, auto-increment, or reuse a release version from history or an earlier conversation. Release replacement needs the release/tag choices plus separate fresh approvals for each GitHub release, Git tag, and Docker tag deletion.
- Every release must use a version-matched section in `CHANGELOG.md` with clear human-readable changes, verification, and upgrade impact. Publish the rendered notes as the GitHub release body and asset, and include the same notes and OCI release metadata in the Docker carrier.
  Before publication, require automated disclosure validation and explicit human public-safety review; public notes must never contain credentials, personal or host-specific information, private infrastructure details, security findings, vulnerability mechanics, or other exploit-enabling detail.

## Mandatory security read order

Before writing or rewriting code or tests that touch filesystem paths, file I/O, logs, HTTP responses, outbound HTTP, SQL, subprocesses, Dockerfiles, workflows, secrets, authentication, or authorization, consult these in order:

1. `python3 tools/regression_guard.py catalog` and `python3 tools/regression_guard.py scan` — the canonical machine-checked anti-regression gate (catalog rules cover every recurring closed-alert family).
2. `docs/reference/ai-agent-security-prevention-playbook.md` for normative coding patterns and external best-practice links.
3. `docs/reference/code-scanning-resolved-findings.md` and `docs/operations/code-scanning.md` for closed-alert history and the live alert workflow (reference only).

Do not start coding until you can name the helper boundary you will harden and the regression tests that will prove the fix.

## Fast load order

1. `docs/reference/ai-agent-context-routing.md` for the smallest correct docs, code roots, skills, and test lanes.
2. `docs/reference/ai-agent-runtime-playbook.md` for Docker, Git ownership, container-network probing, OMERO CLI, testing, log triage, and joined-session rules.
3. `docs/reference/ai-agent-skills.md` and `.agents/skills/` for reusable repo workflows.
4. `docs/index.md` only when the routing doc is insufficient.
5. The nearest plugin or operations doc for the touched subsystem.

## Working contract

- All configuration is environment-driven. Never hard-code paths, credentials, or endpoints.
- In committed code and tests, do not hard-code installation-specific clone paths or host paths unless the product intentionally guarantees that runtime path.
- For live checks, discover active container IDs, published host bindings, service ports, and runtime interpreter paths from Compose and container state. Documented default ports are reference facts, not probe inputs.
- Treat ignored live env files created from tracked `env/*_example.env` contracts as operator-owned host state. Do not regenerate, normalize, migrate, or auto-edit them from example files unless the user explicitly asks for that exact host-local action.
- When a tracked `env/*_example.env` default changes, update the tracked example contract and docs/tests. Do not invent installer migrations, upgrade rewrites, or automatic mutation of existing host env files unless the user explicitly requests that behavior and the change is separately reviewed and tested.
- If live verification shows an ignored host env file has an outdated value, report the exact key and value. Change it only as a narrow host-local edit after explicit user approval, preserving all unrelated values.
- Custom import workflows must keep upload and conversion work in tmp/shared-transfer space and move data into `ManagedRepository` only at the final persistent import handoff.
- Do not assume any non-root user, group, Dataset, Project, Screen, Image, file, annotation, script ID, plugin row, or other OMERO object already exists in a live installation unless the current task explicitly provisions it first.
- When tests or live verification need OMERO images, files, annotations, acquisition metadata, users, groups, or plugin index rows, create deterministic disposable fixtures inside the test or verification flow and clean or isolate them by unique names. A user-named live object may be inspected only as a diagnostic target, never as a product assumption or required test precondition.
- Keep changes deterministic, explicit, minimal, and reproducible; less is more when fewer lines prove full functional parity and satisfy every repo rule.
- If the user explicitly asks for lower-token replies, use opt-in `caveman` only for internal AI communication. It never rewrites repo docs, comments, or user-facing copy, and never changes routing, tools, verification, or uncertainty handling; drop it for destructive/security/ambiguous work.
- Update `docs/` whenever behavior or operating assumptions change; preserve every required meaning when compacting docs, add objective regression checks before line-budget changes, and fix a proven avoidable retry/error loop in repo instructions/tools only after the correct workflow is verified.
- When creating or editing plugin help pages, follow
  `docs/reference/plugin-help-page-style-guide.md` for user-facing copy,
  screenshots, collapse behavior, and button/link consistency.
- Run `python3 tools/lint_docs_structure.py` after documentation or instruction-surface edits.
- Use Ruff as the canonical Python formatter and lint gate; host `ruff` must match the repo-pinned version, then run `ruff check .` and `ruff format --check .`; if only the module is available, use `python3 -m ruff check .` and `python3 -m ruff format --check .`.
- Run split `pytest` suites separately; never combine the repo into one giant `pytest` process.
- Do not modify README badges or workflow badges unless the user explicitly asked for that badge change.
- The README top badge row is generated by `tools/update_readme_badges.py`; keep it limited to active repository-native status surfaces and do not add a DeepSource active-issues badge.
- Do not search for, create, restore, or edit `.deepsource.toml`; DeepSource counts need explicit credentials and can be unavailable for auth, subscription, or access. GitHub HTTPS Git operations require a PAT/credential manager, never an account password; use `tools/git_push_with_pat.py`. If a GitHub PAT is unavailable, ask immediately and pause; do not retry auth failures except local tasks.
  If DeepSource scanning is skipped or unavailable, report it as unavailable, not zero, and continue the rest of the local and GitHub workflow verification instead of treating it as a blocking failure.
- After every push, verify GitHub workflows are green and compare DeepSource grouped issues and issue occurrences for the pushed commit against the pre-push baseline when DeepSource auth and repository access are available; if either count increased, fetch grouped issue details, fix the regression root cause, rerun targeted tests, and repeat post-push verification.
  When many unrelated workflows fail at once, check official GitHub Status and
  exact job logs before deciding whether the root cause is an outage or a repo
  regression.
- Prefer focused unit/contract tests first; when live testing makes sense or the user explicitly requests it for functional OMERO/install/Compose/startup/plugin/env-contract changes, reconcile the live root, preserve unrelated dirty work non-destructively, match the exact checkout, run env guards, rebuild/inject/restart affected containers, and test mechanisms end to end before commit/push.
- Pin image tags and dependency versions. Never use `:latest`.
- Treat plugin input as untrusted and validate at system boundaries.
- Treat every tracked `*_example*` file as the canonical configuration contract.
- Prefer repo-local skills before falling back to generic workflows.
- For broad repo navigation, the CocoIndex Code gate is mandatory: check for a `cocoindex-code` MCP server or tool first, then use `.agents/skills/cocoindex-code-search/` as semantic routing before exact `rg`. Use direct `rg` first only for precise string, symbol, scanner-count, or already-small searches.
  It uses one XDG/`AGENT_COCOINDEX_HOME` install with per-repo external mirrors/DB/runtime dirs, never live-checkout `.cocoindex_code/`, and does not weaken the single-session rule.
  If CocoIndex starts a cold semantic index, tell the user once that the first search can take several minutes and later searches reuse the external cache. It indexes text-decodable mirrored files through CocoIndex Code 0.2.37; do not claim binary semantic search, add repo-specific language rewrites/file-type exclusions, or use `--lang` on mixed-language files unless proven safe.
  After MCP install or launcher changes, prove `initialize`, `list_tools`, and probes with `python3 tools/cocoindex_agent_search.py mcp-smoke`; use `--include-search` only against an active index. For current edits run `python3 tools/cocoindex_agent_search.py index --allow-dirty-index` or `search --refresh "<query>"`; MCP search itself never refreshes and can return stale active-index text.
- Native adapter files exist for GitHub Copilot, Cursor, Claude, and Gemini. Treat `AGENTS.md` as the universal baseline; adapters are additive only.
- Never create, edit, overwrite, delete, normalize, or print values from non-example deployment env files (`.env`, `installation_paths.env`, `env/*.env`) unless the user explicitly grants a one-off exception for that exact operation; examples remain the tracked contract.
- Run `python3 tools/env_safety_guard.py check` and `python3 tools/env_safety_guard.py compose-guard` before any `docker compose` operation to verify deployment env files are intact and the checkout matches the live installation root. Use `python3 tools/env_safety_guard.py template-check` only to report env-template key drift without values.
- Validate Markdown with `npx --yes markdownlint-cli2@0.23.1` after editing `.md` files; for frontend preview, run `export PATH="$(python3 tools/frontend_preview_tooling.py install-node --print-bin):$PATH"` before bootstrap if Node.js mismatches. Add workflow `setup-node` only when a workflow actually runs host Node.js; Super-Linter uses its pinned container.
- Before committing or pushing code, tests, workflow, or documentation changes, run `python3 tools/run_local_workflow_gates.py --setup --profile ci`. Use `--profile all` when the Docker-backed Super-Linter gate must be mirrored locally.
- `tools/run_local_workflow_gates.py` installs Python-backed workflow tools from the same hash-pinned requirement files used by GitHub Actions and runs the locally reproducible workflow gates. GitHub-only services such as SARIF upload, OIDC publishing, CodeQL hosted analysis, repository Scorecard checks, and Codecov upload still require the post-push workflow result.

## Repository map

- `README.md`: deployment scope, service topology, quick start, and plugin summaries.
- `ARCHITECTURE.md`: layer model, dependency boundaries, data flow, and plugin structure.
- `docs/index.md`: full documentation hub.
- `docs/reference/ai-agent-context-routing.md`: minimal task router for docs, code roots, skills, and verification lanes.
- `docs/reference/ai-agent-runtime-playbook.md`: deep operational procedures and pitfalls.
- `docs/reference/ai-agent-skills.md`: harness-neutral skill catalog for `.agents/skills/`.
- `docs/reference/ai-agent-integrations.md`: Copilot, Cursor, Claude, Gemini, and ECC adapter map.
- `docs/reference/ai-agent-upstream-sources.md` and `third_party/ecc-v2.0.0/`: pinned ECC provenance.
- `docs/reference/ai-agent-security-prevention-playbook.md`: canonical anti-regression security guide.
- `docs/reference/plugin-help-page-style-guide.md`: canonical plugin help page formatting and verification rules.

## Domain roots

- Infrastructure: `docker-compose.yml`, `docker/`, `startup/`, `installation/`, `maintenance/`, `env/*_example.env`, `installation_paths_example.env`
- Web plugins: `omeroweb_omp_plugin/`, `omeroweb_import/`, `omeroweb_admin_tools/`, `omero_imaris_connector/`, `omeroweb_tools/`, `omero_web_zarr/`
- Shared library: `omero_plugin_common/`
- Monitoring: `monitoring/`, `docs/operations/monitoring.md`
- Tests: `tests/`, `omero_plugin_common/tests/`, `omero_imaris_connector/tests/`, `omeroweb_admin_tools/tests/`, `omeroweb_omp_plugin/tests/`, `omeroweb_import/tests/`, `omeroweb_tools/tests/`, `omero_web_zarr/tests/`

## Topology facts

- This deployment has `21 Compose services` total and runs `20 long-running runtime containers by default`; 21 when the profile-gated `crowdsec` service is enabled.
- The `redis-sysctl-init` helper is a one-shot profile-gated service, not a long-running runtime container.
- The `omeroweb` container runs OMERO.web, Imaris and Tools Celery workers, and the storage-quota reconciliation loop under `supervisord`.

## Small-context rules

- Start with `rg` and the routing doc before opening files.
- Treat the routing doc's numeric caps as mandatory, not advisory.
- Open one domain doc, one nearest test module, and one matching skill before broadening context.
- Stop once you can name the exact files to edit and the exact suites to run.
- Summarize long docs once, batch independent read-only work with bounded output, and reuse fresh evidence instead of reopening files or repolling unchanged external state.
- Keep a verification ledger keyed by command and relevant tree/runtime state: do not retry a failed tool without a changed hypothesis or input, do not repeat an unchanged passing gate, and run the full matrix once against the stable final tree.

## Verification minimum

```bash
python3 tools/lint_docs_structure.py
python3 -m unittest -v tests/test_lint_docs_structure.py
python3 -m pytest tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_imaris_connector/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_admin_tools/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_omp_plugin/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_import/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_tools/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_web_zarr/tests/ -v -p no:cacheprovider -W error
ruff check .
ruff format --check .
```

If the active host exposes Ruff only as a Python module, replace those two Ruff commands with `python3 -m ruff check .` and `python3 -m ruff format --check .`.

Use the routing doc and `verification-loop` skill to choose the minimal subset during normal iteration, but report the exact verification level achieved.

## Deep references

- Operational pitfalls, Docker socket/network procedure, OMERO CLI rules, testing fallbacks, log triage, and joined-session constraints live in `docs/reference/ai-agent-runtime-playbook.md`.
- Anti-regression gate is `tools/regression_guard.py` (machine-checked catalog); `docs/reference/ai-agent-security-prevention-playbook.md`, `docs/reference/code-scanning-resolved-findings.md`, and `docs/operations/code-scanning.md` are reference-only history.
- When a reusable environment-specific failure is discovered, update the relevant deep doc in the same change so later agents do not rediscover it.
