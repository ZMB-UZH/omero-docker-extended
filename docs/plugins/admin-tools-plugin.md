# Admin Tools Plugin Guide (`omeroweb_admin_tools`)

## Purpose

The admin tools plugin exposes operational interfaces for log exploration, system resource visibility, storage analytics, and server diagnostics within OMERO.web. Access is restricted to OMERO root users.

## Main capabilities

- Log query via Loki (LogQL) with container filtering and internal log file browsing.
- Embedded/proxied Grafana dashboards and Prometheus query interface.
- Docker container resource monitoring (stats, system info, process lists).
- Storage usage analytics by user and group from OMERO API.
- Quota management tab for group-level quota definitions with CSV import/template export and enforcement reconciliation logs.
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
| `/omeroweb_admin_tools/storage/data/` | GET | Fetch storage usage data plus quota reconciliation state |
| `/omeroweb_admin_tools/storage/quota/data/` | GET | Fetch persisted group quota state and reconciliation logs |
| `/omeroweb_admin_tools/storage/quota/update/` | POST | Update quota values from Quotas tab edits |
| `/omeroweb_admin_tools/storage/quota/import/` | POST | Import quota values from CSV (`Group`, `Quota [GB]`) |
| `/omeroweb_admin_tools/storage/quota/template/` | GET | Download CSV template for quota import |
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
| `ADMIN_TOOLS_QUOTA_STATE_PATH` | JSON state file for persisted quotas and logs | `/tmp/omero-admin-tools/group-quotas.json` |
| `ADMIN_TOOLS_MIN_QUOTA_GB` | Minimum accepted quota value (GB) used by UI validation, backend validation, and ext4 enforcer script | `0.10` |
| `ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE` | Optional command template used to enforce quotas. If unset on ext4, a built-in project-quota enforcer script is used. | ` /opt/omero/web/bin/enforce-ext4-project-quota.sh --group {group} --group-path {group_path} --quota-gb {quota_gb} --mount-point {mount_point}` |
| `ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS` | Background reconciliation interval for quota enforcement loop | `60` |
| `ADMIN_TOOLS_QUOTA_PROJECTS_FILE` | ext4 project-quota mapping file updated by the enforcer | `/tmp/omero-admin-tools/quota/projects` |
| `ADMIN_TOOLS_QUOTA_PROJID_FILE` | ext4 project-name mapping file updated by the enforcer | `/tmp/omero-admin-tools/quota/projid` |
| `ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN` | Minimum project ID used when assigning new group IDs | `200000` |

The Docker socket (`/var/run/docker.sock`) must be mounted read-only for container stats functionality.

The quota compatibility check reads `CONFIG_omero_fs_repo_path` from the shared OMERO.server environment (`env/omeroserver.env`), which is also loaded into the `omeroweb` service in `docker-compose.yml` to keep a single source of truth for the repository template.

ManagedRepository quota enforcement uses a fixed in-container group root: `/OMERO/ManagedRepository` (no fallback paths are used).

To prevent quotas from affecting unrelated directories, enforcement is blocked unless the resolved root is an existing directory under `/OMERO`; when this validation fails, quotas stay pending and an explicit error is recorded in quota logs (including detection reason metadata).


Grafana proxy authentication depends on passing session and auth headers through OMERO.web. The proxy forwards `Authorization` and `Cookie` request headers, rewrites `Origin` and `Referer` to match the Grafana backend origin, and preserves `Set-Cookie` responses. Cookie `Path` attributes are rewritten to `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/` so Grafana login sessions continue to work when Grafana is accessed through the plugin proxy route.
The proxy also rewrites Grafana boot settings (`appSubUrl` and `appUrl`) to the proxy prefix, preventing top-right **Sign in** redirects from escaping to an unmapped root route. Grafana root requests (`/`) through the proxy now redirect users directly to the configured default OMERO dashboard route under the proxy prefix (for example when users click **Home** or complete **Sign in**).

## Typical admin workflow

1. Use the Logs page to inspect recent service events, filter by container, browse internal log files.
2. Use Resource Monitoring to inspect infrastructure health via embedded Grafana dashboards and Docker container stats.
3. Use Storage page to identify disk growth hotspots by user and group.
4. Use Server Database Testing to run platform end-to-end health diagnostics.
5. Apply operational actions externally based on findings (cleanup, scaling, user guidance).

If the configured ManagedRepository template does not start with `%group%/%user%/`, the Quotas tab is intentionally disabled and shows an incompatibility warning to prevent unsafe quota enforcement assumptions.

Quota values are validated with a minimum accepted value configured by `ADMIN_TOOLS_MIN_QUOTA_GB` (default **0.10 GB**) in UI edits, backend processing (including CSV imports), and ext4 enforcement.

## Operator checklist

- Validate connectivity to Loki, Prometheus, and Grafana from the omeroweb container.
- Restrict plugin access to authorized admin users (plugin enforces root-only access).
- Review Grafana dashboard provisioning files after monitoring configuration changes.
- Keep query timeouts and entry caps aligned with cluster scale.
- Verify Docker socket is accessible (check `docker compose logs omeroweb` for socket permission errors).


### ext4 project-quota enforcement behavior

When the managed repository is on `ext4`, quota reconciliation now uses `/opt/omero/web/bin/enforce-ext4-project-quota.sh` by default unless `ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE` is explicitly set.

The enforcer performs the following for each group directory with a configured quota:

1. Validates that the target directory exists and is inside the detected mount point.
2. Resolves or assigns a stable project ID for the group.
3. Updates both mapping files (`/tmp/omero-admin-tools/quota/projects` and `/tmp/omero-admin-tools/quota/projid` by default).
4. Applies project ID to the group directory via `chattr -p`.
5. Enables project inheritance on the group directory via `chattr +P`.
6. Sets hard block quota with `setquota -P` on the filesystem mount point.

Project quota is enforced at the parent group directory, and all files/subdirectories inside that tree count toward the same project quota domain.
