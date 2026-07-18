# Admin Tools Plugin Guide (`omeroweb_admin_tools`)

## Purpose

The admin tools plugin exposes operational interfaces for log exploration, system resource visibility, storage analytics, and server diagnostics within OMERO.web. Access is restricted to OMERO root users.

## Main capabilities

- Log query via Loki (LogQL) with container filtering and internal log file browsing.
- Log API requests accept only known Compose log-source keys and safe internal
  log basenames before any LogQL is built.
- Log retrieval is optimized for large log volumes: the UI applies text/severity filters locally after load, auto-refresh uses incremental fetches, repeated identical requests are served from process-local RAM cache, and internal log file selections are batched with bounded split retries so a slow multi-file query does not silently drop a source.
- Log severity normalization maps mixed Loki/source labels (including missing/`unknown`) to canonical severities (`debug`, `info`, `warn`, `error`, `fatal`) using stream labels plus message-pattern inference, with traceback-continuation and RedisBloom `bf-error-rate` lines treated as non-error noise.
- Embedded/proxied Grafana dashboards and Prometheus query interface.
- Grafana/Prometheus resource monitoring, with Docker API diagnostics only when
  operators explicitly mount a read-only Docker socket.
- Storage usage analytics by user and group from OMERO API.
- Quota management tab for group-level quota definitions with CSV import/template export and enforcement reconciliation logs.
- Server and database diagnostic scripts (platform end-to-end health checks).
- Root-only access enforcement on all endpoints.
- Direct PostgreSQL sanity checks from the `omeroweb` runtime, plus optional
  Docker-backed compose-state inspection when a read-only engine socket is
  explicitly mounted.

## Key routes

| Route                                                               | Method   | Purpose                                                   |
| ------------------------------------------------------------------- | -------- | --------------------------------------------------------- |
| `/omeroweb_admin_tools/`                                            | GET      | Main admin dashboard                                      |
| `/omeroweb_admin_tools/root-status/`                                | GET      | Check root user status                                    |
| `/omeroweb_admin_tools/logs/`                                       | GET      | Log exploration UI                                        |
| `/omeroweb_admin_tools/logs/data/`                                  | GET      | Fetch log entries from Loki                               |
| `/omeroweb_admin_tools/logs/internal-labels/`                       | GET      | List internal log file labels                             |
| `/omeroweb_admin_tools/resource-monitoring/`                        | GET      | Resource monitoring UI                                    |
| `/omeroweb_admin_tools/resource-monitoring/data/`                   | GET      | Fetch container stats and system info                     |
| `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/`          | GET/POST | Redirect to the configured default Grafana dashboard      |
| `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/<path>`    | GET/POST | Proxy to Grafana API                                      |
| `/omeroweb_admin_tools/resource-monitoring/prometheus-proxy/`       | GET      | Redirect to Prometheus targets                            |
| `/omeroweb_admin_tools/resource-monitoring/prometheus-proxy/<path>` | GET      | Proxy to Prometheus API                                   |
| `/omeroweb_admin_tools/storage/`                                    | GET      | Storage analytics UI                                      |
| `/omeroweb_admin_tools/storage/data/`                               | GET      | Fetch storage usage data plus quota reconciliation state  |
| `/omeroweb_admin_tools/storage/quota/data/`                         | GET      | Fetch persisted group quota state and reconciliation logs |
| `/omeroweb_admin_tools/storage/quota/update/`                       | POST     | Update quota values from Quotas tab edits                 |
| `/omeroweb_admin_tools/storage/quota/import/`                       | POST     | Import quota values from CSV (`Group`, `Quota [GB]`)      |
| `/omeroweb_admin_tools/storage/quota/template/`                     | GET      | Download CSV template for quota import                    |
| `/omeroweb_admin_tools/server-database-testing/`                    | GET      | Server diagnostics UI                                     |
| `/omeroweb_admin_tools/server-database-testing/run/`                | POST     | Execute diagnostic scripts                                |
| `/omeroweb_admin_tools/help/`                                       | GET      | Serve plugin help documentation (Markdown)                |

