# OMERO.web Help — Admin Tools (`omeroweb_admin_tools`)

## Overview

Admin Tools provides operational interfaces for OMERO platform administrators, including aggregated logs, infrastructure monitoring, storage/quota analytics, and diagnostic script execution.

## Access model

- Intended for the **OMERO root/admin user**.
- Non-root users are intentionally blocked in the UI.
- Treat all actions as production-impacting.

## Main sections

### 1) Logs

Purpose: inspect service logs in one place (OMERO.server, OMERO.web, databases, Redis, and related components).

Use cases:

- incident triage,
- verifying deployment changes,
- validating service recoveries.

### 2) Resource monitoring

Purpose: live operational view of host and service health.

Capabilities include:

- host CPU/memory/disk indicators,
- Grafana and Prometheus reachability,
- scrape target health summary,
- Docker compose service-health diagnostics.

### 3) Storage viewer & quotas

Purpose: visualize storage usage and manage per-group quotas.

Capabilities include:

- user/group/top-N storage distribution views,
- quota editing with minimum thresholds,
- CSV template export/import for quota management,
- quota enforcement log visibility.

### 4) OMERO.server and database testing

Purpose: run packaged diagnostics against server and PostgreSQL services.

Capabilities include:

- script selection and execution,
- PASS/WARN/FAIL result badges,
- response metadata and request identifiers.

## Operational guardrails

- Apply quota changes deliberately and in maintenance-aware windows.
- Capture request IDs and result payloads for auditability.
- For severe failures, preserve diagnostics before rerunning scripts.

## Troubleshooting

- **No data loaded**: confirm backend services and plugin API endpoints are reachable.
- **Monitoring links unauthorized/not found**: use documented Grafana navigation guidance in UI subtitle.
- **Quota updates fail**: verify repository compatibility and permissions.
- **Diagnostics fail broadly**: investigate shared infrastructure dependencies first (database, network, Docker health).

## Best practices

- Use Logs + Monitoring together during incidents.
- Establish recurring quota reviews for top-consuming groups.
- Run diagnostics after major upgrades and before release sign-off.
