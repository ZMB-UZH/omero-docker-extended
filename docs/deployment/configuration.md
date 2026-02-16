# Deployment Configuration Guide

## Configuration Sources

This repository uses environment variables as the primary configuration surface.

- `env/installation_paths.env`: filesystem path definitions (including reverse-proxy state paths).
- `env/omeroserver.env`: OMERO.server runtime, DB, and script processor options.
- `env/omeroweb.env`: OMERO.web apps, UI links, plugin settings, and admin tool endpoints.
- `env/omero-celery.env`: Celery and Imaris connector processing controls.
- `env/grafana.env`: Grafana credentials and runtime options (renamed from `env/compose.env`).

## Required Hardening Before Deployment

1. Rotate all credentials and secrets.
2. Disable debug options where enabled.
3. Review open host ports and reduce exposure.
4. Confirm TLS and secure session settings.
5. Restrict external access to monitoring services.

## Plugin Registration

Plugins are registered in `CONFIG_omero_web_apps` and top-link entries in `CONFIG_omero_web_ui_top__links`.

When adding or removing a plugin:

1. update app registration,
2. update URL mapping,
3. restart OMERO.web,
4. verify menu link visibility and route health.

## Data and Logs

Paths declared in `env/installation_paths.env` map host storage into containers for:

- OMERO data,
- databases,
- OMERO server/web logs,
- monitoring state.

Ensure host paths exist and are writable by container runtime users before startup.

## Celery and Imaris Export Configuration

Relevant variables include:

- `OMERO_IMS_USE_CELERY`
- `OMERO_IMS_CELERY_BROKER_URL`
- `OMERO_IMS_CELERY_BACKEND_URL`
- `OMERO_IMS_CELERY_QUEUE`
- timeout/retry/concurrency controls

Queue names and broker URLs must be consistent between job producer and worker.

## Configuration Change Process (Recommended)

1. Edit env files in version control.
2. Validate syntax and variable expansions.
3. Rebuild/restart impacted services.
4. Run health checks and targeted plugin workflow checks.
5. Document the change in release notes.

## Reverse Proxy (Nginx Proxy Manager)

Nginx Proxy Manager is exposed on host ports `80`, `81`, and `443`.

- Admin UI: `http://<host>:81`
- HTTP proxy entry point: `http://<host>:80`
- HTTPS proxy entry point: `https://<host>:443`

For OMERO.web forwarding, create a host in Nginx Proxy Manager with:

- Scheme: `http`
- Forward Hostname / IP: `omeroweb`
- Forward Port: `4090`

This preserves local/internal HTTP access to OMERO.web while allowing you to add TLS certificates later inside Nginx Proxy Manager.
