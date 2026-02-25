# Architecture Overview

## System intent

OMERO Docker Extended packages an OMERO imaging platform with custom web plugins, background workers, and a full observability stack into a reproducible containerized deployment. It serves microscopy researchers and operators who need metadata workflows, file import management, Imaris format conversion, and administrative visibility.

## Layer model

```
┌─────────────────────────────────────────────────────────────────┐
│  4. Operations layer                                            │
│     docs/operations/, maintenance/postgres/, monitoring/        │
│     Monitoring, alerting, database maintenance, runbooks        │
├─────────────────────────────────────────────────────────────────┤
│  3. Application layer                                           │
│     omeroweb_omp_plugin/  omeroweb_upload/                     │
│     omeroweb_admin_tools/  omeroweb_imaris_connector/          │
│     omero_plugin_common/  XTOmeroConnector.py                  │
│     Plugin business logic, OMERO API integration, UI           │
├─────────────────────────────────────────────────────────────────┤
│  2. Runtime bootstrap layer                                     │
│     startup/  supervisord.conf  omero-web.config               │
│     Deterministic startup, process management, runtime config  │
├─────────────────────────────────────────────────────────────────┤
│  1. Infrastructure layer                                        │
│     docker-compose.yml  docker/  env/  installation_paths.env  │
│     Image builds, service wiring, networking, health checks    │
└─────────────────────────────────────────────────────────────────┘
```

### 1. Infrastructure layer

**Files:** `docker-compose.yml`, `docker/`, `env/`, `installation_paths.env`

Defines the complete service topology: 20 containers on a single `omero` bridge network. Every service has explicit health checks, pinned image versions, `no-new-privileges` security, and environment-driven configuration.

Key design decisions:
- Two PostgreSQL instances: `database` (OMERO core, port 5432) and `database_plugin` (OMERO plugin data, port 5433) for isolation.
- Redis as pure cache (no persistence: `--save "" --appendonly no`, tmpfs-backed, 512MB LRU).
- `redis-sysctl-init` one-shot sidecar sets `vm.overcommit_memory=1` before Redis starts.
- All container data paths bind-mount from host paths defined in `installation_paths.env`.
- PostgreSQL uses a `pgdata` subdirectory inside the mount to avoid ext4 `lost+found` issues.

### 2. Runtime bootstrap layer

**Files:** `startup/`, `supervisord.conf`, `omero-web.config`

Bootstrap scripts run at container start to configure services that cannot be fully set up at build time:
- `10-server-bootstrap.sh`: configures `omero.scripts.python`, generates TLS certificates with SANs, creates job-service user, clones OMERO.Figure scripts, registers official scripts.
- `10-web-bootstrap.sh`: validates log directory write access, auto-discovers and configures Docker socket GID for the omeroweb container.
- `40-start-imaris-celery-worker.sh`: dynamically discovers the venv path, tests task import, starts celery worker.
- `50-install-omero-downloader.sh`: downloads OMERO.downloader from GitHub releases (version-gated).
- `51-install-imarisconvert.sh`: compiles ImarisConvertBioformats from source with CMake, downloads Bio-Formats JAR.

The `omeroweb` container runs two processes via supervisord:
1. OMERO.web (Django application server)
2. Imaris Celery worker (async export tasks)

### 3. Application layer

**Files:** `omeroweb_*`, `omero_plugin_common/`, `XTOmeroConnector.py`

Four Django app plugins register in OMERO.web via `CONFIG_omero_web_apps`:

```
omeroweb_omp_plugin ──────┐
omeroweb_upload ──────────┤
omeroweb_admin_tools ─────┼──> omero_plugin_common
omeroweb_imaris_connector ┘         │
                                    ├── env_utils (typed env var loading)
                                    ├── logging_utils (gateway noise reduction)
                                    ├── omero_helpers (object data extraction)
                                    ├── request_utils (JSON/POST parsing)
                                    └── string_utils (case conversion)
```

Each plugin follows a standard layout: `apps.py` (AppConfig), `config.py` (env-driven settings), `urls.py` (routing), `views/` (request handlers), `services/` (business logic), `strings/` (error/message functions), `templates/`, `static/`, `tests/`.

**Plugin data flow patterns:**

