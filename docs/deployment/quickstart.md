# Deployment Quick Start

## Prerequisites

- Docker Engine and Docker Compose plugin installed.
- Host storage paths prepared for OMERO data and logs.
- Appropriate filesystem permissions for container users.

## 1) Configure Environment Files

Review and update:

- `env/installation_paths.env`
- `env/omeroserver.env`
- `env/omeroweb.env`
- `env/omero-celery.env`
- `env/grafana.env`


Do not deploy with default credentials.

## 2) Build Images

```bash
docker compose --env-file env/installation_paths.env build
```

## 3) Start the Platform

```bash
docker compose --env-file env/installation_paths.env up -d
```

## 4) Verify Service Health

```bash
docker compose --env-file env/installation_paths.env ps
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
docker compose --env-file env/installation_paths.env stop

# Stop and remove containers
docker compose --env-file env/installation_paths.env down

# Follow logs for a service
docker compose --env-file env/installation_paths.env logs -f omeroweb
```

## External Reverse Proxy setup (IT-managed)

1. Configure your external reverse proxy (for example, nginx managed via Ansible) to forward traffic to `http://omeroweb:4090`.
2. Keep direct local HTTP access available at `http://localhost:4090` for troubleshooting when needed.
3. Manage TLS certificates in your external proxy stack.
