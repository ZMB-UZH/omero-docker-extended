# System Architecture Overview

## Purpose

This platform packages an OMERO deployment and extends OMERO.web with domain-specific plugins for metadata workflows, staged/native imports, store-backed OME-Zarr viewing, administrative observability, and Imaris export automation. It runs as a fully containerized stack with integrated monitoring and automated database maintenance.

## Core runtime components

### OMERO.server (`omeroserver`)

Stateful backend providing the OMERO API, image storage, script execution, and data management.

- Custom Dockerfile (`docker/omero-server.Dockerfile`) based on `openmicroscopy/omero-server`.
- Installs CLI plugins: omero-cli-render, omero-metadata, omero-cli-duplicate, omero-rdf.
- Installs OMERO.Figure PDF export support (reportlab, markdown).
- Installs pinned `pytest` in the OMERO.server virtualenv for in-container regression checks.
- Clones official OME scripts and BIOP scripts during build, and bundles a pinned `Figure_To_Pdf.py` from `ome/omero-figure` so PDF export does not depend on runtime GitHub access.
- Bootstrap script (`startup/10-server-bootstrap.sh`) configures Python path, TLS certificates, job-service user, requires `OMERO_FIGURE_VERSION` from `env/omeroserver.env`, validates or upgrades the OMERO.Figure PDF export script, and registers official scripts.
- Optional runtime installation: OMERO.downloader (`startup/50-install-omero-downloader.sh`).
- ImarisConvertBioformats is installed during the `omeroserver` image build from the pinned `BIOFORMATS_VERSION`; `startup/51-install-imarisconvert.sh` verifies the build artifact at container start and fails fast if the image is incomplete.
- Compose starts the service as `root` only for bind-mount reconciliation; the
  long-running OMERO.server process runs as `omero-server`. The host/container
  API port mapping is driven by `OMERO_SERVER_HOST_PORT` and `OMERO_CLI_PORT`
  from `env/omeroserver.env`.
- Health check: admin login attempt via OMERO CLI.

### OMERO.web (`omeroweb`)

Django-based web frontend with all registered plugin apps and co-located Celery workers.

- Custom Dockerfile (`docker/omero-web.Dockerfile`) based on `openmicroscopy/omero-web-standalone`.
- Installs all five plugin packages, `omero_plugin_common`, plus third-party OMERO.web plugins (gallery, figure, fpbioimage, iviewer, mapr, parade, web-zarr, autotag, tagsearch).
- Installs matplotlib (SEM-EDX visualization), psycopg2-binary (plugin database), celery+redis (Imaris export and Tools enhanced-search indexing), and pinned `pytest` for in-container plugin regression tests.
- Managed by supervisord (`supervisord.conf`): runs OMERO.web, the Imaris Celery worker, the Tools Celery worker, and the storage-quota reconciliation loop as four supervised processes.
- Bootstrap script (`startup/10-web-bootstrap.sh`) validates/repairs the OMERO.web `var/` runtime layout, guarantees `var/django_secret_key` exists, validates log-directory access, and secures quota metadata.
- Compose starts the service as `root` only for bind-mount reconciliation; the
  supervised OMERO.web and worker processes run as `omero-web`.
- Exposed on port 4090, health check: `curl` to `/webgateway/`.
- Mounts: OMERO data (read-write), upload temp directory (tmpfs for job files), and server logs (read-only for admin tools).

### PostgreSQL databases

Two isolated PostgreSQL 16.12 instances:

- **`database`** (port 5432): primary OMERO database. User `omero`, database `omero`.
- **`database_plugin`** (port 5433): OMERO plugin storage. User `omero-plugin`, database `omero-plugin`. Stores variable sets, AI credentials, user settings, special method configurations, and the Tools enhanced-search index/saved queries for OMERO.web plugins.

Both use a `pgdata` subdirectory inside bind mounts to avoid ext4 `lost+found` issues. Timezone set to `Europe/Zurich`.

### Redis (`redis`)

Cache backend and Celery message broker:

- Version 8.6.3-alpine with in-memory only configuration (`--save ""` `--appendonly no`).
- 512MB max memory with LRU eviction, backed by tmpfs.
- Requires `vm.overcommit_memory=1`, persisted on the host by the installation script (`/etc/sysctl.d/99-redis-overcommit.conf`). The profile-gated `redis-sysctl-init` one-shot sidecar is available as a fallback.
- Used as: OMERO.web session cache (db 1), Imaris Celery broker/result backend (db 2), Tools enhanced-search broker/result backend (db 3).

