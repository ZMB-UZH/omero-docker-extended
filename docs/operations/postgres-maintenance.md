# PostgreSQL Maintenance

## Overview

The repository includes a dedicated PostgreSQL maintenance workflow under `maintenance/postgres/` to run safe online maintenance for both:

- OMERO primary database,
- plugin database.

## Updating PostgreSQL 16

The database images and maintenance client use PostgreSQL 16.16. Both
database images use the same build stage and the existing data directories.
The update does not require changes to the deployment environment files.

PostgreSQL 16 is recommended by
[OMERO.server 5.6.18](https://omero.readthedocs.io/en/v5.6.18/sysadmins/version-requirements.html#postgresql).
Before an existing installation moves to 16.16, review the upstream
[migration notes](https://www.postgresql.org/docs/16/release-16-16.html#RELEASE-16-16-MIGRATION)
and the notes for any skipped 16.x releases. Stop application writes,
back up both databases and their roles, and verify recovery on separate
storage. Keep the original database directories and mounts in place. A
16.x minor upgrade does not require `pg_upgrade` or a dump and restore.

After startup, check both databases' collation versions, extensions, and
query results. The 16.16 notes call for reindexing existing B-tree indexes
on `bpchar` columns declared without a length limit, and existing GiST
indexes using `gist_trgm_ops`. Review the other `REINDEX` conditions in
the upstream notes and verify integrity after any required repair.
Plan this work before resuming application traffic. The installer does not
automatically reindex user data. Fresh 16.16 databases do not need the legacy
index review.

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
