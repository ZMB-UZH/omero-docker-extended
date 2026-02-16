# OMERO ZMB OMP Platform

OMERO deployment and plugin repository for metadata workflows, upload/import management, monitoring interfaces, and Imaris export integration.

## What this repository contains

- Container orchestration for OMERO services and dependencies.
- Docker build definitions for server, web, worker, and support images.
- Environment-based configuration files.
- Startup scripts for deterministic service initialization.
- OMERO.web plugin packages:
  - `omeroweb_omp_plugin`
  - `omeroweb_upload`
  - `omeroweb_admin_tools`
  - `omeroweb_imaris_connector`
- Shared plugin utilities in `omero_plugin_common`.
- Project documentation in `docs/`.

## Repository layout

- `docker-compose.yml` — service orchestration.
- `docker/` — Dockerfiles.
- `env/` — environment variable files.
- `startup/` — startup and bootstrap scripts.
- `monitoring/` — Prometheus, Grafana, Loki, Alloy, dashboards.
- `maintenance/` — maintenance automation scripts.
- `omeroweb_omp_plugin/` — filename/metadata plugin.
- `omeroweb_upload/` — upload/import plugin.
- `omeroweb_admin_tools/` — admin tools plugin.
- `omeroweb_imaris_connector/` — Imaris connector plugin.
- `docs/` — documentation set.

## Setup flow

1. Review and update configuration in `env/`.
2. Build images:

```bash
docker compose --env-file env/installation_paths.env build
```

3. Start services:

```bash
docker compose --env-file env/installation_paths.env up -d
```

4. Verify service state:

```bash
docker compose --env-file env/installation_paths.env ps
```

## Documentation entry points

- `docs/index.md`
- `docs/architecture/system-overview.md`
- `docs/deployment/quickstart.md`
- `docs/deployment/configuration.md`
- `docs/plugins/`
- `docs/operations/`
- `docs/troubleshooting/`
- `docs/reference/`

## Documentation rules

- Keep repository-root Markdown limited to `README.md`.
- Keep all other project documentation under `docs/`.
- Keep content instructional and implementation-focused.
