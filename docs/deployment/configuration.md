# Deployment Configuration Guide

## Configuration Sources

This repository uses environment variables as the primary configuration surface.

Tracked files in git are templates (`*_example*`). Deployments must create runtime copies without `_example`.

- `installation_paths_example.env` -> `installation_paths.env`: filesystem path definitions.
- `env/omeroserver_example.env` -> `env/omeroserver.env`: OMERO.server runtime, DB, and script processor options.
- `env/omeroweb_example.env` -> `env/omeroweb.env`: OMERO.web apps, UI links, plugin settings, and admin tool endpoints.
- `env/omeroserver.env` is also loaded by `omeroweb` for shared server-derived settings (for example `CONFIG_omero_fs_repo_path` consumed by admin-tools quota compatibility checks).
- `env/omero-celery_example.env` -> `env/omero-celery.env`: Celery and Imaris connector processing controls.
- `env/grafana_example.env` -> `env/grafana.env`: Grafana credentials and runtime options (renamed from `env/compose.env`).
- `env/omero_secrets_example.env` -> `env/omero_secrets.env`: credentials and secrets (deployment-local only; never commit runtime secrets).

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

Paths declared in `installation_paths.env` map host storage into containers for:

- OMERO data,
- databases,
- OMERO server/web logs,
- monitoring state.

Ensure host paths exist and are writable by container runtime users before startup.

### Managed Repository Path Setting

In `env/omeroserver.env`, `CONFIG_omero_fs_repo_path` configures the managed
repository import parent-directory template.

OMERO expands supported terms automatically when written with surrounding `%`
characters (for example: `%group%/%user%/%year%-%month%-%day%/%time%`).

If token syntax is malformed (for example `%group/%user/%year-%month-%day/%time`
without trailing `%`), OMERO treats those strings literally and creates
directories named with `%...` segments.

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

## Reverse Proxy (Managed Externally)

Reverse proxy and TLS termination are managed outside this repository.

For OMERO.web forwarding from your external reverse proxy (for example, nginx managed via Ansible), target:

- Scheme: `http`
- Forward Hostname / IP: `omeroweb`
- Forward Port: `4090`

This keeps direct internal access to OMERO.web (`http://omeroweb:4090`) available while IT-managed proxy configuration is applied.
