# OMERO Docker Extended

Production-grade (**DISCLAIMER:** see [LICENSE](LICENSE) for details), security-hardened, dockerized OMERO deployment with custom web plugins for microscopy metadata workflows, file upload/import management, direct Imaris integration, administrative tools, and a full server monitoring stack.

## What this repository delivers

This repository packages the complete runtime for the OMERO microscopy data storage & management platform, extending it with four purpose-built OMERO.web plugins, a shared utility library, an observability stack, automated database maintenance, and deployment/update tooling. Every service runs in separate Docker containers with explicit health checks, pinned image versions, and environment variable driven configuration.

## Service topology

The platform runs **17 containers** on a single Docker bridge network (`omero`):

| Service | Image | Purpose | Port |
|---|---|---|---|
| `omeroserver` | Custom (CentOS) | OMERO.server: image storage, metadata API, script execution | 4064 |
| `omeroweb` | Custom (CentOS) | OMERO.web + all plugins + Celery worker (supervisord) | 4090 |
| `database` | postgres:16.12 | Primary OMERO PostgreSQL database | 5432 (internal) |
| `database_plugin` | postgres:16.12 | OMERO plugin PostgreSQL database | 5433 (internal) |
| `redis` | redis:8.4.0-alpine | Session cache + Celery broker/result backend | 6379 (internal) |
| `redis-sysctl-init` | Alpine 3.21 | One-shot sidecar: sets `vm.overcommit_memory=1` | none |
| `pg-maintenance` | Custom (postgres:16.12) | Cron-scheduled VACUUM ANALYZE / REINDEX for both databases | none |
| `portainer` | portainer-ce:2.38.1 | Docker container management UI | 9000, 9443 |
| `prometheus` | prom/prometheus:v3.5.1 | Metrics scraping and storage | 9090 |
| `grafana` | grafana/grafana:12.3.3 | Dashboards and visualization | 3000 |
| `loki` | grafana/loki:3.2.0 | Log aggregation backend | 3100 |
| `alloy` | grafana/alloy:v1.12.2 | Log collection pipeline (Docker + file-based) | 12345 (internal) |
| `blackbox-exporter` | prom/blackbox-exporter:v0.28.0 | HTTP/TCP endpoint probing | 9115 (internal) |
| `node-exporter` | prom/node-exporter:v1.10.2 | Host-level metrics | 9100 (internal) |
| `cadvisor` | gcr.io/cadvisor/cadvisor:v0.55.1 | Container resource metrics | 8080 (internal) |
| `postgres-exporter` | postgres-exporter:v0.19.0 | OMERO database metrics | 9187 (internal) |
| `postgres-exporter-plugin` | postgres-exporter:v0.19.0 | Plugin database metrics | 9187 (internal) |
| `redis-exporter` | redis_exporter:v1.81.0 | Redis metrics | 9121 (internal) |

## OMERO.web plugins

### OMP Plugin (`omeroweb_omp_plugin`)

Filename-to-metadata extraction workflow. Parses scientific image filenames into structured key-value annotations and writes them to OMERO.

- Regex-based and AI-assisted filename parsing (supports OpenAI, Anthropic, Google, Mistral)
- Variable set management with per-user PostgreSQL persistence
- Background job execution with progress tracking
- Hash-based ownership for safe plugin-only annotation deletion
- Rate limiting on major actions
- REMBI-aligned default variable names with scientific nomenclature-aware hyphen protection

### Upload Plugin (`omeroweb_upload`)

Staged file upload and controlled import into OMERO.

- Job lifecycle: start, upload, import, confirm, prune
- SEM-EDX spectrum parsing (EMSA format) with matplotlib visualization and genetic algorithm label placement
- OMERO CLI-based import with configurable batching and concurrency
- File attachment support (attach related files to imported images)
- Stale upload cleanup automation
- Per-user settings and special method configurations

### Admin Tools Plugin (`omeroweb_admin_tools`)

Operational observability interfaces embedded in OMERO.web.

- Log exploration via Loki (LogQL queries with container filtering)
- Grafana and Prometheus proxy endpoints for embedded dashboards
- Docker container resource monitoring (stats, system info)
- Storage analytics by user and group
- Server and database diagnostic scripts
- Root-only access controls

### Imaris Connector Plugin (`omeroweb_imaris_connector`)

OMERO image export to Imaris (.ims) format.

- Celery-based async job execution with Redis broker
- Synchronous and asynchronous request modes with status polling
- OMERO script processor availability detection and retry logic
- Job-service account support for background execution
- ImarisConvertBioformats integration (compiled from source in server image)

### Shared Library (`omero_plugin_common`)

