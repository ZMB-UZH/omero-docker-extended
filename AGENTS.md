# AGENTS guide

This file is the **table of contents** for repository-local knowledge used by coding agents.
It is intentionally short. Deep context lives in the files it points to.

## Working contract

- All configuration is environment-driven. Never hard-code paths, credentials, or endpoints.
- Keep changes deterministic, explicit, and reproducible across environments.
- Prefer small, focused pull requests with clear acceptance criteria.
- Update documentation in `docs/` whenever behavior or operating assumptions change.
- Run `python3 tools/lint_docs_structure.py` before proposing changes.
- Prefer focused unit tests or other fast local verification before live runtime tests whenever that is feasible. Use live tests after that, not instead of that, so debugging cycles stay short and failures surface earlier.
- Pin image tags and dependency versions. Never use `:latest`.
- Treat plugin input as untrusted; validate at system boundaries.
- Treat every `*_example*` file in this repository as the canonical reference for expected configuration and helper scripts.
- Assume the system administrator has provisioned the corresponding non-example runtime file(s) on the target host, and that those files match their tracked `*_example*` counterparts unless explicitly documented otherwise.
- The example-file pattern exists so repository updates (including `github_pull_project_bash_example` workflows) can refresh templates without overwriting site-specific runtime files.
- Treat this distribution as a full-stack, multi-container deployment that may contend with pre-existing Docker workloads (for example via host ports, network names, volumes, or maintenance automation). Operators are expected to validate coexistence in their own environment before production rollout.
- Keep agent commentary terse and action-first. Prefer short progress updates over long explanations.
- When a general command fails for a reusable environment-specific reason, update `AGENTS.md` or the relevant doc in the same change so later agents do not repeat it.
- Never create, edit, overwrite, or delete `env/omero_secrets.env` as an AI agent. Treat it as operator-managed secret material.
- For log triage, use the Admin Tools logging path first: prefer the Loki-backed backend used by `omeroweb_admin_tools/logs/` (for example `omeroweb_admin_tools/services/log_query.py`) over ad-hoc `docker logs` sweeps. Fall back to direct container logs, internal log files, or Docker inspection only when the Admin Tools/Loki mechanism returns no data, appears stale/inconsistent with service state, or is itself suspected to be unhealthy.

## Where to look first

1. **`README.md`** -- deployment scope, service topology (17 containers), plugin summaries, quick start.
2. **`ARCHITECTURE.md`** -- layer model, dependency boundaries, data flow, plugin structure.
3. **`docs/index.md`** -- full documentation index with cross-links to every doc.
4. **`docs/QUALITY_SCORE.md`** -- current quality grades and debt priorities.
5. **`docs/exec-plans/`** -- active and completed implementation plans.
6. **`docs/operations/installation-permissions.md`** -- authoritative install/update/bootstrap permission and ownership model.

## Domain map

### Infrastructure (Docker + runtime)
- Service orchestration: `docker-compose.yml` (17 services, single `omero` network)
- Image builds: `docker/omero-server.Dockerfile`, `docker/omero-web.Dockerfile`, `docker/omero-celery-worker.Dockerfile`, `docker/pg-maintenance.Dockerfile`, `docker/redis-sysctl-init.Dockerfile`
- Bootstrap scripts: `startup/10-server-bootstrap.sh`, `startup/10-web-bootstrap.sh`, `startup/40-start-imaris-celery-worker.sh`, `startup/50-install-omero-downloader.sh`, `startup/51-install-imarisconvert.sh`
- Process manager: `supervisord.conf` (OMERO.web + Celery worker in omeroweb container)
- Environment config: `env/omeroserver.env`, `env/omeroweb.env`, `env/omero-celery.env`, `env/grafana.env`
- Path definitions: `installation_paths.env` (15 host filesystem paths)

### Web plugins (Django apps in omeroweb container)
- **`omeroweb_omp_plugin/`** -- filename parsing, metadata annotation, AI-assisted regex, variable sets, job execution
- **`omeroweb_import/`** -- staged upload, OMERO CLI import, SEM-EDX spectrum parsing, file attachment
- **`omeroweb_admin_tools/`** -- log query (Loki), resource monitoring, Grafana/Prometheus proxy, storage analytics
- **`omeroweb_imaris_connector/`** -- Imaris export via Celery tasks, OMERO CLI launch from `omeroweb`, job-service account
- **`omero_plugin_common/`** -- shared env_utils, logging_utils, omero_helpers, request_utils, string_utils

