# System Architecture Overview

## Purpose

This platform packages an OMERO deployment and extends OMERO.web with domain-specific plugins for metadata workflows, uploads, administrative observability, and Imaris export automation. It runs as a fully containerized stack with integrated monitoring and automated database maintenance.

## Core runtime components

### OMERO.server (`omeroserver`)

Stateful backend providing the OMERO API, image storage, script execution, and data management.

- Custom Dockerfile (`docker/omero-server.Dockerfile`) based on `openmicroscopy/omero-server`.
- Installs CLI plugins: omero-cli-render, omero-metadata, omero-cli-duplicate, omero-rdf.
- Installs OMERO.Figure PDF export support (reportlab, markdown).
- Clones official OME scripts and BIOP scripts during build.
- Bootstrap script (`startup/10-server-bootstrap.sh`) configures Python path, TLS certificates, job-service user, OMERO.Figure scripts, and registers official scripts.
- Optional runtime installations: OMERO.downloader (`startup/50-install-omero-downloader.sh`) and ImarisConvertBioformats (`startup/51-install-imarisconvert.sh`).
- Runs as `omero-server` user (non-root), exposed on port 4064.
- Health check: admin login attempt via OMERO CLI.

### OMERO.web (`omeroweb`)

Django-based web frontend with all registered plugin apps and a co-located Celery worker.

- Custom Dockerfile (`docker/omero-web.Dockerfile`) based on `openmicroscopy/omero-web-standalone`.
- Installs all four plugin packages, `omero_plugin_common`, plus third-party OMERO.web plugins (gallery, figure, fpbioimage, iviewer, mapr, parade, web-zarr, autotag, tagsearch).
- Installs matplotlib (SEM-EDX visualization), psycopg2-binary (plugin database), celery+redis (Imaris export).
- Managed by supervisord (`supervisord.conf`): runs OMERO.web and the Imaris Celery worker as two supervised processes.
- Bootstrap script (`startup/10-web-bootstrap.sh`) validates log directory access and configures Docker socket GID.
- Exposed on port 4090, health check: `curl` to `/webgateway/`.
- Mounts: OMERO data (read-write), upload temp directory (tmpfs for job files), Docker socket (read-only), server logs (read-only for admin tools).

### PostgreSQL databases

Two isolated PostgreSQL 16.12 instances:

- **`database`** (port 5432): primary OMERO database. User `omero`, database `omero`.
- **`database_plugin`** (port 5433): OMERO plugin storage. User `omero-plugin`, database `omero-plugin`. Stores variable sets, AI credentials, user settings, and special method configurations for OMERO.web plugins, including OMP and Upload.

Both use a `pgdata` subdirectory inside bind mounts to avoid ext4 `lost+found` issues. Timezone set to `Europe/Zurich`.

### Redis (`redis`)

Cache backend and Celery message broker:

- Version 8.4.0-alpine with in-memory only configuration (`--save "" --appendonly no`).
- 512MB max memory with LRU eviction, backed by tmpfs.
- Requires `vm.overcommit_memory=1` set by the `redis-sysctl-init` one-shot sidecar.
- Used as: OMERO.web session cache (db 1), Celery broker and result backend (db 2).

### Monitoring stack

- **Prometheus** (v3.5.1): scrapes 9 metric sources plus blackbox HTTP probes for 12 endpoints and TCP probes for 4 ports.
- **Grafana** (12.3.3): 4 auto-provisioned dashboards (OMERO infrastructure, database metrics, plugin database metrics, Redis metrics).
- **Loki** (3.2.0): log aggregation backend with TSDB storage and 5000 max entries per query.
- **Alloy** (v1.12.2): collects Docker container logs and OMERO server/web internal log files, pushes to Loki.
- **Blackbox exporter** (v0.28.0): HTTP 2xx and TCP connect probes.
- **Node exporter** (v1.10.2): host-level metrics.
- **cAdvisor** (v0.55.1): container resource metrics.
- **Postgres exporters** (v0.19.0, x2): one per PostgreSQL instance.
- **Redis exporter** (v1.81.0): Redis metrics.

### Maintenance sidecar (`pg-maintenance`)

Custom image based on postgres:16.12 with cron:
- VACUUM ANALYZE: weekly (Sunday 03:00).
- REINDEX CONCURRENTLY: monthly (first Sunday 04:00).
- Targets both OMERO and plugin databases.
- Waits for database readiness before executing.

