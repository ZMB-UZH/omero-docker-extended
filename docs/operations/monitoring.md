# Monitoring and Observability

## Stack components

| Service                    | Version              | Purpose                                                                 | Internal endpoint                          |
| -------------------------- | -------------------- | ----------------------------------------------------------------------- | ------------------------------------------ |
| Prometheus                 | v3.11.2              | Metrics scraping and storage                                            | `http://prometheus:9090`                   |
| Grafana                    | 13.0.1               | Dashboards and visualization                                            | `http://grafana:3000`                      |
| Loki                       | 3.7.1                | Log aggregation backend                                                 | `http://loki:3100`                         |
| Alloy                      | v1.15.1              | Log collection pipeline (Docker + files)                                | `http://alloy:12345`                       |
| Blackbox exporter          | v0.28.0              | HTTP/TCP endpoint probing                                               | `http://blackbox-exporter:9115`            |
| Node exporter              | v1.11.1              | Host-level metrics                                                      | `http://node-exporter:9100`                |
| cAdvisor                   | v0.56.2              | Container resource metrics                                              | `http://cadvisor:8080`                     |
| Postgres exporter          | v0.19.1              | OMERO database metrics                                                  | `http://postgres-exporter:9187`            |
| Postgres exporter (plugin) | v0.19.1              | Plugin database metrics                                                 | `http://postgres-exporter-plugin:9187`     |
| Redis exporter             | v1.82.0              | Redis metrics                                                           | `http://redis-exporter:9121`               |
| Path usage exporter        | custom (Python 3.12) | OMERO volume disk usage via textfile collector                          | writes to node-exporter textfile directory |
| CrowdSec                   | v1.7.6               | Host-wide cybersecurity engine (host syslog/auth + Docker log analysis) | `http://crowdsec:8080`                     |

Monitoring data-directory ownership is auto-detected by
`installation/installation_script.sh` before each install/update. For images
that set `Config.User`, the installer resolves IDs from image metadata (with
`/etc/passwd` fallback where needed, such as Loki). For images that leave
`Config.User` empty but still run non-root by default (for example Prometheus),
the installer first probes runtime IDs via `id` inside the image and then
falls back to reading UID/GID from `/proc/1/status` in a started probe
container. If both probes fail, installation now exits with a clear error
instead of silently defaulting to root ownership, and operators must set
explicit overrides such as `PROMETHEUS_UID` / `PROMETHEUS_GID`. `LOKI_UID` /
`LOKI_GID`, `ALLOY_UID` / `ALLOY_GID`, and other `*_UID` / `*_GID` variables
remain optional explicit overrides when required by host policy.

## Configuration sources

| File                                                                | Content                                                                                    |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `monitoring/prometheus/prometheus.yml`                              | Scrape targets, blackbox probe definitions                                                 |
| `monitoring/loki/loki-config.yml`                                   | TSDB storage, ingestion rates, retention, single-node burst tuning                         |
| `monitoring/alloy/alloy-config.alloy`                               | Docker log discovery, file log discovery, Loki push                                        |
| `monitoring/grafana/provisioning/datasources/prometheus.yml`        | Prometheus data source                                                                     |
| `monitoring/grafana/provisioning/dashboards/dashboard-provider.yml` | Dashboard auto-provisioning                                                                |
| `monitoring/grafana/dashboards/*.json`                              | Dashboard definitions                                                                      |
| `monitoring/blackbox/config.yml`                                    | HTTP and TCP probe modules                                                                 |
| `monitoring/postgres-exporter/postgres_exporter.yml`                | Explicit Postgres exporter config file (keeps startup deterministic, no implicit defaults) |
| `monitoring/crowdsec/acquis.yaml`                                   | CrowdSec log acquisition sources (host syslog, Docker containers)                          |
| `monitoring/path-usage-exporter/path_usage_exporter.py`             | Path usage exporter script for OMERO volume metrics                                        |
| `monitoring/prometheus/smart_disk_monitor.sh`                       | Standalone disk textfile helper; not part of the default Compose stack                     |

## Prometheus scrape targets

Configured in `monitoring/prometheus/prometheus.yml`:

- `prometheus` -- self-monitoring
- `node-exporter` -- host metrics
- `cadvisor` -- container metrics
- `loki` -- log backend health
- `alloy` -- pipeline metrics
- `grafana` -- dashboard service health
- `postgres-exporter` -- OMERO database
- `postgres-exporter-plugin` -- plugin database
- `redis-exporter` -- Redis cache/broker
- `blackbox-exporter` -- blackbox exporter self-metrics

### Discovery behavior (important)

Prometheus in this stack currently uses explicit `static_configs` for scrape jobs and probe targets; it does **not** use Docker service discovery or other automatic target discovery in `prometheus.yml`.

What this means operationally:

- If you add a new exporter or service endpoint, you must add/update a Prometheus scrape job (or blackbox probe target) in `monitoring/prometheus/prometheus.yml`.
- Existing targets continue to work automatically only as long as service names and ports remain unchanged (for example `redis-exporter:9121`).
- Alloy **does** auto-discover Docker containers for logs, but that behavior is independent from Prometheus metric scraping.

### Do you need to change Prometheus after a deployment change?

| Change type                                                                       | Update `monitoring/prometheus/prometheus.yml`? | Why                                                                                |
| --------------------------------------------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------- |
| Restarting containers, host reboot, normal redeploy with same service names/ports | No                                             | Targets remain the same (`service:port`), so existing scrape config still matches. |
| Updating image tags/versions only                                                 | No (usually)                                   | Scrape discovery is name/port/path based, not image-tag based.                     |
| Adding a new exporter/service that should be monitored                            | Yes                                            | Prometheus only scrapes configured jobs/targets in this stack.                     |
| Renaming a Docker Compose service                                                 | Yes                                            | Target hostname changes (for example `redis-exporter` -> new service name).        |
| Changing metrics port or metrics path                                             | Yes                                            | Scrape endpoint changed; Prometheus must point to the new address/path.            |
| Adding/removing blackbox probe endpoints                                          | Yes                                            | Probe target lists are explicitly declared under blackbox jobs.                    |

Quick operator check after any change:

1. Open `http://localhost:9090/targets`.
2. Confirm expected jobs are `UP`.
3. If a target is missing, add/update it in `monitoring/prometheus/prometheus.yml` and reload Prometheus (`/-/reload`) or restart the service.

## Blackbox probes

**HTTP probes** (verify 2xx response):

- Loki, Prometheus, Grafana, cAdvisor
- All exporters (node, postgres x2, redis, blackbox)
- Portainer (`/api/system/status`)
- CrowdSec (`/health`) — managed by the installation script (see below)
- OMERO.web (port 4090)
- Alloy (`/metrics`)

The checked-in file currently contains 13 HTTP probe targets when the CrowdSec
target line is present, or 12 after the installation script removes that line
for deployments without CrowdSec.

### Conditional CrowdSec probe

The checked-in `monitoring/prometheus/prometheus.yml` contains a
`CROWDSEC_PROBE_MARKER` comment and may contain the CrowdSec health probe line
immediately after it. The installation script
(`installation/installation_script.sh`) conditionally ensures that probe target
is present or absent at that marker:

- **CrowdSec enabled** (valid `CROWDSEC_ENROLL_KEY` in `omero_secrets.env`): the script injects `- http://crowdsec:8080/health` after the marker so blackbox-exporter monitors CrowdSec.
- **CrowdSec disabled** (key empty, missing, or set to placeholder `CHANGEVALUE2`/`CHANGEVALUE3`): the script removes any previously injected CrowdSec probe line, preventing blackbox-exporter from producing recurring connection-refused errors for a non-existent service.

This means operators never need to manually edit `prometheus.yml` for CrowdSec — the installation script handles it automatically based on credentials.

**TCP probes** (verify connectivity):

- `database:5432` (OMERO PostgreSQL)
- `database-plugin:5433` (plugin PostgreSQL)
- `redis:6379` (Redis)
- `omeroserver:4063` (OMERO.server SSL)
- `omeroserver:${OMERO_CLI_PORT}` (OMERO.server; default example value 4064)

## Grafana dashboards

Four dashboards auto-provisioned in the `OMERO` folder:

1. **OMERO Infrastructure** (`omero-infrastructure.json`) -- service health
   overview, blackbox probe results, container stats. Set as Grafana home
   dashboard. Top summary stats include host CPU/memory, root and swap usage,
   and dynamic filesystem utilization for OMERO data and database paths from
   `installation_paths.env`, collected by the path-usage exporter via host
   `df -kP`. The database-path stat renders one percentage when both
   database paths are on the same filesystem mountpoint, or two percentages
   when they are on different mountpoints.