### Databases
- `database` (port 5432): primary OMERO database (`omero` user, `omero` db)
- `database_plugin` (port 5433): OMERO plugin storage (`omero-plugin` user, `omero-plugin` db) -- used by OMERO.web plugins (including OMP and Upload) for user settings, variable sets, AI credentials

### Monitoring and observability
- Stack: Prometheus, Grafana (4 dashboards), Loki, Alloy, blackbox-exporter, node-exporter, cadvisor, postgres-exporter (x2), redis-exporter
- Config files: `monitoring/prometheus/prometheus.yml`, `monitoring/alloy/alloy-config.alloy`, `monitoring/loki/loki-config.yml`, `monitoring/grafana/`
- Operations docs: `docs/operations/monitoring.md`

### Maintenance
- PostgreSQL: `maintenance/postgres/pg-maintenance.sh` (VACUUM ANALYZE weekly, REINDEX monthly)
- Deployment: `installation/installation_script.sh`, `github_pull_project_bash_example`
- Container package/version inspection: `helper_scripts_debian/docker_image_analysis.sh` (use this first when debugging stripped images or missing runtime packages)

## Plugin structure pattern

Each `omeroweb_*` plugin follows a consistent Django app layout:

```
omeroweb_<name>/
├── __init__.py          # default_app_config
├── apps.py              # AppConfig.ready() -> configure_omero_gateway_logging()
├── config.py            # Environment-driven configuration via omero_plugin_common.env_utils
├── constants.py         # Module-level constants
├── urls.py              # Django URL routing
├── views/               # Request handlers (one file per concern)
├── services/            # Business logic and external integrations
│   ├── omero/           #   OMERO API interaction
│   ├── jobs/            #   Job file storage (JSON on tmpfs)
│   └── ...
├── strings/             # Error and message string functions
├── templates/           # Django HTML templates
├── static/              # CSS and JS assets
├── utils/               # Internal helpers
└── tests/               # Unit tests
```

## Key invariants

- Plugin packages depend on `omero_plugin_common`, never the reverse.
- Startup scripts consume only environment-provided configuration.
- All health checks are defined in `docker-compose.yml` with `healthcheck:` blocks.
- The `omeroweb` container runs two processes via supervisord: OMERO.web and the Imaris Celery worker.
- Job state files use `portalocker` for safe concurrent access on tmpfs.
- The `pg-maintenance` sidecar uses `REINDEX CONCURRENTLY` (PostgreSQL 12+), never `VACUUM FULL`.
- Interactive installation defaults Docker image security hardening to enabled, while Docker Scout vulnerability scanning remains opt-in.
- Locale data is preserved across the hardened images; treat package and dependency updates, not locale stripping, as the security control.

## Operational pitfalls for AI agents

### File ownership
- `/opt/omero` is typically owned by `root`. Git operations (fetch, checkout, stash, push) will fail with `Permission denied` unless the agent's user has write access. Request `sudo chown -R <user>:<user> /opt/omero/.git` for git-only access, or `sudo chown -R <user>:<user> /opt/omero` for full file operations.
- **Do not** `chown` bind-mounted data directories (`postgresdb/`, `omero_data/`, `omero_temp/`) to a non-service user — this breaks container runtime permissions. If you must `chown` the repo root, restore data directory ownership afterward via `installation/installation_script.sh` or targeted `chown` commands matching the UIDs in `docker-compose.yml`.

### Git worktrees and finding commits
- The repo uses git worktrees. Active and prunable worktrees live under `/tmp/omero-*`. Standalone clones may also exist there (e.g. `/tmp/omero-alpha-publish`).
- If a commit hash is not found in the main repo (`git cat-file -t <hash>` fails), search worktrees and standalone clones: `find /tmp -maxdepth 2 -name ".git" 2>/dev/null` then `git -C <path> log --all --oneline | grep <hash>`.
- To bring a commit from another local repo: `git fetch <path> <hash>` then `git cherry-pick FETCH_HEAD`.
- Always `git fetch origin <branch>:refs/remotes/origin/<branch> --force` before rebasing to avoid stale tracking refs.

