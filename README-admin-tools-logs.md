# Admin tools logging (Loki + Grafana Alloy)

This repository ships a native log viewer inside the Admin tools plugin that reads from a
local Loki instance. Logs are collected from **all Docker containers** via Grafana Alloy and
presented in the Admin tools "Logs and analysis" view.

## Services added

- **Loki** (Grafana Loki 3.2.0) stores logs.
- **Grafana Alloy** (Grafana Alloy v1.12.2) reads Docker logs from the host and ships them to Loki.

Both services are defined in `docker-compose.yml` with pinned versions and healthchecks.

## Required environment variables (omeroweb)

The Admin tools backend expects Loki to be reachable from the omeroweb container.

```
ADMIN_TOOLS_LOKI_URL=http://loki:3100
ADMIN_TOOLS_LOG_LOOKBACK_SECONDS=900
ADMIN_TOOLS_LOG_MAX_ENTRIES=5000
ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS=10
```

## Optional environment variables (compose env file)

Configure where the OMERO containers write internal log files. These are mounted into
Grafana Alloy for file-based log collection.

```
OMERO_SERVER_LOG_DIR=/opt/omero/server/OMERO.server/var/log
OMERO_WEB_LOG_DIR=/opt/omero/web/OMERO.web/var/log
OMERO_WEB_SUPERVISOR_LOG_DIR=/opt/omero/web/logs
GRAFANA_HOST_PORT=3001
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
GRAFANA_ANONYMOUS_ENABLED=true
GRAFANA_ANONYMOUS_ROLE=Viewer
```

Grafana container settings live in `env/compose.env` (loaded via `env_file` in the grafana service).
The host port mapping (`3001:3000`) and the Docker socket GID (`group_add`) are set directly in `docker-compose.yml`.

For the Admin tools resource monitoring page, proxy links are now host-agnostic by default.
If you also want to expose direct external links, set these optional variables in `env/omeroweb.env`:

```
ADMIN_TOOLS_GRAFANA_PUBLIC_URL=https://monitoring.example.org/grafana
ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL=https://monitoring.example.org/prometheus
```

## How it works

1. Grafana Alloy discovers containers via Docker socket and labels them with the compose service
   name (e.g., `omeroserver`, `omeroweb`, `database`, `database_plugin`, `redis`). The Admin tools
   backend queries Loki using the `compose_service` label so the service names must match the
   Docker Compose service keys.
2. Grafana Alloy also tails internal OMERO log files and labels them with dedicated
   `compose_service` values (`omeroserver_internal`, `omeroweb_internal`) so they show up as
   distinct sources in the Admin tools UI.
3. Loki stores the entries.
4. The Admin tools plugin queries Loki via its backend (`/logs/data/`) and renders the UI
   without exposing Loki directly to the browser.

## Notes

- Root user access is enforced by the Admin tools plugin.
- Auto-refresh is enabled by default and can be disabled in the UI.
- Filtering supports time range, severity, and a free-text search.
- The Grafana Alloy v1.12.2 Docker image does not include `wget` or `curl`, so the
  Docker Compose healthcheck uses a process check (`kill -0 1`) instead of an HTTP probe.
- Grafana Alloy reads container stdout/stderr. If a service writes logs to files only, route
  those logs to stdout or mount the log paths and extend `monitoring/alloy/alloy-config.alloy`
  accordingly.

## Internal log availability troubleshooting

- The internal log sources (`omeroserver_internal`, `omeroweb_internal`) are file-based and
  only appear after the OMERO server/web containers have started and written log files into
  their log directories.
- Grafana Alloy uses `local.file_match` to discover log files via glob patterns and
  `discovery.relabel` to attach the `compose_service` / `container` labels. **Do not** use
  inline glob patterns in `loki.source.file` static targets — `loki.source.file` treats
  `__path__` as a literal path when targets are defined inline, which causes `stat` errors.
- If the UI shows no internal log entries, confirm the OMERO server and web containers are
  healthy and expand the time range selector in the UI (the default is the last 15 minutes).
- Verify that the named volume mount paths in `docker-compose.yml` match the actual
  directories where OMERO writes its logs. The `omeroserver` service must mount
  `omero_server_logs` at the real log directory (default:
  `/opt/omero/server/OMERO.server/var/log`), not at an unrelated path.