## Code structure

```text
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

This plugin requires reachable monitoring service endpoints and log-query
controls configured in `env/omeroweb.env`; missing active assignments disable
the log-query backend instead of using code-side defaults:

| Variable                                       | Purpose                                                                                                                                                            | Example                                        |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| `ADMIN_TOOLS_LOKI_URL`                         | Loki base URL for log queries                                                                                                                                      | `http://loki:3100`                             |
| `ADMIN_TOOLS_GRAFANA_URL`                      | Grafana base URL for dashboard embedding                                                                                                                           | `http://grafana:3000`                          |
| `ADMIN_TOOLS_GRAFANA_DASHBOARD_UID`            | Default dashboard UID used by the embedded dashboard and Grafana proxy root redirect                                                                               | `omero-infrastructure`                         |
| `ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG`           | Default dashboard slug used with `ADMIN_TOOLS_GRAFANA_DASHBOARD_UID`                                                                                               | `server-infrastructure`                        |
| `ADMIN_TOOLS_GRAFANA_PUBLIC_URL`               | Optional browser-facing Grafana base URL; also used as a proxy fallback when the internal URL is unreachable                                                       | unset                                          |
| `ADMIN_TOOLS_PROMETHEUS_URL`                   | Prometheus base URL for metric queries                                                                                                                             | `http://prometheus:9090`                       |
| `ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL`            | Optional browser-facing Prometheus base URL; also used as a proxy fallback when the internal URL is unreachable                                                    | unset                                          |
| `ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME`          | Fallback scheme for generated internal Grafana/Prometheus URLs; invalid values fall back to `http`                                                                 | `http`                                         |
| `ADMIN_TOOLS_DOCKER_SOCKET`                    | Optional Docker API Unix socket used for container stats, compose-state inspection, and Docker diagnostic checks when explicitly mounted                           | `/var/run/docker.sock`                         |
| `ADMIN_TOOLS_DOCKER_SOCKET_REQUIRED`           | Set to `true` only when operators intentionally mount the Docker socket and want the UI to warn if socket diagnostics are unavailable                              | `false`                                        |
| `ADMIN_TOOLS_COMPOSE_PROJECT_NAME`             | Compose project label used when diagnostics inspect service containers through the Docker API                                                                      | `omero`                                        |
| `GRAFANA_HOST_PORT`                            | Host port used to synthesize a direct Grafana browser URL when no public URL is configured and the request is not behind a reverse proxy                           | `3000`                                         |
| `PROMETHEUS_HOST_PORT`                         | Host port used to synthesize a direct Prometheus browser URL when no public URL is configured and the request is not behind a reverse proxy                        | `9090`                                         |
| `ADMIN_TOOLS_DIAGNOSTIC_TIMEOUT_SECONDS`       | Timeout used by database and OMERO runtime diagnostic probes                                                                                                       | `3.5`                                          |
| `ADMIN_TOOLS_OMERO_SERVER_HOST`                | OMERO.server host used by server diagnostic probes; falls back to `OMEROHOST`/`CONFIG_omero_host`                                                                  | `omeroserver`                                  |
| `ADMIN_TOOLS_OMERO_BLITZ_PORT`                 | OMERO Blitz port used by server diagnostic probes; falls back to `OMERO_PORT`/`OMERO_CLI_PORT`                                                                     | `4064`                                         |
| `ADMIN_TOOLS_OMERO_SECURE_PORT`                | OMERO secure port used by server diagnostic probes; falls back to `OMERO_SECURE_PORT`                                                                              | `4063`                                         |
| `ADMIN_TOOLS_OMERO_WEB_HOST`                   | OMERO.web host used by server diagnostic probes                                                                                                                    | `omeroweb`                                     |
| `ADMIN_TOOLS_OMERO_WEB_PORT`                   | OMERO.web port used by server diagnostic probes; falls back to `CONFIG_omero_web_application__server_port`                                                         | `4090`                                         |
| `ADMIN_TOOLS_OMERO_WEB_PATH`                   | OMERO.web health path used when `ADMIN_TOOLS_OMERO_WEB_HEALTH_URL` is unset                                                                                        | `/webclient/`                                  |
| `ADMIN_TOOLS_OMERO_WEB_HEALTH_URL`             | Optional full OMERO.web health URL override used by server diagnostic probes                                                                                       | unset                                          |
| `ADMIN_TOOLS_LOG_LOOKBACK_SECONDS`             | Default log query time range                                                                                                                                       | `3600`                                         |
| `ADMIN_TOOLS_LOG_MAX_ENTRIES`                  | Maximum log entries per query                                                                                                                                      | `5000`                                         |
| `ADMIN_TOOLS_LOG_REQUEST_TIMEOUT_SECONDS`      | HTTP timeout for Loki requests                                                                                                                                     | `30`                                           |
| `ADMIN_TOOLS_LOG_CACHE_MAX_MB`                 | Process-local RAM budget for cached log query results                                                                                                              | `1024`                                         |
| `ADMIN_TOOLS_LOG_INTERNAL_FILE_BATCH_SIZE`     | Internal log filenames per Loki batch before adaptive split retries                                                                                                | `12`                                           |
| `ADMIN_TOOLS_LOG_MAX_PARALLEL_QUERIES`         | Maximum concurrent Loki queries per log request                                                                                                                    | `4`                                            |
| `ADMIN_TOOLS_QUOTA_STATE_PATH`                 | JSON state file for persisted quotas and reconciliation logs; the host enforcer reads the same file                                                                | `/OMERO/.admin-tools/group-quotas.json`        |
| `ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH`       | Marker file written when host-side quota enforcement is installed; OMERO.web uses it to report whether enforcement is available                                    | `/OMERO/.admin-tools/quota-enforcer-installed` |
| `ADMIN_TOOLS_MANAGED_GROUP_ROOT`               | Optional override for the ManagedRepository group root; if unset, reconciliation uses absolute `CONFIG_omero_managed_dir` or `${OMERO_DATA_DIR}/ManagedRepository` | unset                                          |
| `ADMIN_TOOLS_MIN_QUOTA_GB`                     | Minimum accepted quota value (GB) used by UI validation, backend validation, and ext4 enforcer script                                                              | `0.10`                                         |
| `ADMIN_TOOLS_DEFAULT_GROUP_QUOTA_GB`           | Default quota value (GB) auto-assigned to newly created OMERO groups when auto mode is enabled                                                                     | `0.10`                                         |
| `ADMIN_TOOLS_AUTO_SET_DEFAULT_GROUP_QUOTA`     | Boolean flag (`true`/`false`) enabling automatic default quota creation for new OMERO groups                                                                       | `false`                                        |
| `ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS` | Background reconciliation interval for quota enforcement loop                                                                                                      | `60`                                           |
| `ADMIN_TOOLS_QUOTA_PROJECTS_FILE`              | ext4 project-quota mapping file updated by the host enforcer                                                                                                       | `/OMERO/.admin-tools/quota/projects`           |
| `ADMIN_TOOLS_QUOTA_PROJID_FILE`                | ext4 project-name mapping file updated by the host enforcer                                                                                                        | `/OMERO/.admin-tools/quota/projid`             |
| `ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN`             | Minimum project ID used when assigning new group IDs                                                                                                               | `200000`                                       |

