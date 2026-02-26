# Deployment Quick Start

## Prerequisites

- Docker Engine and Docker Compose plugin installed.
- Host storage paths prepared for OMERO data and logs.
- Appropriate filesystem permissions for container users.

## 1) Configure Environment Files

Create deployment-local runtime files from the tracked templates, then review and update:

- `installation_paths_example.env` -> `installation_paths.env`
- `env/omeroserver_example.env` -> `env/omeroserver.env`
- `env/omeroweb_example.env` -> `env/omeroweb.env`
- `env/omero-celery_example.env` -> `env/omero-celery.env`
- `env/grafana_example.env` -> `env/grafana.env`
- `env/omero_secrets_example.env` -> `env/omero_secrets.env` (ALL credentials live here; keep runtime secret files only on the server)

Do not deploy with default credentials.

`docker compose` commands run from the repository root automatically load
both `installation_paths.env` and `env/omero_secrets.env` via `.env` (`COMPOSE_ENV_FILES`).

IMPORTANT: This stack uses additional variables from `env/omero_secrets.env` (credentials; never auto-created).
After `installation/installation_script.sh` runs, generated `.env` includes
`COMPOSE_ENV_FILES=installation_paths.env:env/omero_secrets.env` and mirrors the
compose-interpolated secret variables (`OMERO_DB_PASS`, `OMP_PLUGIN_DB_PASS`) so
manual `docker compose` commands resolve required variables automatically.

If `.env` is missing (for example before first installation), export secrets first:

```bash
set -a
source env/omero_secrets.env
set +a
```

Then run your `docker compose ...` commands as usual.


If you run compose commands from a different working directory, pass:

```bash
docker compose --env-file installation_paths.env <command>
```

## 2) Build Images

```bash
docker compose --env-file installation_paths.env build
```

### Optional: Build + push compressed images with Buildx

For registry-oriented deployments, use BuildKit/Buildx compression to reduce
image transfer size and improve pull speed. The repository includes an example
helper script that wraps `docker buildx bake` and validates required inputs:

```bash
DOCKER_REGISTRY_PREFIX=myregistry.example.com/omero \
DOCKER_IMAGE_TAG=2026.02.0 \
DOCKER_BUILD_COMPRESSION_TYPE=zstd \
DOCKER_BUILD_COMPRESSION_LEVEL=15 \
./installation/docker_buildx_compressed_push.sh
```

Notes:

