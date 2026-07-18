# Release Notes

## 2026-07-18 Dependency and Runtime Refresh

- Updated pinned GitHub Actions for CodeQL (`4.37.1`), Ruff (`4.1.0`), and
  Docker Scout (`1.23.1`), and aligned the pinned Scout CLI to `1.23.1` after
  reviewing upstream release notes and verifying the CLI archive digest.
- Updated the Codecov uploader CLI to `11.3.1` after reviewing its upload URL
  validation changes and corrected Linux x86_64 build baseline. Retained the
  official OSV reusable action at its latest release, `2.3.8`; OSV Scanner
  `2.4.0` has not yet been published through that action.
- Updated the repository lint and preview toolchains to Ruff `0.15.22`,
  markdownlint-cli2 `0.23.1`, Node.js LTS `24.18.0`, Vite `8.1.5`, Vitest
  `4.1.10`, jsdom `29.1.1`, and Playwright `1.61.1` after reviewing their
  compatibility ranges and intervening release notes.
- Extended the narrow Ruff correctness gate with `B904` and made translated
  exception causes explicit. Database and AI-provider wrappers now suppress raw
  backend context after sanitized logging, while harmless import failures retain
  their diagnostic cause.
- Removed an invalid `exc_info` request from the regular-image tile validation
  path and added `LOG014` coverage so expected client errors cannot emit a
  misleading `NoneType: None` traceback.
- Updated the immutable Semgrep workflow image to `1.170.0` after reviewing the
  `1.169.0` and `1.170.0` release notes, including its Dockerfile heredoc parser
  fix, and verifying the published multi-platform image digest.
- Added Dependabot Docker coverage for the root Compose manifest while retaining
  the separate `/docker` Dockerfile update surface. PostgreSQL major upgrades
  remain held for migration review while patch releases and digest refreshes are
  now allowed through normal Dependabot maintenance.
- Made release publication explicitly upload the carrier SBOM analysis to Docker
  Scout before running the release CVE report, so Docker Hub receives stored
  analysis data instead of relying only on a one-off CLI report.
- Enabled Bash validation in Super-Linter and corrected the hardened image
  probe's quoted tmpfs argument and an unused retry-loop variable found by a
  full ShellCheck `0.11.0` pass. The local `all` profile now forwards the same
  Bash scope and current vendor exclusion regex as the GitHub workflow.
- Refreshed hash-locked CI dependencies, including Mypy `2.3.0`, Django and
  django-stubs `6.0.7`, Coverage `7.15.2`, NumPy `2.5.1`, matplotlib `3.11.1`,
  and tifffile `2026.7.14`.
- Replaced floating OMERO.web Python installs with exact current pins, made the
  plugin runtime's direct `portalocker` dependency explicit instead of relying
  on a transitive OMERO.web dependency, upgraded
  redis-py from `5.0.8` to `8.0.1` for Redis 8.8 support, and updated in-image
  pytest to `9.1.1`. Celery remains at its current `5.6.3` release.
- Made the direct Python tooling, curated update set, OMERO.server CLI plugins,
  and Figure PDF dependencies reproducible across image builds. This includes
  ReportLab `5.0.0`; its reviewed remote-image trust change does not alter the
  local-file PDF export path. Retained setuptools `80.9.0` because OMERO startup
  tooling still imports `pkg_resources`.
- Added host-agnostic `/tmp` defaults for OMERO temporary files so each image's
  CLI and healthcheck work in standalone container runs; Compose continues to
  override them with the installation-specific temporary path.
- Expanded the offline documentation gate to validate relative links across all
  first-party Markdown documents while excluding external URLs, code examples,
  and immutable vendored documentation from rewrite scope.
- Added input-aware verification-efficiency rules for AI agents: deduplicate
  successful checks until their inputs change, parallelize independent
  read-only gates, serialize stateful live operations, and run one complete
  matrix against the final tree before release.
- Updated the selected vendored AI reference skills to ECC `2.0.0` and caveman
  `1.9.1`, preserving exact upstream provenance while explicitly excluding
  hooks, control-plane components, MCP configuration, installers, implicit
  activation, and multi-agent orchestration from the active repo overlays.
- Updated the monitoring and supporting service images for Alloy `v1.17.1`,
  Prometheus `v3.13.1`, Node exporter `v1.12.1`, cAdvisor `0.60.5`, Postgres
  exporter `v0.20.1`, Redis exporter `v1.87.0-alpine`, Redis `8.8.0-alpine`,
  and Ollama `0.32.1`.
- Refreshed immutable Ubuntu 26.04 and PostgreSQL 16.14 base-image digests and
  advanced the pinned BIOP OMERO-scripts revision after verifying that the
  installed CellProfiler export script is unchanged upstream.
