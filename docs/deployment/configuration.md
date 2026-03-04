# Deployment Configuration Guide

## Configuration Sources

This repository uses environment variables as the primary configuration surface.

Tracked files in git are templates (`*_example*`). Deployments must create runtime copies without `_example`.

- `installation_paths_example.env` -> `installation_paths.env`: filesystem path definitions.
- `env/omeroserver_example.env` -> `env/omeroserver.env`: OMERO.server runtime, DB, and script processor options.
- `env/omeroweb_example.env` -> `env/omeroweb.env`: OMERO.web apps, UI links, plugin settings, and admin tool endpoints.
- `env/omeroserver.env` is also loaded by `omeroweb` for shared server-derived settings (for example `CONFIG_omero_fs_repo_path` consumed by admin-tools quota compatibility checks).
- `env/omero-celery_example.env` -> `env/omero-celery.env`: Celery and Imaris connector processing controls.
- `env/grafana_example.env` -> `env/grafana.env`: Grafana credentials and runtime options (renamed from `env/compose.env`).
- `env/omero_secrets_example.env` -> `env/omero_secrets.env`: credentials and secrets (deployment-local only; never commit runtime secrets).
- CrowdSec pre-installs the `cs-firewall-bouncer` binary plus both `nftables` and `iptables`/`ipset` backends at image build time (`docker/crowdsec.Dockerfile`). At container startup the entrypoint auto-detects the host's firewall backend: on Ubuntu 24.04+ and Debian 13+ (Trixie) — which use nftables natively — the bouncer starts in `mode: nftables`, creating its own nftables tables (`crowdsec` / `crowdsec6`) with INPUT-hook chains at priority -10 and supplementary FORWARD-hook chains for Docker bridge traffic protection. On older hosts with iptables-legacy the bouncer falls back to `mode: iptables` with `INPUT` and `DOCKER-USER` chains. Set `CROWDSEC_REQUIRE_BOUNCERS=true` to enforce fail-fast behavior when bouncers are mandatory. CrowdSec installs the `crowdsecurity/linux` and `crowdsecurity/sshd` collections plus `crowdsecurity/docker-logs` and `crowdsecurity/cri-logs` parsers for Docker log analysis. Log acquisition sources are defined in `monitoring/crowdsec/acquis.yaml`. CrowdSec UID/GID is auto-detected from the built image and used to chown `CROWDSEC_DB_PATH` and `CROWDSEC_CONFIG_PATH` during installation. The CrowdSec service healthcheck uses `GET http://localhost:8080/health` to avoid repeated authenticated watcher-login noise from `cscli lapi status` polling. Set `CROWDSEC_ENGINE_NAME` in `env/omero_secrets.env` to a fixed name (e.g. the hostname) so that console enrollment reuses the same engine identity across container rebuilds; this avoids duplicate approval requests in the CrowdSec dashboard. When set, enrollment uses `--name` and `--overwrite` flags. Leave empty to let CrowdSec generate a random engine name (default behavior).
- LDAP bind and directory settings (`CONFIG_omero_ldap_urls`, `CONFIG_omero_ldap_username`, `CONFIG_omero_ldap_password`, and `CONFIG_omero_ldap_base`) must be set in `env/omero_secrets.env` when `CONFIG_omero_ldap_config=true`. `CONFIG_omero_ldap_user__filter` is optional and is applied only when declared.
- `CONFIG_omero_ldap_new__user__group` (in `env/omeroserver.env`) should be set when LDAP is enabled to avoid fallback to OMERO's built-in `omero.ldap.new_user_group=default` behavior, which can auto-create/use a `default` OMERO group for LDAP-created users. Static non-default values (for example `users_ldap`) are validated at startup and bootstrapped automatically if missing. If unset/commented or explicitly set to `default`, bootstrap does not fail and explicit group creation is skipped. At startup, `startup/10-server-bootstrap.sh` also applies LDAP properties explicitly via `omero config set` and verifies persisted `omero.ldap.new_user_group` to avoid underscore-translation ambiguity in environment-driven config loading. Dynamic LDAP expressions beginning with `:` are passed through unchanged and are not auto-created because they resolve memberships at login time.
- `OMERO_INSTALL_GROUP_LIST` (in `env/omeroserver.env`) controls installation-time OMERO group bootstrap as `group:permission` entries (comma-separated). Supported permissions: `private`, `read-only`, `read-annotate`, `read-write`. Empty values and comment-only values (for example `OMERO_INSTALL_GROUP_LIST=# disabled`) are treated as disabled bootstrap, so fresh installations can run with zero custom groups. The installation script creates each configured group only if it does not already exist. Bootstrap resolves a valid OMERO CLI path inside the running `omeroserver` container (`/opt/omero/server/venv*/bin/omero` preferred, with `/opt/omero/server/OMERO.server/bin/omero` fallback), then executes login and group-creation commands as user `omero-server` with explicit `HOME`/`TMPDIR`/`OMERO_TMPDIR`/`OMERO_TEMPDIR` to match the runtime temp-directory model and avoid root-owned temp artifacts.
- When `OMERO_JOB_SERVICE_JOIN_ALL_GROUPS=1` (in `env/omeroserver.env`) and both `OMERO_JOB_SERVICE_PASS` and `ROOTPASS` are set, the installation script automatically adds the job-service account (`OMERO_JOB_SERVICE_USERNAME`, default `job-service`) to every discovered OMERO group immediately after startup, including groups created later in the same installation flow. The job-service user is created if it does not already exist (default group: `user`). This ensures background plugin operations (uploads, Imaris exports) can access data in all groups from the moment installation completes. Exceptions: the `root`, `system`, and `user` groups are excluded. At runtime, `startup/10-server-bootstrap.sh` continues to synchronize the job-service account into any newly created groups on a configurable interval (`OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS`, default 3600 seconds). Runtime sync now targets configurable OMERO endpoint settings (`OMERO_JOB_SERVICE_HOST`, default `localhost`; `OMERO_JOB_SERVICE_PORT`, default `4064`) to match installation-time behavior in non-default deployments. The sync uses jitter (`OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS`, default 20) and exponential backoff to avoid thundering-herd effects and does not affect active user sessions. To reduce false startup errors during initial database/schema migrations, only the first sync attempt in the first cycle uses the long readiness window (`OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS`); retries in the same cycle and all later cycles use a short readiness probe window (`12 * OMERO_JOB_SERVICE_READINESS_POLL_SECONDS`) so the loop actually executes all configured retries (`OMERO_JOB_SERVICE_SYNC_MAX_RETRIES`, default 3). User creation also retries with `OMERO_JOB_SERVICE_USER_ENSURE_RETRIES`. All sync-loop variables (`OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS`, `OMERO_JOB_SERVICE_SYNC_MAX_RETRIES`, `OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS`) are defined in `env/omeroserver.env` and are the single source of truth. `startup/10-server-bootstrap.sh` validates the readiness and sync variables at startup and fails fast if any of them is missing, empty, non-numeric, or less than 1 (jitter allows zero).

