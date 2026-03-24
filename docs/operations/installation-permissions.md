# Installation Permissions

Authoritative map of ownership, mode bits, and writable-path assumptions during install, update, and bootstrap.

Use this document when investigating:
- permission-denied startup failures,
- ownership drift after `github_pull_project_bash`,
- missing writable directories,
- Docker socket access problems,
- quota metadata write failures,
- monitoring/database bind-mount ownership issues.

## 1. Authority and Flow

The permission model is enforced in layers:

1. `installation/installation_script.sh`
   This is the primary host-side ownership normalizer for bind-mounted paths from `installation_paths.env`.
2. `startup/*.sh`
   These scripts repair runtime-critical writable paths inside containers on every boot.
3. `docker/*.Dockerfile`
   Image builds establish ownership and executable bits for image-internal paths, but not host bind mounts.
4. `github_pull*_example` and runtime pull helpers
   These preserve runtime files and invoke the installation script. They do not own the final host permission model themselves.

The high-risk shared area is `OMERO_TMP_PATH` because both `omeroserver` and `omeroweb` use it. Its correctness depends on subtree-specific ownership, not a single recursive `chown` across the full root.

## 2. Path Model

### `OMERO_TMP_PATH`

Intent:
- temp root is traversable by both OMERO.web and OMERO.server,
- OMERO.web/plugin subtrees are owned by `omero-web`,
- `${OMERO_TMP_PATH}/omero-server` is owned recursively by `omero-server`.

Host-side installer:
- `installation/installation_script.sh`
  - `ensure_omero_tmp_layout()`
  - creates the temp root,
  - sets the temp root owner to `OMERO_WEB_UID:GID`,
  - keeps the root traversable with `u+rwx,go+rx`,
  - recursively re-owns top-level non-server temp subtrees to `OMERO_WEB_UID:GID`,
  - recursively restores `${OMERO_TMP_PATH}/omero-server` to `OMERO_SERVER_UID:GID`,
  - sets `${OMERO_TMP_PATH}/omero-server` and `${OMERO_TMP_PATH}/omero-server/tmp` to `0700`.

Server bootstrap:
- `startup/10-server-bootstrap.sh`
  - creates `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp`,
  - sets it writable for runtime use,
  - prepares `runtime*` temp slots,
  - removes stale legacy `omero_${requested_owner}` lock namespaces directly under `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp`,
  - repairs `.lock` ownership in-place if cleanup cannot fully remove stale state,
  - symlinks legacy `/opt/omero/server/omero/tmp` to the selected runtime slot.

Web bootstrap:
- `startup/10-web-bootstrap.sh`
  - manages OMERO.web `var/omero/tmp`,
  - not the shared `${OMERO_TMP_PATH}/omero-server` namespace.

Operational risk:
- repeated reinstall/update flows can corrupt OMERO.server temp ownership if the installer recursively normalizes the whole temp root to the OMERO.web UID.
- stale `omero_omero-server/.../.lock` trees can trigger `PermissionError` on restart if ownership is wrong.

### `OMERO_USER_DATA_PATH`

Intent:
- primary OMERO managed repository and server certs are owned by `omero-server`.

Host-side installer:
- `installation/installation_script.sh`
  - `chown_tree_or_die "${OMERO_USER_DATA_PATH}" ... "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"`
  - explicitly normalizes `${OMERO_USER_DATA_PATH}/certs` to the same owner.

Quota helper:
- `scripts/install-quota-enforcer.sh`
  - creates `${OMERO_DATA_DIR}/.admin-tools/quota`,
  - sets `.admin-tools` and `.admin-tools/quota` to `0777`,
  - sets `group-quotas.json` to `0666` so host root and non-root `omeroweb` can both update quota state.

Managed-repository shared-prefix bridge:
- `startup/10-server-bootstrap.sh`
  - derives the managed-repository path prefixes that appear before `%user%`,
  - seeds its group list from both live OMERO group discovery and `OMERO_INSTALL_GROUP_LIST`,
  - creates missing shared prefixes with `omero fs mkdir --parents`,
  - reassigns those shared prefix directory objects to `root`,
  - repeats the same repair in the background on
    `OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS`,
  - writes the latest cycle status to
    `${OMERO_SERVER_VAR_PATH}/repo-root-sync.status`.

Managed-repository Zarr staging:
- `omeroweb_import/omero_scripts/Manage_Zarr_ManagedRepository.py`
  - runs on OMERO.server, not in the OMERO.web request process,
  - stages `.zarr` directories only inside
    `${OMERO_DATA_DIR}/${CONFIG_omero_managed_dir}`,
  - reads the managed-repository root and repository template from persisted
    OMERO config (`omero.data.dir`, `omero.managed.dir`,
    `omero.fs.repo.path`) and reads the env-derived shared tmp root from the
    bootstrap-written runtime state file
    `OMERO.server/var/managed-zarr-runtime.env` rather than relying on
    hardcoded paths,
  - requires the `%user%` prefix from `CONFIG_omero_fs_repo_path` to already
    exist, so the web plugin does not create group/user repository roots with
    the wrong owner,
  - creates only the suffix directories after `%user%` and normalizes the
    copied tree to repository-safe `0755` directories and `0644` files.

