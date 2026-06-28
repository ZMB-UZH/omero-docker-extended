# Service and Plugin Endpoints Reference

## Infrastructure endpoints

These are the shipped defaults. Treat live env files and Compose overrides as
authoritative: before operational probes, discover current bindings from the
running containers or `docker compose config`; do not assume these host ports.

| Service | URL | Purpose |
| --- | --- | --- |
| OMERO.server | `${OMERO_CLI_HOST}:${OMERO_CLI_PORT}` inside the stack; `${OMERO_SERVER_HOST_PORT}` on the host | OMERO API (Ice protocol) |
| OMERO.web | `http://localhost:4090` | Web frontend and plugin UIs |
| Portainer | `https://<host>:9443` on `${PORTAINER_HOST_BIND:-0.0.0.0}` | Container management |
| Prometheus | `http://localhost:9090` on `127.0.0.1` | Metrics and targets |
| Grafana | `http://localhost:3000` on `127.0.0.1` | Dashboards |
| Loki | `http://localhost:3100` on `127.0.0.1` | Log query API |

## Internal-only endpoints (Docker network)

| Service | Internal URL | Purpose |
| --- | --- | --- |
| OMERO database | `database:5432` | PostgreSQL (OMERO core) |
| Plugin database | `database-plugin:5433` | PostgreSQL (plugin data) |
| Redis | `redis:6379` | Cache (db 1) + Imaris Celery broker (db 2) + Tools Celery broker (db 3) |
| Ollama | `ollama:11434` | Local AI inference for OMP's `Local` provider |
| Alloy | `alloy:12345` | Log pipeline metrics |
| Node exporter | `node-exporter:9100` | Host metrics |
| cAdvisor | `cadvisor:8080` | Container metrics |
| Blackbox exporter | `blackbox-exporter:9115` | Probe results |
| Postgres exporter | `postgres-exporter:9187` | OMERO DB metrics |
| Postgres exporter (plugin) | `postgres-exporter-plugin:9187` | Plugin DB metrics |
| Redis exporter | `redis-exporter:9121` | Redis metrics |
| Path usage exporter | `path-usage-exporter` (no HTTP port) | OMERO volume disk usage (textfile collector) |
| CrowdSec | `crowdsec:8080` | Host-wide cybersecurity engine LAPI |

## OMERO.web plugin routes

### OMP Plugin

Base: `/omeroweb_omp_plugin/`

| Route | Purpose |
| --- | --- |
| `/` | Main plugin page |
| `/projects/` | Project and dataset listing |
| `/root-status/` | Check if current user is OMERO root |
| `/start_job/` | Start metadata write job |
| `/start_acq_job/` | Start acquisition metadata job |
| `/start_delete_all_job/` | Start delete-all annotations job |
| `/start_delete_plugin_job/` | Start delete plugin-owned annotations job |
| `/delete_all/` | Delete all MapAnnotations (direct, non-job) |
| `/delete_plugin/` | Delete plugin-owned MapAnnotations (direct, non-job) |
| `/progress/<str:job_id>/` | Poll job progress |
| `/varsets/`, `/varsets/save/`, `/varsets/load/`, `/varsets/delete/` | Variable set CRUD |
| `/ai-credentials/`, `/ai-credentials/save/`, `/ai-credentials/test/`, `/ai-credentials/models/` | AI credential management |
| `/user-settings/save/` | Save user preferences |
| `/user-data/delete-api-keys/`, `/user-data/delete-variable-sets/`, `/user-data/delete-all/` | User data deletion |
| `/help/` | Help Markdown document download |

### Import Plugin

Base: `/omeroweb_import/`

| Route | Purpose |
| --- | --- |
| `/` | Main upload page |
| `/start/` | Create upload session |
| `/upload/<str:job_id>/` | Transfer files |
| `/import/<str:job_id>/` | Trigger OMERO import |
| `/confirm/<str:job_id>/` | Confirm import completion |
| `/prune/<str:job_id>/` | Remove temporary files |
| `/status/<str:job_id>/` | Poll job status |
| `/projects/` | List accessible projects |
| `/root-status/` | Check if current user is OMERO root |
| `/user-settings/save/` | Save upload preferences |
| `/special-method-settings/save/`, `/special-method-settings/load/` | SEM-EDX method settings |
| `/help/` | Help Markdown document download |

### Tools Plugin

Base: `/omeroweb_tools/`

| Route | Purpose |
| --- | --- |
| `/` | Tools landing page |
| `/root-status/` | Check if current user is OMERO root |
| `/enhanced-search/` | Enhanced search UI |
| `/enhanced-search/sync/` | Request scope index refresh |
| `/enhanced-search/sync-state/` | Fetch current sync-state table |
| `/enhanced-search/settings/` | Save enhanced-search UI and indexing settings |
| `/enhanced-search/saved-queries/save/` | Save current query for the logged-in user |
| `/enhanced-search/saved-queries/delete/` | Delete a saved query |
| `/enhanced-search/saved-queries/<int:query_id>/` | Re-open a saved query |
| `/help/` | Tools HTML help |

### OMERO.web Zarr Plugin

Base: `/zarr/`