- **OMP Plugin**: user selects project/dataset -> filenames fetched from OMERO -> regex/AI parsing -> preview -> background job writes MapAnnotations with hash-based ownership tracking. Per-user data (variable sets, AI credentials, settings) persisted in the OMERO plugin database (`database_plugin`) via psycopg2.
- **Upload Plugin**: user starts upload session -> files transferred to tmpfs job directory -> OMERO CLI import with batching -> file attachments linked -> confirm/prune lifecycle. SEM-EDX files parsed (EMSA format) with matplotlib visualization. Settings persisted in the OMERO plugin database (`database_plugin`).
- **Admin Tools**: proxies Loki LogQL queries, Grafana dashboards, Prometheus metrics. Queries Docker socket for container stats. Computes storage usage from OMERO API. Root-only diagnostic scripts.
- **Imaris Connector**: export request -> Celery task dispatched to Redis queue -> worker opens OMERO session (user session or job-service account) -> finds and runs IMS export script -> polls for completion -> returns result with download path.

**`XTOmeroConnector.py`** is a standalone Tkinter GUI application (not a web plugin) that runs as an ImarisXT extension for bidirectional Imaris-to-OMERO image transfer.

### 4. Operations layer

**Files:** `monitoring/`, `maintenance/postgres/`, `docs/operations/`

Monitoring stack:
- Prometheus scrapes node-exporter, cadvisor, postgres-exporter (x2), redis-exporter, loki, alloy, grafana, plus blackbox HTTP probes for 12 endpoints and TCP probes for 4 ports.
- Alloy collects Docker container stdout/stderr logs plus OMERO server and web internal log files (`.log`, `.out`, `.err`), pushes to Loki.
- Grafana: 4 dashboards auto-provisioned (OMERO infrastructure, database metrics, plugin database metrics, Redis metrics).

Database maintenance:
- `pg-maintenance` sidecar runs cron: VACUUM ANALYZE weekly (Sunday 03:00), REINDEX CONCURRENTLY monthly (first Sunday 04:00), against both databases.
- Waits for database readiness before executing (30 retries x 5s).
- `VACUUM FULL` intentionally excluded (requires exclusive locks).

## Dependency boundaries

```
                    ┌─────────────────────┐
                    │  omero_plugin_common │
                    └──────────┬──────────┘
                               │ depends on
          ┌────────────────────┼────────────────────┐
          │                    │                     │
   omeroweb_omp_plugin  omeroweb_upload  omeroweb_admin_tools
          │
          └─── omeroweb_imaris_connector
```

Rules:
- Plugin packages depend on `omero_plugin_common`, never the reverse.
- Plugins do not depend on each other.
- Startup scripts consume only environment variables; they never import Python code.
- Documentation is the source of truth for runtime behavior and operational procedures.
- All external service URLs (Loki, Grafana, Prometheus) are injected via `env/omeroweb.env`, never hard-coded.

## Configuration model

Configuration flows through environment variables at three levels:

1. **Host paths** (`installation_paths.env`): 15 variables defining where data, databases, logs, and monitoring state live on the host filesystem.
2. **Service config** (`env/*.env`): database credentials, Java heap, OMERO settings, plugin parameters, Celery broker/queue config, monitoring endpoints.
3. **Docker Compose** (`docker-compose.yml`): maps env files to containers, defines service dependencies, health checks, networks, and volume mounts.

Startup scripts read environment variables at runtime. Plugin `config.py` modules use `omero_plugin_common.env_utils` for typed access with validation and helpful error messages referencing the correct env file.

## Security model

- All containers run with `security_opt: no-new-privileges:true`.
- Default credentials in example env files must be rotated before deployment.
- Secrets stay in `env/*.env` files (gitignored, never committed).
- Plugin input is validated at boundaries; OMERO permissions checked for data access.
- OMP plugin uses HMAC-based hashing (with optional secret) for annotation ownership.
- Rate limiting on major plugin actions (6 actions / 60 seconds per user).
- Docker socket access in omeroweb is read-only for container stats.
- Monitoring interfaces should not be exposed publicly without authentication.

## Quality gates

- Documentation structure and cross-links enforced by `tools/lint_docs_structure.py` (CI).
- Dependabot monitors pip and Docker image dependencies weekly.
- Architectural decisions captured under `docs/design-docs/`.
- Technical debt tracked in `docs/exec-plans/tech-debt-tracker.md`.
