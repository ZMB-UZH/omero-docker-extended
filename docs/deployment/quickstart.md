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

If you use Nginx Proxy Manager, also verify `NGINX_PROXY_MANAGER_DATA_PATH` and `NGINX_PROXY_MANAGER_LETSENCRYPT_PATH` in `env/installation_paths.env`.

Do not deploy with default credentials.

## 2) Build Images

```bash
docker compose build
```

## 3) Start the Platform

```bash
docker compose up -d
```

## 4) Verify Service Health

```bash
docker compose ps
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
docker compose stop

# Stop and remove containers
docker compose down

# Follow logs for a service
docker compose logs -f omeroweb
```

## Optional Nginx Proxy Manager setup

1. Open `http://localhost:81` and complete the initial admin setup.
2. Add a Proxy Host for OMERO.web targeting `http://omeroweb:4090`.
3. Keep direct local HTTP access available at `http://localhost:4090` during migration.
4. Add TLS certificates in Nginx Proxy Manager when ready.
