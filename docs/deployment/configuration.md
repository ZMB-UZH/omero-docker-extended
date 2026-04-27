# Deployment Configuration Guide

## Configuration Sources

This repository uses environment variables as the primary configuration surface.

Tracked files in git are templates (`*_example*`). Deployments must create runtime copies without `_example`.

For OMERO configuration property names, defaults, and semantics, use the official OMERO config glossary as the single source of truth:

- `https://omero.readthedocs.io/en/stable/sysadmins/config.html`

This repository expresses those OMERO properties in env files with the existing `CONFIG_omero_...` naming pattern already present in the tracked examples. Example: the official `omero.pixeldata.threads` property maps to `CONFIG_omero_pixeldata_threads`.

- `installation_paths_example.env` -> `installation_paths.env`: filesystem path definitions, including `OMERO_DATA_DIR` for the in-container OMERO data root.
- **CRITICAL:** The `omeroserver` service in `docker-compose.yml` **must** pass
  `OMERO_DATA_DIR` and `OMERO_DIR` into its container environment block. These
  variables tell the OMERO server where the bind-mounted data volume (`/OMERO`)
  is. Without them, the server resolves relative paths (including
  `CONFIG_omero_managed_dir`) against its install directory instead of
  `/OMERO`, causing imported files to land inside the container's ephemeral
  filesystem and be **lost on restart**. **Never remove these two environment
  entries from the omeroserver service.**
- `env/omeroserver_example.env` -> `env/omeroserver.env`: OMERO.server runtime, DB, script processor options, and managed-repository settings such as `CONFIG_omero_managed_dir` and `CONFIG_omero_fs_repo_path`.
- `env/omeroweb_example.env` -> `env/omeroweb.env`: OMERO.web apps, UI links,
  Open With registrations, right-panel plugin entries, plugin settings, admin
  tool endpoints, host/internal web ports, the default login-logo setting
  (`CONFIG_omero_web_login__logo=/static/branding/logo.png`), and Gunicorn
  startup overrides such as `OMERO_WEB_WSGI_ARGS`. When a deployment-local
  `logo/logo.png` exists at build time, the `omeroweb` image build copies it
  into that static path, and OMERO.web startup re-synchronizes the mounted
  `var/static/` tree from the image so existing installations also receive
  updated branding and plugin static assets. `logo/logo.png` is a site-local
  asset and is intentionally gitignored.
- `env/omeroserver.env` is also loaded by `omeroweb` for shared server-derived settings (for example `CONFIG_omero_fs_repo_path` consumed by admin-tools quota compatibility checks).
- `env/omero-celery_example.env` -> `env/omero-celery.env`: Celery and Imaris connector processing controls.
- `env/grafana_example.env` -> `env/grafana.env`: Grafana credentials and runtime options (renamed from `env/compose.env`).
- `env/omero_secrets_example.env` -> `env/omero_secrets.env`: credentials and secrets (deployment-local only; never commit runtime secrets). This now includes the local `supervisord` socket credentials used by the `omeroweb` container's `supervisorctl` interface.
- Redis memory sizing is interpolated from the generated `.env` file. The
  installer writes `REDIS_MAXMEMORY=512mb`,
  `REDIS_MAXMEMORY_POLICY=allkeys-lru`, `REDIS_DATA_TMPFS_SIZE=512m`,
  `REDIS_APPENDONLY=no`, and an empty `REDIS_SAVE_POLICY` unless the operator
  provides different values before generation. Existing installs that do not
  have these keys keep the same Compose defaults through fallback
  interpolation.
