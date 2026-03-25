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

## Root Cause Timeline

### 1. Relative managed repository setting

On 2026-03-22, commit
`b277b2d4a9a7073b311cf50f021941f088bd31f3` changed the tracked server example
configuration to:

`CONFIG_omero_managed_dir=ManagedRepository`

That value is unsafe because OMERO resolves it relative to the server process
working directory when it is not an absolute path.

### 2. Server startup from the install tree

The same runtime path became dangerous because OMERO.server was launched from the
install tree. Two places made that possible:

- On 2026-03-19, commit
  `cd835ced0e808a98d1937855b48c93c26b7a2ded` left the `omeroserver` container
  with `working_dir: /opt/omero/server/OMERO.server`.
- The generated `/startup/99-run.sh` in
  `docker/omero-server.Dockerfile` contained `cd /opt/omero/server` before
  `omero admin start --foreground`.

With those two conditions combined, OMERO resolved the relative
`ManagedRepository` path into the image-local server tree instead of the
persistent bind mount.

### 3. Amplification by follow-up maintenance jobs

Existing bootstrap logic later normalized shared prefix ownership and ran
`omero admin cleanse`. Those jobs did not create the second repository, but they
were operating after the repository contract had already drifted. That allowed
wrong repository UUIDs and stale repository-description rows to accumulate and
made the incident harder to diagnose.

### 4. Repository-object lookup was not repository-aware

The shared-prefix bootstrap previously matched repository directory objects by
path/name only. In a database that already contained more than one repository,
that lookup could resolve the wrong `OriginalFile` row. The lookup needed to be
anchored to the active repository UUID returned by OMERO.

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

### Configuration and startup

- `CONFIG_omero_managed_dir` is now tracked as the absolute path
  `/OMERO/ManagedRepository`.
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

1. Tracked configuration uses an absolute managed-repository path.
2. The server launcher no longer depends on a cwd inside the image tree.
3. Bootstrap validation fails closed before startup proceeds.
4. Runtime validation blocks background maintenance jobs if drift occurs.
5. Container healthchecks fail if the repository path drifts or if a second
   image-local `ManagedRepository` appears.
6. Repository bootstrap lookups are anchored to the active repository UUID.
7. Plugin code rejects relative managed-repository values instead of silently
   accepting them.

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