- If unset, `DOCKER_IMAGE_TAG` defaults to `custom`.
- Compression is explicit and environment-driven (`DOCKER_BUILD_COMPRESSION_*`).
- When push mode is disabled (`DOCKER_BUILD_PUSH_IMAGES=0`, the default without `DOCKER_REGISTRY_PREFIX`), the helper builds local images without `force-compression=true` to avoid unnecessary BuildKit recompression/memory pressure.
- When `DOCKER_REGISTRY_PREFIX` is set, `DOCKER_BUILD_PUSH_IMAGES` defaults to `1` (push enabled).
- When `DOCKER_REGISTRY_PREFIX` is unset, `DOCKER_BUILD_PUSH_IMAGES` defaults to `0` (local images only).
- By default, build targets are auto-discovered from `docker-compose.yml` (all services with a `build:` block).
- Override `DOCKER_BUILD_TARGETS` only if you explicitly want a subset of services.
- `DOCKER_REGISTRY_PREFIX` is only required when push mode is enabled.
- Transient Buildx export failures are retried automatically, including layer-lock contention (`(*service).Write failed ... ref layer-sha256:... locked ... unavailable`) and cache-export transport failures (`failed to receive status ... Unavailable ... EOF`).
- OMERO.web and OMERO.server image builds now harden Rocky package retrieval by default: retry transient `dnf` metadata/package fetch failures (for example mirror `500/504` responses), prefer Rocky `mirrorlist` as a fallback only after the first `dnf` failure, then clean metadata/cache before retrying so transient mirror errors can recover without changing first-attempt behavior. The default profile is intentionally strict: 3 attempts, no inter-attempt sleep, `--setopt=timeout=20`, and `--setopt=retries=2`.
- Advanced override: Docker builds can tune these safeguards with `--build-arg DNF_MAX_ATTEMPTS=...`, `--build-arg DNF_RETRY_SLEEP_SECONDS=...`, and `--build-arg DNF_USE_ROCKY_MIRRORLIST=0|1`.
- During `pg-maintenance` image builds on Debian-based images, `invoke-rc.d`/`policy-rc.d` and `sysctl: permission denied on key ...` messages can appear while package post-install scripts run in an unprivileged build container; these are expected build-time warnings when the layer still completes successfully.
- Retry behavior is configurable via `DOCKER_BUILD_BAKE_RETRY_COUNT` (default: `3`) and `DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS` (default: `2`).
- `DOCKER_BUILD_BAKE_SERIAL_MODE` controls execution strategy: `auto` (default), `always`, or `never`.
- The helper enforces `DOCKER_BUILDX_DRIVER=docker-container` and will fail fast if another driver is requested (local cache export requires the containerized BuildKit driver).
- Optional `DOCKER_BUILDX_DRIVER_OPTS` (comma-separated `key=value` values) are passed through to `docker buildx create --driver-opt` for deterministic BuildKit sizing/tuning.
- Set `DOCKER_BUILDX_FORCE_RECREATE_BUILDER=1` to force builder recreation when testing driver/driver-opt changes.
- In `auto` mode, multi-target cached builds run serially up front when local cache export is enabled (to avoid known BuildKit local-cache lock contention); if lock contention still appears in parallel mode, the helper falls back to serial per-target `buildx bake` execution.
- Root cause note: observed hangs occur during BuildKit local cache export (`exporting cache to client directory`) and are amplified by `cache-to mode=max` on large multi-stage images.
- Local cache export remains enabled by default (`DOCKER_BUILD_LOCAL_CACHE_ENABLED=1`), but now uses `DOCKER_BUILD_LOCAL_CACHE_MODE=min` by default to reduce cache-export pressure while keeping deterministic cache reuse.
- Local cache export now writes each target into a per-run staging directory and atomically swaps it into place only after a successful build, preventing unbounded stale cache growth from interrupted/failed exports.
- Set `DOCKER_BUILD_LOCAL_CACHE_MODE=max` only when you explicitly need full cache graph export despite the higher risk of long export phases.
- If retries still fail with cache-export transport errors, the helper automatically performs one fallback build with local cache export disabled for that run (compression remains enabled).
- Image compression settings (`DOCKER_BUILD_COMPRESSION_TYPE`, `DOCKER_BUILD_COMPRESSION_LEVEL`, `force-compression=true`) are unchanged by local cache mode; compressed image output remains enabled.
- The installation workflow enables this compressed Buildx mode by default, and prompts whether to keep Buildx enabled during each interactive run (question 2). If you disable it, the script falls back to `docker compose build`. Run:
- If you answer **No** to the installation prompt `Use build cache?`, the installer now performs deterministic local cache cleanup before rebuilding:
  - always prunes Docker builder cache (`docker builder prune -a -f`),
  - and, when Buildx compressed workflow is enabled for that run, also removes the Buildx local cache directory (auto-detected from `BUILDX_DATA_PATH` or defaulting to `${OMERO_DATA_PATH}/buildx_cache`).
  This keeps "no cache" runs consistent with operator expectations while avoiding unnecessary Buildx cache deletion when Buildx is disabled.

```bash
bash installation/installation_script.sh
```

- To push compressed images to a registry, run:

```bash
DOCKER_REGISTRY_PREFIX=myregistry.example.com/omero \
DOCKER_IMAGE_TAG=2026.02.0 \
bash installation/installation_script.sh
```

- `github_pull_project_bash` preserves the installation script prompts by default.
- `github_pull_project_bash` defaults to `REPO_BRANCH=main` only for that script; branch defaults for other pull scripts are script-specific.
- For unattended automation, you can explicitly set `INSTALLATION_AUTOMATION_MODE=1`.
- `installation/installation_script.sh` rewrites `installation_paths.env` only after path prompts are resolved, so selected non-default paths are persisted immediately for future pull/update runs.

- To integrate with the pull/update workflow, run:

```bash
bash github_pull_project_bash
```

## 3) Start the Platform

```bash
docker compose --env-file installation_paths.env up -d
```

## 4) Verify Service Health

```bash
docker compose --env-file installation_paths.env ps
```

Verify all required services are `healthy` or `running`.

## 5) Basic Connectivity Checks

```bash
curl -I http://localhost:4090
```

Adjust host/port if your deployment maps OMERO.web differently.

## 6) First Operational Checks

- Confirm OMERO.server and OMERO.web logs show successful startup.
- Confirm plugin menu entries are visible in OMERO.web.
- Confirm Celery worker process is active if Imaris export is enabled.
- Confirm monitoring endpoints are scraping targets.

## Lifecycle Commands

```bash
# Stop services without removing resources
docker compose --env-file installation_paths.env stop

# Stop and remove containers
docker compose --env-file installation_paths.env down

# Follow logs for a service
docker compose --env-file installation_paths.env logs -f omeroweb

# Remove optional post-build leftovers (redis-sysctl-init + buildx buildkit)
bash installation/cleanup_build_containers.sh
```

## External Reverse Proxy setup (IT-managed)

1. Configure your external reverse proxy (for example, nginx managed via Ansible) to forward traffic to `http://omeroweb:4090`.
2. Keep direct local HTTP access available at `http://localhost:4090` for troubleshooting when needed.
3. Manage TLS certificates in your external proxy stack.
