# Common Troubleshooting

## 1. Services not healthy after startup

Checks:

```bash
docker compose --env-file installation_paths.env ps
docker compose --env-file installation_paths.env logs --since=10m omeroserver
docker compose --env-file installation_paths.env logs --since=10m omeroweb
```

Focus on:

- permission/write errors on mounted paths,
- DB connection failures,
- missing environment variables,
- startup script failures.

## 2. OMERO.web plugin routes unavailable

Checks:

```bash
docker compose --env-file installation_paths.env exec omeroweb env | rg CONFIG_omero_web_apps
docker compose --env-file installation_paths.env logs --since=10m omeroweb
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

- one or both env files were not loaded (`installation_paths.env` for paths, `env/omero_secrets.env` for credentials).

Fix:

Security rationale:

- Do **not** bind host `/dev/disk` into cAdvisor unless you explicitly require device symlink metadata.
- Use the standard compose `tmpfs:` key to override `/dev/disk`, which blocks anonymous volume creation without exposing host block-device topology.

```bash
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env down
```

If you run compose commands manually, always include the same `--env-file` value for
`build`, `up`, `down`, `ps`, and `logs`.

If you installed with `installation/installation_script.sh`, generated `.env` already sets
`COMPOSE_ENV_FILES=installation_paths.env:env/omero_secrets.env` and mirrors
`OMERO_DB_PASS` plus `OMP_PLUGIN_DB_PASS` (mode `0600`), so plain
`docker compose <command>` works from the installation root.

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

Fix:

Security rationale:

- Do **not** bind host `/dev/disk` into cAdvisor unless you explicitly require device symlink metadata.
- Use the standard compose `tmpfs:` key to override `/dev/disk`, which blocks anonymous volume creation without exposing host block-device topology.

```bash
docker compose --env-file installation_paths.env down
docker compose --env-file installation_paths.env up -d

docker volume ls
# If a leftover anonymous volume still exists and is unused:
docker volume rm <anonymous-volume-name>
```

Expected compose configuration:

- `cadvisor` uses the standard compose `tmpfs:` section: `/dev/disk:ro,noexec,nosuid,nodev,size=1m,mode=0555`.

## 10. Postgres keeps rejecting `omero` after startup

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
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env up -d database omeroserver omeroweb
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env logs --since=5m database omeroserver
```

Expected result:

- `database` no longer logs repeated auth failures for user `omero`.


## 11. LDAP users are placed into `default` group instead of `users_ldap`

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
docker compose --env-file installation_paths.env --env-file env/omero_secrets.env exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config get omero.ldap.new_user_group
```

Expected result:

- Output is your configured target (for example `users_ldap`) or a deliberate dynamic expression (for example `:dn_attribute:memberOf`), not implicit `default`.
- If output is still `default` and this is intentional, startup will continue (no failure) and explicit LDAP group bootstrap is skipped.
- If output is still `default` but you expect another group, inspect OMERO.server bootstrap logs for LDAP config apply/validation failures.