- `CONFIG_omero_pixeldata_threads` (in `env/omeroserver*.env`) sets OMERO's `omero.pixeldata.threads` property. The official OMERO docs list a default of `2`; this repository tracks `4` to increase concurrent pixel-pyramid work via the same env-driven server configuration path.
- CrowdSec pre-installs the `cs-firewall-bouncer` binary plus both `nftables`
  and `iptables`/`ipset` backends at image build time
  (`docker/crowdsec.Dockerfile`). At container startup the entrypoint
  auto-detects the host's firewall backend: on Ubuntu 24.04+ and Debian 13+
  (Trixie), which use nftables natively, the bouncer starts in
  `mode: nftables`, creating its own nftables tables (`crowdsec` / `crowdsec6`)
  with INPUT-hook chains at priority -10 and supplementary FORWARD-hook chains
  for Docker bridge traffic protection. The entrypoint waits for the
  bouncer-created per-origin nftables sets before installing these FORWARD
  chains so Docker bridge protection is not skipped during startup races. On
  older hosts with iptables-legacy the bouncer falls back to `mode: iptables`
  with `INPUT` and `DOCKER-USER` chains. Set
  `CROWDSEC_REQUIRE_BOUNCERS=true` to enforce fail-fast behavior when bouncers
  are mandatory. CrowdSec installs the `crowdsecurity/linux` and
  `crowdsecurity/sshd` collections plus `crowdsecurity/docker-logs` and
  `crowdsecurity/cri-logs` parsers for Docker log analysis. Log acquisition
  sources are defined in `monitoring/crowdsec/acquis.yaml`. The CrowdSec image
  defaults to a named non-root user for image hygiene, while Compose explicitly
  runs the service as `root` because host firewall changes require
  `NET_ADMIN` plus root privileges. CrowdSec UID/GID is auto-detected from the
  built image and used to chown `CROWDSEC_DB_PATH` and `CROWDSEC_CONFIG_PATH`
  during installation. The CrowdSec service healthcheck uses
  `GET http://localhost:8080/health` to avoid repeated authenticated
  watcher-login noise from `cscli lapi status` polling. Set
  `CROWDSEC_ENGINE_NAME` in `env/omero_secrets.env` to a fixed name (for
  example the hostname) if you want installation-time enrollment requests to
  use a predictable engine name. CrowdSec console enrollment is armed only by
  `installation/installation_script.sh`, and every install run with a real
  `CROWDSEC_ENROLL_KEY` removes the dedicated
  `.console-enrollment-install.done` marker before container startup so
  CrowdSec creates a fresh dashboard approval request for that installation.
  The marker is still used inside the container to suppress duplicate enroll
  attempts within the same install-armed startup, and it remains separate from
  `online_api_credentials.yaml` because CrowdSec writes Central API credentials
  there even before Console approval exists. Ordinary
  `docker compose up -d crowdsec`, `docker restart crowdsec`, and other regular
  lifecycle commands do not arm enrollment and therefore do not create fresh
  approval requests. During each install-armed CrowdSec start, OMERO prints a
  dedicated approval banner before container startup begins and schedules one
  non-blocking `docker restart crowdsec` about 10 minutes after CrowdSec first
  boots in that install run; that one-shot restart is not installed for normal
  compose lifecycle commands.
- LDAP bind and directory settings (`CONFIG_omero_ldap_urls`, `CONFIG_omero_ldap_username`, `CONFIG_omero_ldap_password`, and `CONFIG_omero_ldap_base`) must be set in `env/omero_secrets.env` when `CONFIG_omero_ldap_config=true`. `CONFIG_omero_ldap_user__filter` is optional and is applied only when declared.
- `CONFIG_omero_ldap_new__user__group` (in `env/omeroserver.env`) should be
  set when LDAP is enabled to avoid fallback to OMERO's built-in
  `omero.ldap.new_user_group=default` behavior, which can auto-create/use a
  `default` OMERO group for LDAP-created users. Static non-default values (for
  example `users_ldap`) are validated at startup and bootstrapped
  automatically if missing. If unset/commented or explicitly set to `default`,
  bootstrap does not fail and explicit group creation is skipped. At startup,
  `startup/10-server-bootstrap.sh` also applies LDAP properties explicitly via
  `omero config set` and verifies persisted `omero.ldap.new_user_group` to
  avoid underscore-translation ambiguity in environment-driven config loading.
  Dynamic LDAP expressions beginning with `:` are passed through unchanged and
  are not auto-created because they resolve memberships at login time.
