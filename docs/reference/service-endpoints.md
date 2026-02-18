# Service and Plugin Endpoints Reference

## Infrastructure endpoints (host-exposed)

| Service | URL | Purpose |
|---|---|---|
| OMERO.server | `localhost:4064` (TCP) | OMERO API (Ice protocol) |
| OMERO.web | `http://localhost:4090` | Web frontend and plugin UIs |
| Portainer | `https://localhost:9443` / `http://localhost:9000` | Container management |
| Prometheus | `http://localhost:9090` | Metrics and targets |
| Grafana | `http://localhost:3000` | Dashboards |
| Loki | `http://localhost:3100` | Log query API |

## Internal-only endpoints (Docker network)

| Service | Internal URL | Purpose |
|---|---|---|
| OMERO database | `database:5432` | PostgreSQL (OMERO core) |
| Plugin database | `database-plugin:5433` | PostgreSQL (plugin data) |
| Redis | `redis:6379` | Cache (db 1) + Celery broker (db 2) |
| Alloy | `alloy:12345` | Log pipeline metrics |
| Node exporter | `node-exporter:9100` | Host metrics |
| cAdvisor | `cadvisor:8080` | Container metrics |
| Blackbox exporter | `blackbox-exporter:9115` | Probe results |
| Postgres exporter | `postgres-exporter:9187` | OMERO DB metrics |
| Postgres exporter (plugin) | `postgres-exporter-plugin:9187` | Plugin DB metrics |
| Redis exporter | `redis-exporter:9121` | Redis metrics |

## OMERO.web plugin routes

### OMP Plugin

Base: `/omeroweb_omp_plugin/`

| Route | Purpose |
|---|---|
| `/` | Main plugin page |
| `/projects/` | Project and dataset listing |
| `/start_job/` | Start metadata write job |
| `/progress/<job_id>/` | Poll job progress |
| `/varsets/`, `/varsets/save/`, `/varsets/load/`, `/varsets/delete/` | Variable set CRUD |
| `/ai-credentials/`, `/ai-credentials/save/`, `/ai-credentials/test/`, `/ai-credentials/models/` | AI credential management |
| `/user-settings/save/` | Save user preferences |
| `/user-data/delete-api-keys/`, `/user-data/delete-variable-sets/`, `/user-data/delete-all/` | User data deletion |
| `/help/` | Help PDF download |

### Upload Plugin

Base: `/omeroweb_upload/`

| Route | Purpose |
|---|---|
| `/` | Main upload page |
| `/start/` | Create upload session |
| `/upload/<job_id>/` | Transfer files |
| `/import/<job_id>/` | Trigger OMERO import |
| `/confirm/<job_id>/` | Confirm import completion |
| `/prune/<job_id>/` | Remove temporary files |
| `/status/<job_id>/` | Poll job status |
| `/user-settings/save/` | Save upload preferences |
| `/special-method-settings/save/`, `/load/`, `/delete/` | SEM-EDX method settings |

### Admin Tools Plugin

Base: `/omeroweb_admin_tools/`

| Route | Purpose |
|---|---|
| `/` | Main admin dashboard |
| `/logs/`, `/logs/data/`, `/logs/internal-labels/` | Log exploration and data |
| `/resource-monitoring/`, `/resource-monitoring/data/` | Container stats and system info |
| `/resource-monitoring/grafana-proxy/<subpath>` | Grafana API proxy |
| `/resource-monitoring/prometheus-proxy/<subpath>` | Prometheus API proxy |
| `/storage/`, `/storage/data/` | Storage analytics |
| `/server-database-testing/`, `/server-database-testing/run/` | Diagnostic scripts |

### Imaris Connector

| Route | Purpose |
|---|---|
| `/imaris-export/` | Start export, poll status, download result |

## Health check endpoints (used by Docker)

| Service | Health check method |
|---|---|
| `omeroserver` | OMERO CLI admin login |
| `omeroweb` | `curl http://127.0.0.1:4090/webgateway/` |
| `database` | `pg_isready -U omero -d omero -p 5432` |
| `database_plugin` | `pg_isready -U omero-plugin -d omero-plugin -p 5433` |
| `redis` | `redis-cli ping` |
| `pg-maintenance` | `pgrep -x cron` |
| `prometheus` | `wget http://localhost:9090/-/ready` |
| `grafana` | `wget http://localhost:3000/api/health` |
| `loki` | `wget http://localhost:3100/ready` |
| `portainer` | `wget http://localhost:9000/api/system/status` |

## External reverse proxy forwarding target

For OMERO.web proxying from your external reverse proxy (e.g., nginx managed via Ansible):

- Forward to: `http://omeroweb:4090` on the Docker network.
- Scheme: `http` (TLS terminates at the proxy).
- Direct local access remains available at `http://localhost:4090`.
