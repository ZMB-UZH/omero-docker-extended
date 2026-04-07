# Claude Code instructions

Project-specific instructions for Claude Code sessions working on this repository.

## Fast load order

1. `AGENTS.md`
2. `docs/reference/ai-agent-context-routing.md`
3. `docs/reference/ai-agent-runtime-playbook.md`
4. `docs/reference/ai-agent-skills.md`
5. the nearest plugin or operations doc

## Core rules

- Treat `AGENTS.md` as the universal baseline and this file as a Claude-specific adapter.
- Keep context small: load one task class, one code root, one nearest test module, and one matching skill before broadening scope.
- Follow the routing doc's numeric caps before broadening scope.
- Use `.agents/skills/` and `docs/reference/ai-agent-skills.md` for reusable workflows.
- Never use background agents or subagents unless the user explicitly asks for them.
- Keep configuration environment-driven. Do not hard-code paths, credentials, hostnames, or ports.
- Never edit `env/omero_secrets.env`.
- Update `docs/` when behavior or operating assumptions change.

## Repository anchors

- Service orchestration: `docker-compose.yml`
- Shared library: `omero_plugin_common/`
- Plugins: `omeroweb_omp_plugin/`, `omeroweb_import/`, `omeroweb_admin_tools/`, `omeroweb_imaris_connector/`, `omero_web_zarr/`
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
python3 -m pytest omero_web_zarr/tests/ -v -p no:cacheprovider -W error
python3 -m ruff check .
python3 -m ruff format --check .
```

Use the routing doc and `verification-loop` skill to select the smallest correct subset while iterating, then state the exact verification level achieved.

## Runtime reminders

- Docker compose commands normally need both env files.
- Switch from host `localhost` probes to container-network probes after the first sandbox miss.
- Never run OMERO CLI as `root` inside OMERO containers.
- Use the runtime playbook for Git ownership issues, Docker socket permissions, joined-session rules, and log triage.
