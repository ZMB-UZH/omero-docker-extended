# Product Sense

Understanding who uses this platform and what matters to them.

## User personas

### Microscopy researchers
Primary users who interact with OMERO.web plugins daily. They need:
- Reliable metadata workflows (OMP plugin) that correctly parse complex scientific filenames.
- Straightforward file upload and import (Upload plugin) that handles specialized formats like SEM-EDX.
- Imaris export (Imaris connector) that works asynchronously without blocking their session.
- Predictable behavior: the same inputs should produce the same outputs every time.

### Platform operators
Administrators who deploy, monitor, and maintain the OMERO installation. They need:
- Clear deployment procedures with explicit configuration surfaces.
- Operational visibility through logs, metrics, and dashboards (Admin tools plugin).
- Automated maintenance that runs safely without intervention (pg-maintenance).
- Troubleshooting procedures that lead to resolution without guesswork.

### Integration developers
Engineers who extend or modify the platform. They need:
- Clear architectural boundaries and consistent plugin patterns.
- Environment-driven configuration that works identically across dev/staging/production.
- Documentation that accurately reflects the current state of the code.

## Product principles

1. **Reliability over speed**: favor recoverability and correctness over rapid but fragile feature additions. A failed upload or lost annotation is worse than a slower workflow.
2. **Operational impact awareness**: ensure operational impact is documented before merge. Changes to startup scripts, Docker configuration, or monitoring affect the entire platform.
3. **Preserve contracts**: minimize surprise by preserving existing plugin API contracts, URL routes, and configuration variables unless explicitly versioned and documented.
4. **Explicit over implicit**: users and operators should not need to guess what a setting does or where a log file lives. Error messages should point to the correct env file and variable name.
5. **Autonomous maintenance**: the platform should run unattended between deployments. Database maintenance, log rotation, and health monitoring operate automatically.
