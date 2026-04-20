# Common Troubleshooting

## 1. Services not healthy after startup

Checks:

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env ps
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env logs --since=10m omeroserver
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env logs --since=10m omeroweb
```

Focus on:

- permission/write errors on mounted paths,
- DB connection failures,
- missing environment variables,
- startup script failures.

## 2. OMERO.web plugin routes unavailable

Checks:

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env exec omeroweb env | rg CONFIG_omero_web_apps
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env logs --since=10m omeroweb
```

Ensure the plugin app name exists in `CONFIG_omero_web_apps` and OMERO.web was restarted after config change.

## 3. Upload workflow stalls

Checks:

- write access to upload temp directory,
- job status endpoint response,
- import logs in OMERO.web and OMERO.server.

## 4. Admin tools show empty data

Checks:

- Loki/Prometheus/Grafana service health,
- endpoint URLs in `env/omeroweb.env`,
- plugin proxy/log-query timeout values.

## 5. Database performance degradation

Checks:

- pg-maintenance container logs,
- maintenance cron execution timestamps,
- index bloat and table growth trends in monitoring dashboards.

## 6. Docker health diagnostics reports socket permission error

Symptom in Resource Monitoring:

- `Docker socket exists but API call failed`
- current process UID/GIDs do not include the docker socket group

Fix (host shell, deterministic):

```bash
stat -c '%g' /var/run/docker.sock
id
# Then rerun your OMERO deployment/update script so it can auto-apply
# runtime socket permissions for omeroweb.
```

`docker-compose.yml` no longer requires manual `DOCKER_SOCKET_GID` injection.

## 7. `docker compose down` fails with a missing required variable

Symptom:

- compose exits with an interpolation error such as:
  - `required variable OMERO_USER_DATA_PATH is missing a value`
  - `required variable OMP_PLUGIN_DB_PASS is missing a value`
  - `Set OMERO_USER_DATA_PATH (use --env-file installation_paths.env)`
  - `Set OMP_PLUGIN_DB_PASS in env/omero_secrets.env`

Cause:

- one or more required env files were not loaded (`installation_paths.env` for
  paths, `env/omero_secrets.env` for credentials, `env/omeroserver.env` for
  compose-interpolated server/build variables).

Fix:

Security rationale:

- Do **not** bind host `/dev/disk` into cAdvisor unless you explicitly require device symlink metadata.
- Use the standard compose `tmpfs:` key to override `/dev/disk`, which blocks anonymous volume creation without exposing host block-device topology.

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env down
```

If you run compose commands manually, always include all three env files for
`build`, `up`, `down`, `ps`, `logs`, and `exec`.

If you installed with `installation/installation_script.sh`, generated `.env` already sets
`COMPOSE_ENV_FILES=installation_paths.env:env/omero_secrets.env:env/omeroserver.env`
and mirrors `OMERO_DATA_DIR`, `OMERO_DB_PASS`, and `OMP_PLUGIN_DB_PASS`
(mode `0600`), so plain `docker compose <command>` works from the installation
root.

If you run the installer with `sudo`, the script now assigns `.env` ownership to
the invoking sudo user (from `SUDO_UID:SUDO_GID`) while keeping mode `0600`, so
non-root compose commands from that same account continue to work.

## 8. `docker compose down` fails with `.env: permission denied`

Symptom:

- `open /opt/omero/.env: permission denied`

Cause:

- `.env` is present but owned by `root` from a previous installer run.

Fix:

```bash
sudo chown "$(id -u):$(id -g)" .env
chmod 600 .env
```

Then rerun `installation/installation_script.sh` once so future runs keep `.env`
owned by the invoking user automatically.

## 9. Anonymous Docker volume appears after monitoring stack startup

Symptom:

- `docker volume ls` shows a random hash-like volume name.
- `docker volume inspect <name>` includes `"com.docker.volume.anonymous"`.

Cause:

- cAdvisor may trigger an anonymous volume when its image-defined `/dev/disk` mount is not explicitly overridden.
- Historically, the installer also created short-lived probe containers using `docker create` against images that declare `VOLUME`; removing those probe containers without `docker rm -v` could leave anonymous volumes behind.

Fix:

Security rationale:

- Do **not** bind host `/dev/disk` into cAdvisor unless you explicitly require device symlink metadata.
- Use the standard compose `tmpfs:` key to override `/dev/disk`, which blocks anonymous volume creation without exposing host block-device topology.

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env down
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env up -d

docker volume ls
# If a leftover anonymous volume still exists and is unused:
docker volume rm <anonymous-volume-name>
```