2. **Database Metrics** (`database-metrics.json`) -- OMERO core database: connections, transactions, index usage, table sizes.
3. **Plugin Database Metrics** (`plugin-database-metrics.json`) -- OMERO plugin database: same metrics for the omero-plugin database.
4. **Redis Metrics** (`redis-metrics.json`) -- memory usage, connected clients, commands/sec, keyspace stats.

### Path usage exporter controls

The default Compose stack mounts `installation_paths.env` at
`/config/installation_paths.env`, the host root at `/host`, and the
node-exporter textfile directory at `/textfile`. The path usage exporter keeps
those defaults for existing deployments and also accepts these optional runtime
overrides when a derived deployment needs different mount points or timing:

- `PATH_USAGE_EXPORTER_OUTPUT` (default `/textfile/omero_paths.prom`)
- `PATH_USAGE_EXPORTER_INTERVAL_SECONDS` (default `30`)
- `PATH_USAGE_EXPORTER_ENV_FILE` (default `/config/installation_paths.env`)
- `PATH_USAGE_EXPORTER_HOST_ROOT` (default `/host`)
- `PATH_USAGE_EXPORTER_DF_TIMEOUT_SECONDS` (default `10`)

The exporter reads only absolute paths from `installation_paths.env`, resolves
them under the configured host-root mount, and escapes Prometheus label values
before writing textfile metrics atomically.

## Alloy log collection

Alloy collects logs from two sources:

1. **Docker container logs**: discovered via Docker socket (`/var/run/docker.sock`), relabeled with `compose_service` and `container` labels.
2. **OMERO internal log files**: discovered by file path patterns in mounted
   OMERO server and web log directories (`*.log`, `*.out`, `*.err`). Compose
   mounts the installation-specific host paths into Alloy under neutral
   collector paths (`/logs/omeroserver`, `/logs/omeroweb`, and
   `/logs/omeroweb-supervisor`), so the Alloy config does not encode the host
   installation root. Labeled with `compose_service`, `log_type=internal`, and
   `filepath`.

All logs are pushed to Loki at `http://loki:3100/loki/api/v1/push`.

The internal OMERO file tails start from the beginning when Alloy has no stored
position (`tail_from_end = false`). That keeps first-run and recreated-collector
installations from skipping log lines that were written before Alloy discovered
the file. Existing installations still resume from `/data-alloy` positions, so
normal restarts do not replay already-collected logs.

Alloy stores Docker and file-tail positions under `/data-alloy`, backed by
`ALLOY_DATA_PATH` from `installation_paths.env`. That path must persist across
container restarts so `loki.source.docker` and `loki.source.file` resume at the
recorded offsets instead of replaying historical container logs that Loki would
reject as stale.

Loki does not configure a repository-specific retention period in
`monitoring/loki/loki-config.yml`; search visibility is controlled by the log
query time range, Loki storage availability, and whether Alloy collected the
line before source files rotated away.

## CrowdSec log expectations

- `No matching files for pattern /var/log/auth.log` and `/var/log/syslog` is expected on hosts that do not expose those files (for example journald-only systems). Docker log acquisition still starts normally via `source: docker`.
- The CrowdSec healthcheck is HTTP-based (`/health`) and should not generate repeated `POST /v1/watchers/login` entries by itself.

## CrowdSec firewall bouncer

The firewall bouncer runs inside the CrowdSec container (not as a separate host package) and manipulates the **host's** firewall rules directly via `network_mode: host` and `NET_ADMIN` capability.

At startup the entrypoint auto-detects the host firewall backend:

| Host OS                                  | Backend detected | Bouncer mode     | Protection scope                                                                                             |
| ---------------------------------------- | ---------------- | ---------------- | ------------------------------------------------------------------------------------------------------------ |
| Ubuntu 24.04+, Debian 13+ (Trixie)       | nftables         | `mode: nftables` | INPUT-hook (host) + FORWARD-hook (Docker bridge) via dedicated `crowdsec`/`crowdsec6` tables at priority -10 |
| Older distributions with iptables-legacy | iptables         | `mode: iptables` | `INPUT` + `DOCKER-USER` chains                                                                               |