- `OMERO_INSTALL_GROUP_LIST` (in `env/omeroserver.env`) controls
  installation-time OMERO group bootstrap as `group:permission` entries
  (comma-separated). Supported permissions: `private`, `read-only`,
  `read-annotate`, `read-write`. Empty values and comment-only values (for
  example `OMERO_INSTALL_GROUP_LIST=# disabled`) are treated as disabled
  bootstrap, so fresh installations can run with zero custom groups. The
  installation script creates each configured group only if it does not already
  exist. Bootstrap resolves a valid OMERO CLI path inside the running
  `omeroserver` container (`/opt/omero/server/venv*/bin/omero` preferred, with
  `/opt/omero/server/OMERO.server/bin/omero` fallback), then executes login
  and group-creation commands as `OMERO_CLI_USER` with explicit
  `HOME`/`TMPDIR`/`OMERO_TMPDIR`/`OMERO_TEMPDIR` to match the runtime
  temp-directory model and avoid root-owned temp artifacts. The same list is
  also the authoritative source for managed-repository shared-prefix
  normalization when `CONFIG_omero_fs_repo_path` contains `%group%`, so every
  non-default group prefix that should be normalized by startup must appear
  here, or come from the static LDAP new-user group setting.
- Runtime startup wrappers and the `omeroserver` healthcheck resolve the active
  OMERO virtualenv from the container's `OMERODIR` at execution time, then fail
  fast with explicit errors when required env values or executables are missing.
- When `OMERO_JOB_SERVICE_JOIN_ALL_GROUPS=1` (in `env/omeroserver.env`) and
  both `OMERO_JOB_SERVICE_PASS` and `ROOTPASS` are set, the installation script
  automatically adds the job-service account
  (`OMERO_JOB_SERVICE_USERNAME`, default `job-service`) to every discovered
  OMERO group immediately after startup, including groups created later in the
  same installation flow. The job-service user is created if it does not
  already exist (default group: `user`). This ensures background plugin
  operations (uploads, Imaris exports) can access data in all groups from the
  moment installation completes. Exceptions: the `root`, `system`, and `user`
  groups are excluded. Group membership sync does not grant OMERO
  administrator privileges, and background workers must not reopen a browser
  user's live OMERO.web `session_key` as a fallback because closing that helper
  connection can destroy the login session. At runtime,
  `startup/10-server-bootstrap.sh` continues to synchronize the job-service
  account into any newly created groups on a configurable interval
  (`OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS`, default 3600 seconds). Runtime
  sync now targets configurable OMERO endpoint settings
  (`OMERO_JOB_SERVICE_HOST`, default `localhost`; `OMERO_JOB_SERVICE_PORT`,
  default `4064`) to match installation-time behavior in non-default
  deployments. The sync uses jitter (`OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS`,
  default 20) to avoid synchronized retries and does not affect active user
  sessions. Each sync attempt uses the configured readiness window
  (`OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS`, default 900 seconds) so slow first
  starts, schema checks, or database recovery do not turn expected OMERO
  startup time into failed short probes. Retry pauses use
  `OMERO_JOB_SERVICE_READINESS_POLL_SECONDS`; no fixed sleep interval is
  embedded in the loop. The number of sync attempts per cycle is controlled by
  `OMERO_JOB_SERVICE_SYNC_MAX_RETRIES` (default 3). User creation also retries with
  `OMERO_JOB_SERVICE_USER_ENSURE_RETRIES`. All sync-loop variables
  (`OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS`,
  `OMERO_JOB_SERVICE_SYNC_MAX_RETRIES`,
  `OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS`) are defined in
  `env/omeroserver.env` and are the single source of truth.
  `startup/10-server-bootstrap.sh` validates the readiness and sync variables
  at startup and fails fast if any of them is missing, empty, non-numeric, or
  less than 1 (jitter allows zero).
