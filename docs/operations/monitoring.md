# Monitoring and Observability

## Stack components

| Service | Version | Purpose | Internal endpoint |
|---|---|---|---|
| Prometheus | v3.5.1 | Metrics scraping and storage | `http://prometheus:9090` |
| Grafana | 12.4.0 | Dashboards and visualization | `http://grafana:3000` |
| Loki | 3.2.0 | Log aggregation backend | `http://loki:3100` |
| Alloy | v1.12.2 | Log collection pipeline (Docker + files) | `http://alloy:12345` |
| Blackbox exporter | v0.28.0 | HTTP/TCP endpoint probing | `http://blackbox-exporter:9115` |
| Node exporter | v1.10.2 | Host-level metrics | `http://node-exporter:9100` |
| cAdvisor | v0.55.1 | Container resource metrics | `http://cadvisor:8080` |
| Postgres exporter | v0.19.0 | OMERO database metrics | `http://postgres-exporter:9187` |
| Postgres exporter (plugin) | v0.19.0 | Plugin database metrics | `http://postgres-exporter-plugin:9187` |
| Redis exporter | v1.80.2 | Redis metrics | `http://redis-exporter:9121` |

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

## Blackbox probes

**HTTP probes** (verify 2xx response):
- Loki, Prometheus, Grafana, cAdvisor
- All exporters (node, postgres x2, redis, blackbox)
- OMERO.server (port 4064 via HTTP)
- OMERO.web (port 4090)

**TCP probes** (verify connectivity):
- `database:5432` (OMERO PostgreSQL)
- `database-plugin:5433` (plugin PostgreSQL)
- `redis:6379` (Redis)
- `omeroserver:4064` (OMERO.server)

## Grafana dashboards

Four dashboards auto-provisioned in the `OMERO` folder:

1. **OMERO Infrastructure** (`omero-infrastructure.json`) -- service health overview, blackbox probe results, container stats. Set as Grafana home dashboard.
2. **Database Metrics** (`database-metrics.json`) -- OMERO core database: connections, transactions, index usage, table sizes.
3. **Plugin Database Metrics** (`plugin-database-metrics.json`) -- OMERO plugin database: same metrics for the omero-plugin database.
4. **Redis Metrics** (`redis-metrics.json`) -- memory usage, connected clients, commands/sec, keyspace stats.

## Alloy log collection

Alloy collects logs from two sources:

1. **Docker container logs**: discovered via Docker socket (`/var/run/docker.sock`), relabeled with `compose_service` and `container` labels.
2. **OMERO internal log files**: discovered by file path patterns in mounted OMERO server and web log directories (`*.log`, `*.out`, `*.err`). Labeled with `compose_service`, `log_type=internal`, and `filepath`.

All logs are pushed to Loki at `http://loki:3100/loki/api/v1/push`.

## Operational baseline checks

1. Prometheus targets page (`http://localhost:9090/targets`) shows all targets as UP.
2. Grafana data sources are healthy (Settings > Data Sources > Test).
3. Loki receives logs: query `{compose_service=~".+"}` returns recent entries.
4. All four dashboards load with recent data.
5. Exporters respond on expected internal endpoints (verify via blackbox probe status).

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
