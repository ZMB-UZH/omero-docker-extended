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
| `/omeroweb_admin_tools/help/` | GET | Serve plugin help documentation (Markdown) |

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
| `ADMIN_TOOLS_DEFAULT_GROUP_QUOTA_GB` | Default quota value (GB) auto-assigned to newly created OMERO groups when auto mode is enabled | `0.10` |
| `ADMIN_TOOLS_AUTO_SET_DEFAULT_GROUP_QUOTA` | Boolean flag (`true`/`false`) enabling automatic default quota creation for new OMERO groups | `false` |
| `ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE` | Optional command template used to enforce quotas. If unset on ext4, a built-in project-quota enforcer script is used. | ` /opt/omero/web/bin/enforce-ext4-project-quota.sh --group {group} --group-path {group_path} --quota-gb {quota_gb} --mount-point {mount_point}` |
| `ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS` | Background reconciliation interval for quota enforcement loop | `60` |
| `ADMIN_TOOLS_QUOTA_PROJECTS_FILE` | ext4 project-quota mapping file updated by the enforcer | `/tmp/omero-admin-tools/quota/projects` |
| `ADMIN_TOOLS_QUOTA_PROJID_FILE` | ext4 project-name mapping file updated by the enforcer | `/tmp/omero-admin-tools/quota/projid` |
| `ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN` | Minimum project ID used when assigning new group IDs | `200000` |

The Docker socket (`/var/run/docker.sock`) must be mounted read-only for container stats functionality.

The quota compatibility check reads `CONFIG_omero_fs_repo_path` from the shared OMERO.server environment (`env/omeroserver.env`), which is also loaded into the `omeroweb` service in `docker-compose.yml` to keep a single source of truth for the repository template.

ManagedRepository quota enforcement uses an environment-driven group root: `${ADMIN_TOOLS_MANAGED_GROUP_ROOT:-${OMERO_DATA_DIR}/ManagedRepository}` (no fallback scan paths are used).

To prevent quotas from affecting unrelated directories, enforcement is blocked unless the resolved root is an existing directory under `${OMERO_DATA_DIR}`; when this validation fails, quotas stay pending and an explicit error is recorded in quota logs (including detection reason metadata).

Quota reconciliation responses include explicit path-access diagnostics for the managed group root (`managed_group_root_access`) and the resolved enforcer marker file path (`quota_enforcer_marker_path`) so operators can quickly diagnose UID/GID ownership and mode mismatches.

Quota reconciliation and the host enforcer intentionally do **not** create missing ManagedRepository group directories. OMERO.server must create/register those directories first; creating them externally can trigger import failures such as `Directory exists but is not registered`.


Grafana proxy authentication depends on passing session and auth headers through OMERO.web. The proxy forwards `Authorization` and `Cookie` request headers, rewrites `Origin` and `Referer` to match the Grafana backend origin, and preserves `Set-Cookie` responses. Cookie `Path` attributes are rewritten to `/omeroweb_admin_tools/resource-monitoring/grafana-proxy/` so Grafana login sessions continue to work when Grafana is accessed through the plugin proxy route.
The proxy also rewrites Grafana boot settings (`appSubUrl` and `appUrl`) to the proxy prefix, preventing top-right **Sign in** redirects from escaping to an unmapped root route. Grafana root requests (`/`) through the proxy now redirect users directly to the configured default OMERO dashboard route under the proxy prefix (for example when users click **Home** or complete **Sign in**).

## Typical admin workflow

1. Use the Logs page to inspect recent service events, filter by container, browse internal log files.
2. Use Resource Monitoring to inspect infrastructure health via embedded Grafana dashboards and Docker container stats.
3. Use Storage page to identify disk growth hotspots by user and group.
4. Use Server Database Testing to run platform end-to-end health diagnostics.
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
- Verify Docker socket is accessible (check `docker compose logs omeroweb` for socket permission errors).


### ext4 project-quota enforcement behavior

When the managed repository is on `ext4`, quota reconciliation uses the bundled enforcer script inside the OMERO.web image by default unless `ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE` is explicitly set.

The enforcer performs the following for each group directory with a configured quota:

During host installer updates, `scripts/install-quota-enforcer.sh` now verifies byte-level integrity (`sha256`) of `scripts/omero-quota-enforcer.sh`: identical files are kept with refreshed permissions, and changed files are reinstalled with post-install checksum verification.
The installer and `installation/installation_script.sh` both enforce `.admin-tools` directories with mode `0777` (no sticky bit) so quota-state persistence survives container restarts and project updates without `os.replace` rename failures.
During installation and upgrades, the installer also repairs (or creates) `.admin-tools/group-quotas.json` with mode `0666` so the non-root `omeroweb` container process can always persist quota edits while the host-side systemd enforcer (root) continues to read the same file.

1. Validates that the target directory already exists (created/registered by OMERO.server) and is inside the detected mount point.
2. Resolves or assigns a stable project ID for the group.
3. Updates both mapping files (`/tmp/omero-admin-tools/quota/projects` and `/tmp/omero-admin-tools/quota/projid` by default).
4. Applies project ID to the group directory via `chattr -p`.
5. Enables project inheritance on the group directory via `chattr +P`.
6. Sets hard block quota with `setquota -P` on the filesystem mount point.
7. Clears stale project mappings, resets stale project quotas (`setquota -P <project_id> 0 0 0 0`), and removes stale project-id attributes (`chattr -R -p 0`) when a group quota is deleted from Admin Tools, so removed quotas stop blocking uploads.

Project quota is enforced at the parent group directory, and all files/subdirectories inside that tree count toward the same project quota domain.
