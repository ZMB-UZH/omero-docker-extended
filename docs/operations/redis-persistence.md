# Redis Session Persistence

Redis stores OMERO.web sessions and queued work. Treat its data as persistent
application state: never flush it, prune its volume, or recreate an older
temporary-storage container before retaining its current state.

## New Installations

The project-scoped `redis-data` volume is mounted at the image's data directory.
The tracked environment template enables append-only persistence and selects
`noeviction`. Memory sizing remains installation-specific. The health check
requires successful AOF writes and rewrites, completed loading, and the
non-evicting policy; a successful ping alone is insufficient.

Redis's default once-per-second AOF synchronization preserves orderly restarts
but can lose roughly the last second of acknowledged writes after a sudden
host or storage failure. This is not high availability or a backup strategy.
Monitor memory and disk headroom: at the configured memory limit, new writes
fail rather than evicting sessions. Normal session expiry and explicit logout
remain unchanged. Redis persistence does not make an OMERO.server restart
preserve its in-memory sessions.

## Existing Installations

Plan a short maintenance window. Discover the actual Compose project, Redis
container, data directory and image from the running deployment; do not assume
an installation path or container name. Keep configuration and data backups
outside the container until validation succeeds. Agent-led replacements and
environment edits require the repository's separate, exact approvals.

1. Verify disk headroom, current session continuity, database key counts and
   expiry times. Run the environment safety checks and retain the current
   configuration and image. Stop clients from introducing writes during the
   final snapshot and cutover; do not clear queues or session keys.
2. Follow the upstream [RDB-to-AOF procedure](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/#how-i-can-switch-to-aof-if-im-currently-using-dumprdb-snapshots):
   enable AOF on the running instance before changing its launch configuration.
   Wait for `aof_rewrite_in_progress` and `aof_rewrite_scheduled` to be zero and
   `aof_last_bgrewrite_status` to be `ok`. Retain the complete data directory,
   including the multipart AOF manifest and every referenced file.
3. Temporary storage disappears when its container stops. Before stopping it,
   disable automatic AOF rewriting, wait for active persistence work to finish,
   select synchronous AOF flushing, and pause writes with a bounded
   `CLIENT PAUSE ... WRITE`. Copy and verify the complete, now-quiescent data
   directory from inside the running container's mount namespace within that
   pause window. A daemon-side `docker cp` of a tmpfs mount is not sufficient:
   it can return the underlying empty directory. Verify that the export includes
   the AOF manifest and all referenced data files. If the window cannot be met, abort,
   restore the original runtime settings and unpause the original instance;
   do not use a potentially inconsistent copy. Retain the verified snapshot
   before replacing the container or starting the new persistent instance.
   Never copy a changing AOF directory as a consistent backup or start an empty
   AOF beside an old RDB file. Restore the normal AOF rewrite/flush defaults on
   the replacement; temporary migration settings must not become its defaults.
4. Set only the approved `.env` keys: `REDIS_APPENDONLY=yes` and
   `REDIS_MAXMEMORY_POLICY=noeviction`. The old `REDIS_DATA_TMPFS_SIZE` key is
   unused; the installer must not rewrite unrelated operator settings.
5. Start the replacement with the same service identity and network, then
   verify persistence readiness, original unexpired keys and absolute expiry
   times, broker operation, and the original browser cookie and OMERO session.
   Verify an orderly Redis restart without logging in again. Retain rollback
   state until all checks pass; obtain approval before deleting it.

Fresh and upgraded instances use the same persistent layout. Do not claim an
upgrade is verified from a fresh-instance test alone. The container regression
suite exercises both lifecycles, including memory pressure and unhealthy
persistence configurations.