### Local AI inference (`ollama`)

Internal-only Ollama service for OMP's `Local` AI provider:

- Version 0.24.0, pinned as `ollama/ollama:0.24.0`.
- Stores model data under `OLLAMA_DATA_PATH` when set, otherwise `/disks/omero_temp/ollama`.
- Exposes port 11434 only on the Docker network.
- Health check: `ollama list`.

### Monitoring stack

- **Prometheus** (v3.11.3): scrapes 10 direct metric targets plus blackbox HTTP probes and TCP probes for 5 internal endpoints.
- **Grafana** (13.0.1): 4 auto-provisioned dashboards (OMERO infrastructure, database metrics, plugin database metrics, Redis metrics).
- **Loki** (3.7.1): log aggregation backend with TSDB storage and 5000 max entries per query.
- **Alloy** (v1.16.1): collects OMERO server/web internal log files and pushes them to Loki.
- **Blackbox exporter** (v0.28.0): HTTP 2xx and TCP connect probes.
- **Node exporter** (v1.11.1): host-level metrics.
- **cAdvisor** (v0.56.2): container resource metrics.
- **Postgres exporters** (v0.19.1, x2): one per PostgreSQL instance.
- **Redis exporter** (v1.83.0): Redis metrics.
- **Path usage exporter** (custom Python 3.12 image): reads OMERO data/database paths from `installation_paths.env` every 30 seconds and runs portable host `df -kP` checks for those paths to measure actual filesystem usage (including symlink-resolved targets). Writes Prometheus textfile-collector metrics (`omero_path_used_ratio`, `omero_path_bytes_total`, `omero_path_bytes_used`) consumed by node-exporter.
- **CrowdSec** (v1.7.8): host-wide cybersecurity engine analyzing mounted host
  syslog and SSH auth logs. The firewall bouncer auto-detects
  the host's firewall backend at startup: on Ubuntu 26.04 LTS and Debian 13
  (Trixie) it uses `mode: nftables` with dedicated `crowdsec`/`crowdsec6`
  tables, INPUT-hook chains (host protection) and supplementary FORWARD-hook
  chains (Docker bridge traffic protection) at priority -10. On older hosts it
  falls back to `mode: iptables` with `INPUT` and `DOCKER-USER` chains. The
  bouncer binary and both firewall backends (nftables, iptables, ipset) are
  pre-installed at image build time. Runs with `network_mode: host` and
  `NET_ADMIN`+`NET_RAW` capabilities so firewall commands operate directly on
  the host's network stack without Docker `privileged` mode. Integrated into
  the UID/GID auto-detection mechanism for host directory ownership.
  Acquisition sources configured via `monitoring/crowdsec/acquis.yaml`.
  Console enrollment via `CROWDSEC_ENROLL_KEY` in `env/omero_secrets.env`.

### Maintenance sidecar (`pg-maintenance`)

Custom image based on postgres:16.12 with cron:

- VACUUM ANALYZE: weekly (Sunday 03:00).
- REINDEX CONCURRENTLY: monthly (first Sunday 04:00).
- Targets both OMERO and plugin databases.
- Waits for database readiness before executing.

### Container management (`portainer`)

Portainer CE (2.40.0) is profile-gated behind the `management` Compose profile.
When enabled, it exposes HTTPS only on `127.0.0.1:9443`.

## Plugin architecture

All plugin packages are standard Django app modules registered via `CONFIG_omero_web_apps` in `env/omeroweb.env`. Each plugin's `AppConfig.ready()` method configures runtime logging behavior via `omero_plugin_common.logging_utils`.

### OMP Plugin (`omeroweb_omp_plugin`)

Filename parsing and metadata annotation workflow:

- Parses scientific filenames using configurable regex or AI-assisted suggestions.
- AI providers: Local/Ollama, Groq, Gemini, Claude, Perplexity, xAI, and Cohere; external provider credentials are stored per-user in the plugin database.
- Writes OMERO MapAnnotations with HMAC-based hash ownership tracking.
- Background job execution with tmpfs job files and portalocker concurrency.
- REMBI-aligned default variables, scientific nomenclature-aware hyphen protection.
- Rate limiting: 6 major actions per 60 seconds per user.
- Database: stores variable sets, AI credentials, user settings in the OMERO plugin database (`database_plugin`) via psycopg2.