Installer readiness gate:
- `installation/installation_script.sh`
  - waits for a successful current-cycle
    `${OMERO_SERVER_VAR_PATH}/repo-root-sync.status`
    before reporting startup success when the repository template contains `%group%`.

### `OMERO_SERVER_VAR_PATH`

Intent:
- owned by `omero-server`.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns to `OMERO_SERVER_UID:GID`.
  - also creates `${OMERO_SERVER_VAR_PATH}/tmp`, sets it to server-owned `1777`.

Image build:
- `docker/omero-server.Dockerfile`
  - ensures `/opt/omero/server/OMERO.server/var` is owned by `omero-server`.

### `OMERO_SERVER_LOGS_PATH`

Intent:
- owned by `omero-server`.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns to `OMERO_SERVER_UID:GID`.

### `OMERO_WEB_VAR_PATH`

Intent:
- owned by `omero-web`.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns to `OMERO_WEB_UID:GID`.

Web bootstrap:
- `startup/10-web-bootstrap.sh`
  - creates/repairs web runtime directories,
  - recursively `chown -R` the web var tree to `omero-web`,
  - sets `var` and `var/omero` to `0755`,
  - sets `var/omero/tmp` to `1777`,
  - generates `django_secret_key` with `0600`,
  - preserves a real `branding/logo.png` across static sync,
  - restores a site-local `logo/logo.png` from the image when present,
  - only generates a fallback `branding/logo.png` when the login-logo env
    explicitly targets `/static/branding/logo.png` and no real logo is available.

### `OMERO_WEB_LOGS_PATH` and `OMERO_WEB_SUPERVISOR_LOGS_PATH`

Intent:
- owned by `omero-web`.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns both paths to `OMERO_WEB_UID:GID`.

Image build:
- `docker/omero-web.Dockerfile`
  - ensures `/opt/omero/web/logs` is owned by `omero-web`.

Web bootstrap:
- `startup/10-web-bootstrap.sh`
  - revalidates both mounted log trees after container start,
  - repairs stale file ownership in existing log files,
  - parses `supervisord.conf` and prepares every declared `logfile`, `stdout_logfile`, and `stderr_logfile` target for the runtime user before supervisord drops privileges.

### Upload / plugin temp subtrees

Intent:
- plugin temp folders under `OMERO_TMP_PATH` are owned by `omero-web`.
- the original staged upload tree remains private to `omero-web`,
- any server-readable bridge for Zarr staging must be a separate transient copy,
  not a permission broadening of the main upload tree.

Code path:
- `omero_plugin_common/tmp_utils.py`
  - all plugin temp directories derive from `OMERO_TMP_PATH`.
  - calling packages such as `omeroweb_import` map to host subtrees like `omeroweb-import`.

Installer expectation:
- non-server top-level temp/plugin subtrees are normalized to the web UID/GID by `ensure_omero_tmp_layout()`.

Import-plugin Zarr bridge:
- `omeroweb_import/views/core_functions.py`
  - creates `${OMERO_TMP_PATH}/omeroweb-import/managed-zarr-transfer` as a
    traversal-only handoff root for OMERO.server,
  - creates each per-transfer parent directory with `0711`,
  - normalizes copied Zarr directories to `0755` and files to `0644`,
  - removes the transfer subtree immediately after the server-side staging step,
  - leaves `${OMERO_TMP_PATH}/omeroweb-import/data` and the original `_staged/`
    upload tree under OMERO.web ownership.

### Database paths

Paths:
- `OMERO_DATABASE_PATH`
- `OMERO_PLUGIN_DATABASE_PATH`

Intent:
- owned by the Postgres runtime user inside the corresponding image.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns both paths to auto-detected database image UIDs/GIDs.

### Monitoring data paths

Paths include:
- Prometheus data,
- Grafana data,
- Loki data,
- node-exporter/path-usage textfile output.

Intent:
- owned by the runtime users inside the monitoring images.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns these paths using detected image UIDs/GIDs such as `PROMETHEUS_UID`, `GRAFANA_UID`, and `LOKI_UID`.

### Installation transcript path

Path:
- `${OMERO_DATA_PATH}/installation_logs`

Intent:
- root-owned archive of the exact visible terminal session from
  `github_pull_project_bash`
  and `installation/installation_script.sh`.

Host-side installer / pull helpers:
- `installation/install_transcript_utils.sh`
  - starts transcript capture before clone/update output begins,
  - finalizes the destination only after `installation_paths.env` resolves
    `OMERO_DATA_PATH`,
  - creates `${OMERO_DATA_PATH}/installation_logs` with mode `0700`,
  - writes transcript files with mode `0600`.

### CrowdSec paths

Paths:
- `CROWDSEC_DB_PATH`
- `CROWDSEC_CONFIG_PATH`

