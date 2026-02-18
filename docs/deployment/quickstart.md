# Deployment Quick Start

## Prerequisites

- Docker Engine and Docker Compose plugin installed.
- Host storage paths prepared for OMERO data and logs.
- Appropriate filesystem permissions for container users.

## 1) Configure Environment Files

Review and update:

- `installation_paths.env`
- `env/omeroserver.env`
- `env/omeroweb.env`
- `env/omero-celery.env`
- `env/grafana.env`
- `env/omero_secrets.env`  (ALL credentials live here; YOU create it manually from `env/omero_secrets_example.env` and keep it only on the server)


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
