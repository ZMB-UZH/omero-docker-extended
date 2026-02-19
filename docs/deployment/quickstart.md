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
- When `DOCKER_REGISTRY_PREFIX` is set, `DOCKER_BUILD_PUSH_IMAGES` defaults to `1` (push enabled).
- When `DOCKER_REGISTRY_PREFIX` is unset, `DOCKER_BUILD_PUSH_IMAGES` defaults to `0` (local images only).
- By default, build targets are auto-discovered from `docker-compose.yml` (all services with a `build:` block).
- Override `DOCKER_BUILD_TARGETS` only if you explicitly want a subset of services.
- `DOCKER_REGISTRY_PREFIX` is only required when push mode is enabled.
- The installation workflow enables this compressed Buildx mode by default, and prompts whether to keep Buildx enabled during each interactive run (question 2). If you disable it, the script falls back to `docker compose build`. Run:

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
- For unattended automation, you can explicitly set `INSTALLATION_AUTOMATION_MODE=1`.

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
```

## External Reverse Proxy setup (IT-managed)

1. Configure your external reverse proxy (for example, nginx managed via Ansible) to forward traffic to `http://omeroweb:4090`.
2. Keep direct local HTTP access available at `http://localhost:4090` for troubleshooting when needed.
3. Manage TLS certificates in your external proxy stack.
