# Release Notes

## 2026-05-26 Prebuilt Carrier Installation and Toolchain Pins

- Added a manual `release-prebuilt-carrier` GitHub Actions workflow that creates
  a source archive, builds hardened flattened runtime images, bundles the
  Compose image set into one Docker Hub carrier image, verifies the carrier
  contents, and creates a GitHub release with the same SemVer pre-release tag
  as the Docker image tag. Docker Hub credentials use repository secrets named
  `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, the release job runs in the
  `dockerhub-release` GitHub Actions environment for optional protection rules,
  `DOCKERHUB_TOKEN` is documented as a Docker Hub access token for
  two-factor-authenticated accounts, release write permissions are scoped to
  the release job, and the workflow uses the built-in `GITHUB_TOKEN` to create
  a branch-targeted draft prerelease before publishing it after carrier-image
  verification.
- Added `installation/easy_installation_script.sh` and
  `installation/load_prebuilt_carrier.sh`. Easy installation uses
  `PREBUILT_IMAGE_MODE=require`, asks first for the prebuilt release version to
  install, skips the Buildx, build-cache, final-image flattening, and
  image-hardening prompts so the easy path has ten interactive questions,
  verifies the carrier manifest and compressed archive checksum, loads the
  bundled images with `docker load`, checks temporary and Docker-root free
  space before loading, and starts Compose with `--no-build`.
- Kept standard installation behavior intact by preserving the existing image
  defaults in `docker-compose.yml` while allowing the custom image references to
  be supplied through environment variables.
- Moved generated `.env` Redis defaults into tracked `.env_example`; the
  installer now preserves deployment-local `.env` Redis values while rendering
  Compose-only keys from the tracked template contract.
- Switched the shared ImarisConvertBioformats build-time Bio-Formats download
  to OME Artifactory's versioned `ome/bioformats_package` Maven artifact with
  `.sha256` verification, preserving the same build path for standard and
  prebuilt-carrier images.
- Reduced prebuilt-carrier release runner storage pressure by disabling
  ephemeral Buildx local-cache export in the manual release workflow and by
  flattening each serially built target before the next target is built.
- Eliminated the prebuilt carrier's duplicate runtime-archive layer by applying
  carrier ownership and read-only permissions at `COPY` time instead of
  mutating the large archive in a later Dockerfile layer. The runtime service
  images inside `runtime-images.tar.gz` are the flattened images; the carrier
  itself intentionally remains a small normal image wrapper around one large
  archive layer.
- Updated Ruff to `0.15.14` and Mypy to `2.1.0`, including workflow pins,
  pre-commit configuration, hash-locked Mypy requirements, documentation, and
  regression contracts.
- Updated the repo-local CocoIndex Code wrapper to `0.2.33` after upstream
  release review. Codex MCP installation now writes a host-stable launcher
  under `AGENT_COCOINDEX_HOME` and pins the checkout through
  `AGENT_COCOINDEX_REPO`, so stale temporary-clone paths are repaired by
  `mcp-install` instead of breaking Codex startup.

## 2026-05-12 Import and Imaris Connector Hardening

- Refreshed pinned infrastructure images after upstream release-note review:
  CrowdSec `v1.7.8`, Alloy `v1.16.1`, Redis `8.6.3-alpine`,
  Redis exporter `v1.83.0-alpine`, Prometheus `v3.11.3`, and Ollama
  `0.23.2`.
- Strengthened image-pin regression coverage so Compose, Dockerfile, and
  workflow container images cannot use untagged or floating aliases such as
  `latest`, `stable`, `edge`, `main`, `master`, `nightly`, `rolling`, or
  `current`.
- Project-selected imports now create or reuse Dataset targets only inside the
  selected Project. If a target cannot be placed there, import stops before any
  file is imported.
- The Imaris XT connector preserves selected OMERO image names by default,
  prompts before replacing same-name local files, and uses timestamped duplicate
  names only by explicit user choice or opt-in setting.
- The XT connector help button now opens a larger user-focused modal help
  window. Search fields, browser lists, Search, and Append-to-observed-folders
  controls are disabled before connection and after disconnect while preserving
  loaded setting values.

## 2026-05-06 Imaris XT Connector UI Refresh

### Highlights

- Added a timed password reveal control to the standalone XT connector while
  keeping passwords out of autosave settings and clearing the visible password
  field after successful login.
- Restored converter selection as an autosaved setting and persisted converter
  changes immediately when `Autosave settings` is enabled.
- Added `Show log` and placeholder `Search function` preferences to the
  connector settings file. `Show log` defaults on and can hide the command
  window while retaining the rolling file log; `Search function` defaults off
  until the feature is wired.
- Added a connector settings version tag that is refreshed on every standalone
  XT startup. If an existing `settings.env` has no current matching version,
  the connector archives it as `settings.env.old`, rotating existing generated
  backups upward as `settings.env.old2`, `settings.env.old3`, and so on before
  creating a fresh current-version settings file.
- Tightened OMERO.web host validation so the Host field accepts hostnames/IPs
  only. `http://` and `https://` belong to the `Use HTTPS` checkbox state, and
  ports belong to the Port field.
