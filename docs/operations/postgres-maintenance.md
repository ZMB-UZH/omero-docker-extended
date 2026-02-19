# PostgreSQL Maintenance

## Overview
The repository includes a dedicated PostgreSQL maintenance workflow under `maintenance/postgres/` to run safe online maintenance for both:

- OMERO primary database,
- plugin database.

## Included Scripts

- `maintenance/postgres/pg-maintenance.sh`
  - actions: `vacuum_analyze`, `reindex`, `all`
- `maintenance/postgres/pg-maintenance-entrypoint.sh`
  - exports env values for cron and launches scheduled jobs
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

The script exits fast if required values are missing.

## Scheduling

Default cron schedule (container timezone):

- Sunday 03:00: `vacuum_analyze`
- First Sunday 04:00: `reindex`

## Manual Invocation

```bash
docker exec pg-maintenance pg-maintenance.sh all
```

Adjust container name if compose project prefixes differ.
