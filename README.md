# OMERO Docker Extended

<!-- BEGIN GENERATED BADGES -->
[![License](https://img.shields.io/github/license/ZMB-UZH/omero-docker-extended)](LICENSE)
[![tests](https://img.shields.io/github/actions/workflow/status/ZMB-UZH/omero-docker-extended/tests.yml?branch=main&label=tests)](https://github.com/ZMB-UZH/omero-docker-extended/actions/workflows/tests.yml)
[![security-code-scanning](https://img.shields.io/github/actions/workflow/status/ZMB-UZH/omero-docker-extended/security-code-scanning.yml?branch=main&label=security-code-scanning)](https://github.com/ZMB-UZH/omero-docker-extended/actions/workflows/security-code-scanning.yml)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/ZMB-UZH/omero-docker-extended)](https://github.com/ZMB-UZH/omero-docker-extended/commits/main)
[![Codecov](https://img.shields.io/codecov/c/github/ZMB-UZH/omero-docker-extended?label=Codecov&logo=codecov)](https://codecov.io/gh/ZMB-UZH/omero-docker-extended)
[![Mypy](https://img.shields.io/github/actions/workflow/status/ZMB-UZH/omero-docker-extended/mypy.yml?branch=main&logo=python&label=Mypy)](https://github.com/python/mypy)
[![super-linter](https://img.shields.io/github/actions/workflow/status/ZMB-UZH/omero-docker-extended/super-linter.yml?branch=main&label=super-linter&logo=github)](https://github.com/super-linter/super-linter)
[![Ruff](https://img.shields.io/github/actions/workflow/status/ZMB-UZH/omero-docker-extended/ruff.yml?branch=main&logo=ruff&label=Ruff)](https://github.com/astral-sh/ruff)
[![Vulture](https://img.shields.io/github/actions/workflow/status/ZMB-UZH/omero-docker-extended/vulture.yml?branch=main&logo=python&label=Vulture)](https://github.com/jendrikseipp/vulture)
[![cocoindex-code](https://img.shields.io/static/v1?label=&message=cocoindex-code&color=555&logo=github&logoColor=white)](https://github.com/cocoindex-io/cocoindex-code)
[![everything-claude-code](https://img.shields.io/static/v1?label=&message=everything-claude-code&color=555&logo=github&logoColor=white)](https://github.com/affaan-m/everything-claude-code)
[![caveman](https://img.shields.io/static/v1?label=&message=caveman&color=555&logo=github&logoColor=white)](https://github.com/JuliusBrussee/caveman)
[![andrej-karpathy-skills](https://img.shields.io/static/v1?label=&message=andrej-karpathy-skills&color=555&logo=github&logoColor=white)](https://github.com/forrestchang/andrej-karpathy-skills)
<!-- END GENERATED BADGES -->

Production-grade (see [LICENSE](LICENSE) for details), security-hardened, dockerized OMERO deployment with custom OMERO.web plugins for microscopy metadata workflows, file upload/import management, direct Imaris 11 integration, administrator tools, and a full server monitoring stack.

<details open>
<summary><h2>What this repository delivers</h2></summary>

This repository packages the complete runtime for the OMERO microscopy data
storage & management platform, extending it with five purpose-built OMERO.web
plugins (with several subroutines each), a shared utility library, an
observability stack, automated database maintenance, and deployment/update
tooling. Every service runs in separate docker containers with explicit health
checks, pinned image versions, and environment variable driven configuration.

> This project is delivered as an integrated container platform rather than a single-service image. In environments that already run other docker containers, validate port mappings, network/volume naming, and installation/update automation behavior in a test host first; coexistence possibility and behavior must be verified by the system administrator.

For the official OMERO documentation, release notes, and guides, your first points of reference should be: <https://www.openmicroscopy.org/omero/> and <https://github.com/ome/omero-server-docker>.

</details>

<details open>
<summary><h2>Current development state</h2></summary>

## ✅ Works great

- All official OMERO software components
- All base installation and orchestration layers
- Official and third-party scripts included in this repository
- Import plugin (`omeroweb_import`)
- Tools plugin (`omeroweb_tools`) / Enhanced search
- Admin tools (`omeroweb_admin_tools`)

## 🛠️ Works partially / under active development

- OMP plugin (`omeroweb_omp_plugin`)
- Direct Imaris 11 integration
- Unofficial and helper scripts specific to this repository

## 🐢 Not working yet / progressing slowly / planned

- Additional Tools entries beyond Enhanced search

</details>

<details>
<summary><h2>Repository layout</h2></summary>

```text
.
├── .agents/skills/                    # Reusable repo-local agent workflows
├── .claude/settings.json              # Claude Code local project settings
├── .cursor/rules/                     # Cursor adapters for AGENTS/skills
├── .github/                           # GitHub automation and repository metadata
│   ├── workflows/                     #   CI, security, CodeQL, and release workflows
│   ├── requirements/                  #   Hash-pinned CI tool requirement files
│   ├── instructions/                  #   GitHub Copilot path-specific instructions
│   ├── ISSUE_TEMPLATE/                #   GitHub issue forms
│   ├── codeql/codeql-config.yml       #   CodeQL configuration
│   ├── copilot-instructions.md        #   GitHub Copilot repo-wide instructions
│   ├── dependabot.yml                 #   Dependabot update policy
│   ├── pull_request_template.md       #   Pull request checklist
│   ├── readme_badges.json             #   Source for generated README badges
│   └── SECURITY.md                    #   GitHub security policy pointer
├── .dockerignore                      # docker build context exclusions
├── .env_manifest                      # Environment-template manifest used by repo checks
├── .markdownlint.yaml                 # Markdown lint configuration
├── .pre-commit-config.yaml            # Optional local pre-commit hook configuration
├── .ruff.toml                         # Ruff lint/format configuration
├── .yamllint                          # YAML lint configuration
├── AGENTS.md                          # AI agent working contract
├── ARCHITECTURE.md                    # Architectural overview and dependency boundaries
├── CLAUDE.md                          # Claude Code working instructions
├── CODE_OF_CONDUCT.md                 # Community conduct policy
├── CONTRIBUTING.md                    # Contributor workflow and checks
├── GEMINI.md                          # Gemini CLI project context
├── LICENSE                            # Project license
├── README.md                          # This file
├── SECURITY.md                        # Root security policy pointer
├── codecov.yml                        # Codecov status configuration
├── conftest.py                        # Pytest repository configuration
├── docker-compose.yml                 # Compose topology: 21 services, 19 default runtime containers
├── docker/                            # dockerfiles and image helper scripts
│   ├── crowdsec.Dockerfile            #   CrowdSec service with custom bootstrap
│   ├── firewall-bouncer.Dockerfile    #   CrowdSec firewall bouncer sidecar
│   ├── omero-celery-worker.Dockerfile #   Standalone Celery worker (Ubuntu 26.04 LTS)
│   ├── omero-server.Dockerfile        #   OMERO.server with CLI plugins, scripts, ImarisConvert
│   ├── omero-web.Dockerfile           #   OMERO.web with all plugins, supervisord, Celery workers
│   ├── path-usage-exporter.Dockerfile #   Custom filesystem usage metrics exporter
│   ├── pg-maintenance.Dockerfile      #   PostgreSQL maintenance sidecar with cron
│   ├── prebuilt-carrier.Dockerfile    #   Scratch data carrier for easy installs
│   ├── redis-sysctl-init.Dockerfile   #   Redis kernel-tuning helper image
│   ├── *-entrypoint.sh                #   Service entrypoint helpers
│   ├── patch_*.py                     #   Runtime patch helpers copied into images
│   └── redis-sysctl-init.sh           #   Redis sysctl helper script
├── env/                               # Environment variable templates
│   ├── grafana_example.env            #   Grafana credentials and auth
│   ├── omero-celery_example.env       #   Celery broker, queue, timeouts, worker settings
│   ├── omero_secrets_example.env      #   Secrets template; runtime copy is host-owned
│   ├── omeroserver_example.env        #   Server: DB, Java, scripts, security settings
│   └── omeroweb_example.env           #   Web: apps, plugins, admin tools, upload config
├── startup/                           # Container bootstrap scripts
│   ├── 10-server-bootstrap.sh         #   Server config, certs, job-service user, scripts
│   ├── 10-web-bootstrap.sh            #   Log dir validation, docker socket access
│   ├── 40-start-*-celery-worker.sh    #   Imaris and Tools Celery worker startup helpers
│   ├── 50-config.py                   #   OMERO.web runtime configuration generator
│   ├── 50-install-omero-downloader.sh #   OMERO.downloader install/verify helper
│   ├── 51-install-imarisconvert.sh    #   ImarisConvert install/verify helper
│   ├── 60-default-web-config.sh       #   Default OMERO.web config handoff
│   ├── 60-enforce-ext4-project-quota.sh # Project-quota enforcement
│   ├── 61-storage-quota-reconcile-loop.sh # Quota reconciliation
│   ├── 98-cleanprevious.sh            #   Image-local startup cleanup hook
│   ├── dropbox_user_dir_sync.py       #   Dropbox user-directory sync helper
│   ├── healthcheck-omeroserver.sh     #   OMERO.server healthcheck helper
│   ├── job_service_group_sync.py      #   Job-service group sync helper
│   └── repo_root_sync_helper.py       #   Repository root sync helper
├── omero_plugin_common/               # Shared Python library for all plugins
├── omero_web_zarr/                    # OMERO.web Zarr preview integration
├── omero_imaris_connector/            # Imaris export plugin + XT connector
├── omeroweb_admin_tools/              # Admin observability plugin
├── omeroweb_import/                   # Import plugin
├── omeroweb_omp_plugin/               # Metadata filename parsing plugin
├── omeroweb_tools/                    # User-facing tools plugin (Enhanced search)
├── monitoring/                        # Observability stack configuration
│   ├── alloy/alloy-config.alloy       #   docker + file log collection to Loki
│   ├── blackbox/config.yml            #   HTTP/TCP probe definitions
│   ├── cadvisor/                      #   cAdvisor entrypoint helper
│   ├── crowdsec/                      #   CrowdSec acquisition config
│   ├── grafana/                       #   Dashboard JSON + provisioning
│   ├── loki/loki-config.yml           #   Log storage and ingestion settings
│   ├── path-usage-exporter/           #   Filesystem usage exporter
│   ├── postgres-exporter/             #   PostgreSQL exporter config and entrypoint
│   └── prometheus/                    #   Scrape config and disk-monitor helper
├── maintenance/postgres/              # Database maintenance automation
│   ├── pg-maintenance.sh              #   VACUUM ANALYZE + REINDEX CONCURRENTLY
│   ├── pg-maintenance-entrypoint.sh   #   Private cron environment setup
│   ├── pg-maintenance-cron-runner     #   Sources cron env before scheduled jobs
│   └── pg-maintenance-cron            #   Weekly/monthly schedule
├── installation/                      # Deployment automation
│   ├── cleanup_build_containers.sh    #   Build container cleanup
│   ├── crowdsec_install_auto_restart.sh # CrowdSec install-mode restart helper
│   ├── docker_buildx_compressed_push.sh # Buildx compressed image build/push helper
│   ├── easy_installation_script.sh    #   Strict prebuilt carrier installation entrypoint
│   ├── env_assignment_utils.sh        #   Shell env-file assignment helpers
│   ├── github_pull_project_bash       #   Safe pull/update launcher with source-ref selection
│   ├── install_transcript_utils.sh    #   Installation transcript utilities
│   ├── installation_script.sh         #   Full orchestration: env, builds, ownership
│   └── load_prebuilt_carrier.sh       #   Verifies and loads carrier-bundled runtime images
├── helper_scripts_debian/             # Host provisioning helpers
│   ├── docker_debian_13_install_script
│   ├── extra_packages_debian_13_install_script
│   └── docker_image_analysis.sh
├── scripts/                           # Host service installers and systemd units
│   ├── enable-storage-quotas.sh       #   Storage quota enablement
│   ├── install-quota-enforcer.sh      #   Quota enforcer installer
│   ├── install-tmp-cleaner.sh         #   Temporary-file cleaner installer
│   ├── omero-host-service-lib.sh      #   Shared host-service installer library
│   ├── omero-quota-enforcer.*         #   Quota enforcer script and systemd units
│   └── omero-tmp-cleaner.*            #   Temporary-file cleaner units
├── supervisord.conf                   # OMERO.web and co-located Celery processes
├── omero-web.config                   # OMERO.web runtime overrides (log directory)
├── .env_example                       # Template for Compose interpolation defaults
├── installation_paths_example.env     # Template for filesystem paths
├── iter_test_helpers.py               # Shared test helper functions
├── mypy.ini                           # Mypy configuration
├── docs/                              # Full documentation set (see docs/index.md)
├── fuzzing/                           # Fuzz targets for parser and input-boundary checks
├── logo/                              # Runtime logo template asset
├── third_party/ecc-v1.10.0/            # Pinned selected ECC v1.10.0 skill snapshot (MIT)
├── tools/                             # Agent, env-safety, lint, release, and CI tools
├── tests/                             # Test suite
└── typings/                           # Local type stubs
```

</details>

<details>
<summary><h2>Service topology</h2></summary>

`docker-compose.yml` declares **21 Compose services total** on a single docker
bridge network (`omero`): **19 long-running runtime containers by default**,
**20 when the profile-gated `crowdsec` service is enabled**. The one-shot
`redis-sysctl-init` helper is also profile-gated (`sysctl-init`); the
installation script persists `vm.overcommit_memory=1` on the host so it is not
needed during normal `docker compose up` cycles.

The table below lists the long-running services available in the full profile set:

| Service | Image | Purpose | Port |
| --- | --- | --- | --- |
| `omeroserver` | Custom (CentOS) | OMERO.server: image storage, metadata API, script execution | `OMERO_SERVER_HOST_PORT` -> `OMERO_CLI_PORT` |
| `omeroweb` | Custom (CentOS) | OMERO.web + all plugins + Celery workers (supervisord) | 4090 |
| `database` | postgres:16.12 | Primary OMERO PostgreSQL database | 5432 (internal) |
| `database_plugin` | postgres:16.12 | OMERO plugin PostgreSQL database (OMP, Import, Tools) | 5433 (internal) |
| `redis` | redis:8.6.3-alpine | Session cache + Celery broker/result backend | 6379 (internal) |
| `ollama` | ollama/ollama:0.23.2 | Local AI inference endpoint for OMP's `Local` provider | 11434 (internal) |
| `pg-maintenance` | Custom (postgres:16.12) | Cron-scheduled VACUUM ANALYZE / REINDEX for both databases | none |
| `portainer` | portainer/portainer-ce:2.40.0-alpine | docker container management UI | 9000, 9443 |
| `prometheus` | prom/prometheus:v3.11.3 | Metrics scraping and storage | 9090 |
| `grafana` | grafana/grafana:13.0.1 | Dashboards and visualization | 3000 |
| `loki` | grafana/loki:3.7.1 | Log aggregation backend | 3100 |
| `alloy` | grafana/alloy:v1.16.1 | Log collection pipeline (docker + file-based) | 12345 (internal) |
| `blackbox-exporter` | prom/blackbox-exporter:v0.28.0 | HTTP/TCP endpoint probing | 9115 (internal) |
| `node-exporter` | prom/node-exporter:v1.11.1 | Host-level metrics | 9100 (internal) |
| `cadvisor` | ghcr.io/google/cadvisor:0.56.2 | Container resource metrics | 8080 (internal) |
| `postgres-exporter` | prometheuscommunity/postgres-exporter:v0.19.1 | OMERO database metrics | 9187 (internal) |
| `postgres-exporter-plugin` | prometheuscommunity/postgres-exporter:v0.19.1 | Plugin database metrics | 9187 (internal) |
| `redis-exporter` | oliver006/redis_exporter:v1.83.0-alpine | Redis metrics | 9121 (internal) |
| `path-usage-exporter` | Custom (python:3.12-slim) | Exposes OMERO/data path usage metrics to node-exporter textfile collector | none |
| `crowdsec` (profile-gated) | Custom (crowdsecurity/crowdsec:v1.7.8) | Host-wide cybersecurity engine (host syslog, SSH auth, and docker log analysis) | 8080 |

</details>

<details open>
<summary><h2>OMERO.web plugins</h2></summary>

### OMP Plugin (`omeroweb_omp_plugin`)

Filename-to-metadata extraction workflow. Parses scientific image filenames into structured key-value annotations and writes them to OMERO.

- Regex-based and AI-assisted filename parsing (supports Local/Ollama, Groq, Gemini, Claude, Perplexity, xAI, and Cohere)
- Variable set management with per-user PostgreSQL persistence
- Background job execution with progress tracking
- Hash-based ownership for safe plugin-only annotation deletion
- Rate limiting on major actions
- REMBI-aligned default variable names with scientific nomenclature-aware hyphen protection

### Import Plugin (`omeroweb_import`)

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
- docker container resource monitoring (stats, system info)
- Storage analytics by user and group
- Server and database diagnostic scripts
- Root-only access controls

### Tools Plugin (`omeroweb_tools`)

User-facing utilities that share the Admin Tools layout pattern without admin-only access.

- Landing page for future user tools inside OMERO.web
- Enhanced search over the OMERO index plus a user-scoped PostgreSQL metadata index stored only in the plugin database
- Fielded search UI for indexed image metadata with async image previews
- Saved queries per user in the plugin database
- Per-user opt-in metadata indexing with automatic background sync for that user's images
- Regular-user access only; root is intentionally blocked from running searches and refreshes

### Imaris Connector Plugin (`omero_imaris_connector`)

OMERO image export to Imaris (.ims) format.

- Celery-based async job execution with Redis broker
- Synchronous and asynchronous request modes with status polling
- OMERO CLI-based script launch from the `omeroweb` container
- Job-service account support for background execution
- ImarisConvertBioformats integration (compiled from source in server image)
- Standalone XT connector requires Windows 10 or newer on the Imaris
  workstation and includes a typed folder path selector for loading images into
  Imaris. `Export folder to OMERO` always opens the native folder chooser and
  can use the typed path only as the first chooser location hint for that
  session. User settings autosave stores host, port, username, HTTPS state,
  path, selected converter, and autosave state only, never the password. The
  password field clears after a successful login, and silent read-only health
  checks return the UI to connect-ready state if the OMERO connection is lost
  after retries.
- Container package inspection helper: `helper_scripts_debian/docker_image_analysis.sh`

### Shared Library (`omero_plugin_common`)

Common utilities shared across all plugins:

- `env_utils.py` -- typed environment variable loading with validation (string, int, float, bool, sanitized+bounded)
- `logging_utils.py` -- OMERO gateway log noise reduction
- `omero_helpers.py` -- OMERO object data extraction (text values, IDs, owners, permissions)
- `request_utils.py` -- Django request parsing (JSON body, username resolution)
- `string_utils.py` -- case conversion and message payload building

</details>

<details open>
<summary><h2>Deployment</h2></summary>

### Prerequisites

- Root access on the Linux host.
- 64-bit Linux distribution. Verified on Debian 13 (Trixie) on amd64.
- Hardware baseline:
  - CPU: minimum 8 cores for few-user operation
  - RAM: minimum 16 GB (32 GB recommended)
- docker engine and docker compose plugin installed on the host.
- Host storage paths with adequate filesystem permissions.
- Network access to GitHub configured if using the pull-based update workflow (see `installation/github_pull_project_bash`).

### Recommended installation workflow

This workflow mirrors the intended deployment pattern where the repository content is staged under a fixed host path and then synchronized with the pull/update workflow script.

**1.** Prepare the installation root (assumed path: `/opt/omero`; change according to your needs):

```bash
sudo mkdir -p /opt/omero/env
cd /opt/omero
```

**2.** Copy the following from the repository into `/opt/omero`:

- `installation_paths_example.env`
- `.env_example`
- `docker-compose.yml`
- `env/` directory
- `installation/` directory
- `helper_scripts_debian/` directory

Then, create runtime copies by removing the `_example` suffix where applicable
(`installation_paths.env`, environment files, etc.). The installer generates
`.env` from deployment-local values and renders Compose-only keys from
`.env_example` while preserving existing generated `.env` assignments. Keep
installation-specific settings in non-example runtime files; non-example runtime
files are authoritative and are not overwritten by the pull/update workflow.

> IMPORTANT!
> **Mandatory credential setup before first installation**
>
> Open `/opt/omero/env/omero_secrets.env` (the non-example renamed file) and replace the right-hand side of every empty variable with strong unique credentials (15+ random alphanumeric characters recommended). These credentials protect OMERO.web, the databases, and plugin services. It is recommended that you use a password manager for maximum security in your everyday web browsing activities.

**3.** Install docker using the official documentation for your OS. For example, for Debian, go to <https://docs.docker.com/engine/install/debian/> or use the provided convenience script: <https://docs.docker.com/engine/install/debian/#install-using-the-convenience-script>.

An experimental Debian 13 docker installation script exists at `/opt/omero/helper_scripts_debian/docker_debian_13_install_script`, but it is provided as-is and should be used only if you understand and accept that risk.

Upon completion, verify docker runtime health:

```bash
systemctl status docker
systemctl status containerd
docker --version
docker compose version
docker compose ps
```

**4.** Prepare and execute the pull/update workflow script:

```bash
cd /opt/omero
sudo chown root:root installation/github_pull_project_bash
sudo chmod +x installation/github_pull_project_bash
sudo bash ./installation/github_pull_project_bash
```

For the standard build-based workflow, the first prompt asks which source
version to install. Empty input or `latest` keeps the default behavior and uses
the latest commit from `REPO_BRANCH`; when `REPO_BRANCH` is unset, the launcher
resolves the repository's remote default branch instead of assuming a branch
name. An exact GitHub release tag uses that release's source tree; a commit hash
checks out that commit. Invalid or unavailable selections fail before repository
files are replaced. After the source tree is selected, the script prompts for
installation parameters (defaults are available), installs/updates all necessary
files, and finally starts the full stack upon choice. Installation duration
depends on host CPU and disk performance, and is optimized for multi-threaded
systems. For unattended standard installs, set `REPO_SOURCE_REF` to `latest`,
the release tag, or the commit hash; when it is unset in automation mode, the
launcher uses `latest`.

The pull/update script also saves a full terminal transcript of the visible session under `${OMERO_DATA_PATH}/installation_logs/`, for example `github_pull_project_bash_20260318T080431Z.log`. The destination is finalized after the installation paths are resolved, so runs that move `OMERO_DATA_PATH` still write the transcript into the selected data path.

### Easy installation with a prebuilt carrier image

The easy installer uses a manually published release carrier image from docker
hub instead of building the repository dockerfiles on the target host. The
carrier is a single docker image tagged with the same docker-compatible SemVer
version as the GitHub release. During installation,
`installation/easy_installation_script.sh` pulls that one carrier, verifies its
manifest and compressed archive checksum, loads the bundled runtime image tags
into docker by streaming the verified archive to `docker load`, then starts the
normal multi-container Compose deployment with `--no-build`.

The release workflow flattens the bundled runtime service images before they
are written into `runtime-images.tar.gz`. The carrier image itself is a
scratch-based data image with one payload layer and does not include Alpine,
BusyBox, a package manager, or a shell; it uses `HEALTHCHECK NONE` metadata
instead of a runnable healthcheck command.

This path does not switch to the build workflow if the carrier cannot be pulled, verified, streamed, or loaded. It fails before container startup so existing OMERO data and deployment-local environment files stay under the same installer ownership rules as the standard workflow.

Run the easy installer from an updated installation root. The first prompt asks
which prebuilt docker image tag to install:

```bash
cd /opt/omero
sudo bash ./installation/easy_installation_script.sh
```

Enter the docker hub carrier image tag. Do not use `latest`. For unattended
runs, set `PREBUILT_IMAGE_RELEASE` explicitly instead of relying on a prompt.

Carrier images are published with the manual `release-prebuilt-carrier` GitHub
Actions workflow. Store `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` as
repository secrets before running it. The workflow uses GitHub Actions'
built-in `GITHUB_TOKEN` with job-scoped `contents: write` permission to create
the GitHub release; no separate GitHub PAT secret is required when repository
Actions settings allow workflow write permissions. The release targets the
default branch ref, creates a draft GitHub release with source artifacts,
pushes and verifies the carrier image, then publishes the release. If the
carrier publish fails after the draft was created, the workflow deletes that
draft release and its tag. The release job deliberately does not use a GitHub
Actions environment, because job environments create deployment records. Keep
the Docker Hub credentials as repository secrets with the documented names.
Before the runtime archive is saved, the
workflow derives the required image references from Compose and prunes only
runner-local docker images outside that required set to keep hosted-runner
storage available without changing the released image list. The
`DOCKERHUB_TOKEN` value must be a docker hub access token with write access to
the carrier repository; do not store a docker hub account password there.

**5.** After a successful installation, run:

- Portainer: <http://localhost:9000> (set admin password on first login)
- OMERO.web: <http://localhost:4090>

Log in to OMERO.web using the root credential configured in `env/omero_secrets.env`.

### Environment configuration files

| File | Scope |
| --- | --- |
| `.env_example` | Template for Compose-only interpolation defaults mirrored into generated `.env`; existing `.env` values are preserved by the installer |
| `installation_paths_example.env` | Template for all required filesystem paths during installation |
| `env/omeroserver_example.env` | Template for server DB, Java heap, script processors, security, and all other OMERO.server settings |
| `env/omeroweb_example.env` | Template for web app registration, plugin config, admin tool endpoints, upload, and all other OMERO.web settings |
| `env/omero-celery_example.env` | Template for Celery broker URL, queue name, timeouts, worker concurrency |
| `env/grafana_example.env` | Template for Grafana admin and other settings |
| `env/omero_secrets_example.env` | Template for all credentials/secrets (must never be committed, should remain as a host-only file) |

Create deployment-local runtime files by copying these templates and removing `_example` in your target host path.

### Example templates and runtime files

- All `*_example*` files in this repository are the templates for configuration and operational helper scripts.
- For AI-assisted analysis and maintenance, AI Agents are instructed to always assume the corresponding non-example runtime files are present on the target system and structurally aligned with their `*_example*` versions.
- This split exists so update flows (including `installation/github_pull_project_bash`) can pull repository changes without replacing site-local runtime files, configured runtime paths, Buildx cache paths, or `.env_backups/` that admins manage outside git.
- The pull/update workflow preserves only existing site-local `logo/logo.png` in place (no backup/restore copy), while still refreshing sibling template assets such as `logo/logo_example.png` from upstream.

### Basic docker commands

```bash
# Stop all services without removing containers
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env stop

# Stop and remove all containers
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env down

# Check logs for a specific container (example: omeroweb)
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env logs -f omeroweb

# Rebuild a single container (example: omeroweb)
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env build omeroweb
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env up -d omeroweb
```

### Storage quotas

Storage quotas use Linux ext4 project quotas, not docker volume limits. Admin
Tools writes quota values to
`${OMERO_USER_DATA_PATH}/.admin-tools/group-quotas.json`; the host
`omero-quota-enforcer` systemd path/timer reads that file, assigns one ext4
project ID to each existing
`${OMERO_USER_DATA_PATH}/ManagedRepository/<group>` directory with `chattr`,
and applies identical soft and hard block limits with `setquota -P`.

Only the configured `ManagedRepository` under the current `OMERO_USER_DATA_PATH`
is counted. Bytes stored in another managed repository, on another filesystem,
or through in-place import paths are outside this quota domain and are not part
of the limit calculation.

Enablement is supported only on Debian 13 and Ubuntu 26.04 LTS, and only when
the filesystem containing `OMERO_USER_DATA_PATH` is ext4. Before changing the
host filesystem, take a backup or storage snapshot and plan downtime. If the
data filesystem is mounted, the helper may stop the Compose stack, unmount or
remount that filesystem, then start the stack again. It never uses forced or
lazy unmounts. If `OMERO_USER_DATA_PATH` is on `/` and the ext4 `project`
feature is not already enabled, the helper refuses to continue; enabling that
feature for a running root filesystem requires rescue media or a separate ext4
data filesystem.

Run the same command on Debian 13 and Ubuntu 26.04 LTS from the OMERO Docker
Extended installation directory:

```bash
sudo scripts/enable-storage-quotas.sh --yes-i-have-a-backup
```

The installer asks the same question during setup and defaults to `no`. The
helper verifies `/etc/os-release`, installs required host packages, runs a
disposable ext4 project-quota write-denial test, parses
`installation_paths.env`, resolves `OMERO_USER_DATA_PATH`, verifies the active
filesystem type, and matches exactly one active `/etc/fstab` entry. It appends
`prjquota` only when neither `prjquota` nor `project` is already present, keeps
all other mount options unchanged, and creates a timestamped `/etc/fstab`
backup only when it edits that file. If project quotas are already active, it
installs or refreshes only the enforcer units and does not tune, unmount,
remount, or rewrite the filesystem.

The helper exits before filesystem mutation for non-ext4 filesystems, missing
or duplicate `/etc/fstab` matches, unsupported fstab source types, nested
mounts below the data path, failed disposable quota self-tests, failed Compose
preflight checks, and root filesystems that still need the ext4 `project`
feature. Linux project quotas are enforced for normal OMERO and container
writes; privileged host-root writes can bypass quota accounting.

### Reverse proxy

This is currently disabled, but easy to enable, at least without strong certificate verification. Reverse proxy and TLS termination can be managed externally (e.g., nginx/Ansible). Forward traffic to `http://omeroweb:4090` on the docker network. Direct local access at `http://localhost:4090` remains available for troubleshooting.

</details>

<details open>
<summary><h2>Monitoring</h2></summary>

The observability stack provides:

- **Prometheus** scrapes 10 direct metric targets, plus blackbox HTTP probes
  for the configured service endpoints and TCP probes for 5 internal endpoints
  (databases, Redis, OMERO.server SSL, and OMERO.server).
- **Alloy** collects docker container logs and OMERO server/web internal log files, pushes to Loki.
- **Grafana** ships with 4 pre-provisioned dashboards: OMERO infrastructure, database metrics, plugin database metrics, Redis metrics.
- **Blackbox exporter** validates HTTP 2xx for all web endpoints and TCP connectivity for critical internal services.
- **CrowdSec** provides host-wide security telemetry by analyzing host syslog/auth logs and docker logs via mounted sources.

</details>

<details open>
<summary><h2>Database maintenance</h2></summary>

The `pg-maintenance` sidecar runs automated maintenance against both PostgreSQL databases:

- **Weekly** (Sunday, 03:00 am): `VACUUM ANALYZE` -- reclaims dead tuples, updates query planner statistics.
- **Monthly** (first Sunday, 04:00 am): `REINDEX CONCURRENTLY` -- rebuilds indexes online with short lock phases.

Both operations are designed for online use. However, they may briefly acquire locks; the maintenance scripts are configured to fail fast instead of waiting on locks.

</details>

<details open>
<summary><h2>Documentation</h2></summary>

Optional AI Agent compression is available to all supported agents via the
opt-in [`caveman`](https://github.com/JuliusBrussee/caveman) overlay for
internal AI communication only. Repository documentation, comments, docstrings,
function descriptions, and user-facing text stay in standard prose.

Broad AI Agent repo navigation must use the all-agent
`cocoindex-code-search` skill as the mandatory semantic routing gate before
exact `rg` validation. Agents check for an existing MCP server or tool named
`cocoindex-code` first, while using direct `rg` first only for precise string,
symbol, scanner-count, or already-small searches. Its wrapper keeps the pinned
host install under XDG data paths or `AGENT_COCOINDEX_HOME`, with
per-repository mirrors, databases, and runtime directories outside the live
checkout and no `.cocoindex_code/` there. The Codex installer writes a
host-stable launcher under `AGENT_COCOINDEX_HOME`, pins the target checkout with
`AGENT_COCOINDEX_REPO`, and repairs stale same-name entries instead of adding
duplicates. The wrapper
reuses matching daemons, starts one only when needed, and stops only daemons it
started itself so `ccc run-daemon` processes do not linger after CLI or MCP
checks. After MCP install or launcher changes, agents verify the stdio
handshake, raw protocol probes, and tool listing with
`python3 tools/cocoindex_agent_search.py mcp-smoke`; use `--include-search`
only against an existing active index. If it cold-indexes, agents tell the user
once that the first search can take several minutes; later searches reuse the
external cache. The mirror asks CocoIndex Code 0.2.33 to include every
Git-visible mirrored file pattern; CocoIndex indexes text-decodable content and
skips undecodable binary files.

MCP search itself never refreshes and can return stale active-index text after
local edits. Before relying on it for current-tree routing, agents refresh the
external index explicitly with
`python3 tools/cocoindex_agent_search.py index --allow-dirty-index` for an
intentional dirty-worktree index, or
`python3 tools/cocoindex_agent_search.py search --refresh "<query>"` on a clean
tree. Exact `rg`, file reads, and tests still confirm every candidate before
editing.

| Entry point | Purpose |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Agent/AI navigation map and working contract |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Architectural overview, layer model, dependency rules |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code specific working instructions |
| [`GEMINI.md`](GEMINI.md) | Gemini CLI project context |
| [`docs/reference/ai-agent-skills.md`](docs/reference/ai-agent-skills.md) | Harness-neutral skill catalog for recurring AI Agent workflows |
| [`docs/reference/ai-agent-integrations.md`](docs/reference/ai-agent-integrations.md) | Native adapter map for Copilot, Cursor, Claude, Gemini, and shared skills |
| [`docs/reference/ai-agent-upstream-sources.md`](docs/reference/ai-agent-upstream-sources.md) | Pinned upstream provenance for ECC-derived local skills, Karpathy baseline, and vendored caveman prompt references |
| [`docs/index.md`](docs/index.md) | Full documentation index with cross-links |
| [`docs/deployment/quickstart.md`](docs/deployment/quickstart.md) | Step-by-step deployment guide |
| [`docs/deployment/configuration.md`](docs/deployment/configuration.md) | Configuration reference |
| [`docs/plugins/`](docs/plugins/) | Per-plugin operation guides |
| [`docs/operations/`](docs/operations/) | Monitoring and maintenance runbooks |
| [`docs/troubleshooting/`](docs/troubleshooting/) | Diagnostic procedures |
| [`docs/reference/`](docs/reference/) | Endpoint map and release notes |

</details>

<details>
<summary><h2>Documentation rules</h2></summary>

- Keep `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `CLAUDE.md`, and `GEMINI.md` at repository root.
- Keep all other project documentation under `docs/`.
- Documentation structure is enforced by CI via `tools/lint_docs_structure.py`.
- Update `docs/index.md` cross-links when introducing new documents.

</details>

<details open>
<summary><h2>Copyright and third-party software notice</h2></summary>

This project is maintained in good faith for technical, educational, and operational use. The maintainer does not intend to infringe any copyright, trademark, license, or other intellectual property rights.

To the best of the maintainer's knowledge, all software dependencies and components used or referenced referenced in this repository are sourced from publicly available channels and are used under their respective published terms and conditions. No paid or proprietary software packages are intentionally redistributed through this repository unless explicitly identified and licensed for that purpose.

If you are a rights holder and believe any content, dependency reference, or distribution pattern in this repository is inappropriate or requires correction, please make contact by opening an issue and describe the concern so it can be reviewed and addressed promptly.

</details>

<details open>
<summary><h2>License</h2></summary>

See [LICENSE](LICENSE) for details.

</details>

<details open>
<summary><h2>Support</h2></summary>

If this project helps your work, you can show your support here:

[Support project maintenance](https://buymeacoffee.com/strmt7)

</details>
