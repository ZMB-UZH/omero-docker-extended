# Claude Code instructions

Project-specific Claude adapter; start with `AGENTS.md` and its pinned Karpathy agent baseline.

## Single-session rule

- AI Agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule must not be bypassed except for the Codex Security exception below.
- Codex Security exception: multi-worker vulnerability scanning is on-demand only. Before launching a Codex Security scan, pause and clearly ask the user to authorize the exact scan target, mode, and worker/subagent use. Continue only after explicit user approval or the Codex Security UI Start Scan handoff; all edits, commits, pushes, releases, and reconciliation stay in the parent session.

## Fast load order

1. `AGENTS.md`
2. `docs/reference/ai-agent-context-routing.md`
3. `docs/reference/ai-agent-runtime-playbook.md`
4. `docs/reference/ai-agent-skills.md`
5. the nearest plugin or operations doc

## Core rules

- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI Agent <>`; never use profile-mapped AI/tool emails; AI co-author trailers use `Co-authored-by: AI Agent` with no email; audits include anonymous contributors (`contributors?anon=1`).
- Non-AI commits use real human GitHub or actual human author identities, never host/local placeholders. Develop, commit, push, and verify on the current remote default branch unless the user explicitly names another branch; resolve it dynamically and do not create feature branches, PR branches, temporary remote branches, or draft PRs for routine work.
- Pause before every release and obtain explicit confirmation of the exact GitHub release tag and Docker repository/tag; never infer or auto-increment versions. Require a matching human-readable `CHANGELOG.md` section, automated disclosure validation, and human public-safety review.
  Never publish credentials, personal or host-specific information, private infrastructure, findings, vulnerability mechanics, or exploit-enabling detail. Publish the same notes through GitHub and the Docker carrier.
- Pause before deleting any pre-existing or persistent object. Each GitHub release, Git tag, Docker image/tag, branch, file tree, volume, backup, data object, or remote artifact needs fresh approval naming that one deletion; blanket, earlier, same-version, replace, or recreate permission never carries forward.
- Keep context small: load one task class, one code root, one nearest test module, and one matching skill; follow the routing doc's numeric caps, batch bounded read-only work, reuse fresh evidence, and never rerun unchanged checks or tools without a changed input or hypothesis.
- CocoIndex: broad navigation has a mandatory `cocoindex-code` MCP check and uses `.agents/skills/cocoindex-code-search/` for semantic routing before exact `rg`; use direct `rg` first only for precise string, symbol, scanner-count, or already-small searches.
  State cold-index waits once; external cache/state stays under `AGENT_COCOINDEX_HOME`, outside `.cocoindex_code/`, text-decodable; `mcp-smoke` verifies MCP changes. For current edits run `index --allow-dirty-index` or `search --refresh "<query>"`; MCP search itself never refreshes and can return stale active-index text.
- If the user asks for lower-token replies, use opt-in `caveman`; it is only for internal AI communication, never repo docs/comments/docstrings/function descriptions/user-facing copy, and changes reply style only, not routing, tool choice, verification scope, or uncertainty handling. Drop it when safety, sequencing, or ambiguity matters.
- Keep configuration environment-driven. Do not hard-code paths, credentials, hostnames, ports, or edit/normalize/print values from non-example deployment env files such as `env/omero_secrets.env` without an explicit one-off user exception.
- Do not search for, create, restore, or edit `.deepsource.toml`; use `tools/scanner_inventory.py` for live counts and `tools/regression_guard.py` before commit. GitHub HTTPS Git needs a PAT, never an account password; use `tools/git_push_with_pat.py`. If a GitHub PAT is missing, ask immediately and pause for input; continue only unrelated local work until GitHub auth is available.
- Live-test OMERO/installation changes when appropriate/requested: reconcile dirty/stale live roots, rebuild/restart from exact checkout before commit/push, then confirm green GitHub workflows and no DeepSource count increase when auth/repo access exists; if DeepSource is skipped or unavailable due credentials, subscription, repo access, or API availability, report it and continue verification.
- Update `docs/` when behavior or operating assumptions change; less is more only when fewer lines prove full parity and all repo rules; fix proven bad instructions/tools only after the correct workflow is verified.

## Repository anchors

- Service orchestration: `docker-compose.yml`
- Shared library: `omero_plugin_common/`
- Plugins: `omeroweb_omp_plugin/`, `omeroweb_import/`, `omeroweb_admin_tools/`, `omero_imaris_connector/`, `omeroweb_tools/`, `omero_web_zarr/`
- Configuration templates: `env/*_example.env`, `installation_paths_example.env`
- Full doc hub: `docs/index.md`
- Cross-agent adapter map: `docs/reference/ai-agent-integrations.md`
- Pinned ECC provenance: `docs/reference/ai-agent-upstream-sources.md`, `third_party/ecc-v2.0.0/`

## Verification

Run split suites separately and keep the cache provider disabled in root-owned clones:

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
python3 tools/regression_guard.py scan
```

If `ruff` is unavailable as a binary on the active host, use `python3 -m ruff check .` and `python3 -m ruff format --check .` instead. Host `ruff` must match the repo-pinned version before claiming local verification.

Use the routing doc and `verification-loop` skill to select the smallest correct subset while iterating, then state the exact verification level achieved.

## Env file protection

Deployment config files (`env/*.env`, `installation_paths.env`) are **untracked** and **irreplaceable** from git alone. Before ANY file-sync or rsync operation:

```bash
python3 tools/env_safety_guard.py check    # verify all exist
python3 tools/env_safety_guard.py backup   # create timestamped backup
```

**NEVER use `rsync --delete` or any tree-replacement command on the working directory.** Always sync via a disposable clone. See `docs/operations/repository-sync-safety.md`.

## Runtime reminders

- Agent/script Docker Compose commands use the full explicit env-file list from the runtime playbook.
- Discover live host bindings, container IDs, and OMERO.web virtualenv paths from Compose/container state; default ports and paths are not probe inputs.
- Switch from host `localhost` probes to container-network probes after the first sandbox miss.
- Never run OMERO CLI as `root` inside OMERO containers.
- Use the runtime playbook for Git ownership issues, Docker socket permissions, joined-session rules, and log triage.
