# Admin Tools Plugin Guide (`omeroweb_admin_tools`)

## Purpose
The admin tools plugin exposes operational interfaces for logs, system resource visibility, and storage usage analytics within OMERO.web.

## Main Capabilities

- log query and label browsing,
- embedded/proxied Grafana and Prometheus views,
- resource monitoring panels,
- storage usage views by user and group,
- root-status checks for environment diagnostics.

## Key Routes

- `/omeroweb_admin_tools/`
- `/omeroweb_admin_tools/logs/`
- `/omeroweb_admin_tools/logs/data/`
- `/omeroweb_admin_tools/logs/internal-labels/`
- `/omeroweb_admin_tools/resource-monitoring/`
- `/omeroweb_admin_tools/resource-monitoring/data/`
- `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/<subpath>`
- `/omeroweb_admin_tools/resource-monitoring/prometheus-proxy/<subpath>`
- `/omeroweb_admin_tools/storage/`
- `/omeroweb_admin_tools/storage/data/`

## Dependencies

This plugin expects reachable service endpoints configured in `env/omeroweb.env`:

- `ADMIN_TOOLS_LOKI_URL`
- `ADMIN_TOOLS_GRAFANA_URL`
- `ADMIN_TOOLS_PROMETHEUS_URL`

## Typical Admin Workflow

1. Use Logs page to inspect recent service events.
2. Use Resource Monitoring to inspect infrastructure health and dashboards.
3. Use Storage page to identify growth hotspots by user/group.
4. Apply operational action externally (cleanup, scaling, user guidance).

## Operator Checklist

- Validate connectivity to Loki/Prometheus/Grafana.
- Restrict plugin access to authorized admin users.
- Review dashboard provisioning files after monitoring changes.
- Keep query timeouts and entry caps aligned with cluster scale.
