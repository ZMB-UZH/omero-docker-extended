# Service and Plugin Endpoints Reference

## Infrastructure Endpoints (default host mappings)

- OMERO.web: `http://localhost:4090`
- Portainer: `https://localhost:9443` (and `http://localhost:9000` when enabled)
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Loki API: `http://localhost:3100`

Validate mapped ports in your active `docker-compose.yml` deployment.

## OMERO.web Plugin Routes

### OMP Plugin
Base: `/omeroweb_omp_plugin/`

Key actions:
- project listing,
- metadata job launch + progress,
- variable sets,
- AI credentials,
- user settings and data deletion.

### Upload Plugin
Base: `/omeroweb_upload/`

Key actions:
- start/upload/import/confirm/prune/status,
- project listing,
- user and special-method settings.

### Admin Tools Plugin
Base: `/omeroweb_admin_tools/`

Key actions:
- logs UI + data,
- resource monitoring and data,
- Grafana/Prometheus proxy,
- storage UI + data.

### Imaris Connector
Endpoint: `/imaris-export/`

Key actions:
- start export,
- poll export status,
- download completed result.