The Docker socket is not mounted by default. If Docker-backed diagnostics are
required, mount the path from `ADMIN_TOOLS_DOCKER_SOCKET` read-only and restrict
the Admin Tools routes to trusted root users.

Server/database diagnostics resolve PostgreSQL connection settings from the
live `omeroweb` runtime environment. OMERO database checks use
`ADMIN_TOOLS_OMERO_DB_*` when set, otherwise the shared OMERO.server values
(`CONFIG_omero_db_host`, `CONFIG_omero_db_user`, `CONFIG_omero_db_name`,
`OMERO_DB_PASS`). Plugin database checks use `ADMIN_TOOLS_PLUGIN_DB_*` when
set, otherwise the plugin runtime values (`OMP_DATA_HOST`, `OMP_DATA_PORT`,
`OMP_DATA_USER`, `OMP_DATA_DB`, `OMP_DATA_PASS`).

The quota compatibility check reads `CONFIG_omero_fs_repo_path` from the shared OMERO.server environment (`env/omeroserver.env`), which is also loaded into the `omeroweb` service in `docker-compose.yml` to keep a single source of truth for the repository template.

ManagedRepository quota enforcement uses an environment-driven group root: `${ADMIN_TOOLS_MANAGED_GROUP_ROOT}` when explicitly set, otherwise `CONFIG_omero_managed_dir` when that server setting is absolute, otherwise the legacy fallback `${OMERO_DATA_DIR}/ManagedRepository`. No fallback scan paths are used.

