# ManagedRepository Incident RCA

Date: 2026-03-25

## Summary

OMERO.server was allowed to resolve the managed repository to a relative path
named `ManagedRepository` instead of the bind-mounted persistent path
`/OMERO/ManagedRepository`. Because the server process started from the image
install tree, OMERO created and used a second repository inside the container
filesystem under `/opt/omero/server/.../ManagedRepository`. Files written there
were lost when the container was deleted or rebuilt.

This was a deployment/runtime contract failure, not a one-off import bug.

## Symptoms

- New imported data appeared in OMERO metadata but the corresponding binaries
  were written inside the container image tree instead of the bind-mounted
  managed repository.
- After container recreation, those binaries disappeared and affected objects in
  OMERO.web became inaccessible.
- OMERO logs showed repository initialization and repository-description updates
  for `ManagedRepository` without the expected absolute `/OMERO/...` root.
- Multiple repository UUIDs appeared in `originalfile.repo`, indicating that
  OMERO had registered more than one binary repository over time.
- The shared-prefix sync and binary-repository-cleanse jobs then operated in a
  mixed-repository environment, which amplified the damage and confusion.

## Root Cause

The `OMERO_DATA_DIR` and `OMERO_DIR` environment variables were removed from the
`omeroserver` service `environment:` block in `docker-compose.yml`. Without these
variables, the OMERO server has no knowledge of the bind-mounted data volume at
`/OMERO` and resolves `CONFIG_omero_managed_dir` against its own install
directory (`/opt/omero/server/OMERO.server-5.6.17-ice36/`).

This created a second managed repository inside the container's ephemeral
filesystem. Imported files landed there instead of the persistent bind-mounted
`/OMERO/ManagedRepository`, and were lost on container restart.

### Contributing factors

1. **Missing compose environment variables.** `OMERO_DATA_DIR` and `OMERO_DIR`
   were accidentally removed from the `omeroserver` service `environment:` block
   in `docker-compose.yml`. These variables are the only mechanism by which the
   OMERO server learns where the bind-mounted data volume is mounted.

2. **Relative managed repository path.** `CONFIG_omero_managed_dir` was set to
   the relative value `ManagedRepository` instead of the absolute
   `/OMERO/ManagedRepository`. A relative value is inherently unsafe because
   OMERO resolves it against `OMERODIR`, which defaults to the server install
   directory when `OMERO_DIR` is not set in the container environment.

3. **No startup guard for environment variables.** While the bootstrap script
   had a `validate_managed_repository_configuration()` function, the guard's
   expected-root calculation depended on `OMERO_DIR` being set — the very
   variable that was missing.

4. **Amplification by maintenance jobs.** The shared-prefix sync and
   `omero admin cleanse` continued to run after the repository had drifted.
   These jobs did not create the second repository, but they operated against
   wrong repository paths and accumulated stale database rows.

5. **Repository-object lookup was not repository-aware.** The shared-prefix
   bootstrap previously matched repository directory objects by path/name only.
   In a database that already contained more than one repository, that lookup
   could resolve the wrong `OriginalFile` row.

## Observed Live Evidence

The incident was confirmed from live logs, filesystem state, database rows, and
API behavior.

Examples of observed evidence:

- OMERO logs showed repository initialization against the relative
  `ManagedRepository` path.
- A real image chain resolved to an image-local path under
  `/opt/omero/server/OMERO.server-5.6.17-ice36/ManagedRepository/...`.
- Wrong repository UUIDs existed in `originalfile.repo`.
- Stray repository-description `OriginalFile` rows existed for image-local
  `ManagedRepository` paths.
- Live render and thumbnail access failed for affected objects after the
  container-local binaries disappeared.

## Structural Fix

The repair was implemented as a hard failure on unsafe configuration plus a
runtime verification loop. The system now refuses to start or continue cleanup
work if the managed-repository contract drifts.

### Docker Compose environment

- `OMERO_DATA_DIR` and `OMERO_DIR` are restored to the `omeroserver` service
  `environment:` block with required-variable syntax and a CRITICAL DO NOT REMOVE
  comment block so future editors understand why these variables exist.

### Configuration and startup

