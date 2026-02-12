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
- `env/compose.env`

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
