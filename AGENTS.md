# AGENTS guide

This file is the **table of contents** for repository-local knowledge used by coding agents.
It is intentionally short. Deep context lives in the files it points to.

## Working contract

- All configuration is environment-driven. Never hard-code paths, credentials, or endpoints.
- Keep changes deterministic, explicit, and reproducible across environments.
- Prefer small, focused pull requests with clear acceptance criteria.
- Update documentation in `docs/` whenever behavior or operating assumptions change.
- Run `python3 tools/lint_docs_structure.py` before proposing changes.
- Pin image tags and dependency versions. Never use `:latest`.
- Treat plugin input as untrusted; validate at system boundaries.
- Treat every `*_example*` file in this repository as the canonical reference for expected configuration and helper scripts.
- Assume the system administrator has provisioned the corresponding non-example runtime file(s) on the target host, and that those files match their tracked `*_example*` counterparts unless explicitly documented otherwise.
- The example-file pattern exists so repository updates (including `github_pull_project_bash_example` workflows) can refresh templates without overwriting site-specific runtime files.
- Treat this distribution as a full-stack, multi-container deployment that may contend with pre-existing Docker workloads (for example via host ports, network names, volumes, or maintenance automation). Operators are expected to validate coexistence in their own environment before production rollout.
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
- **`omeroweb_upload/`** -- staged upload, OMERO CLI import, SEM-EDX spectrum parsing, file attachment
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
- `docker compose --env-file installation_paths.env ps` will fail if `env/omero_secrets.env` is missing (it is gitignored). Use `docker ps --format "table {{.Names}}\t{{.Status}}"` as a fallback to check container health.

### Testing
- Run each test directory as a separate `pytest` invocation to avoid cross-contamination from `conftest.py` mock stubs. Running all suites in a single `pytest` call causes false failures in log-sanitization and multipart-upload tests.
- In root-owned deployment clones, disable the pytest cache provider so verification stays warning-free even when the repo root is not writable.
- Correct pattern:
  ```bash
  python3 -m pytest tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omero_plugin_common/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_imaris_connector/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_admin_tools/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_omp_plugin/tests/ -v -p no:cacheprovider -W error
  python3 -m pytest omeroweb_upload/tests/ -v -p no:cacheprovider -W error
  ```
- Always also run: `python3 tools/lint_docs_structure.py`

### Log checking
- Follow AGENTS.md log triage order: Loki first, then container logs.
- Loki query for errors in last hour: `curl -s "http://localhost:3100/loki/api/v1/query_range?query=%7Bjob%3D%22docker%22%7D%20%7C%3D%20%60error%60&start=$(date -u -d '1 hour ago' +%s)000000000&end=$(date -u +%s)000000000&limit=50"`
- Container logs fallback: `docker logs <container> --since 1h --tail 30`

## Knowledge maintenance

- Repository-local knowledge is the system of record. Keep decisions in version control.
- Add cross-links in `docs/index.md` when introducing new top-level docs.
- Validate docs structure: `python3 tools/lint_docs_structure.py`
- CI enforces structure via `.github/workflows/docs-knowledge-base.yml`.
- Capture architectural decisions under `docs/design-docs/`.
- Track technical debt in `docs/exec-plans/tech-debt-tracker.md`.
