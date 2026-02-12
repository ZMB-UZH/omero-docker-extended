# Monitoring and Observability

## Stack Components

- **Prometheus**: metrics scraping and storage.
- **Grafana**: dashboards and visualization.
- **Loki**: log aggregation backend.
- **Alloy**: telemetry pipeline agent.
- **Exporters**: node, cAdvisor, Redis, PostgreSQL, blackbox.

## Configuration Sources

- `monitoring/prometheus/prometheus.yml`
- `monitoring/loki/loki-config.yml`
- `monitoring/alloy/alloy-config.alloy`
- `monitoring/grafana/provisioning/*`
- `monitoring/grafana/dashboards/*`

## Operational Baseline Checks

1. Prometheus target status page shows active targets.
2. Grafana data sources are healthy.
3. Loki receives logs from core services.
4. Dashboards load with recent data.
5. Exporters respond on expected internal endpoints.

## Recommended Alerts (Minimum)

- OMERO.server unavailable.
- OMERO.web unavailable.
- Database unavailable.
- Redis unavailable.
- Disk usage thresholds breached.
- Error-rate spikes in plugin logs.

## Security Notes

- Avoid exposing monitoring interfaces publicly without authentication.
- Restrict dashboard write access.
- Rotate Grafana admin credentials.