### Container management (`portainer`)

Portainer CE (2.38.1) for Docker container management UI, exposed on ports 9000 and 9443.

## Plugin architecture

All plugin packages are standard Django app modules registered via `CONFIG_omero_web_apps` in `env/omeroweb.env`. Each plugin's `AppConfig.ready()` method configures runtime logging behavior via `omero_plugin_common.logging_utils`.

### OMP Plugin (`omeroweb_omp_plugin`)

Filename parsing and metadata annotation workflow:
- Parses scientific filenames using configurable regex or AI-assisted suggestions.
- AI providers: OpenAI, Anthropic, Google, Mistral (credentials stored per-user in plugin database).
- Writes OMERO MapAnnotations with HMAC-based hash ownership tracking.
- Background job execution with tmpfs job files and portalocker concurrency.
- REMBI-aligned default variables, scientific nomenclature-aware hyphen protection.
- Rate limiting: 6 major actions per 60 seconds per user.
- Database: stores variable sets, AI credentials, user settings in the OMERO plugin database (`database_plugin`) via psycopg2.

### Upload Plugin (`omeroweb_upload`)

Staged file upload and OMERO import:
- Job lifecycle: start session, transfer files, CLI import with batching, confirm, prune.
- SEM-EDX EMSA spectrum parsing with matplotlib visualization and genetic algorithm label placement.
- File attachment support (link related files to imported OMERO images).
- Configurable: concurrency, batch size, cleanup intervals, temp directory locations.
- Database: stores user settings and special method configurations in the OMERO plugin database (`database_plugin`).

### Admin Tools Plugin (`omeroweb_admin_tools`)

Operational observability for platform administrators:
- Log exploration: Loki LogQL queries with container filtering, internal log file browsing.
- Resource monitoring: Docker container stats via Docker socket, Grafana/Prometheus embedded via proxy.
- Storage analytics: per-user and per-group disk usage computed from OMERO API.
- Server diagnostics: platform end-to-end health scripts, database connectivity tests.
- Access: restricted to OMERO root users.

### Imaris Connector Plugin (`omeroweb_imaris_connector`)

Asynchronous OMERO-to-Imaris export:
- Dispatches Celery tasks to Redis queue for processing by the co-located worker.
- Supports sync mode (wait for result) and async mode (return job ID for polling).
- Script processor retry with backoff, fast-fail when processors disabled.
- Job-service account support: export tasks can use a dedicated OMERO account instead of the user's session.
- OMERO script: `IMS_Export.py` (registered at server startup).

### Shared Library (`omero_plugin_common`)

Five utility modules shared across all plugins:
- `env_utils.py`: typed environment variable loading (string, int, float, bool, sanitized+bounded) with validation errors that reference the correct env file.
- `logging_utils.py`: reduces OMERO gateway debug noise by raising `omero.gateway.utils` to INFO.
- `omero_helpers.py`: extracts text, IDs, owners, and permissions from OMERO objects.
- `request_utils.py`: parses Django request bodies (JSON or POST form data) and resolves usernames.
- `string_utils.py`: `snake_to_camel` conversion and message payload building.

## Configuration model

Configuration is environment-driven and consumed at three levels:

1. **Host paths** (`installation_paths.env`): 15 variables for OMERO data, databases, logs, monitoring state.
2. **Service parameters** (`env/*.env`): database credentials, Java heap, OMERO settings, plugin config, Celery settings, monitoring endpoints.
3. **Docker Compose** (`docker-compose.yml`): maps env files to containers, defines dependencies with health conditions, networks, and volume mounts.

Plugin code accesses configuration through `config.py` modules that use `omero_plugin_common.env_utils` for typed, validated reads. Error messages include the env file path and variable name for fast debugging.

## Security and operations notes

- All containers: `security_opt: no-new-privileges:true`.
- Secrets in `env/*.env` (gitignored). Rotate all defaults before deployment.
- Only 6 services expose host ports; all others are internal to the `omero` network.
- OMERO.web should run behind a TLS-terminating reverse proxy.
- Docker socket is read-only in omeroweb (admin tools container stats only).
- Validate health checks and logs after each deployment change.
- See `docs/SECURITY.md` for full security documentation.