- Reworked folder export so `Export folder to OMERO` always opens the native
  folder chooser before `Confirm folder export`; the typed path is only the
  first export chooser location hint for a session.
- Added draggable Projects, Datasets, and Images panel splitters with bounded
  proportional widths and removed refresh-time action-button repaint flicker.
- Stabilized the converter selector popup so opening it does not restore stale
  browser-panel focus highlights.
- Tightened `Load images into Imaris` availability so it stays disabled until
  the connection, converter, path, and at least one Images-panel selection are
  all present.
- Wired the connector info button to a modal version, author, and as-is
  disclaimer dialog that locks the main connector window behind it.

### Validation Focus

- Focused standalone connector unit coverage for password handling, autosaved
  converter and log-visibility settings, folder-export chooser ordering,
  bounded panel resizing, and refresh action-button state.
- Tk/Xvfb layout verification for minimum-width behavior and visible widget
  alignment.

## 2026-04-26 Documentation Audit Refresh

This refresh audited the documentation set against the current repository code,
tests, workflows, and scanner runbooks.

### Highlights

- Updated OMERO.web supervisord topology docs to match the four declared
  programs in `supervisord.conf`.
- Moved the completed knowledge-base bootstrap plan from active planning into
  completed execution-plan history.
- Updated planning, quality, and backlog docs to use current-default-branch
  change records instead of routine branch/PR language.
- Refreshed code-scanning guidance so historical critical/high findings are not
  mistaken for current open file-level alerts.
- Updated plugin-database documentation for OMP, Import, and Tools enhanced
  search data stores.
- Corrected Import plugin upload configuration docs to use the current
  `OMERO_WEB_UPLOAD_*` environment contract and the shared `OMERO_TMP_PATH`
  runtime subtree.
- Refreshed the Python acceleration design note's tracked file and line counts
  against the current repository tree.
- Removed routine pull-request triggers and hard-coded `main` branch filters
  from checked-in workflows; workflow jobs now rely on the current default
  branch guard.

### Validation Focus

- Documentation structure and required index links.
- Regression checks for scanner snapshot wording and topology facts.
- Markdown linting and workflow-local gates before accepting the change.

## Current Documentation Refresh

This release restructures project documentation for public consumption and maintainability.

### Highlights

- Consolidated non-root Markdown documents into `docs/`.
- Replaced ad hoc historical narratives with implementation-level documentation.
- Added plugin-specific operation guides for each OMERO.web plugin package.
- Added architecture, deployment, operations, troubleshooting, and endpoint references.

### Documentation Principles Applied

- public-safe language,
- no personal incident details,
- explicit operational guidance,
- consistent structure for future updates.

## Future Update Template

For future releases, record:

1. Feature additions and behavior changes.
2. Backward compatibility notes.
3. Configuration migrations (if any).
4. Test and rollout validation summary.
