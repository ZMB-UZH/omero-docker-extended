# Admin Tools Plugin Guide (`omeroweb_admin_tools`)

## Purpose

The admin tools plugin exposes operational interfaces for log exploration, system resource visibility, storage analytics, and server diagnostics within OMERO.web. Access is restricted to OMERO root users.

## Main capabilities

- Log query via Loki (LogQL) with container filtering and internal log file browsing.
- Embedded/proxied Grafana dashboards and Prometheus query interface.
- Docker container resource monitoring (stats, system info, process lists).
- Storage usage analytics by user and group from OMERO API.
- Server and database diagnostic scripts (platform end-to-end health checks).
- Root-only access enforcement on all endpoints.

## Key routes

| Route | Method | Purpose |
|---|---|---|
| `/omeroweb_admin_tools/` | GET | Main admin dashboard |
| `/omeroweb_admin_tools/root-status/` | GET | Check root user status |
| `/omeroweb_admin_tools/logs/` | GET | Log exploration UI |
| `/omeroweb_admin_tools/logs/data/` | GET | Fetch log entries from Loki |
| `/omeroweb_admin_tools/logs/internal-labels/` | GET | List internal log file labels |
| `/omeroweb_admin_tools/resource-monitoring/` | GET | Resource monitoring UI |
| `/omeroweb_admin_tools/resource-monitoring/data/` | GET | Fetch container stats and system info |
| `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/<subpath>` | GET/POST | Proxy to Grafana API |
| `/omeroweb_admin_tools/resource-monitoring/prometheus-proxy/<subpath>` | GET/POST | Proxy to Prometheus API |
| `/omeroweb_admin_tools/storage/` | GET | Storage analytics UI |
| `/omeroweb_admin_tools/storage/data/` | GET | Fetch storage usage data |
| `/omeroweb_admin_tools/server-database-testing/` | GET | Server diagnostics UI |
| `/omeroweb_admin_tools/server-database-testing/run/` | POST | Execute diagnostic scripts |

## Code structure

```
omeroweb_admin_tools/
├── views/
│   ├── index_view.py        # All view functions (logs, monitoring, storage, diagnostics)
│   └── utils.py             # Request utility re-exports
├── services/
│   ├── log_query.py         # Loki LogQL query builder and response parser
│   └── system_diagnostics.py # Platform diagnostic scripts
├── config.py                # LogConfig dataclass, Loki/monitoring endpoint configuration
├── templates/omeroweb_admin_tools/
│   ├── index.html                    # Main dashboard
│   ├── logs.html                     # Log exploration
│   ├── resource_monitoring.html      # Resource monitoring with Grafana iframe
│   ├── storage.html                  # Storage analytics
│   └── server_database_testing.html  # Diagnostic scripts
└── static/omeroweb_admin_tools/styles.css
```

## Dependencies

This plugin requires reachable monitoring service endpoints configured in `env/omeroweb.env`:

| Variable | Purpose | Example |
|---|---|---|
| `ADMIN_TOOLS_LOKI_URL` | Loki base URL for log queries | `http://loki:3100` |
| `ADMIN_TOOLS_GRAFANA_URL` | Grafana base URL for dashboard embedding | `http://grafana:3000` |
| `ADMIN_TOOLS_PROMETHEUS_URL` | Prometheus base URL for metric queries | `http://prometheus:9090` |
| `ADMIN_TOOLS_LOG_LOOKBACK_SECONDS` | Default log query time range | `3600` |
| `ADMIN_TOOLS_LOG_MAX_ENTRIES` | Maximum log entries per query | `5000` |
| `ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS` | HTTP timeout for Loki requests | `30` |

The Docker socket (`/var/run/docker.sock`) must be mounted read-only for container stats functionality.

Grafana proxy authentication depends on passing session and auth headers through OMERO.web. The proxy forwards `Authorization` and `Cookie` request headers, rewrites `Origin` and `Referer` to match the Grafana backend origin, and preserves `Set-Cookie` responses. Cookie `Path` attributes are rewritten to `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/` so Grafana login sessions continue to work when Grafana is accessed through the plugin proxy route.
The proxy also rewrites Grafana boot settings (`appSubUrl` and `appUrl`) to the proxy prefix, preventing top-right **Sign in** redirects from escaping to an unmapped root route. If Grafana root (`/`) returns 404 through the proxy, the plugin now serves an operator guidance page that points users to **Dashboards -> OMERO**.

## Typical admin workflow

1. Use the Logs page to inspect recent service events, filter by container, browse internal log files.
2. Use Resource Monitoring to inspect infrastructure health via embedded Grafana dashboards and Docker container stats.
3. Use Storage page to identify disk growth hotspots by user and group.
4. Use Server Database Testing to run platform end-to-end health diagnostics.
5. Apply operational actions externally based on findings (cleanup, scaling, user guidance).

## Operator checklist

- Validate connectivity to Loki, Prometheus, and Grafana from the omeroweb container.
- Restrict plugin access to authorized admin users (plugin enforces root-only access).
- Review Grafana dashboard provisioning files after monitoring configuration changes.
- Keep query timeouts and entry caps aligned with cluster scale.
- Verify Docker socket is accessible (check `docker compose logs omeroweb` for socket permission errors).
