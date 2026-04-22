# PostgreSQL Maintenance

## Overview

The repository includes a dedicated PostgreSQL maintenance workflow under `maintenance/postgres/` to run safe online maintenance for both:

- OMERO primary database,
- plugin database.

## Included Scripts

- `maintenance/postgres/pg-maintenance.sh`
  - actions: `vacuum_analyze`, `reindex`, `all`
- `maintenance/postgres/pg-maintenance-entrypoint.sh`
  - writes the private cron environment and launches scheduled jobs
- `maintenance/postgres/pg-maintenance-cron-runner`
  - sources the private cron environment before each scheduled run
- `maintenance/postgres/pg-maintenance-cron`
  - weekly and monthly schedules

## Maintenance Policy

Implemented operations are online-safe:

1. `VACUUM ANALYZE` (weekly)
2. `REINDEX CONCURRENTLY` (monthly)

`VACUUM FULL` is intentionally excluded because it requires exclusive locks and planned downtime.

## Environment Variables

Required variables include host, port, db name, user, and password for both databases:

- `OMERO_DB_*`
- `PLUGIN_DB_*`

The container entrypoint writes these values into a `0600` shell-quoted cron
environment file. Cron jobs never source raw `printenv` output and the static
cron schedule is not rewritten on restart.

The script exits fast if required values are missing. Maintenance command
failures are fatal so failed `vacuumdb` or `reindexdb` runs cannot be hidden as
warnings.

Optional timeout controls:

- `PG_MAINTENANCE_LOCK_TIMEOUT` (default `2s`)
- `PG_MAINTENANCE_VACUUM_STATEMENT_TIMEOUT` (default `0`)
- `PG_MAINTENANCE_REINDEX_STATEMENT_TIMEOUT` (default `0`)

## Scheduling

Default cron schedule (container timezone):

- Sunday 03:00: `vacuum_analyze`
- First Sunday 04:00: `reindex`

## Manual Invocation

```bash
docker exec pg-maintenance pg-maintenance.sh all
```

Adjust container name if compose project prefixes differ.