For nftables mode the entrypoint adds supplementary FORWARD-hook chains referencing the bouncer's banned-IP sets so that Docker-bridged containers are also protected — the bouncer's built-in nftables mode only creates INPUT-hook chains.

Expected startup log lines:

- `Detected host firewall backend: nftables` (or `iptables`)
- `Validated: nftables kernel access OK (NET_ADMIN + host network)`
- `Added IPv4 FORWARD chain in table 'ip crowdsec' (set=...)`
- `Added IPv6 FORWARD chain in table 'ip6 crowdsec6' (set=...)`

## Operational baseline checks

1. Prometheus targets page (`http://localhost:9090/targets`) shows all targets as UP.
2. Grafana data sources are healthy (Settings > Data Sources > Test).
3. Loki receives logs: query `{compose_service=~".+"}` returns recent entries.
4. All four dashboards load with recent data.
5. Exporters respond on expected internal endpoints (verify via blackbox probe status).

## Manual troubleshooting commands

Use these host-side commands when Grafana panels are blank or proxy navigation fails.

### 1) Validate scrape jobs and node exporter target labels

```bash
curl -s http://127.0.0.1:9090/api/v1/label/job/values
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=up{job=~"node-exporter|node_exporter"}'
curl -s http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="node_exporter" or .labels.job=="node-exporter") | {health:.health,instance:.labels.instance,lastError:.lastError,scrapeUrl:.scrapeUrl}'
```

### 2) Validate Host CPU / Host memory panel queries directly in Prometheus

```bash
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=(1 - avg(rate(node_cpu_seconds_total{job=~"node-exporter|node_exporter", mode="idle"}[5m])))'
curl -sG http://127.0.0.1:9090/api/v1/query_range --data-urlencode 'query=(1 - avg(rate(node_cpu_seconds_total{job=~"node-exporter|node_exporter", mode="idle"}[5m])))' --data-urlencode 'start='"$(date -u -d '30 minutes ago' +%s)" --data-urlencode 'end='"$(date -u +%s)" --data-urlencode 'step=30s'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=(1 - (node_memory_MemAvailable_bytes{job=~"node-exporter|node_exporter"} / node_memory_MemTotal_bytes{job=~"node-exporter|node_exporter"}))'
curl -sG http://127.0.0.1:9090/api/v1/query_range --data-urlencode 'query=(1 - (node_memory_MemAvailable_bytes{job=~"node-exporter|node_exporter"} / node_memory_MemTotal_bytes{job=~"node-exporter|node_exporter"}))' --data-urlencode 'start='"$(date -u -d '30 minutes ago' +%s)" --data-urlencode 'end='"$(date -u +%s)" --data-urlencode 'step=30s'
```

### 3) Diagnose Local IP panel data availability

```bash
curl -s http://127.0.0.1:9100/metrics | grep -E 'node_network_address_info|node_network_route_info' | head -n 50
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=max by (address) (node_network_address_info{job=~"node-exporter|node_exporter", family="inet", scope="global"})'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=label_replace(up{job=~"node-exporter|node_exporter"}, "address", "$1", "instance", "^([0-9.]+):.*$")'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=label_replace(up{job=~"node-exporter|node_exporter"}, "address", "$1", "instance", "^([^:]+):.*$")'
```

If `node_network_address_info` is absent from `/metrics`, node-exporter is not exposing interface-address metrics in the current runtime; the dashboard then falls back to `instance` label parsing.

### 4) Diagnose Grafana sign-in routing through OMERO proxy

```bash
container="$(docker compose --env-file .env --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env --env-file env/omeroweb.env --env-file env/omero-celery.env --env-file env/grafana.env ps -q omeroweb)"
base_url=""
while read -r _arrow_prefix _arrow binding; do
  [ -n "${binding:-}" ] || continue
  host="${binding%:*}"
  port="${binding##*:}"
  host="${host#[}"
  host="${host%]}"
  case "$host" in
    ""|0.0.0.0|::) host="127.0.0.1" ;;
    *:*) host="[${host}]" ;;
  esac
  candidate="http://${host}:${port}"
  if curl -fsS -o /dev/null "${candidate}/webgateway/"; then
    base_url="$candidate"
    break
  fi
done < <(docker port "$container")
[ -n "$base_url" ] || { echo "OMERO.web binding not found" >&2; exit 1; }
curl -sI "${base_url}/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"
curl -sI "${base_url}/omeroweb_admin_tools/resource-monitoring/grafana-proxy/login"
curl -s "${base_url}/omeroweb_admin_tools/resource-monitoring/grafana-proxy/login" | rg 'appSubUrl|appUrl|href="/|href="login"' | head -n 20
```

