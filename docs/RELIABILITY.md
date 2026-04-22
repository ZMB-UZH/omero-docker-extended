# Reliability

Practices and invariants that keep the platform running predictably.

## Startup determinism

- All startup scripts (`startup/*.sh`) run sequentially before the main process starts.
- Scripts fail fast with descriptive error messages when required environment variables or paths are missing.
- `10-server-bootstrap.sh` validates writable directories, auto-detects the
  OMERO CLI binary (with optional `OMERO_BIN` override), explicitly prepares a
  clean OMERO CLI runtime temp namespace under
  `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp/runtime*` before any OMERO CLI call,
  requires `OMERO_CLI_USER` instead of embedding the service account in code,
  removes stale legacy `omero_${OMERO_CLI_USER}` lock namespaces directly under
  `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp`, normalizes bootstrap lock
  directories under `OMERO.server/var` so OMERO admin commands remain writable
  by `omero-server`, removes stale repository lock files from
  `${OMERO_DIR}/.omero/repository/*/.lock` before OMERO.server starts, and
  writes the env-derived import helper state file
  `OMERO.server/var/managed-zarr-runtime.env` from `${OMERO_TMP_PATH}`. It also
  fails closed if `CONFIG_omero_managed_dir` is not an absolute path inside
  `${OMERO_DIR}` or if a second image-local `ManagedRepository` exists under
  `/opt/omero/server`. The background shared-prefix sync now plans only
  deterministic configured prefixes plus prefixes already present in the active
  managed repository, and startup `omero admin cleanse` plus the sync loop both
  refuse to run unless runtime validation confirms OMERO still resolves the
  managed repository to the expected absolute path and no second repository has
  appeared. Bootstrap then configures certificates and schedules async
  operations (job-service user creation, script registration, binary-repository
  `omero admin cleanse`) that do not block server startup. The `omeroserver`
  healthcheck uses the same service-user and OMERO temp environment contract.
- `installation/installation_script.sh` preserves the OMERO.server temp namespace under `OMERO_TMP_PATH` during reinstall/update runs instead of recursively handing the entire temp tree to OMERO.web. This avoids ownership drift in stale OMERO.server lock trees across repeated installation and update workflows.
- `10-web-bootstrap.sh` validates and repairs the OMERO.web `var/` runtime
  layout (including `var/omero/tmp`, `var/run`, and `var/django_secret_key`
  generation when missing), repairs and verifies the runtime-user write path
  for both the OMERO.web log tree and every supervisor-managed log file
  declared in `supervisord.conf`, normalizes site-local versus generated
  branding logos at `branding/logo.png`, refreshes known legacy generated
  placeholders, and configures Docker socket permissions before supervisord
  starts.
- Bootstrap scripts are idempotent: re-running after a restart produces the same result.

## Health checks

Every service in `docker-compose.yml` has a health check with consistent parameters:

- Interval: 10s, timeout: 10s, retries: 30.
- Start periods vary by service (10s for fast services, 30-60s for OMERO server/web).
- Services with `depends_on:` use `condition: service_healthy` to enforce startup order.

Health check methods by service type:

- PostgreSQL: `pg_isready` against the configured user and database.
- Redis: `redis-cli ping`.
- OMERO.server: admin login attempt via CLI.
- OMERO.web: `curl` to `/webgateway/` endpoint.
- Monitoring services: HTTP GET to their health/ready endpoints.
- pg-maintenance: `pgrep -x cron` (validates cron process is running).

See `docs/reference/service-endpoints.md` for the complete endpoint map.

## Process management

The `omeroweb` container runs three processes via supervisord:

1. **omero-web**: the Django application server (autorestart on failure).
2. **imaris-celery-worker**: the Celery worker for Imaris export tasks (autorestart on unexpected exit).
3. **tools-celery-worker**: the Celery worker for Tools enhanced-search indexing (autorestart on unexpected exit when enabled).

All three processes have dedicated log files with rotation (20MB max, 3 backups).

## Database reliability

- Two isolated PostgreSQL instances prevent plugin operations from affecting OMERO core.
- `pg-maintenance` sidecar runs automated VACUUM ANALYZE (weekly) and REINDEX CONCURRENTLY (monthly).
- Maintenance scripts wait for database readiness (30 retries x 5 seconds) before executing.
- Scheduled maintenance uses a private shell-quoted cron environment file and fails loud on `vacuumdb` or `reindexdb` command errors.
- `VACUUM FULL` is intentionally excluded because it requires exclusive locks and planned downtime.
- PostgreSQL data directories use a `pgdata` subdirectory to avoid ext4 `lost+found` volume issues.

## Failure patterns and mitigation

- **Celery task timeout**: Imaris export tasks have configurable time limits (`OMERO_IMS_CELERY_TIME_LIMIT`). Timed-out tasks are reported as failures.
- **Imaris export startup failures**: The Imaris connector launches `IMS_Export.py` through the OMERO CLI inside the `omeroweb` container. If exports stall, first verify `Processor-0` is active in `omero admin diagnostics`, then validate direct `omero script launch` from both `omeroserver` and `omeroweb`.
- **Enhanced search refresh failures**: the Tools plugin writes only to `database_plugin`, but refresh jobs still need OMERO API read access and a healthy `tools-celery-worker` when celery mode is enabled. Check the OMERO.web container logs, `tools-celery-worker` logs, and scope configuration before rerunning refresh.
- **Upload cleanup**: The Import plugin prunes stale temporary files based on configurable age thresholds to prevent disk growth.
- **Zarr helper startup timing**: managed-repository staging retries `NoProcessorAvailable` for an env-driven window (`OMERO_WEB_UPLOAD_SCRIPT_START_TIMEOUT_SECONDS` / `OMERO_WEB_UPLOAD_SCRIPT_START_RETRY_SECONDS`) instead of failing immediately when script processors are still coming up.
- **Job file locking**: OMP and Import plugins use `portalocker` for safe concurrent access to job JSON files on tmpfs.
- **Rate limiting**: OMP plugin enforces per-user rate limits on major actions (6 actions / 60 seconds) to prevent misuse.

## Incident documentation

Capture recurring incident classes in `docs/troubleshooting/` and link mitigation steps. Current troubleshooting guides:

- `troubleshooting/common.md` -- service health, plugin routes, uploads, admin tools, database, Docker socket
- `troubleshooting/imaris-export.md` -- auth regressions, `waiting_for_processor`, processor startup failures, CLI validation, recovery actions