- `CONFIG_omero_managed_dir` is now tracked as the absolute path
  `/OMERO/ManagedRepository` with a critical comment in the env template
  explaining why it must remain absolute.
- The server launcher no longer changes directory into `/opt/omero/server`
  before starting OMERO.server.
- The `omeroserver` service no longer declares
  `working_dir: /opt/omero/server/OMERO.server`.

### Bootstrap fail-closed checks

`startup/10-server-bootstrap.sh` now:

- requires `CONFIG_omero_managed_dir` to be absolute,
- requires it to remain under `${OMERO_DIR}`,
- rejects `${OMERO_DIR}` itself as the managed repository root,
- creates the expected root when missing,
- refuses startup if any image-local `ManagedRepository` exists under
  `/opt/omero/server`,
- verifies at runtime that persisted `omero.managed.dir` still matches the
  expected root,
- blocks the shared-prefix sync and binary-repository-cleanse jobs when runtime
  validation fails.

### Repository-aware shared-prefix lookup

The shared-prefix bootstrap now resolves the active repository UUID from OMERO's
repository descriptions and only matches directory `OriginalFile` rows from that
repository. This prevents cross-repository confusion when stale rows exist in
the database.

### Plugin-side path safety

- The managed-Zarr staging script now rejects relative
  `omero.managed.dir` values.
- Admin Tools quota logic now prefers the absolute server-side managed root when
  `CONFIG_omero_managed_dir` is already absolute.

### Health-check enforcement

The `omeroserver` healthcheck now verifies both of the following on every health
probe:

- persisted `omero.managed.dir` equals the expected absolute configured path,
- no image-local `ManagedRepository` exists anywhere under `/opt/omero/server`.

## Data Cleanup Performed

After the structural fix was live, the actual bind-mounted managed repository
was audited against the OMERO database.

Cleanup principles:

- delete stale database references only after confirming the backing files were
  absent,
- relink only if payloads still existed in the real managed repository,
- do not perform metadata-only patchwork before the fundamental repository
  contract is fixed.

Results:

- The bad-repository payload rows found during audit no longer had backing files
  on disk, so there was nothing safe to relink for those records.
- Broken import metadata and stale stray-repository directory rows were removed
  from OMERO.
- After cleanup, only the real repository UUID remained in `originalfile.repo`
  for managed payload rows.

## Safeguards Against Recurrence

The specific failure mode that created the second repository is now blocked by
multiple independent safeguards:

1. `OMERO_DATA_DIR` and `OMERO_DIR` are required variables in `docker-compose.yml`
   with fail-fast syntax and a CRITICAL DO NOT REMOVE comment block.
2. Tracked configuration uses an absolute managed-repository path with a critical
   comment in the env template explaining why.
3. The server launcher no longer depends on a cwd inside the image tree.
4. Bootstrap validation fails closed before startup proceeds.
5. Runtime validation blocks background maintenance jobs if drift occurs.
6. Container healthchecks fail if the repository path drifts or if a second
   image-local `ManagedRepository` appears.
7. Repository bootstrap lookups are anchored to the active repository UUID.
8. Plugin code rejects relative managed-repository values instead of silently
   accepting them.
9. Contract tests verify the compose environment variables, absolute env path,
   and bootstrap guard presence in CI.

## Verification

Verification included:

- focused regression tests for the startup contract,
- focused regression tests for repository-aware shared-prefix lookup,
- focused Admin Tools path-resolution tests,
- live container rebuild and restart,
- live OMERO config verification,
- live filesystem verification that no image-local `ManagedRepository` exists,
- live database verification that stale wrong-repository rows were removed,
- live OMERO API checks that broken objects were gone and known-good objects
  remained accessible.

## Files Changed For The Fix

- `docker-compose.yml`
- `docker/omero-server.Dockerfile`
- `env/omeroserver_example.env`
- `startup/10-server-bootstrap.sh`
- `omeroweb_import/omero_scripts/Manage_Zarr_ManagedRepository.py`
- `omeroweb_admin_tools/services/storage_quotas.py`
- `omeroweb_admin_tools/tests/test_storage_quotas_root_resolution.py`
- `tests/test_build_workflow_integration_contract.py`
- `tests/test_repo_root_sync_regressions.py`
- documentation updates under `docs/`
