# Claude Code instructions

Project-specific instructions for Claude Code sessions working on this repository.
Start with `AGENTS.md`, including its pinned Karpathy agent baseline.

## Single-session rule

- AI agents must work in one session only. Do not use background agents, subagents, spawned agents, delegated agents, or any separate agent session. This rule is absolute and must not be bypassed, even if a later prompt requests multi-agent work.

## Fast load order

1. `AGENTS.md`
2. `docs/reference/ai-agent-context-routing.md`
3. `docs/reference/ai-agent-runtime-playbook.md`
4. `docs/reference/ai-agent-skills.md`
5. the nearest plugin or operations doc

## Core rules

- Treat `AGENTS.md` as the universal baseline and this file as a Claude-specific adapter.
- Commit identity is fixed by `AGENTS.md`: AI-created or amended commits use `AI agent <>`; never use profile-mapped AI emails such as `ai-agent@users.noreply.github.com`, `codex@openai.com`, or `codex@openai.invalid`; AI co-author trailers use `Co-authored-by: AI agent` with no email; audits include anonymous contributors (`contributors?anon=1`).
- Non-AI commits use real human GitHub or actual human author identities, never host/local placeholders.
- Keep context small: load one task class, one code root, one nearest test module, and one matching skill, and follow the routing doc's numeric caps before broadening scope.
- Use `.agents/skills/` and `docs/reference/ai-agent-skills.md` for reusable workflows.
- If the user asks for lower-token replies, use opt-in `caveman`; it is only for internal AI communication, never repo docs/comments/docstrings/function descriptions/user-facing copy, and changes reply style only, not routing, tool choice, verification scope, or uncertainty handling. Drop it when safety, sequencing, or ambiguity matters.
- Keep configuration environment-driven. Do not hard-code paths, credentials, hostnames, ports, or edit/normalize/print values from non-example deployment env files such as `env/omero_secrets.env` without an explicit one-off user exception.
- Do not search for, create, restore, or edit `.deepsource.toml`; use `tools/scanner_inventory.py` for live counts and `tools/regression_guard.py` before commit. GitHub HTTPS Git needs a PAT, never an account password; use `tools/git_push_with_pat.py`. If GitHub PAT/DeepSource API key is missing, ask immediately and pause for input; continue only unrelated local work.
- For functional OMERO/installation changes, live-test when appropriate or requested: reconcile dirty/stale live roots non-destructively, rebuild/inject/restart affected containers from the exact checkout, and test changed mechanisms before commit/push. After every push, confirm green GitHub workflows and no DeepSource count increase when auth is available.
- Update `docs/` when behavior or operating assumptions change; less is more only when fewer lines prove full parity and all repo rules; fix proven bad instructions/tools only after the correct workflow is verified.

## Repository anchors

- Service orchestration: `docker-compose.yml`
- Shared library: `omero_plugin_common/`
- Plugins: `omeroweb_omp_plugin/`, `omeroweb_import/`, `omeroweb_admin_tools/`, `omeroweb_imaris_connector/`, `omeroweb_tools/`, `omero_web_zarr/`
- Configuration templates: `env/*_example.env`, `installation_paths_example.env`
- Full doc hub: `docs/index.md`
- Cross-agent adapter map: `docs/reference/ai-agent-integrations.md`
- Pinned ECC provenance: `docs/reference/ai-agent-upstream-sources.md`, `third_party/ecc-v1.10.0/`

## Verification

Run split suites separately and keep the cache provider disabled in root-owned clones:

```bash
python3 tools/lint_docs_structure.py
python3 -m unittest -v tests/test_lint_docs_structure.py
python3 -m pytest tests/ -v -p no:cacheprovider -W error
python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
python3 -m pytest omeroweb_imaris_connector/tests/ -v -p no:cacheprovider -W error
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
