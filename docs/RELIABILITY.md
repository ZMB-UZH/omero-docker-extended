# Reliability

Practices and invariants that keep the platform running predictably.

## Startup determinism

- All startup scripts (`startup/*.sh`) run sequentially before the main process starts.
- Scripts fail fast with descriptive error messages when required environment variables or paths are missing.
- `10-server-bootstrap.sh` validates writable directories, configures certificates, and schedules async operations (job-service user creation, script registration) that do not block server startup.
- `10-web-bootstrap.sh` validates log directory write access and configures Docker socket permissions before supervisord starts.
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

The `omeroweb` container runs two processes via supervisord:
1. **omero-web**: the Django application server (autorestart on failure).
2. **imaris-celery-worker**: the Celery worker for Imaris export tasks (autorestart on unexpected exit).

Both processes have dedicated log files with rotation (20MB max, 3 backups).

## Database reliability

- Two isolated PostgreSQL instances prevent plugin operations from affecting OMERO core.
- `pg-maintenance` sidecar runs automated VACUUM ANALYZE (weekly) and REINDEX CONCURRENTLY (monthly).
- Maintenance scripts wait for database readiness (30 retries x 5 seconds) before executing.
- `VACUUM FULL` is intentionally excluded because it requires exclusive locks and planned downtime.
- PostgreSQL data directories use a `pgdata` subdirectory to avoid ext4 `lost+found` volume issues.

## Failure patterns and mitigation

- **Celery task timeout**: Imaris export tasks have configurable time limits (`OMERO_IMS_CELERY_TIME_LIMIT`). Timed-out tasks are reported as failures.
- **Script processor unavailable**: The Imaris connector retries with backoff when no OMERO script processor is available, and fails fast if processors are explicitly disabled (`omero.scripts.processors=0`).
- **Upload cleanup**: The Upload plugin prunes stale temporary files based on configurable age thresholds to prevent disk growth.
- **Job file locking**: OMP and Upload plugins use `portalocker` for safe concurrent access to job JSON files on tmpfs.
- **Rate limiting**: OMP plugin enforces per-user rate limits on major actions (6 actions / 60 seconds) to prevent misuse.

## Incident documentation

Capture recurring incident classes in `docs/troubleshooting/` and link mitigation steps. Current troubleshooting guides:
- `troubleshooting/common.md` -- service health, plugin routes, uploads, admin tools, database, Docker socket
- `troubleshooting/imaris-export.md` -- Celery config, worker activity, script processors, recovery actions