`/resource-monitoring/grafana-proxy/*` is protected by OMERO.web authentication. An unauthenticated `curl` request correctly receives `302` to `/webclient/login/...`; this does not indicate a Grafana proxy failure.

When Grafana is down or unreachable, the proxy now returns a custom `503 Service Unavailable` HTML page (instead of forwarding raw upstream gateway HTML). The page reports the attempted upstream endpoint(s), includes `Cache-Control: no-store`, and sends `Retry-After: 30` to support cleaner operator experience and browser behavior.

### 5) Check Grafana runtime version and datasource API auth behavior

```bash
docker compose exec grafana grafana-server -v
docker compose images grafana
curl -s http://127.0.0.1:3000/api/health
curl -s http://127.0.0.1:3000/api/datasources
curl -s -u "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" http://127.0.0.1:3000/api/datasources | jq '.[].name'
```

If runtime Grafana version does not match the tag pinned in `docker-compose.yml`, refresh only the Grafana service image and container:

```bash
docker compose pull grafana
docker compose up -d grafana
```

### 6) Diagnose `Swap usage` panel showing `No swap configured`

The `Server Infrastructure -> Swap usage` stat intentionally shows `No swap configured` when the host reports zero swap capacity. This is not a dashboard failure by itself.

Panel query (from `monitoring/grafana/dashboards/omero-infrastructure.json`):

```promql
((node_memory_SwapTotal_bytes{job=~"node-exporter|node_exporter"} - node_memory_SwapFree_bytes{job=~"node-exporter|node_exporter"}) / node_memory_SwapTotal_bytes{job=~"node-exporter|node_exporter"}) and on(instance) (node_memory_SwapTotal_bytes{job=~"node-exporter|node_exporter"} > 0)
```

Direct checks:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=node_memory_SwapTotal_bytes{job=~"node-exporter|node_exporter"}'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=node_memory_SwapFree_bytes{job=~"node-exporter|node_exporter"}'
```

Interpretation:

- If `SwapTotal` is `0`, Grafana displays `No swap configured` by design.
- If `SwapTotal` is greater than `0` and the panel is still empty, check node-exporter scrape health and label matching (`job=~"node-exporter|node_exporter"`).

### 7) Compare current panel behavior vs one week ago (repo-level)

Use git history to verify whether dashboard logic changed recently:

```bash
git log --since='14 days ago' --oneline -- monitoring/grafana/dashboards/omero-infrastructure.json
git rev-list -1 --before='7 days ago' HEAD -- monitoring/grafana/dashboards/omero-infrastructure.json
git diff "$(git rev-list -1 --before='7 days ago' HEAD -- monitoring/grafana/dashboards/omero-infrastructure.json)"..HEAD -- monitoring/grafana/dashboards/omero-infrastructure.json
```

For the `Swap usage` panel specifically, only presentation options (for example graph mode/description text) should differ across recent revisions; the PromQL logic and `noValue` fallback are expected to remain unchanged unless intentionally updated.

## Recommended alerts (minimum)

- OMERO.server unavailable (blackbox TCP probe failure).
- OMERO.web unavailable (blackbox HTTP probe failure).
- Database unavailable (blackbox TCP probe failure or postgres-exporter down).
- Redis unavailable (blackbox TCP probe failure or redis-exporter down).
- Disk usage thresholds breached (node-exporter filesystem metrics).
- Error-rate spikes in plugin logs (Loki query-based alerting).
- pg-maintenance cron not running (process check failure).

## Security notes

- Do not expose Grafana, Prometheus, or Loki publicly without authentication.
- Restrict Grafana dashboard write access to admin users.
- Rotate Grafana admin credentials (configured in `env/grafana.env`).
- Grafana outbound analytics, update checks, and automatic preinstalled-plugin updates are disabled in `env/grafana_example.env` for offline or restricted-network deployments; this prevents recurring startup warnings when egress is blocked and avoids write attempts against bundled plugin directories.
- Alloy has read-only access to the Docker socket and log files.
