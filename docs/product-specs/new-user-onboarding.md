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
cp env/omero_secrets_example.env env/omero_secrets.env
```

Edit each file to set site-specific values. Rotate all default credentials.

### 2. Build and start services

```bash
bash installation/installation_script.sh
```

Or manually:

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env build
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env up -d
```

### 3. Verify service health

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env ps
```

All services should show `healthy` or `running` status. Check logs if any service is unhealthy:

```bash
docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env logs --since=10m <service-name>
```

### 4. Verify plugin availability

Discover the active OMERO.web binding and open that URL:

```bash
container="$(docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env ps -q omeroweb)"
base_url=""
while read -r _arrow_prefix _arrow binding; do
  [ -n "${binding:-}" ] || continue
  host="${binding%:*}"
  port="${binding##*:}"
  host="${host#[}"
  host="${host%]}"
  case "$host" in
    ""|0.0.0.0|::) host="127.0.0.1" ;;
    *:*) host="[${host}]" ;;
  esac
  candidate="http://${host}:${port}"
  if curl -fsS -o /dev/null "${candidate}/webgateway/"; then
    base_url="$candidate"
    break
  fi
done < <(docker port "$container")
[ -n "$base_url" ] || { echo "OMERO.web binding not found" >&2; exit 1; }
printf '%s\n' "$base_url"
```

Then confirm:

- Login works with valid OMERO credentials.
- Plugin menu entries are visible for an account that is allowed to use them.
- Each plugin page loads without errors.
- If no regular users or data exist yet, create disposable verification
  fixtures or verify only the blank-state behavior.

### 5. Verify monitoring

- Grafana: `http://localhost:3000` -- confirm dashboards load with data.
- Prometheus: `http://localhost:9090/targets` -- confirm all targets are UP.
- Portainer: `https://localhost:9443` -- confirm container visibility.

### 6. First operational checks

- Confirm OMERO.server logs show successful startup and script registration.
- Confirm the `omeroweb` supervisord programs are active: OMERO.web, Imaris Celery worker, Tools Celery worker, and storage-quota reconciliation loop.
- If using OMP's Local AI provider, confirm the `ollama` service is healthy and the configured model is available.
- Confirm pg-maintenance container is running with cron active.
- Run a test metadata parse, upload, or Imaris export to validate end-to-end functionality.

## Post-onboarding

- Configure your external reverse proxy to forward to `http://omeroweb:4090`.
- Set up TLS certificates in your proxy stack.
- Review `docs/SECURITY.md` for hardening checklist.
- Bookmark `docs/troubleshooting/common.md` for operational reference.