## Required Hardening Before Deployment

1. Rotate all credentials and secrets.
2. Disable debug options where enabled.
3. Review open host ports and reduce exposure.
4. Confirm TLS and secure session settings.
5. Restrict external access to monitoring services.

## Plugin Registration

Plugins are registered in `CONFIG_omero_web_apps` and top-link entries in `CONFIG_omero_web_ui_top__links`.

When adding or removing a plugin:

1. update app registration,
2. update URL mapping,
3. restart OMERO.web,
4. verify menu link visibility and route health.

## Data, Temp, and Logs

Paths declared in `installation_paths.env` map host storage into containers for:

- OMERO data,
- databases,
- temporary/working data (`OMERO_TMP_PATH`),
- OMERO server/web logs,
- monitoring state.

Ensure host paths exist and are writable by container runtime users before startup.

### Centralized Temporary File Storage

`OMERO_TMP_PATH` (set in `installation_paths.env`) is the single persistent root for temporary/working data. It is mounted into both `omeroweb` and `omeroserver` at the same absolute path value configured in `OMERO_TMP_PATH` (host path equals in-container path).

Each plugin automatically receives its own subfolder (detected from the Python package name at runtime via `omero_plugin_common.tmp_utils`). Plugins further subdivide into purpose-specific subdirectories (`data`, `jobs`, `compat-check`, etc.).

