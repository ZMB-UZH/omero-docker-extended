# AI Agent Runtime Playbook

Deep operational guidance for AI agents. `AGENTS.md` should route here instead of duplicating these details.

## Git ownership and local clones

- Deployment clones are often root-owned. `git` write operations can fail until ownership is fixed.
- If a read-only `git` command reports dubious ownership, use `git -c safe.directory=<repo> ...` for inspection.
- Do not `chown` bind-mounted data directories such as `postgresdb/`, `omero_data/`, or `omero_temp/` to a non-service user.
- Worktrees and related clones can exist under `/tmp/omero-*`. Search them before declaring a commit missing.
- Before rebasing, refresh tracking refs explicitly with `git fetch origin <branch>:refs/remotes/origin/<branch> --force`.

## Cross-repository sync safety

- Treat repo-to-repo copying as tree-content sync, not branch-history integration.
- Resolve the remote default branch explicitly before pushing; do not assume it matches the local branch name.
- If there is no expected merge base, stop and follow `docs/operations/repository-sync-safety.md`.
- Keep dated `backup/<date>-<reason>/...` refs until the repaired branch family is verified.

## Docker compose and env files

- In this repo, `docker compose build`, `up`, and `config` normally require both `--env-file installation_paths.env` and `--env-file env/omero_secrets.env`.
- `docker compose --env-file installation_paths.env ps` fails when the secrets env file is absent. Use `docker ps --format "table {{.Names}}\t{{.Status}}"` as the fallback probe.
- Treat a Docker socket permission error as a sandbox or privilege problem, not proof that Docker is down.

## Host sandbox vs container network

- Do not keep retrying host-side `localhost` probes after one failure.
- Switch to the Docker network path from inside a running container, usually `omeroweb`, using service DNS names such as `http://loki:3100`.
- Prefer the runtime interpreter inside the OMERO.web virtualenv for container-local Python checks.

## OMERO CLI and container Python

- Never run OMERO CLI as `root` inside `omeroserver` or `omeroweb`.
- Put OMERO auth flags before the subcommand.
- Resolve the active virtualenv first if the exact interpreter path is uncertain.
- For OMERO.web import validation, authenticate as a regular OMERO user; the Import plugin intentionally blocks `root`.
- If repository modules are missing inside a container, switch to the runtime virtualenv instead of retrying plain `python3`.

## Multiline container probes

Prefer:

```bash
docker exec -i omero-omeroweb-1 python3 - <<'PY'
...
PY
```

or:

```bash
docker exec -i <container> bash -s <<'SH'
...
SH
```

Avoid deeply nested heredocs inside `docker exec ... bash -lc "..."`.

## Testing policy

- Fix production code instead of weakening tests.
- Run each test directory as a separate `pytest` invocation.
- In root-owned clones, keep `-p no:cacheprovider -W error`.
- If host `pytest` cannot import Django, switch to the dependency-complete runtime first.
- If full runtime verification is blocked, use direct-module or syntax validation only as an explicit fallback and report that limitation accurately.

## Verification order

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

## Log triage order

1. Admin Tools or Loki-backed log access
2. installation transcripts under `${OMERO_DATA_PATH}/installation_logs/`
3. container logs
4. direct Docker inspection

Preferred Loki pattern:

```bash
docker exec -i omero-omeroweb-1 /opt/omero/web/venv-3.12/bin/python3 - <<'PY'
import json, urllib.parse, urllib.request
params = urllib.parse.urlencode({
    "query": '{compose_service="omeroserver", log_type="internal"} |~ "(?i)error"',
    "direction": "backward",
    "start": "START_NS",
    "end": "END_NS",
    "limit": "50",
})
with urllib.request.urlopen(f"http://loki:3100/loki/api/v1/query_range?{params}", timeout=20) as response:
    print(json.loads(response.read().decode("utf-8", errors="replace")))
PY
```

## Joined-session and import-thread rules

- When request-scoped helper code joins an existing end-user OMERO session, call `detachOnDestroy()` on the joined session before wrapping it in `BlitzGateway`.
- Do not reopen the importing user's live OMERO.web session inside background threads or subprocess follow-up work.
- Do not assume the `job-service` account can impersonate users with `suConn()`.
- Keep request-path dataset-target preparation light and format-agnostic.
- Keep heavy import-unit planning and CLI dry-run scans in background compatibility/import threads, not in upload HTTP handlers.
- For grouped-package naming, prefer OMERO CLI `-n` over post-import rename work when possible.
- Keep native Zarr scan timeouts long and environment-driven.
- When OMERO CLI returns non-zero, check stdout and stderr for created object IDs before declaring the import failed.

## Native Zarr and rendering notes

- `omero zarr import` is reference-based and stores the managed-store path in `Image.details.externalInfo.lsid`.
- Native Zarr metadata finalization must normalize shorthand units such as `nm` or `µm` before persisting physical sizes.
- Restage browser uploads to a durable server-readable location before native Zarr import; do not point native import at `_staged/`.
- Route every Zarr layout supported by the installed `omero-cli-zarr` runtime through the native path.
- For NGFF-backed images, thumbnail/render failures often surface in `master.err` from the Zarr pixel service or reader stack.
- OMERO.iviewer and OMERO.figure import `omeroweb.webgateway.marshal.imageMarshal` by value at import time. Hardened marshal overrides must patch already-imported viewer modules too.

## Security workflow reminders

- Before security-sensitive edits, read `docs/reference/ai-agent-security-prevention-playbook.md`, `docs/reference/code-scanning-resolved-findings.md`, and `docs/operations/code-scanning.md`.
- Fix root causes before considering suppressions.
- Refresh action versions from official GitHub releases or tags before touching workflow pins.
- Do not bind pure CI jobs to GitHub environments unless deployment records are intended.
