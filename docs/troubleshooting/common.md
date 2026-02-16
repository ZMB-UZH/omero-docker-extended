# Common Troubleshooting

## 1. Services not healthy after startup

Checks:

```bash
docker compose ps
docker compose logs --since=10m omeroserver
docker compose logs --since=10m omeroweb
```

Focus on:

- permission/write errors on mounted paths,
- DB connection failures,
- missing environment variables,
- startup script failures.

## 2. OMERO.web plugin routes unavailable

Checks:

```bash
docker compose exec omeroweb env | rg CONFIG_omero_web_apps
docker compose logs --since=10m omeroweb
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

## 7. `docker compose down` fails with `invalid spec ... empty section between colons`

Symptom:

- warnings like `The "OMERO_SERVER_LOGS_PATH" variable is not set`;
- compose exits with an `invalid spec` error for a bind mount.

Cause:

- the path variables from `env/installation_paths.env` were not loaded.

Fix:

```bash
docker compose --env-file env/installation_paths.env down
```

If you run compose commands manually, always include the same `--env-file` value for
`build`, `up`, `down`, `ps`, and `logs`.