### Docker compose requires secrets
- In this repo, `docker compose build`, `up`, and `config` commands should normally include both `--env-file installation_paths.env` and `--env-file env/omero_secrets.env`. Using only `installation_paths.env` can fail during variable interpolation for secrets-backed settings such as database exporter credentials.
- `docker compose --env-file installation_paths.env ps` will fail if `env/omero_secrets.env` is missing (it is gitignored). Use `docker ps --format "table {{.Names}}\t{{.Status}}"` as a fallback to check container health.

### Sandboxed Docker socket access
- In this environment, agent-shell Docker commands may fail with `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock` even when Docker itself is healthy.
- Treat that exact error as a sandbox/privilege issue, not as evidence that the Docker daemon, container, or mounted socket is down.
- If the Docker command is important to the task, rerun the same command immediately with escalated permissions (`sandbox_permissions=require_escalated`). Do not keep retrying the unprivileged form.
- Apply the same rule to `docker run`, `docker logs`, `docker exec`, `docker inspect`, `docker compose ...`, and similar commands that need daemon access.

### Sandboxed localhost vs container network
- Do not assume host-shell `localhost` or published ports are reachable from the coding-agent sandbox. A host-side `curl http://localhost:3100/...` failure is often a path/isolation issue, not evidence that Loki or the target service is down.
- If a host-side probe to `localhost`, `127.0.0.1`, or a published port fails once, stop repeating it. Switch immediately to the Docker network path by running the probe inside a running container with `docker exec` and the compose service DNS name (for example `http://loki:3100`, `http://omeroserver:4064`, `database:5432`).
- Prefer `omeroweb` for in-network HTTP/Python diagnostics because it already has `curl` and the OMERO.web virtualenv. Use the active runtime interpreter, for example `/opt/omero/web/venv-3.12/bin/python3`.
- In agent commentary, do not keep repeating that a host endpoint "isn't reachable from the sandbox". State the procedural switch once and continue with the container-network probe.

### Dockerfile hardening vs pinned stacks
- Security-hardening passes in Dockerfiles must never blanket-upgrade entire Python virtualenvs after OMERO/plugin packages are installed. Curated allowlists only.
- Treat compatibility-pinned packages as protected runtime state. Examples in this repo include OMERO/ZeroC packages and `omero-web-zarr` with its Zarr compatibility pin.
- If a hardening change upgrades arbitrary outdated packages in a venv, assume it can silently break the image even when the base build succeeds. Fix the Dockerfile, do not normalize the breakage as expected.

### OMERO CLI inside containers
- Never run OMERO CLI as `root` inside `omeroserver` or `omeroweb`. OMERO emits `FATAL: Running ... as root can corrupt your directory permissions.` and the agent must treat that as a procedure error, not as noise to repeat.
- If that root-warning appears once, stop repeating the same command and switch immediately to the container service account.
- Correct wrappers:
  ```bash
  docker exec omero-omeroserver-1 bash -lc 'su omero-server -s /bin/bash -c "HOME=/tmp /opt/omero/server/venv-3.11/bin/omero ..."'
  docker exec omero-omeroweb-1 bash -lc 'su omero-web -s /bin/bash -c "HOME=/tmp /opt/omero/web/venv-3.12/bin/python3 -m pytest ..."'
  ```
- For OMERO CLI, keep connection/auth flags before the subcommand. Example: `omero -s localhost -p 4064 -u root -w "$ROOTPASS" delete Image:123 --wait 120`. Do not place `-s/-p/-u/-w` after `delete`, `import`, or other subcommands.
- When the exact virtualenv path is uncertain, resolve it first as the service user and then run the command as that same service user. Do not probe by executing OMERO CLI as `root`.
- For live OMERO.web import tests, authenticate as a regular OMERO user. The Import plugin intentionally blocks `root`, so using `root` for `/omeroweb_import/` validation is an invalid test procedure.