To prevent quotas from affecting unrelated directories, enforcement is blocked unless the resolved root is an existing directory under `${OMERO_DATA_DIR}`; when this validation fails, quotas stay pending and an explicit error is recorded in quota logs (including detection reason metadata).

Quota reconciliation responses include explicit path-access diagnostics for the managed group root (`managed_group_root_access`) and the resolved enforcer marker file path (`quota_enforcer_marker_path`) so operators can quickly diagnose UID/GID ownership and mode mismatches.

Quota reconciliation and the host enforcer intentionally do **not** create missing ManagedRepository group directories. OMERO.server must create/register those directories first; creating them externally can trigger import failures such as `Directory exists but is not registered`.

Grafana proxy authentication depends on passing session and auth headers
through OMERO.web. The proxy forwards `Authorization`, `Cookie`, and
`X-Grafana-Csrf-Token` request headers, rewrites `Origin` and `Referer` to
match the Grafana backend origin, and preserves `Set-Cookie` responses.
The Grafana proxy is not `@csrf_exempt`: OMERO.web requires an authenticated
root user before proxying, and Django CSRF validation still protects
state-changing proxy requests. Grafana can then validate its own login CSRF
token and cookie after the proxy rewrites origin/referrer headers and forwards
the Grafana CSRF header. Prometheus proxy requests use standard Django CSRF
handling as well. Cookie `Path` attributes are rewritten to
`/omeroweb_admin_tools/resource-monitoring/grafana-proxy/` so Grafana login
sessions continue to work when Grafana is accessed through the plugin proxy
route.
The proxy also rewrites Grafana boot settings (`appSubUrl` and `appUrl`) to the
proxy prefix, preventing top-right **Sign in** redirects from escaping to an
unmapped root route. Grafana root requests (`/`) through the proxy now redirect
users directly to the configured default OMERO dashboard route under the proxy
prefix (for example when users click **Home** or complete **Sign in**).
Grafana Live is disabled in Compose because this authenticated Django proxy is
HTTP-only and does not tunnel WebSockets. Dashboard queries and refreshes use
ordinary proxied HTTP requests, avoiding recurring failed Live handshakes.
Prometheus requests are proxied as standard request/response traffic only; the
proxy root redirects to the Prometheus targets page. If a proxied backend
exposes `/api/v1/notifications/live` as `text/event-stream`, the proxy
intentionally short-circuits that response with `204 No Content` because the
Django proxy does not stream chunked event responses; slow upstream reads return
`504 Gateway Timeout` instead of surfacing a Django `500`.

## Typical admin workflow

1. Use the Logs page to inspect recent service events, filter by container, browse internal log files.
2. Use Resource Monitoring to inspect infrastructure health via embedded Grafana dashboards and Docker container stats.
3. Use Storage page to identify disk growth hotspots by user and group.
4. Use Server Database Testing to run platform end-to-end health diagnostics, including Docker runtime state and direct SQL probes.
5. Apply operational actions externally based on findings (cleanup, scaling, user guidance).

If the configured ManagedRepository template does not start with `%group%/%user%/`, the Quotas tab is intentionally disabled and shows an incompatibility warning to prevent unsafe quota enforcement assumptions.

Quota values are validated with a minimum accepted value configured by `ADMIN_TOOLS_MIN_QUOTA_GB` in UI edits, backend processing (including CSV imports), and ext4 enforcement.

