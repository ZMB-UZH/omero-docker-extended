# Admin tools logging (Loki + Promtail)

This repository ships a native log viewer inside the Admin tools plugin that reads from a
local Loki instance. Logs are collected from **all Docker containers** via Promtail and
presented in the Admin tools "Logs and analysis" view.

## Services added

- **Loki** (Grafana Loki 2.9.8) stores logs.
- **Promtail** (Grafana Promtail 2.9.8) reads Docker logs from the host and ships them to Loki.

Both services are defined in `docker-compose.yml` with pinned versions and healthchecks.

## Required environment variables (omeroweb)

The Admin tools backend expects Loki to be reachable from the omeroweb container.

```
ADMIN_TOOLS_LOKI_URL=http://loki:3100
ADMIN_TOOLS_LOG_LOOKBACK_SECONDS=900
ADMIN_TOOLS_LOG_MAX_ENTRIES=500
ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS=10
```

## How it works

1. Promtail discovers containers via Docker socket and labels them with the compose service
   name (e.g., `omeroserver`, `omeroweb`, `database`, `database_plugin`, `redis`).
2. Loki stores the entries.
3. The Admin tools plugin queries Loki via its backend (`/logs/data/`) and renders the UI
   without exposing Loki directly to the browser.

## Notes

- Root user access is enforced by the Admin tools plugin.
- Auto-refresh is enabled by default and can be disabled in the UI.
- Filtering supports time range, severity, and a free-text search.
- Promtail is configured with Docker API version 1.44 to match newer Docker daemon
  requirements when discovering containers via the socket.
- This setup reads container stdout/stderr. If a service writes logs to files only, route
  those logs to stdout or mount the log paths and extend `promtail-config.yml` accordingly.