- `OMERO_BINARY_REPO_CLEANSE_ON_START=1` (in `env/omeroserver.env`) enables a
  background `omero admin cleanse` run on every `omeroserver` container start,
  including fresh installs, `docker start`, `docker restart`, and
  update-driven recreates. The startup hook waits for OMERO login readiness,
  runs against `OMERO_BINARY_REPO_CLEANSE_DATA_DIR` (default `/OMERO`), and
  applies a task-local `omero.keep_alive` setting from
  `OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS` (default `30`) through a
  temporary `ICE_CONFIG` file so long repository scans do not depend on a
  separate keepalive shell. `OMERO_BINARY_REPO_CLEANSE_STARTUP_WAIT_SECONDS`
  and `OMERO_BINARY_REPO_CLEANSE_READINESS_POLL_SECONDS` control the readiness
  window. The task is non-blocking for server startup and logs to
  `OMERO.server/var/log/binary-repository-cleanse.log`.
- `OMERO_REPOSITORY_LOCK_CLEANUP_ON_START=1` (in `env/omeroserver.env`) removes stale repository lock files from `${OMERO_DIR}/.omero/repository/*/.lock` on every `omeroserver` container start before `omero admin start --foreground` runs. Disable it only if you intentionally share the same OMERO repository with another independently running server process.
- `OMERO_RENDERING_CACHE_CLEANUP_ON_START=0` (in `env/omeroserver.env`)
  purges pyramid files, Bio-Formats memo cache, and thumbnail cache on
  container start. All regenerate automatically on first user access. No
  original data is deleted. Safe only when
  `OMERO_ZARR_PIXEL_BUFFER_ENABLED=false` (the default), because the standard
  `PixelsService` handles pyramid regeneration. Reset to `0` after one
  successful cleanup cycle.
- `OMERO_ZARR_PIXEL_BUFFER_ENABLED=false` (in `env/omeroserver.env`) controls whether the `omero-zarr-pixel-buffer` server-side plugin is active. When `false`, the plugin JAR is moved out of the classpath so the standard OMERO `PixelsService` handles all pixel buffer requests (including automatic pyramid regeneration). Must be `true` when alternative zarr import or rendering mechanisms are in use.

## Required Hardening Before Deployment

1. Rotate all credentials and secrets.
2. Disable debug options where enabled.
3. Review open host ports and reduce exposure.
4. Confirm TLS and secure session settings.
5. Restrict external access to monitoring services.
6. Replace example `SUPERVISOR_USERNAME` / `SUPERVISOR_PASSWORD` values before production rollout.

## Plugin Registration

Plugins are registered in `CONFIG_omero_web_apps` and top-link entries in `CONFIG_omero_web_ui_top__links`.

When adding or removing a plugin:

1. update app registration,
2. update URL mapping,
3. restart OMERO.web,
4. verify menu link visibility and route health.

The tracked `omeroweb` env places the `Tools` shortcut between `Import` and
`Admin tools` in the OMERO.web top navigation.

### OMP AI provider configuration

`omeroweb_omp_plugin` exposes AI-assisted regex and filename parsing through
the provider list declared in `omeroweb_omp_plugin/services/ai_providers.py`:
Local/Ollama, Groq, Gemini, Claude, Perplexity, xAI, and Cohere. External provider
API keys are stored per user in the plugin database. The Local provider calls
the internal `ollama` Compose service by default.

Related optional `env/omeroweb.env` controls:

- `OMP_OLLAMA_BASE_URL` -- override the Local provider endpoint; default is
  `http://ollama:11434` on the Docker network.
- `OMP_OLLAMA_MODEL` -- override the Local provider model; default is
  `qwen2.5:3b`.

### Tools enhanced-search configuration

`omeroweb_tools` exposes the user-facing `Tools` launcher and the current
`Enhanced search` feature. Its write path is intentionally isolated:

- OMERO metadata is read through the OMERO API only.
- Indexed rows, sync state, and saved queries are written only to the plugin
  database via the existing `OMP_DATA_*` connection variables.
- No enhanced-search data is written into the core OMERO PostgreSQL database.