Common utilities shared across all plugins:

- `env_utils.py` -- typed environment variable loading with validation (string, int, float, bool, sanitized+bounded)
- `logging_utils.py` -- OMERO gateway log noise reduction
- `omero_helpers.py` -- OMERO object data extraction (text values, IDs, owners, permissions)
- `request_utils.py` -- Django request parsing (JSON body, username resolution)
- `string_utils.py` -- case conversion and message payload building

## Repository layout

```
.
├── AGENTS.md                          # Agent navigation map (start here for AI agents)
├── ARCHITECTURE.md                    # Architectural overview and dependency boundaries
├── CLAUDE.md                          # Claude Code working instructions
├── README.md                          # This file
├── docker-compose.yml                 # Full service orchestration (17 containers)
├── docker/                            # Dockerfiles
│   ├── omero-server.Dockerfile        #   OMERO.server with CLI plugins, scripts, ImarisConvert
│   ├── omero-web.Dockerfile           #   OMERO.web with all plugins, supervisord, Celery worker
│   ├── omero-celery-worker.Dockerfile #   Standalone Celery worker (Ubuntu 24.04 + Python 3.9)
│   ├── pg-maintenance.Dockerfile      #   PostgreSQL maintenance sidecar with cron
│   ├── redis-sysctl-init.Dockerfile   #   Alpine sidecar for kernel parameter tuning
│   └── redis-sysctl-init.sh
├── env/                               # Environment variable templates
│   ├── omeroserver_example.env        #   Server: DB, Java, scripts, security settings
│   ├── omeroweb_example.env           #   Web: apps, plugins, admin tools, upload config
│   ├── omero-celery_example.env       #   Celery: broker, queue, timeouts, worker settings
│   └── grafana_example.env            #   Grafana: credentials and auth
├── startup/                           # Container bootstrap scripts
│   ├── 10-server-bootstrap.sh         #   Server config, certs, job-service user, script reg.
│   ├── 10-web-bootstrap.sh            #   Log dir validation, Docker socket access
│   ├── 40-start-imaris-celery-worker.sh # Celery worker startup
│   ├── 50-install-omero-downloader.sh #   OMERO.downloader from GitHub releases
│   └── 51-install-imarisconvert.sh    #   ImarisConvertBioformats compilation
├── omero_plugin_common/               # Shared Python library for all plugins
├── omeroweb_omp_plugin/               # Metadata filename parsing plugin
├── omeroweb_upload/                   # Upload and import plugin
├── omeroweb_admin_tools/              # Admin observability plugin
├── omeroweb_imaris_connector/         # Imaris export plugin
├── monitoring/                        # Observability stack configuration
│   ├── prometheus/prometheus.yml      #   Scrape configs + blackbox probes
│   ├── grafana/                       #   Dashboard JSON + provisioning
│   ├── loki/loki-config.yml           #   Log storage and ingestion settings
│   ├── alloy/alloy-config.alloy       #   Docker + file log collection to Loki
│   └── blackbox/config.yml            #   HTTP/TCP probe definitions
├── maintenance/postgres/              # Database maintenance automation
│   ├── pg-maintenance.sh              #   VACUUM ANALYZE + REINDEX CONCURRENTLY
│   ├── pg-maintenance-entrypoint.sh   #   Cron environment setup
│   └── pg-maintenance-cron            #   Weekly/monthly schedule
├── installation/                      # Deployment automation
│   └── installation_script.sh         #   Full orchestration: env, builds, ownership
├── helper_scripts_debian/             # Host provisioning helpers
│   ├── docker_debian_13_install_script
│   ├── extra_packages_debian_13_install_script
│   └── docker_image_analysis.sh
├── XTOmeroConnector.py                # Standalone Tkinter GUI: Imaris <-> OMERO transfer
├── supervisord.conf                   # Process manager: OMERO.web + Celery worker
├── omero-web.config                   # OMERO.web runtime overrides (log directory)
├── installation_paths_example.env     # Template: all filesystem path definitions
├── github_pull_project_bash_example   # Safe self-updating pull script with data protection
├── docs/                              # Full documentation set (see docs/index.md)
├── tools/                             # Development tooling (docs linter)
├── tests/                             # Test suite
└── .github/                           # CI workflows + Dependabot
```

## Deployment

### Prerequisites

- Docker Engine and Docker Compose plugin installed on the host.
- Host storage paths prepared with correct filesystem permissions.
- SSH access configured if using the pull-based update workflow (`github_pull_project_bash_example`).

### Quick start

