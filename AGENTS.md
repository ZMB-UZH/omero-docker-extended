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

## Where to look first

1. **`README.md`** -- deployment scope, service topology (17 containers), plugin summaries, quick start.
2. **`ARCHITECTURE.md`** -- layer model, dependency boundaries, data flow, plugin structure.
3. **`docs/index.md`** -- full documentation index with cross-links to every doc.
4. **`docs/QUALITY_SCORE.md`** -- current quality grades and debt priorities.
5. **`docs/exec-plans/`** -- active and completed implementation plans.

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
- **`omeroweb_imaris_connector/`** -- Imaris export via Celery tasks, script processor retry, job-service account
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

## Knowledge maintenance

- Repository-local knowledge is the system of record. Keep decisions in version control.
- Add cross-links in `docs/index.md` when introducing new top-level docs.
- Validate docs structure: `python3 tools/lint_docs_structure.py`
- CI enforces structure via `.github/workflows/docs-knowledge-base.yml`.
- Capture architectural decisions under `docs/design-docs/`.
- Track technical debt in `docs/exec-plans/tech-debt-tracker.md`.
