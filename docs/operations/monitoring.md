# Monitoring and Observability

## Stack components

| Service | Version | Purpose | Internal endpoint |
|---|---|---|---|
| Prometheus | v3.5.1 | Metrics scraping and storage | `http://prometheus:9090` |
| Grafana | 12.3.3 | Dashboards and visualization | `http://grafana:3000` |
| Loki | 3.2.0 | Log aggregation backend | `http://loki:3100` |
| Alloy | v1.12.2 | Log collection pipeline (Docker + files) | `http://alloy:12345` |
| Blackbox exporter | v0.28.0 | HTTP/TCP endpoint probing | `http://blackbox-exporter:9115` |
| Node exporter | v1.10.2 | Host-level metrics | `http://node-exporter:9100` |
| cAdvisor | v0.55.1 | Container resource metrics | `http://cadvisor:8080` |
| Postgres exporter | v0.19.0 | OMERO database metrics | `http://postgres-exporter:9187` |
| Postgres exporter (plugin) | v0.19.0 | Plugin database metrics | `http://postgres-exporter-plugin:9187` |
| Redis exporter | v1.81.0 | Redis metrics | `http://redis-exporter:9121` |
| Path usage exporter | custom (Python 3.12) | OMERO volume disk usage via textfile collector | writes to node-exporter textfile directory |
| CrowdSec | v1.7.6 | Host-wide cybersecurity engine (host syslog/auth + Docker log analysis) | `http://crowdsec:8080` |

## Configuration sources

| File | Content |
|---|---|
| `monitoring/prometheus/prometheus.yml` | Scrape targets, blackbox probe definitions |
| `monitoring/loki/loki-config.yml` | TSDB storage, ingestion rates, retention |
| `monitoring/alloy/alloy-config.alloy` | Docker log discovery, file log discovery, Loki push |
| `monitoring/grafana/provisioning/datasources/prometheus.yml` | Prometheus data source |
| `monitoring/grafana/provisioning/dashboards/dashboard-provider.yml` | Dashboard auto-provisioning |
| `monitoring/grafana/dashboards/*.json` | Dashboard definitions |
| `monitoring/blackbox/config.yml` | HTTP and TCP probe modules |
| `monitoring/postgres-exporter/postgres_exporter.yml` | Explicit Postgres exporter config file (keeps startup deterministic, no implicit defaults) |
| `monitoring/crowdsec/acquis.yaml` | CrowdSec log acquisition sources (host syslog, Docker containers) |
| `monitoring/path-usage-exporter/path_usage_exporter.py` | Path usage exporter script for OMERO volume metrics |

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

| Change type | Update `monitoring/prometheus/prometheus.yml`? | Why |
|---|---|---|
| Restarting containers, host reboot, normal redeploy with same service names/ports | No | Targets remain the same (`service:port`), so existing scrape config still matches. |
| Updating image tags/versions only | No (usually) | Scrape discovery is name/port/path based, not image-tag based. |
| Adding a new exporter/service that should be monitored | Yes | Prometheus only scrapes configured jobs/targets in this stack. |
| Renaming a Docker Compose service | Yes | Target hostname changes (for example `redis-exporter` -> new service name). |
| Changing metrics port or metrics path | Yes | Scrape endpoint changed; Prometheus must point to the new address/path. |
| Adding/removing blackbox probe endpoints | Yes | Probe target lists are explicitly declared under blackbox jobs. |

Quick operator check after any change:

1. Open `http://localhost:9090/targets`.
2. Confirm expected jobs are `UP`.
3. If a target is missing, add/update it in `monitoring/prometheus/prometheus.yml` and reload Prometheus (`/-/reload`) or restart the service.

## Blackbox probes

**HTTP probes** (verify 2xx response):
- Loki, Prometheus, Grafana, cAdvisor
- All exporters (node, postgres x2, redis, blackbox)
- Portainer (`/api/system/status`)
- CrowdSec (`/health`)
- OMERO.server (port 4064 via HTTP)
- OMERO.web (port 4090)

**TCP probes** (verify connectivity):
- `database:5432` (OMERO PostgreSQL)
- `database-plugin:5433` (plugin PostgreSQL)
- `redis:6379` (Redis)
- `omeroserver:4064` (OMERO.server)

## Grafana dashboards

Four dashboards auto-provisioned in the `OMERO` folder:

1. **OMERO Infrastructure** (`omero-infrastructure.json`) -- service health overview, blackbox probe results, container stats. Set as Grafana home dashboard. Top summary stats include host CPU/memory, root and swap usage, and dynamic filesystem utilization for OMERO data and database paths from `installation_paths.env`, collected by the path-usage exporter via host `df -P -B1`. The database-path stat renders one percentage when both database paths are on the same filesystem mountpoint, or two percentages when they are on different mountpoints.
2. **Database Metrics** (`database-metrics.json`) -- OMERO core database: connections, transactions, index usage, table sizes.
3. **Plugin Database Metrics** (`plugin-database-metrics.json`) -- OMERO plugin database: same metrics for the omero-plugin database.
4. **Redis Metrics** (`redis-metrics.json`) -- memory usage, connected clients, commands/sec, keyspace stats.

## Alloy log collection

Alloy collects logs from two sources:

1. **Docker container logs**: discovered via Docker socket (`/var/run/docker.sock`), relabeled with `compose_service` and `container` labels.
2. **OMERO internal log files**: discovered by file path patterns in mounted OMERO server and web log directories (`*.log`, `*.out`, `*.err`). Labeled with `compose_service`, `log_type=internal`, and `filepath`.

All logs are pushed to Loki at `http://loki:3100/loki/api/v1/push`.

## CrowdSec log expectations

- `No matching files for pattern /var/log/auth.log` and `/var/log/syslog` is expected on hosts that do not expose those files (for example journald-only systems). Docker log acquisition still starts normally via `source: docker`.
- The CrowdSec healthcheck is HTTP-based (`/health`) and should not generate repeated `POST /v1/watchers/login` entries by itself.

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
curl -sI http://127.0.0.1:4090/omeroweb_admin_tools/resource-monitoring/grafana-proxy/
curl -sI http://127.0.0.1:4090/omeroweb_admin_tools/resource-monitoring/grafana-proxy/login
curl -s http://127.0.0.1:4090/omeroweb_admin_tools/resource-monitoring/grafana-proxy/login | rg 'appSubUrl|appUrl|href="/|href="login"' | head -n 20
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

## Recommended alerts (minimum)

- OMERO.server unavailable (blackbox HTTP/TCP probe failure).
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
- Alloy has read-only access to the Docker socket and log files.