| Route | Purpose |
| --- | --- |
| `/` | Landing page |
| `/preview/image/<image_id>/` | Zarr-aware right-panel preview page for store-backed images |
| `/download/image/<image_id>/original/` | Download original managed-repository Zarr store as a zip archive |
| `/download/image/<image_id>/metadata/` | Download consolidated metadata manifest for the managed store |
| `/download/image/<image_id>/ome-tiff/` | Create and download OME-TIFF directly from the managed store |
| `/v0.3/image/<image_id>.zarr/.zattrs`, `/v0.4/image/<image_id>.zarr/.zattrs` | Raw root attributes |
| `/v0.3/image/<image_id>.zarr/.zgroup`, `/v0.4/image/<image_id>.zarr/.zgroup` | Raw root group metadata |
| `/v0.3/image/<image_id>.zarr/<level>/.zarray`, `/v0.4/image/<image_id>.zarr/<level>/.zarray` | Raw array metadata |
| `/v0.3/image/<image_id>.zarr/<level>/<chunk>`, `/v0.4/image/<image_id>.zarr/<level>/<chunk>` | Raw generated or store-backed chunk bytes |
| `/v0.3/image/<image_id>.zarr/<store_path>`, `/v0.4/image/<image_id>.zarr/<store_path>` | Raw managed-store metadata or file path |
| `/v0.4/preview/image/<image_id>.zarr/.zattrs` | Preview root attributes |
| `/v0.4/preview/image/<image_id>.zarr/.zgroup` | Preview root group metadata |
| `/v0.4/preview/image/<image_id>.zarr/<level>/.zarray` | Preview array metadata |
| `/v0.4/preview/image/<image_id>.zarr/<level>/<chunk>` | Preview chunk bytes |
| `/v0.4/preview/image/<image_id>.zarr/<store_path>` | Preview managed-store metadata or file path |
| `/vizarr/` | Vizarr launcher page |
| `/validator/` | NGFF validator launcher page |

Notes:

- Raw routes preserve the original dataset keys declared in the managed store.
- Preview routes forward the same NGFF payload as the raw routes under a separate URL namespace for OMERO.web launcher integration.
- For non-store-backed images, preview routes delegate to the synthetic OMERO-backed NGFF responses.
- Store-backed rendering and download routes apply only to images whose `externalInfo.lsid` resolves to a managed-repository Zarr store.
- `/vizarr/` serves the pinned third-party vendored production build of `hms-dbmi/vizarr` commit `be7ccc260e848a2829873c8746f32b4f43599435`; the viewer remains client-side and hardware-accelerated through Vizarr's Viv/deck.gl WebGL stack.
- `/vizarr/` and `/validator/` serve a thin launcher shell from OMERO.web, pass `source=` through without file-type inference, normalize root-relative sources against the browser's public origin, and redirect static assets to the pinned local Vizarr static tree or validator upstream origin instead of proxying every asset request through Gunicorn.

### Admin Tools Plugin

Base: `/omeroweb_admin_tools/`

| Route | Purpose |
| --- | --- |
| `/` | Main admin dashboard |
| `/root-status/` | Check if current user is OMERO root |
| `/logs/`, `/logs/data/`, `/logs/internal-labels/` | Log exploration and data |
| `/resource-monitoring/`, `/resource-monitoring/data/` | Container stats and system info |
| `/resource-monitoring/grafana-proxy/`, `/resource-monitoring/grafana-proxy/<path:subpath>` | Grafana API proxy |
| `/resource-monitoring/prometheus-proxy/`, `/resource-monitoring/prometheus-proxy/<path:subpath>` | Prometheus API proxy |
| `/storage/`, `/storage/data/` | Storage analytics |
| `/storage/quota/data/` | Fetch persisted group quota state |
| `/storage/quota/update/` | Update quota values |
| `/storage/quota/import/` | Import quota values from CSV |
| `/storage/quota/template/` | Download CSV template for quota import |
| `/server-database-testing/`, `/server-database-testing/run/` | Diagnostic scripts |
| `/help/` | Help Markdown document download |

### Imaris Connector

Base: `/omero_imaris_connector/`

| Route | Purpose |
| --- | --- |
| `/imaris-export/` | Start export, poll status, download result |

## Health check endpoints (used by Docker defaults)

| Service | Health check method |
| --- | --- |
| `portainer` | `wget --no-check-certificate https://localhost:9443/api/system/status` |
| `loki` | `loki -version` |
| `alloy` | `alloy --help` |
| `prometheus` | `wget http://localhost:9090/-/ready` |
| `blackbox-exporter` | `wget http://localhost:9115/-/healthy` |
| `node-exporter` | `wget -O /dev/null http://localhost:9100/` |
| `path-usage-exporter` | `test -f /textfile/omero_paths.prom` |
| `cadvisor` | `wget http://localhost:8080/metrics` |
| `postgres-exporter` | `wget http://localhost:9187/metrics` |
| `postgres-exporter-plugin` | `wget http://localhost:9187/metrics` |
| `redis-exporter` | `wget http://localhost:9121/metrics` |
| `grafana` | `wget http://localhost:3000/api/health` |
| `database` | `pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" -p 5432` |
| `omeroserver` | OMERO CLI admin login |
| `omeroweb` | container-local `curl` to `/webgateway/` on the configured OMERO.web port |
| `redis` | `redis-cli ping` |
| `database_plugin` | `pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" -p 5433` |
| `pg-maintenance` | `pgrep -x cron` |
| `crowdsec` | `wget http://localhost:8080/health` |
| `ollama` | `ollama list` |

## External reverse proxy forwarding target

For OMERO.web proxying from your external reverse proxy (e.g., nginx managed via Ansible):

- Forward to `omeroweb` on `CONFIG_omero_web_application__server_port`.
- Scheme: `http` (TLS terminates at the proxy).
- Direct local access uses `OMERO_WEB_HOST_PORT`.

Desktop clients that infer OMERO server discovery from OMERO.web URLs may not
honor a nonstandard web port. For BIOP BigDataViewer OMERO loading, expose the
same OMERO.web service through trusted HTTPS on port 443 for the hostname used
in copied image URLs; leave `OMERO_WEB_HOST_PORT` for direct troubleshooting.