Expected compose/runtime configuration:

- `cadvisor` uses the standard compose `tmpfs:` section: `/dev/disk:ro,noexec,nosuid,nodev,size=1m,mode=0555`.
- Installer probe-container cleanup uses `docker rm -fv` so anonymous probe volumes are deleted together with probe containers.

## 10. cAdvisor exits immediately and prints command-line help

Symptom:

- `cadvisor` restarts repeatedly.
- Logs show the full command-line flag help output instead of normal startup messages.

Root cause:

- cAdvisor v0.56.2 in this stack does not accept `--rootfs=/rootfs` as a startup flag.
- Passing an unsupported flag makes cAdvisor exit after printing usage/help.

Fix in this distribution:

- `cadvisor` now runs with its default command (no unsupported custom flags).
- Host filesystem visibility is still provided by the existing read-only root bind mount `/:/rootfs:ro`.

Check/verify commands:

```bash
# 1) Recreate only cAdvisor with current compose config
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env up -d cadvisor

# 2) Confirm startup no longer prints usage/help
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env logs --since=2m cadvisor | rg -n 'Starting cAdvisor version|Usage of|flag provided but not defined'

# 3) Confirm metrics endpoint is reachable inside the container network
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env exec -T cadvisor wget --no-verbose --tries=1 --spider http://localhost:8080/metrics
```

Expected result:

- Logs show normal startup (for example `Starting cAdvisor version ...`) and no unsupported-flag usage output.
- Healthcheck remains healthy and Prometheus can scrape `http://cadvisor:8080/metrics`.

## 11. Postgres keeps rejecting `omero` after startup

Symptom:

- `database` logs repeatedly show:
  - `FATAL: password authentication failed for user "omero"`
  - `Connection matched ... pg_hba.conf ... scram-sha-256`

Cause:

- `database` initialization uses `OMERO_DB_PASS` from `env/omero_secrets.env`.
- OMERO.server expects the variable name `CONFIG_omero_db_pass`.
- If `CONFIG_omero_db_pass` is not explicitly mapped from `OMERO_DB_PASS`, OMERO.server can continuously retry with the wrong credential and generate auth-failure loops.

Fix:

- Ensure compose maps `CONFIG_omero_db_pass` from `OMERO_DB_PASS` for the `omeroserver` service.
- Restart and inspect logs:

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env up -d database omeroserver omeroweb
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env logs --since=5m database omeroserver
```

Expected result:

- `database` no longer logs repeated auth failures for user `omero`.

## 12. LDAP users are placed into `default` group instead of `users_ldap`

Symptom:

- After first LDAP login, OMERO shows a `default` group (if not previously present).
- LDAP-created users have only `default` as selectable group in OMERO.web admin UI.

Cause:

- OMERO LDAP and OMERO non-LDAP groups are not separate systems.
- When LDAP is enabled and `omero.ldap.new_user_group` is not explicitly set, OMERO uses the built-in default `default` value and creates/uses that group for new LDAP users.

Fix:

1. Set a deterministic LDAP group mapping in `env/omeroserver.env` (runtime file, not the example), for example:

   ```bash
   CONFIG_omero_ldap_config=true
   CONFIG_omero_ldap_new__user__group=users_ldap
   ```

2. Restart OMERO.server and OMERO.web to apply LDAP config.
3. Confirm persisted server value is correct (command below).
4. For existing LDAP users already in `default`, move/add memberships as needed using OMERO admin UI or OMERO CLI (`omero group adduser --user-name <ldap_user> --name users_ldap`).

Validation:

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config get omero.ldap.new_user_group
```

Expected result:

- Output is your configured target (for example `users_ldap`) or a deliberate dynamic expression (for example `:dn_attribute:memberOf`), not implicit `default`.
- If output is still `default` and this is intentional, startup will continue (no failure) and explicit LDAP group bootstrap is skipped.
- If output is still `default` but you expect another group, inspect OMERO.server bootstrap logs for LDAP config apply/validation failures.

## 13. OMERO.web fails with `PermissionError` under `/opt/omero/web/OMERO.web/var/omero`

Symptom:

- `omeroweb` logs show:
  - `PermissionError: [Errno 13] Permission denied: '/opt/omero/web/OMERO.web/var/omero'`
  - `Invalid tmp dir: /opt/omero/web/OMERO.web/var/omero/tmp`
  - `Please create a /opt/omero/web/OMERO.web/var/django_secret_key file`

Cause:

- Host bind mount for `OMERO_WEB_VAR_PATH` exists but ownership/permissions do not match the runtime `omero-web` user.
- OMERO.web cannot create runtime temp directories or write `django_secret_key`.

Fix:

```bash
bash installation/installation_script.sh

docker compose up -d --build omeroweb
```

Expected behavior after this fix:

- Installer assigns `OMERO_WEB_VAR_PATH` ownership to OMERO.web UID/GID.
- `startup/10-web-bootstrap.sh` repairs missing `var/omero/tmp`, enforces writable permissions, and auto-generates `var/django_secret_key` when missing.

## 14. Uploads fail for some LDAP users with `No annotate access for parent directory`

Symptom:

- `OMEROweb.log` shows upload imports failing immediately with lines similar to:
  - `Current group: users_ldap`
  - `No annotate access for parent directory: 227`
- `Blitz-0.log` shows the server failing in `RepositoryDaoImpl.makeDirs` while creating a path such as `users_ldap/<username>`.
- The same Import plugin can still work for non-LDAP users or for one specific LDAP user.

Verified diagnosis pattern:

- The upload reaches OMERO successfully and joins the LDAP user's session.
- The target Dataset is writable by the LDAP user.
- The failure happens earlier, while OMERO tries to create the managed-repository directory tree for the import.
- In the confirmed failing case on March 11, 2026:
  - the top-level repository directory object for `users_ldap` was `OriginalFile:227`
  - that object was owned by `j.mateos`
  - the failing uploader was `e.mitridis`
- In the working comparison, the top-level directory object for the working private group was owned by the same user who was importing.

Cause:

- The failure is not LDAP authentication.
- It is a managed-repository ownership mismatch on the already-created top-level group directory object.
- With a template such as `%group%/%user%/%year%-%month%-%day%/%time%`, OMERO must create `<group>/<user>/...`.
- If the existing top-level `<group>` directory object is owned by another user and OMERO refuses writes beneath it, later users in that group can fail before any image import occurs.

Validation:

```bash
rg -n "No annotate access for parent directory|Current group:" /disks/omero_data/omero_web_logs/OMEROweb.log

rg -n "RepositoryDaoImpl.makeDirs|No annotate access for parent directory" /disks/omero_data/omero_server_logs/Blitz-0.log
```

Expected result:

- `OMEROweb.log` shows the user's group and the parent-directory denial.
- `Blitz-0.log` shows the failure while creating the managed-repository path, not while authenticating or writing metadata to the Dataset.

Next step:

- Deploy the current repository patch and restart `omeroserver`.
- Ensure `CONFIG_omero_managed_dir` is the absolute bind-mounted path `/OMERO/ManagedRepository`, not the relative string `ManagedRepository`.
- `startup/10-server-bootstrap.sh` now auto-normalizes the stable shared managed-repository prefixes before `%user%` by building a deterministic plan from configured install/LDAP groups only, creating any missing planned shared prefix directories, and reassigning their OMERO ownership metadata to `root`.
- Keep `OMERO_INSTALL_GROUP_LIST` aligned with every non-default group prefix that should be normalized when `CONFIG_omero_fs_repo_path` contains `%group%`. The runtime no longer infers normalization targets from arbitrary directories found under the managed repository.
- The same bootstrap now fails closed if OMERO is configured with a relative managed-repository path or if a second image-local `ManagedRepository` exists under `/opt/omero/server`.
- The repair is non-destructive: it does not change the configured repository template and does not delete repository payload files.
- The repair is no longer one-shot. A background sync loop continues running on `OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS` and writes its latest result to `${OMERO_SERVER_VAR_PATH}/repo-root-sync.status`.
- `installation/installation_script.sh` now waits for a successful current-cycle `repo-root-sync.status` before it reports startup success whenever the path template has a stable shared prefix to normalize, so new installs and updates do not finish before the active shared prefixes are normalized.

Validation:

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env exec omeroserver \
  cat /opt/omero/server/OMERO.server/var/repo-root-sync.status

docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env logs --since=10m omeroserver \
  | rg 'repo-root-bootstrap|normalized_prefix_count|failed_prefix_count'
