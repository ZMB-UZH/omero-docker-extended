# PostgreSQL Automatic Maintenance

Lightweight cron-based sidecar that keeps both OMERO databases healthy with
**zero-downtime, non-locking** operations.

## What it does

| Task | Frequency | Lock level | Description |
|------|-----------|-----------|-------------|
| `VACUUM ANALYZE` | Weekly (Sun 03:00) | None — runs alongside normal traffic | Reclaims dead-tuple space and refreshes query-planner statistics |
| `REINDEX CONCURRENTLY` | Monthly (1st Sun 04:00) | `SHARE UPDATE EXCLUSIVE` — reads and writes continue | Rebuilds all indexes to eliminate index bloat |

## What it does NOT do

- **`VACUUM FULL`** — requires `ACCESS EXCLUSIVE` lock (blocks **all** reads and
  writes for the entire duration). Only ever run this manually during a planned
  maintenance window after a major bulk delete.

## How it works

A lightweight Docker container (`pg-maintenance`) runs the same `postgres:16.11`
image as the database containers, giving it the exact matching client tools
(`vacuumdb`, `reindexdb`, `pg_isready`). A cron daemon inside the container
triggers the maintenance script on schedule.

## Manual run

```bash
# Run everything (vacuum + reindex) right now
docker exec pg-maintenance pg-maintenance.sh all

# Run only vacuum
docker exec pg-maintenance pg-maintenance.sh vacuum_analyze

# Run only reindex
docker exec pg-maintenance pg-maintenance.sh reindex
```

## Viewing logs

```bash
docker logs pg-maintenance
```

## Files

| File | Purpose |
|------|---------|
| `maintenance/postgres/pg-maintenance.sh` | Main maintenance script |
| `maintenance/postgres/pg-maintenance-cron` | Cron schedule |
| `maintenance/postgres/pg-maintenance-entrypoint.sh` | Container entrypoint (injects env into cron) |
| `docker/pg-maintenance.Dockerfile` | Container image definition |

## Safety guarantees

- **No data loss**: Both `VACUUM ANALYZE` and `REINDEX CONCURRENTLY` are
  standard PostgreSQL maintenance operations designed to run safely online.
- **No table locks**: Plain `VACUUM` and `REINDEX CONCURRENTLY` do not acquire
  exclusive locks. The database remains fully operational during maintenance.
- **Graceful failure**: If a database is unreachable, the script retries for up
  to 150 seconds before reporting an error. Individual failures do not affect
  the other database.
- **Idempotent**: Running the script multiple times has no adverse effect.

## Adjusting the schedule

Edit `maintenance/postgres/pg-maintenance-cron` and rebuild the container:

```bash
docker compose build pg-maintenance
docker compose up -d pg-maintenance
```

## References

- [PostgreSQL 16.11 — Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)
- [PostgreSQL 16.11 — Routine Reindexing](https://www.postgresql.org/docs/current/routine-reindex.html)
- [PostgreSQL 16.11 — VACUUM](https://www.postgresql.org/docs/current/sql-vacuum.html)
- [PostgreSQL 16.11 — REINDEX](https://www.postgresql.org/docs/current/sql-reindex.html)