Metadata indexing is opt-in per OMERO user. Once a user enables universal
metadata indexing from `Tools > Enhanced search`, the plugin automatically
indexes OMERO.web-visible metadata for all images owned by that user. Plugin
index searches are restricted to the current user's scope membership and
candidate rows are revalidated through OMERO before display.
Combined-source searches run the plugin-index lookup and OMERO built-in lookup
concurrently while keeping separate plugin-database and OMERO connection
boundaries.

Related `env/omeroweb.env` controls:

- `TOOLS_ENHANCED_SEARCH_INDEX_BATCH_SIZE`
- `TOOLS_ENHANCED_SEARCH_MAX_RESULTS`
- `TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS`
- `TOOLS_ENHANCED_SEARCH_SCHEMA_VERSION`

Related `env/omero-celery.env` controls:

- `TOOLS_ENHANCED_SEARCH_USE_CELERY`
- `TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL`
- `TOOLS_ENHANCED_SEARCH_CELERY_BACKEND_URL`
- `TOOLS_ENHANCED_SEARCH_CELERY_QUEUE`
- `TOOLS_ENHANCED_SEARCH_CELERY_RESULT_EXPIRES`
- `TOOLS_ENHANCED_SEARCH_CELERY_TIME_LIMIT`
- `TOOLS_ENHANCED_SEARCH_CELERY_LOGLEVEL`
- `TOOLS_ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY`
- `TOOLS_ENHANCED_SEARCH_CELERY_MAX_RETRIES`
- `TOOLS_ENHANCED_SEARCH_CELERY_PREFETCH`

`TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL` and
`TOOLS_ENHANCED_SEARCH_CELERY_BACKEND_URL` are preferred when set. If either is
unset, the plugin reuses the corresponding Imaris connector value from
`OMERO_IMS_CELERY_BROKER_URL` or `OMERO_IMS_CELERY_BACKEND_URL` before falling
back to an empty value.

When celery is enabled, `supervisord.conf` starts a dedicated
`tools-celery-worker` process in the `omeroweb` container. If celery is
disabled, refresh requests fall back to an in-process background thread.

`TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS` controls when an enabled user's
index is considered stale enough for the next page visit or poll request to
trigger a background refresh automatically.

### OMERO.web Zarr UI registration

`omero_web_zarr` has additional UI registration beyond `CONFIG_omero_web_apps`:

- `CONFIG_omero_web_open__with` registers the Vizarr launcher.
- `CONFIG_omero_web_ui_right__plugins` registers the Zarr-aware Preview tab.

The tracked example env enables a Preview right-panel entry that loads `omero_web_zarr/right_plugin.preview.js.html`. That preview path is intended for store-backed OME-Zarr images whose browser viewing should use the authenticated `/zarr/v0.4/preview/image/<id>.zarr` contract instead of the classic OMERO preview viewport.

## Data, Temp, and Logs

Paths declared in `installation_paths.env` map host storage into containers for:

- OMERO data,
- databases,
- temporary/working data (`OMERO_TMP_PATH`),
- OMERO server/web logs,
- monitoring state, including Prometheus, Loki, Alloy, and Grafana data,
- host-side installation/update transcripts under `${OMERO_DATA_PATH}/installation_logs`.

Ensure host paths exist and are writable by container runtime users before startup.

### Centralized Temporary File Storage

`OMERO_TMP_PATH` (set in `installation_paths.env`) is the single persistent root for temporary/working data. It is mounted into both `omeroweb` and `omeroserver` at the same absolute path value configured in `OMERO_TMP_PATH` (host path equals in-container path).

Each plugin automatically receives its own subfolder (detected from the Python package name at runtime via `omero_plugin_common.tmp_utils`). Plugins further subdivide into purpose-specific subdirectories (`data`, `jobs`, `compat-check`, etc.).

Example runtime layout:

```text
${OMERO_TMP_PATH}/
├── omeroweb-import/
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

`OMERO_TMP_PATH` is also used by `startup/10-server-bootstrap.sh` for OMERO CLI
bootstrap operations, but the bootstrap script uses a dedicated server-only
subpath `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp` as `TMPDIR`, `OMERO_TMPDIR`,
and `OMERO_TEMPDIR` to avoid collisions with plugin folders and permission
churn on the shared root. During
installation, `installation/installation_script.sh` pre-creates this namespace
and sets ownership to the OMERO.server runtime UID/GID with `0700` permissions
while preserving root traversal (`x`) so OMERO.web-owned temp roots remain
accessible for server namespace creation.

`OMERO_CLI_USER` controls the in-container service account used for OMERO CLI
startup jobs, installation group bootstrap, and the `omeroserver` healthcheck.
For manual in-container OMERO CLI diagnostics, do not use `su - omero-server`.
That login shell resets the OMERO temp environment before plugin discovery.
Use the same service-account handoff pattern as startup: `runuser -- env` with
explicit `HOME`, `TMPDIR`, `OMERO_TMPDIR`, and `OMERO_TEMPDIR`.

The bootstrap script also derives the OMERO internal lock-file temp path from the
OMERO.server installation root (`$(dirname "${SERVER_HOME}")/omero/tmp`) and
attempts to prepare it for OMERO lock-file compatibility. If this legacy path
cannot be created or is not writable, bootstrap logs a warning; the active
OMERO CLI temp variables remain the env-derived
`${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp/runtime*` namespace.

At image build time, `docker/omero-server.Dockerfile` now also enforces writable permissions on `${SERVER_HOME}/etc/grid` for the runtime `omero-server` account so `omero config set ...` can always persist updates to `config.xml` during bootstrap.

### Managed Repository Path Setting

In `env/omeroserver.env`, `CONFIG_omero_fs_repo_path` configures the managed
repository import parent-directory template.

`CONFIG_omero_managed_dir` must be an absolute path inside `${OMERO_DATA_DIR}`.
The tracked runtime contract is `/OMERO/ManagedRepository`, not the relative
string `ManagedRepository`. Relative values are unsafe because OMERO can resolve
them against the server install tree and create an image-local second
repository.

OMERO expands supported terms automatically when written with surrounding `%`
characters (for example: `%group%/%user%/%year%-%month%-%day%/%time%`).

At runtime, `startup/10-server-bootstrap.sh` now also normalizes the stable
shared managed-repository path prefixes that appear before `%user%` and before
any volatile date/time token (for example the group-level `users_ldap`
directory in `%group%/%user%/...`, or the literal `shared` prefix in
`shared/%user%/...`). The bootstrap builds that plan from deterministic
configured seeds only: `OMERO_INSTALL_GROUP_LIST` plus a static LDAP new-user
group when configured. It intentionally does not infer normalization targets
from arbitrary directories found under the managed repository, because that
filesystem can legitimately contain internal OMERO paths, stale test artifacts,
or historical content that should not block installation-time normalization of
the current deployment contract. It then creates any missing planned shared
prefix directories with
`omero fs mkdir --parents`, and non-destructively reassigns their OMERO
ownership metadata to `root` when an earlier uploader created them under a
personal account. The same repair now continues in the background on a
configurable interval (`OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS`, default 3600
seconds, with jitter from `OMERO_REPO_ROOT_SYNC_JITTER_SECONDS`) so prefixes
 that later become relevant through the configured group contract are
 normalized as well. Each cycle
writes its latest status to `${SERVER_VAR_DIR}/repo-root-sync.status`, and the
host installer waits for a successful current-cycle status before reporting
startup success whenever the repository template has at least one stable shared
prefix to normalize. With the default `%group%/%user%/...` template this work
is bounded to the shared group-level prefixes only; it does not scan per-user
trees, arbitrary repository directories, or payload files.

The pull/update helpers store full visible terminal transcripts under
`${OMERO_DATA_PATH}/installation_logs/`. The final transcript path is written
only after the installation paths are resolved, so changes to `OMERO_DATA_PATH`
during the run still place the log in the selected data root.

### OMERO.dropbox User Directories

`env/omeroserver.env` exposes the DropBox `omero.fs.*` properties used by the
installed OMERO server template as `CONFIG_omero_fs_*` entries. The env-name
mapping is the standard repo mapping: `.` becomes `_`, and a literal `_` in an
OMERO property becomes `__`. The upstream DropBox admin reference is
`https://omero.readthedocs.io/en/stable/sysadmins/dropbox.html`.
The server image installs the pinned `OMERO_DROPBOX_VERSION` package, and
`OMERO_DROPBOX_ENABLED=1` schedules an in-container bootstrap loop that waits
for the running OMERO admin interface and a real OMERO API login before
enabling and starting the required `MonitorServer` and `DropBox` Ice servers.
The image sets the DropBox IceGrid template activation to `manual` so DropBox
does not auto-start before Blitz accepts sessions; the bootstrap remains the
single place that starts DropBox. Recoverable readiness misses are recorded as
`status=retrying` and the loop keeps trying with
`OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS`; non-retryable
configuration errors are recorded as `status=error`. The readiness window per
attempt is controlled by `OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS`
(default 900 seconds), and the total retry budget is controlled by
`OMERO_DROPBOX_ICE_BOOTSTRAP_MAX_RETRY_SECONDS` (default 3600 seconds in new
installs). If repeated recoverable failures exhaust that budget, the loop
records `status=error` with a retry-budget message instead of waiting forever.
The latest result is written to `${SERVER_VAR_DIR}/dropbox-ice-bootstrap.status`.
During installation, a current `status=ok` confirms DropBox readiness,
`status=error` stops the install, and a transient wait timeout is reported
while the in-container loop continues within its configured retry budget.

The supported DropBox layout is the OMERO default convention:

```text
<DropBox root>/<omero username>/...
```

The acceptor root is auto-detected from live OMERO config. A single
`CONFIG_omero_fs_watchDir` value wins when set; otherwise OMERO uses
`CONFIG_omero_fs_defaultDropBoxDir` below `omero.data.dir`. Keep
`CONFIG_omero_fs_importUsers=default` for this username-directory convention.
The startup sync rejects multi-root `watchDir` values and non-default
`importUsers` values so it cannot silently switch to the advanced
semicolon-list layout.

`CONFIG_omero_fs_dirImportWait=600` is the tracked default so DropBox waits 10
minutes after a file event before starting import. This is deliberately longer
than upstream's 60-second default for large multi-file datasets.

`startup/10-server-bootstrap.sh` schedules one lightweight background loop in
the existing OMERO.server container when `OMERO_DROPBOX_USER_DIR_SYNC_ENABLED=1`.
The loop interval is controlled by
`OMERO_DROPBOX_USER_DIR_SYNC_INTERVAL_SECONDS` and the loop uses the same
lockdir/status-file pattern as the managed-repository prefix sync. It reads the
current OMERO experimenter list, creates missing first-level username
directories only, and does not walk or modify payload trees. The first cycle
uses `OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS` (default 900 seconds)
before marking OMERO API readiness as retryable; later cycles continue on the
configured interval. Its status file uses `status=retrying` for recoverable
readiness misses and `status=error` for non-retryable configuration or helper
failures.

Directory ownership and mode are controlled by
`OMERO_DROPBOX_USER_DIR_OWNER`, `OMERO_DROPBOX_USER_DIR_GROUP`, and
`OMERO_DROPBOX_USER_DIR_MODE`. Empty owner/group values inherit the resolved
DropBox root UID/GID, which keeps host-specific filesystem mappings out of the
repo. If the DropBox root must be created, the leaf directory inherits the
parent directory UID/GID and configured mode. The sync only calls `chown` or
`chmod` when a user directory differs from the configured state.

External acquisition or transfer hosts do not get a separate OMERO permission
layer. They must write through the host filesystem export or mount that backs
the same DropBox root visible inside the `omeroserver` container, and the OS
UID/GID/ACL mapping on that export decides whether they can create payload
files. For multiple external hosts, present the same DropBox root and the same
identity/ACL policy to every writer. Writers must target exactly
`<DropBox root>/<omero username>/...`; this deployment does not create or use a
`<group>/<user>` DropBox layout.

The Import plugin's OME-Zarr path handling uses the same managed repository.
It stages `.zarr` directories into `${CONFIG_omero_managed_dir}` through a
server-side OMERO script and renders the destination with
`CONFIG_omero_fs_repo_path`. `startup/10-server-bootstrap.sh` also writes
`${OMERO_TMP_PATH}` into `OMERO.server/var/managed-zarr-runtime.env` so the
server-side helper can validate staged sources without any hardcoded path
fallback. OMERO.web hands the server only a transient copy under
`${OMERO_TMP_PATH}/omeroweb-import/managed-zarr-transfer`; it does not relax
permissions on the original `_staged/` upload tree. If script processors are
slow to come up, helper launch retries are controlled by
`OMERO_WEB_UPLOAD_SCRIPT_START_TIMEOUT_SECONDS` and
`OMERO_WEB_UPLOAD_SCRIPT_START_RETRY_SECONDS`. No plugin-specific permanent-store
path is used.

`startup/10-server-bootstrap.sh` now fails closed when `CONFIG_omero_managed_dir`
is relative, points outside `${OMERO_DIR}`, or when an unexpected image-local
`ManagedRepository` already exists under `/opt/omero/server`. The background
shared-prefix sync and startup `omero admin cleanse` also refuse to run unless
runtime validation confirms OMERO still resolves the managed repository to the
expected absolute path and no second repository has appeared under the server
tree.

The native OME-Zarr parser/runtime baked into `omeroweb` is also environment
driven. `OMERO_DROPBOX_VERSION`, `OMERO_CLI_ZARR_VERSION`,
`OME_ZARR_PY_VERSION`, and `BIOFORMATS2RAW_VERSION` are defined in
`env/omeroserver.env` and are required for manual or installer-driven image
builds; there are no Compose or Dockerfile fallback defaults.
`OMERO_WEB_UPLOAD_NATIVE_ZARR_GZIP_LEVEL` controls the gzip
level used when the disposable managed-repository handoff copy must rewrite
Blosc-backed image arrays for render-safe native import. Those normalizations
apply only to the ephemeral handoff copy, never to the browser-staged source
tree.

Two feature flags control the alternative zarr import and rendering mechanisms:

| Variable                                   | Purpose                                                                                                                                                                                                                                              |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OMERO_WEB_UPLOAD_ALTERNATIVE_ZARR_IMPORT` | Enable the alternative native zarr import method for Bio-Formats-incompatible `.zarr` files (default `false`). When `false`, only the standard Bio-Formats import path is used and incompatible zarr files are skipped.                              |
| `OMERO_WEB_ZARR_ALTERNATIVE_RENDERING`     | Enable alternative zarr rendering overrides that patch OMERO's built-in rendering, preview, and pyramid handling for zarr images (default `false`). When `false`, OMERO's default built-in rendering pipeline applies without zarr-specific patches. |

> **Recommendation:** When disabling either alternative zarr flag after it has
> been active, set `OMERO_RENDERING_CACHE_CLEANUP_ON_START=1` in
> `env/omeroserver.env` for one restart cycle. This purges stale pyramid files,
> Bio-Formats memo cache entries, and thumbnails that were generated while the
> alternative mechanisms were active and may cause rendering errors or broken
> previews under the standard pipeline. OMERO regenerates all of these on
> demand, so no original imaging data is lost. Reset the flag to `0` after the
> cleanup restart.

After native import, OMERO.web access to the managed store is provided by
`omero_web_zarr`. The raw `/zarr/v0.4/image/<id>.zarr/...` routes expose the
underlying managed-repository store, while the preview
`/zarr/v0.4/preview/image/<id>.zarr/...` routes expose only viewer-safe
multiscale levels for browser viewing. This split is intentional and is derived
from store metadata rather than filename or directory heuristics.

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
Each reinstall replaces the repo-managed quota service, timer, and path units
from the active installation paths after removing stale unit files, drop-ins,
and target dependency links for those managed units.

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
- Forward Port: `CONFIG_omero_web_application__server_port`

The host-published troubleshooting port is `OMERO_WEB_HOST_PORT`; both values
default to `4090` in `env/omeroweb_example.env`.