### Nested shell / heredoc procedure
- Do not nest multiline heredocs inside `docker exec ... bash -lc "..."` when the payload contains Python, regexes, JSON, or mixed quotes. That pattern is fragile and wastes time on shell-escaping failures.
- Preferred pattern for multiline container probes:
  ```bash
  docker exec -i omero-omeroweb-1 python3 - <<'PY'
  ...
  PY
  ```
- For multiline shell payloads, prefer:
  ```bash
  docker exec -i <container> bash -s <<'SH'
  ...
  SH
  ```
- Use `docker exec ... bash -lc '...'` only for short single-line commands. If a command needs substantial escaping, stop and convert it to the `docker exec -i ... <interpreter> - <<'EOF'` form instead of fighting the wrapper.

### Container Python imports
- Do not assume repository modules are importable from `/opt/omero` inside containers. In this deployment they are typically available from the active virtualenv site-packages, for example `/opt/omero/web/venv-*/lib/python*/site-packages`.
- Before running container-local Python that imports `omeroweb_import`, `omeroweb_admin_tools`, or `omero_plugin_common`, first resolve the runtime interpreter/module location with `python -c 'import module; print(module.__file__)'` or inspect the active `venv*/site-packages`.
- If a container Python command fails with `ModuleNotFoundError` for repository modules, do not retry the same command. Switch to the runtime virtualenv interpreter or fix the import path first.

### Testing
- Run each test directory as a separate `pytest` invocation to avoid cross-contamination from `conftest.py` mock stubs. Running all suites in a single `pytest` call causes false failures in log-sanitization and multipart-upload tests.
- In root-owned deployment clones, disable the pytest cache provider so verification stays warning-free even when the repo root is not writable.
- Before rerunning `pytest`, confirm the selected Python environment can import Django. If `python3 -m pytest ...` fails while loading `/opt/omero/conftest.py` with `ModuleNotFoundError: django`, do **not** keep retrying the same host-interpreter command.
- Never probe OMERO.web or plugin imports inside containers with plain `python3` from the container default `PATH`. Resolve the active virtualenv first and use that interpreter (or `source` its `activate` script) for all import checks. Treat `docker exec <container> python3 -c 'import ...'` `ModuleNotFoundError` results as an invalid procedure when the package is expected to live in the OMERO venv.
- Recovery order when Django is missing from the current interpreter:
  1. Switch to the project runtime that already has the web/test dependencies installed (typically the OMERO.web container or its virtualenv) and rerun the split `pytest` commands there.
  2. If only a quick regression check is needed and a test module is intentionally self-stubbing, run it directly with `python3 <path-to-test>.py` so it bypasses repository `conftest.py` loading. Example: `python3 tests/test_import_plugin_regressions.py`.
  3. If dependency-complete execution is unavailable, use `python3 -m py_compile <changed python files>` for syntax validation and report that full `pytest` verification was blocked by missing Django in the active interpreter.
- Agent responses must explicitly state which of the three verification levels above was used; do not imply that host-side `pytest` passed when only direct-module or syntax validation was possible.
- Correct pattern:
  ```bash
  python3 -m pytest tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_imaris_connector/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_admin_tools/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_omp_plugin/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_import/tests/ -v -p no:cacheprovider -W error
  ```
- Always also run: `python3 tools/lint_docs_structure.py`

### Log checking
- Follow AGENTS.md log triage order: Loki first, then container logs.
- For install/update failures, check `${OMERO_DATA_PATH}/installation_logs/<script>_<UTC timestamp>.log` before container logs. These transcripts capture the full visible terminal session and often surface path, prompt, or bootstrap failures faster than service logs.
- When the agent shell cannot reach host `localhost`, query Loki from inside `omeroweb` over the Docker network instead of retrying the host probe.
- Preferred Loki pattern:
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
- Replace `START_NS` and `END_NS` with UTC nanosecond timestamps for the window being investigated.
- Container logs fallback: `docker logs <container> --since 1h --tail 30`

## Knowledge maintenance