```bash
# 1. Clone the repository
git clone git@github.com:strmt7/omero-docker-extended.git
cd omero-docker-extended

# 2. Create installation_paths.env from the template
cp installation_paths_example.env installation_paths.env
# Edit installation_paths.env to set all 15 filesystem paths for your host

# 3. Bootstrap environment files from templates
cp env/omeroserver_example.env env/omeroserver.env
cp env/omeroweb_example.env env/omeroweb.env
cp env/omero-celery_example.env env/omero-celery.env
cp env/grafana_example.env env/grafana.env
# IMPORTANT: rotate ALL default credentials before deployment

# Repository rule for operators and AI agents:
# `*_example*` files are the canonical templates in git.
# Runtime non-example files are expected to exist on the deployment host
# and to mirror these templates unless the sysadmin intentionally customizes values.

# 4. Run the installation script (creates paths, sets ownership, builds, starts)
bash installation/installation_script.sh

# Or manually:
docker compose --env-file installation_paths.env build
docker compose --env-file installation_paths.env up -d

# 5. Verify all services are healthy
docker compose --env-file installation_paths.env ps
```

### Configuration files

| File | Scope |
|---|---|
| `installation_paths.env` | All host filesystem paths (15 variables) |
| `env/omeroserver.env` | Server: database, Java heap, script processors, security |
| `env/omeroweb.env` | Web: app registration, plugin config, admin tool endpoints, upload settings |
| `env/omero-celery.env` | Celery: broker URL, queue name, timeouts, worker concurrency |
| `env/grafana.env` | Grafana: admin credentials and authentication settings |

### Example templates and runtime files

- All `*_example*` files in this repository are the source-of-truth templates for configuration and operational helper scripts.
- For AI-assisted analysis and maintenance, assume the corresponding non-example runtime files are present on the target system and structurally aligned with their `*_example*` versions.
- This split exists so update flows (including `github_pull_project_bash_example`) can pull repository changes without replacing site-local runtime files that admins manage outside git.

### Lifecycle commands

```bash
# Stop services without removing resources
docker compose --env-file installation_paths.env stop

# Stop and remove containers
docker compose --env-file installation_paths.env down

# Follow logs for a specific service
docker compose --env-file installation_paths.env logs -f omeroweb

# Rebuild a single service
docker compose --env-file installation_paths.env build omeroweb
docker compose --env-file installation_paths.env up -d omeroweb
```

### Reverse proxy

Reverse proxy and TLS termination are managed externally (e.g., nginx via Ansible). Forward traffic to `http://omeroweb:4090` on the Docker network. Direct local access at `http://localhost:4090` remains available for troubleshooting.

## Monitoring

The observability stack provides:

- **Prometheus** scrapes 9 exporters/services, plus blackbox HTTP probes for 12 endpoints and TCP probes for 4 ports (databases, Redis, OMERO.server).
- **Alloy** collects Docker container logs and OMERO server/web internal log files, pushes to Loki.
- **Grafana** ships with 4 pre-provisioned dashboards: OMERO infrastructure, database metrics, plugin database metrics, Redis metrics.
- **Blackbox exporter** validates HTTP 2xx for all web endpoints and TCP connectivity for critical internal services.

## Database maintenance

The `pg-maintenance` sidecar runs automated maintenance against both PostgreSQL databases:

- **Weekly** (Sunday 03:00): `VACUUM ANALYZE` -- reclaims dead tuples, updates query planner statistics.
- **Monthly** (first Sunday 04:00): `REINDEX CONCURRENTLY` -- rebuilds indexes online without locking.

Both operations are safe for production and do not require downtime.

## Documentation

| Entry point | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agent/AI navigation map and working contract |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Architectural overview, layer model, dependency rules |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code specific working instructions |
| [`docs/index.md`](docs/index.md) | Full documentation index with cross-links |
| [`docs/deployment/quickstart.md`](docs/deployment/quickstart.md) | Step-by-step deployment guide |
| [`docs/deployment/configuration.md`](docs/deployment/configuration.md) | Configuration reference |
| [`docs/plugins/`](docs/plugins/) | Per-plugin operation guides |
| [`docs/operations/`](docs/operations/) | Monitoring and maintenance runbooks |
| [`docs/troubleshooting/`](docs/troubleshooting/) | Diagnostic procedures |
| [`docs/reference/`](docs/reference/) | Endpoint map and release notes |

## Documentation rules

- Keep `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, and `CLAUDE.md` at repository root.
- Keep all other project documentation under `docs/`.
- Documentation structure is enforced by CI via `tools/lint_docs_structure.py`.
- Update `docs/index.md` cross-links when introducing new documents.

## License

See [LICENSE](LICENSE) for details.