- Kept OMERO.web at the current upstream `5.32.0` release after reviewing its
  upgrade notes and source diff against `5.31.1`; the custom API server patch
  targets files untouched by that release. The production `ome-zarr==0.16.0`
  and Bio-Formats2Raw `0.11.0` compatibility holds remain unchanged.

## 2026-05-26 Prebuilt Carrier Installation and Toolchain Pins

- Added a manual `release-prebuilt-carrier` GitHub Actions workflow that creates
  a source archive, builds hardened flattened runtime images, bundles the
  Compose image set into one docker hub carrier image, verifies the carrier
  contents, and creates a GitHub release with the same docker-compatible SemVer tag
  as the docker image tag. docker hub credentials use repository secrets named
  `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, the release job deliberately
  avoids GitHub Actions environments so it cannot create deployment history
  entries, `DOCKERHUB_TOKEN` is documented as a docker hub access token for
  two-factor-authenticated accounts, release write permissions are scoped to
  the release job, and the workflow uses the built-in `GITHUB_TOKEN` to create
  a branch-targeted draft release before publishing it after carrier-image
  verification. The release also publishes `prebuilt-carrier-digest.txt` so
  easy installs can pin the Docker Hub carrier image by immutable digest instead
  of trusting a mutable tag alone.
- Added `installation/easy_installation_script.sh` and
  `installation/load_prebuilt_carrier.sh`. Easy installation uses
  `PREBUILT_IMAGE_MODE=require`, asks first for the prebuilt docker image tag to
  install and then for the matching `PREBUILT_IMAGE_DIGEST`, skips the Buildx,
  build-cache, final-image flattening, and image-hardening prompts so the easy
  path has eleven interactive questions,
  verifies the carrier manifest and compressed archive checksum, streams the
  verified archive into `docker load` without writing a second full archive
  under `OMERO_TMP_PATH`, checks docker-root free space before loading, and
  starts Compose with `--no-build`.
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
- Added a Compose-derived release storage guard that prunes only
  non-required runner-local docker image references before the workflow pulls
  missing required images and saves `runtime-images.tar.gz`.
- Moved the release workflow's Docker data root to `/mnt/docker-data` on
  GitHub-hosted Linux runners before heavy carrier builds, avoiding root
  filesystem exhaustion while pulling the full required image set.
- Eliminated the prebuilt carrier's duplicate runtime-archive layer and removed
  the carrier wrapper's Alpine base image and BusyBox package surface by making
  `docker/prebuilt-carrier.Dockerfile` a scratch-based data image with a single
  payload layer. The runtime service images inside `runtime-images.tar.gz` are
  the flattened images; the carrier wrapper has no OS package layer, package
  manager, shell, or runnable healthcheck command.
- Made the release workflow create and verify the release tag explicitly before
  creating the draft GitHub release, because GitHub draft releases can otherwise
  be represented by an untagged draft URL until publication.
- Updated Ruff to `0.15.20` and Mypy to `2.1.0`, including workflow pins,
  pre-commit configuration, hash-locked Mypy requirements, documentation, and
  regression contracts.
- Refreshed Python CI pins for the Python 3.14 workflow, including pytest,
  coverage, Django, cryptography, NumPy, matplotlib, zarr, and tifffile. Kept
  the production OMERO build-time `OME_ZARR_PY_VERSION=0.16.0` compatibility
  hold after upstream release-note review: `ome-zarr==0.18.0` is compatible
  with the OMERO.web 5.32.0 Python 3.12 runtime, but Python 3.14 CI currently
  resolves it through the prerelease `ome-zarr-models==1.8.0rc0` dependency.
- Updated the repo-local CocoIndex Code wrapper to `0.2.37` after upstream
  release review. Codex MCP installation now writes a host-stable launcher
  under `AGENT_COCOINDEX_HOME` and pins the checkout through
  `AGENT_COCOINDEX_REPO`, so stale temporary-clone paths are repaired by
  `mcp-install` instead of breaking Codex startup.

## 2026-05-12 Import and Imaris Connector Hardening

- Refreshed pinned infrastructure images after upstream release-note review:
  CrowdSec `v1.7.8`, Alloy `v1.17.0`, Redis `8.6.4-alpine`,
  Redis exporter `v1.86.0-alpine`, Prometheus `v3.12.0`, and Ollama
  `0.30.11`.
- Strengthened image-pin regression coverage so Compose, dockerfile, and
  workflow container images cannot use untagged or floating aliases such as
  `latest`, `stable`, `edge`, `main`, `master`, `nightly`, `rolling`, or
  `current`.
- Project-selected imports now create or reuse Dataset targets only inside the
  selected Project. If a target cannot be placed there, import stops before any
  file is imported.
- The Imaris XT connector preserves selected OMERO image names by default,
  prompts before replacing same-name local files, and uses timestamped duplicate
  names only by explicit user choice or opt-in setting. Repeated selected-image
  names inside one multi-image load now timestamp every repeated copy, including
  the first occurrence, before downloads start.
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