Intent:
- owned by the CrowdSec runtime user when CrowdSec is enabled.

Host-side installer:
- `installation/installation_script.sh`
  - recursively re-owns both paths to `CROWDSEC_UID:GID`.

## 3. Special Runtime Permission Bridges

### Docker socket access from `omeroweb`

Script:
- `startup/10-web-bootstrap.sh`

Behavior:
- reads the GID of `/var/run/docker.sock`,
- creates a matching group if needed,
- adds `omero-web` to that group.

Purpose:
- allows Admin Tools to inspect containers and collect Docker-backed metrics without running OMERO.web as root.

### Quota metadata interoperability

Scripts:
- `scripts/install-quota-enforcer.sh`
- `startup/10-web-bootstrap.sh`

Behavior:
- quota state directories may be intentionally `0777`,
- quota state files may fall back to `0664` or `0666`,
- this is deliberate to support both host-side root automation and non-root web-side updates.

This is one of the few intentionally broad write-permission exceptions in the stack.

## 4. Pull / Update Scripts

### `github_pull_project_bash_example`

Behavior:
- preserve runtime files and data paths derived from `installation_paths.env`,
- protect `installation_paths.env` and runtime env files from overwrite,
- create/update a temporary clone,
- execute the installation script afterward,
- save the exact visible terminal session to
  `${OMERO_DATA_PATH}/installation_logs/<script>_<UTC timestamp>.log`
  when the run ends.

Important:
- these scripts do not directly normalize host bind-mount ownership.
- the real permission authority remains `installation/installation_script.sh`.

The private variant also:
- creates `~/.ssh` with `0700`,
- creates `known_hosts` with `0600`,
- configures `GIT_SSH_COMMAND`.

## 5. Image-Build Ownership Work

Relevant Dockerfiles:
- `docker/omero-server.Dockerfile`
- `docker/omero-web.Dockerfile`
- `docker/omero-celery-worker.Dockerfile`
- `docker/pg-maintenance.Dockerfile`
- `docker/crowdsec.Dockerfile`
- `docker/firewall-bouncer.Dockerfile`

These Dockerfiles mostly:
- `chown` image-internal runtime directories to their service user,
- set scripts to executable (`0555` or `0755`),
- set static files such as branding assets to fixed read-only modes.

They do not replace host-side bind-mount normalization.

## 6. Failure Patterns

### Symptom: `PermissionError` on `.lock` under `${OMERO_TMP_PATH}/omero-server/tmp/omero_omero-server/...`

Likely cause:
- stale server temp state under `OMERO_TMP_PATH` is owned by the wrong UID,
- often after repeated reinstall/update cycles that normalized the full temp root incorrectly,
- or after incomplete stale-temp cleanup before server restart.

Relevant files:
- `installation/installation_script.sh`
- `startup/10-server-bootstrap.sh`
- `docs/troubleshooting/common.md`

### Symptom: Admin Tools cannot inspect Docker

Likely cause:
- `omero-web` is not in the Docker socket group matching `/var/run/docker.sock`.

Relevant file:
- `startup/10-web-bootstrap.sh`

### Symptom: quota metadata writes fail intermittently

Likely cause:
- host-side and web-side writers do not agree on `.admin-tools/quota` ownership/modes.

Relevant files:
- `scripts/install-quota-enforcer.sh`
- `startup/10-web-bootstrap.sh`

### Symptom: uploads fail with `No annotate access for parent directory`

Likely cause:
- the shared managed-repository prefix for a group (for example `users_private`)
  already exists in OMERO metadata but is still owned by a different user.
- the recurring repo-root sync has not run successfully yet, or an older
  deployment still has one-shot bootstrap behavior.

Relevant files:
- `startup/10-server-bootstrap.sh`
- `installation/installation_script.sh`
- `${OMERO_SERVER_VAR_PATH}/repo-root-sync.status`

## 7. Audit Checklist

When debugging permission faults, check in this order:

1. Confirm the affected path comes from `installation_paths.env`.
2. Identify the intended runtime user for the owning service.
3. Check whether the path is host bind-mounted or image-internal.
4. Check whether ownership should be normalized by the installer or repaired by a startup script.
5. For `OMERO_TMP_PATH`, inspect subtree ownership separately:
   - root,
   - `omero-server`,
   - `omero-web`,
   - plugin temp subtrees such as `omeroweb-import`,
   - any stale `omero_<user>` lock namespaces.
6. If the fault appeared after `github_pull...`, review the installation script path normalization logic first.
7. For managed-repository import failures, inspect
   `${OMERO_SERVER_VAR_PATH}/repo-root-sync.status` before assuming the latest
   startup actually normalized the shared prefix.
8. Re-check logs through the Admin Tools/Loki path after repair, not only raw container logs.

## 8. Related Documents

- `deployment/configuration.md`
- `RELIABILITY.md`
- `troubleshooting/common.md`
- `operations/monitoring.md`
- `plugins/admin-tools-plugin.md`