### Import Plugin (`omeroweb_import`)

Staged file upload and OMERO import:

- Job lifecycle: start session, transfer files, CLI import with batching, confirm, prune.
- Uses Bio-Formats dry-run grouping as the universal logical import planner across formats.
- Routes supported OME-Zarr image stores through a native `ome-zarr` + `omero-cli-zarr` branch only when Bio-Formats reports the staged store as incompatible.
- Stages native Zarr imports into the managed repository through a server-side helper and validates post-import metadata/render readiness before reporting success.
- SEM-EDX EMSA spectrum parsing with matplotlib visualization and genetic algorithm label placement.
- File attachment support (link related files to imported OMERO images).
- Configurable: concurrency, batch size, cleanup intervals, temp directory locations.
- Database: stores user settings and special method configurations in the OMERO plugin database (`database_plugin`).

### Tools Plugin (`omeroweb_tools`)

User-facing tools surface with an Admin-Tools-style layout:

- Landing page for future regular-user tools inside OMERO.web.
- Current feature: `Enhanced search`, backed by a user-scoped PostgreSQL metadata index in `database_plugin`.
- Users opt in to metadata indexing individually; once enabled, OMERO.web-visible metadata for images they own is indexed in the background.
- Index refresh reads OMERO metadata through the OMERO API, then writes indexed rows, scope membership, sync state, and saved queries only to the plugin database.
- Plugin-index searches are restricted to the current user's scope membership and then revalidated through OMERO before display.
- Access: intended for regular users; root is intentionally blocked from running searches or refreshes.

### OMERO.web Zarr Plugin (`omero_web_zarr`)

Authenticated OME-Zarr browsing and store-backed rendering:

- Exposes managed-repository OME-Zarr stores through authenticated OMERO.web endpoints under `/zarr/`.
- Distinguishes between a raw NGFF endpoint contract and a preview-safe endpoint contract for browser viewing.
- Uses store-backed rendering overrides for thumbnails, image-data payloads, and tile-region responses so external Zarr-backed images do not rely on classic OMERO RenderingEngine pyramid files.
- Adds store-backed downloads for original Zarr content, metadata manifests, and direct OME-TIFF export.
- Preserves stock OMERO.web behavior for non-store-backed images.

### Admin Tools Plugin (`omeroweb_admin_tools`)

Operational observability for platform administrators:

- Log exploration: Loki LogQL queries with container filtering, internal log file browsing.
- Resource monitoring: Grafana/Prometheus embedded via proxy, with Docker socket diagnostics only when operators explicitly mount a read-only socket.
- Storage analytics: per-user and per-group disk usage computed from OMERO API.
- Server diagnostics: platform end-to-end health scripts, database connectivity tests.
- Access: restricted to OMERO root users.

### Imaris Connector Plugin (`omero_imaris_connector`)

Asynchronous OMERO-to-Imaris export:

- Dispatches Celery tasks to Redis queue for processing by the co-located worker.
- Supports sync mode (wait for result) and async mode (return job ID for polling).
- Launches `IMS_Export.py` through the OMERO CLI inside `omeroweb` after locating the registered script ID.
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

1. **Host paths** (`installation_paths.env`): variables for OMERO data, databases, logs, monitoring state, and CrowdSec.
2. **Service parameters** (`env/*.env`): database credentials, Java heap, OMERO settings, plugin config, Celery settings, monitoring endpoints.
3. **Docker Compose** (`docker-compose.yml`): maps env files to containers, defines dependencies with health conditions, networks, and volume mounts.

Plugin code accesses configuration through package `config.py` modules,
package constants, or data-store helpers that use `omero_plugin_common.env_utils`
for typed, validated reads. Error messages include the env file path and
variable name for fast debugging.

## Security and operations notes

- All containers: `security_opt: no-new-privileges:true`.
- Secrets in `env/*.env` (gitignored). Rotate all defaults before deployment.
- Only OMERO.server and OMERO.web expose public host ports by default. Monitoring
  interfaces bind to loopback, and Portainer is disabled unless the
  `management` profile is enabled.
- OMERO.web should run behind a TLS-terminating reverse proxy.
- Docker socket access is not mounted by default; enable it only for explicit
  diagnostics and keep it read-only.
- Validate health checks and logs after each deployment change.
- See `docs/SECURITY.md` for full security documentation.
