# New User Onboarding

Step-by-step onboarding flow for deployment operators setting up the platform for the first time.

## Prerequisites

- Docker Engine and Docker Compose plugin installed on the target host.
- SSH key configured for GitHub access (if using the pull-based update workflow).
- Sufficient disk space for OMERO data, databases, logs, and monitoring state.
- Filesystem permissions appropriate for container runtime users.

## Onboarding steps

### 1. Prepare environment files

```bash
cp installation_paths_example.env installation_paths.env
cp env/omeroserver_example.env env/omeroserver.env
cp env/omeroweb_example.env env/omeroweb.env
cp env/omero-celery_example.env env/omero-celery.env
cp env/grafana_example.env env/grafana.env
```

Edit each file to set site-specific values. Rotate all default credentials.

### 2. Build and start services

```bash
bash installation/installation_script.sh
```

Or manually:

```bash
docker compose --env-file installation_paths.env build
docker compose --env-file installation_paths.env up -d
```

### 3. Verify service health

```bash
docker compose --env-file installation_paths.env ps
```

All services should show `healthy` or `running` status. Check logs if any service is unhealthy:

```bash
docker compose --env-file installation_paths.env logs --since=10m <service-name>
```

### 4. Verify plugin availability

Open OMERO.web at `http://localhost:4090` and confirm:
- Login works with valid OMERO credentials.
- Plugin menu entries are visible in the top navigation (OMP Plugin, Upload, Admin Tools).
- Each plugin page loads without errors.

### 5. Verify monitoring

- Grafana: `http://localhost:3000` -- confirm dashboards load with data.
- Prometheus: `http://localhost:9090/targets` -- confirm all targets are UP.
- Portainer: `https://localhost:9443` -- confirm container visibility.

### 6. First operational checks

- Confirm OMERO.server logs show successful startup and script registration.
- Confirm Celery worker process is active (if Imaris export is enabled).
- Confirm pg-maintenance container is running with cron active.
- Run a test metadata parse, upload, or Imaris export to validate end-to-end functionality.

## Post-onboarding

- Configure your external reverse proxy to forward to `http://omeroweb:4090`.
- Set up TLS certificates in your proxy stack.
- Review `docs/SECURITY.md` for hardening checklist.
- Bookmark `docs/troubleshooting/common.md` for operational reference.
