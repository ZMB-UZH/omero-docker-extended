# System Architecture Overview

## Purpose
This platform packages an OMERO deployment and extends OMERO.web with domain-specific plugins for metadata workflows, uploads, administrative observability, and Imaris export automation.

## Core Runtime Components

- **OMERO.server**: stateful backend, script execution, and data access API.
- **OMERO.web**: Django-based web frontend with registered plugin apps.
- **PostgreSQL databases**:
  - primary OMERO database,
  - plugin database for plugin-specific storage.
- **Redis**:
  - cache backend,
  - Celery broker/result backend for async Imaris jobs.
- **Monitoring stack**: Prometheus + Loki + Alloy + Grafana + exporters.

## Plugin Architecture

All plugin packages are standard Django app modules and register runtime logging behavior in `AppConfig.ready()`.

- `omeroweb_omp_plugin`: filename parsing, metadata processing, variable sets, AI-backed regex/value helper flows.
- `omeroweb_upload`: multipart/staged upload with job tracking and import confirmation.
- `omeroweb_admin_tools`: log exploration, resource monitoring dashboards, and storage analytics.
- `omeroweb_imaris_connector`: IMS export request endpoint with async processing and download workflow.

Shared helper modules live in `omero_plugin_common` for logging and request utility behavior.

## Configuration Model

Configuration is environment-driven (`env/*.env`) and consumed by Docker Compose and service startup scripts.

Design priorities:

- explicit paths,
- explicit service endpoints,
- reproducible builds via pinned image tags,
- startup checks and health probes.

## Security and Operations Notes

- Use least privilege where possible (`security_opt: no-new-privileges:true` in services).
- Replace default credentials before deployment.
- Keep secret values out of public derivatives.
- Validate health checks and logs after each deployment change.