```

Expected result:

- `repo-root-sync.status` reports `status=ok` with a recent `last_success_epoch`.
- The server logs show the shared-prefix normalization cycle completing without failures for the active/configured prefixes that matter to the deployment.

## 14a. Large grouped uploads fail with `OMERO could not prepare the destination for this import.`

Symptom:

- A grouped upload (for example a large `.zarr` tree or another directory-backed import) finishes transferring all bytes.
- The job can spend time in `checking` even when browser-side compatibility checking was disabled.
- The final job error is the generic message:
  - `OMERO could not prepare the destination for this import.`

Cause:

- The Import plugin always lets OMERO CLI/Bio-Formats build the logical import plan before import starts, even when browser-side compatibility checking is disabled.
- Compatibility-disabled jobs use that background step for planning only: it persists `planned_import_units`, but it does not run the first-batch compatibility scan.
- Older broken builds tried to recover by switching background dataset preparation onto a `job-service` impersonation path. On stacks where `job-service` could not impersonate the importing user, that path collapsed into the generic destination-preparation error.
- Fixed builds use an independent admin-created user session for background dataset preparation, so they do not need the browser session and do not reintroduce the historical logout/disconnect problem.

Validation:

```bash
rg -n "planning import units before request-path dataset preparation|cannot reuse the live OMERO.web session|could not open an independent user session|could not switch to OMERO user" \
  /disks/omero_data/omero_web_logs/OMEROweb.log
```

Expected result:

- Healthy behavior:
  - the logs show the planning/import-unit message first
  - either a later browser poll/import-step request prepares datasets on the request path, or the import thread prepares them through an independent background user session
  - the import thread starts without any `job-service` impersonation warning
- Failing behavior:
  - the logs show `Service connection could not switch to OMERO user ... for dataset preparation on job ...` or `Background dataset preparation for job ... cannot reuse the live OMERO.web session.`
  - those messages indicate an older broken session-ownership path and should disappear after the import-plugin rewrite is deployed.

## 15. `omeroserver` restart loop with `ERROR: OMERO_TMP_PATH is required for server bootstrap temp files but is not set.`

Symptom:

- `docker compose up` reports `omeroserver` as unhealthy/restarting.
- `docker compose logs omeroserver` repeatedly shows:
  - `ERROR: OMERO_TMP_PATH is required for server bootstrap temp files but is not set.`

Cause:

- `OMERO_TMP_PATH` is not present in the container environment.
- `startup/10-server-bootstrap.sh` fails fast because it requires `OMERO_TMP_PATH` to create and validate the server bootstrap `TMPDIR` namespace.

Fix:

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env config | rg '^\s+OMERO_TMP_PATH:' -n

# if missing in config output, ensure compose service env wiring and restart
bash installation/installation_script.sh
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env up -d --build omeroserver omeroweb
```

Expected result:

- `omeroserver` healthcheck passes and the service stays `healthy`.
- Bootstrap logs proceed past temp-dir validation without `OMERO_TMP_PATH` errors.

## 16. `omeroserver` logs `WARNING: Legacy OMERO temp directory is not writable` during bootstrap

Symptom:

- `docker compose logs omeroserver` shows:
  - `WARNING: Legacy OMERO temp directory is not writable: /opt/omero/server/omero/tmp`

Cause:

- A pre-existing path under `/opt/omero/server/omero/tmp` is owned by another user/group and is not writable by the OMERO bootstrap user.
- `startup/10-server-bootstrap.sh` treats this legacy lock-file path as
  best-effort compatibility. The active OMERO CLI temp variables remain the
  env-derived `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp/runtime*` namespace.
- Reinstall/update runs before the ownership fix could also recursively reassign stale `${OMERO_TMP_PATH}/omero-server/tmp/omero_omero-server/...` lock trees to the OMERO.web UID because the installer normalized the entire `OMERO_TMP_PATH` recursively before restoring only the top-level server namespace.

Fix (optional hardening):

```bash
# inspect ownership/mode inside the container
docker compose exec omeroserver ls -ld /opt/omero/server/omero/tmp

# fix ownership/permissions on the host path mounted at /opt/omero/server
# so the legacy path is writable and warning-free on startup

docker compose --env-file installation_paths.env --env-file env/omero_secrets.env --env-file env/omeroserver.env up -d --build omeroserver
```

Expected result:

- Bootstrap continues successfully using the env-derived
  `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp/runtime*` namespace as the active
  OMERO CLI temp directory.
- If ownership/permissions are corrected, the legacy warning disappears.
- Current installer/bootstrap logic also reclaims stale `${OMERO_TMP_PATH}/omero-server/tmp/omero_omero-server` lock namespaces so repeated `github_pull...` reinstall runs do not reintroduce `PermissionError` on `.lock` files.

## 16a. Native Zarr import fails with `PermissionError` on `/OMERO/ManagedRepository/.../*.zarr`