- Repository-local knowledge is the system of record. Keep decisions in version control.
- Add cross-links in `docs/index.md` when introducing new top-level docs.
- Validate docs structure: `python3 tools/lint_docs_structure.py`
- CI enforces structure via `.github/workflows/docs-knowledge-base.yml`.
- Capture architectural decisions under `docs/design-docs/`.
- Track technical debt in `docs/exec-plans/tech-debt-tracker.md`.
### Joined OMERO sessions
- When request-scoped helper code opens a second Blitz/ICE client against an end-user's existing OMERO session via `client.joinSession(session_key)`, call `detachOnDestroy()` on the returned session before wrapping it in `BlitzGateway` or closing that helper client.
- Do **not** reopen the importing user's live OMERO.web session inside background threads or subprocess-driven follow-up work. Between HTTP requests OMERO.web may hold no active Blitz reference; if a background helper rejoins that session and then closes, OMERO can destroy the login session and log the user out.
- Do not assume the `job-service` OMERO account can impersonate users. In this repository the bootstrap sync adds `job-service` to groups, but it does not grant OMERO administrator privileges, so `suConn()` can legitimately fail.
- For the Import plugin, keep heavy grouped-import planning in background threads, but do any required user-owned dataset-target preparation on the request path with the live request connection. Do not push that step into background session-rejoin helpers.
- For the Import plugin, keep request-path dataset-target preparation format-agnostic whenever a generic path is feasible. Prefer persisted logical import-unit plans over format-specific or extension-specific heuristics so grouped, packaged, directory-based, and cross-version Zarr imports keep working through the same mechanism. Only bypass this with a narrowly scoped format-specific rule when it is absolutely necessary, and document that reason in the same change.
- For grouped-package naming, prefer OMERO CLI `-n` so the final logical name is set during import instead of requiring a post-import OMERO API rename against the browser session.
- For long-running upload compatibility or post-import work, do not add short browser-side deadlines around status polling. Large structured imports can legitimately spend more than a few minutes in compatibility planning before import begins.
- Do not run `_prepare_job_import_datasets()`, `_build_import_units()`, or OMERO CLI dry-run scans synchronously inside upload HTTP handlers (`upload_files`, `import_step`, `confirm_import`, `prune_upload`). Large `.zarr` uploads can spend long enough in that planning step to trip Gunicorn worker timeouts and surface raw 500s on the final upload request.
- The safe split is: fast request-path dataset-target creation is allowed; heavy `_build_import_units()` probing and OMERO CLI dry-run scans are not.
- Keep heavy grouped-import planning in the background import/compatibility threads, and keep `OMERO_WEB_WSGI_ARGS` configured with a long Gunicorn `--timeout` (the tracked env files now use `--timeout 7200`) so slow chunk uploads are not killed before the browser's own request timeout.
- Keep OMERO CLI dry-run scan timeouts long and environment-driven. The tracked env files now set `OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS=7200`; do not reintroduce a hardcoded short scan timeout for large `.zarr` compatibility/import planning.
- When processing directory-backed formats (`.zarr`, etc.), never load entire arrays or full file contents into memory at once. Operate chunk-by-chunk or file-by-file. A seemingly small zarr can have hundreds of millions of pixels across resolution levels.
- When an OMERO CLI import returns non-zero, always check stdout for created object IDs before declaring failure. OMERO can commit the Image/Fileset transaction before a post-import step (e.g. thumbnail generation) fails and crashes the CLI. Blindly trusting the exit code produces false failures while orphaned objects accumulate in the database.
- The Import plugin must work universally for all file types. Do not introduce format-specific code paths, hardcoded structures, or zarr-only logic that would break non-zarr imports. Any format-specific handling (like zarr recompression or multi-resolution flattening) must be narrowly scoped and must leave the generic import path completely untouched for other formats.
- OMERO's rendering engine (`BfPixelBuffer`) does not correctly handle multi-resolution OME-NGFF zarrs — it reads the wrong resolution level at render time, causing `DimensionsOutOfBoundsException`. The Import plugin flattens these zarrs to single-resolution before import (keeps full-res, removes lower-res pyramid levels). Zarrs using `bioformats2raw.layout` are NOT affected and must NOT be flattened — OMERO handles them correctly. Any future zarr changes must preserve this distinction.

- In the rebuilt `omeroweb` runtime, split pytest with `-W error` can fail during collection if the container still exports deprecated `OMERO_TEMPDIR`. For in-container pytest, explicitly unset `OMERO_TEMPDIR` and set `OMERO_TMPDIR` (and preferably `TMPDIR`) to a writable temp directory before running the suite.