When `ADMIN_TOOLS_AUTO_SET_DEFAULT_GROUP_QUOTA=true`, reconciliation automatically writes a quota entry for each newly detected OMERO group using `ADMIN_TOOLS_DEFAULT_GROUP_QUOTA_GB`; this persisted state is then consumed by the host `omero-quota-enforcer` systemd service on its normal timer cycle.

Quota state persistence is versioned via a `state_schema_version` field in `group-quotas.json`. The service accepts only supported schema versions and fails loudly on unknown future versions to avoid silently misapplying quotas after upgrades.
Quota state writes are atomic by default and include a compatibility fallback for sticky-bit legacy directories: if atomic replace is blocked but the existing state file remains writable, the state is updated in place; otherwise reconciliation fails with an explicit permission error describing required `.admin-tools` permissions.

## Operator checklist

- Validate connectivity to Loki, Prometheus, and Grafana from the omeroweb container.
- Restrict plugin access to authorized admin users (plugin enforces root-only access).
- Review Grafana dashboard provisioning files after monitoring configuration changes.
- Keep query timeouts and entry caps aligned with cluster scale.
- If Docker-backed diagnostics are enabled, verify the Docker socket is
  read-only and accessible (check `docker compose logs omeroweb` for socket
  permission errors).
- Verify `psycopg2-binary` remains installed in the OMERO.web image after image rebuilds or package updates.

### ext4 project-quota enforcement behavior

OMERO.web quota reconciliation validates the configured ManagedRepository root,
auto-creates default quota entries when configured, records configured and
pending groups in `group-quotas.json`, and reports whether the host enforcer
marker exists. The normal OMERO.web reconciliation path does not invoke
`chattr` or `setquota` directly. The host `omero-quota-enforcer` systemd
path/timer reads `group-quotas.json` and applies ext4 project quotas from the
host namespace.

During host installer updates, `scripts/install-quota-enforcer.sh` verifies
byte-level integrity (`sha256`) of `scripts/omero-quota-enforcer.sh` and
disables/removes the repo-managed quota units, their drop-ins, and their
`.wants`/`.requires` dependency links before rendering and enabling the current
service, timer, and path units from the active installation paths. Unit
rendering and defaults-file value quoting are shared through
`scripts/omero-host-service-lib.sh`, while the installed runtime enforcer
remains a standalone script. The timer schedules from activation as well as
from the last service run, so reinstalling or restarting the timer leaves a
future reconciliation trigger.
The runtime enforcer parses quota JSON once per run, rewrites mapping files by
exact group/path matches, and applies quotas only to existing OMERO.server group
directories that resolve under the configured managed repository.
The installer creates `.admin-tools` with mode `0750`, `.admin-tools/quota`
with mode `0700`, and `.admin-tools/group-quotas.json` with mode `0600`.
At runtime, `startup/10-web-bootstrap.sh` assigns the quota state file to the
non-root `omeroweb` runtime user and keeps the parent directory non-world-
writable. The host-side enforcer refuses symlinked or world-writable quota
state and mapping paths before it reads quota JSON, rewrites project mappings,
or invokes `chattr`/`setquota`.

The enforcer performs the following for each group directory with a configured quota:

1. Validates that the target directory already exists (created/registered by OMERO.server) and is inside the detected mount point.
2. Resolves or assigns a stable project ID for the group.
3. Updates both mapping files (`/OMERO/.admin-tools/quota/projects` and `/OMERO/.admin-tools/quota/projid` by default).
4. Applies project ID to the group directory via `chattr -p`.
5. Enables project inheritance on the group directory via `chattr +P`.
6. Sets hard block quota with `setquota -P` on the filesystem mount point.
7. Clears stale project mappings, resets stale project quotas (`setquota -P <project_id> 0 0 0 0`), and removes stale project-id attributes (`chattr -R -p 0`) when a group quota is deleted from Admin Tools, so removed quotas stop blocking uploads.

Project quota is enforced at the parent group directory, and all files/subdirectories inside that tree count toward the same project quota domain.