Example runtime layout:

```
${OMERO_TMP_PATH}/
├── omeroweb-upload/
│   ├── data/         # staged upload files
│   ├── jobs/         # upload job state JSON
│   └── compat-check/ # transient OMERO CLI isolation dirs
├── omeroweb-omp-plugin/
│   └── jobs/         # filename metadata job state
└── omeroweb-imaris-connector/
    └── jobs/         # Imaris export process state

# server bootstrap temp namespace (separate from plugin namespaces)
${OMERO_CLI_USER}/
└── tmp/
```

All plugin paths are controlled exclusively by `OMERO_TMP_PATH`. There are no per-plugin env var overrides.

`OMERO_TMP_PATH` is also used by `startup/10-server-bootstrap.sh` for OMERO CLI bootstrap operations, but the bootstrap script uses a dedicated server-only subpath `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp` as `TMPDIR` to avoid collisions with plugin folders and permission churn on the shared root. During installation, `installation/installation_script.sh` pre-creates this namespace and sets ownership to the OMERO.server runtime UID/GID with `0700` permissions while preserving root traversal (`x`) so OMERO.web-owned temp roots remain accessible for server namespace creation.

The bootstrap script also derives the OMERO internal lock-file temp path from the OMERO.server installation root (`$(dirname "${SERVER_HOME}")/omero/tmp`) and attempts to prepare it for OMERO lock-file compatibility. If this legacy path cannot be created or is not writable, bootstrap logs a warning and continues using the dedicated `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp` namespace as `TMPDIR`.

At image build time, `docker/omero-server.Dockerfile` now also enforces writable permissions on `${SERVER_HOME}/etc/grid` for the runtime `omero-server` account so `omero config set ...` can always persist updates to `config.xml` during bootstrap.

### Managed Repository Path Setting

In `env/omeroserver.env`, `CONFIG_omero_fs_repo_path` configures the managed
repository import parent-directory template.

OMERO expands supported terms automatically when written with surrounding `%`
characters (for example: `%group%/%user%/%year%-%month%-%day%/%time%`).

If token syntax is malformed (for example `%group/%user/%year-%month-%day/%time`
without trailing `%`), OMERO treats those strings literally and creates
directories named with `%...` segments.

## Celery and Imaris Export Configuration

Relevant variables include:

- `OMERO_IMS_USE_CELERY`
- `OMERO_IMS_CELERY_BROKER_URL`
- `OMERO_IMS_CELERY_BACKEND_URL`
- `OMERO_IMS_CELERY_QUEUE`
- timeout/retry/concurrency controls

Queue names and broker URLs must be consistent between job producer and worker.

## Quota Enforcer

The installation script automatically installs the host-side quota enforcer systemd units if the OMERO user data directory is on an **ext4** filesystem mounted with `prjquota` and the `project` feature enabled in the superblock. If these conditions are not met, the installation continues without blocking, but the Quotas tab in the Admin Tools plugin will be disabled.

## Configuration Change Process (Recommended)

1. Edit env files in version control.
2. Validate syntax and variable expansions.
3. Rebuild/restart impacted services.
4. Run health checks and targeted plugin workflow checks.
5. Document the change in release notes.

## Reverse Proxy (Managed Externally)

Reverse proxy and TLS termination are managed outside this repository.

For OMERO.web forwarding from your external reverse proxy (for example, nginx managed via Ansible), target:

- Scheme: `http`
- Forward Hostname / IP: `omeroweb`
- Forward Port: `4090`

This keeps direct internal access to OMERO.web (`http://omeroweb:4090`) available while IT-managed proxy configuration is applied.