Symptom:

- `omero zarr import` returns a traceback ending with:
  - `PermissionError: [Errno 13] Permission denied: '/OMERO/ManagedRepository/.../sample.zarr'`
- The import plugin reports a generic or path-permission failure immediately after the managed-repository staging step.

Cause:

- The server-side native-Zarr stage copied the `.zarr` tree into the managed repository, but the path was normalized too tightly for the separate `omero-web` Unix account.
- OMERO.web only needs to traverse the rendered repository-template path and read the staged `.zarr` tree; it does not need write access to the managed repository.

Fix:

1. Update to the current `Manage_Zarr_ManagedRepository.py` contract.
2. Verify the staged managed path uses:
   - `0711` on the rendered repository-template path
   - `0755` on the staged `.zarr` directories
   - `0644` on staged files
3. Rebuild the affected `omeroserver` and `omeroweb` images, then recreate those containers.

Expected result:

- `omero zarr import` can open the staged managed path without widening write access.
- The import succeeds or fails for a real data reason instead of a filesystem traversal error.

## 16b. Native Zarr import fails with `Directory exists but is not registered`

Symptom:

- `omero zarr import` returns a traceback ending with:
  - `omero.ResourceError: InternalException: Directory exists but is not registered: CheckedPath(...)`
- The failing `CheckedPath(...)` points at a rendered managed-repository template path under
  `/OMERO/ManagedRepository/...`, not at the browser `_staged/` upload tree.

Cause:

- Some part of the native-Zarr staging path under `ManagedRepository` was
  created with raw filesystem operations instead of OMERO's managed-repository
  API.
- OMERO only accepts managed paths whose created directories were registered
  through the repository service; a plain `mkdir` leaves the directory on disk
  but outside OMERO's repository metadata.

Fix:

1. Update to the current `Manage_Zarr_ManagedRepository.py` contract.
2. Keep upload and conversion work in tmp/shared-transfer space; use the
   managed repository only for the final persistent native-Zarr handoff.
3. Ensure the helper creates or deletes only the rendered template container
   path plus the staged native-Zarr leaf through OMERO's repository API, not
   with manual `mkdir` or
   `rmtree`.
4. If the helper now reports that a rendered managed path exists on disk but is not
   registered in OMERO, treat that as stale residue from an older helper
   revision that created managed-repository paths with raw filesystem
   operations. Do not create new files there manually; clean or rotate that
   contaminated path through an operator-controlled maintenance procedure
   before retrying native Zarr staging.
5. Rebuild the affected `omeroserver` and `omeroweb` images, then recreate
   those containers.

Expected result:

- Native Zarr staging produces a managed path that OMERO accepts as registered.
- `omero zarr import` proceeds past the managed-path lookup instead of failing
  before object creation.

## 17. Host-side `pytest` fails with `ModuleNotFoundError: No module named 'django'`

Symptom:

- `python3 -m pytest ...` fails immediately while loading `/opt/omero/conftest.py`.
- The traceback includes:
  - `ImportError while loading conftest '/opt/omero/conftest.py'`
  - `ModuleNotFoundError: No module named 'django'`

Cause:

- The host interpreter does not include the OMERO.web test/runtime dependencies.
- Repository-level `conftest.py` imports Django during collection, so repeating the same host-side `pytest` command will keep failing until you switch environments.

Fix:

1. Prefer the OMERO.web runtime interpreter for full pytest runs.
2. If a test module is intentionally self-contained, run it directly with `python3 <path-to-test>.py` so it bypasses repository `conftest.py`.
3. For in-container pytest, unset deprecated `OMERO_TEMPDIR` and set `OMERO_TMPDIR` plus `TMPDIR` to a writable temp path before collecting tests.

Example full-runtime pattern:

```bash
docker exec -i omero-omeroweb-1 bash -lc '
  unset OMERO_TEMPDIR
  export OMERO_TMPDIR=/tmp/omero-web-pytest
  export TMPDIR=/tmp/omero-web-pytest
  mkdir -p "$OMERO_TMPDIR"
  chown omero-web:omero-web "$OMERO_TMPDIR"
  su omero-web -s /bin/bash -c "
    cd /opt/omero &&
    /opt/omero/web/venv-3.12/bin/python3 -m pytest omeroweb_import/tests/ -v -p no:cacheprovider -W error
  "
'
```

Expected result:

- Pytest collects with the runtime environment that already has Django installed.
- If you still need a quick targeted regression check outside that environment, direct-module execution remains valid for self-contained tests only.
