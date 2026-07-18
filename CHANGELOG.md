# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release
identifiers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Public entries are written for operators and users. They must not contain
credentials, personal or host-specific information, private infrastructure
details, or technical information that would enable misuse.

## [Unreleased]

No changes are currently recorded.

## [1.1.0-main.1] - 2026-07-18

This release consolidates the complete set of notable changes since
`1.0.1-main.1`. It focuses on dependable upgrades, reproducible release
governance, and compatibility across the customized OMERO stack.

### Added

- Added a deployment-contract workflow that validates the complete Compose
  topology, optional profiles, pinned images, and every local image build target
  without publishing or overwriting deployment tags.
- Added a tested Linux helper for release-time configuration preparation. It
  creates private temporary inputs, validates template references, rejects
  unsafe pre-existing targets, and removes only partial files that it created.
- Added a release governance contract requiring an exact user-confirmed tag,
  curated notes covering the full previous-release delta, and independent
  approval for every persistent-object deletion.
- Added automated public-release disclosure checks and mandatory human review
  so release notes cannot publish credentials, identities, local system data,
  private infrastructure, or implementation-level security information.

### Changed

- Disabled Grafana Live in the HTTP-only Admin Tools proxy topology so proxied
  dashboards refresh normally without recurring WebSocket handshake errors.
- Updated the OMERO.server, OMERO.web, and task-worker packaging toolchain to
  the newest compatible Setuptools release and aligned OMERO.web runtime and CI
  coverage with the supported Django 5.2 maintenance line.
- Retained OMERO.web 5.32.0 and the existing application compatibility holds
  after reviewing the upstream dependency contract; this release does not
  change the supported OMERO application release line.
- Standardized Linux runtime behavior for managed uploads, Zarr transfers,
  quota accounting, temporary storage, service startup, and health checks while
  preserving installation-configured persistent storage.
- Made deployment templates, generated installation settings, optional operator
  values, and environment validation share one fail-closed contract for fresh
  installs and upgrades.
- Updated release and agent instructions to require explicit destructive-action
  authorization, evidence-based verification, and deduplicated test execution
  without changing application runtime behavior.

### Fixed

- Corrected authenticated monitoring integration so dashboards use the
  deployment's configured identity and remain available through the supported
  OMERO administration workflow.
- Corrected Zarr download response compatibility for the supported Django line
  while preserving existing image-download behavior.
- Corrected generated installation-setting order and optional-setting handling
  so repeated upgrades no longer create false configuration drift.
- Corrected documentation, dependency inventories, workflow contracts, and
  measured quality records so published guidance matches enforced behavior.

### Removed

- Removed unsupported non-Linux server fallback behavior from managed file and
  quota operations. The documented Linux
  deployment contract now fails clearly when required platform capabilities are
  unavailable instead of silently changing persistence or ownership behavior.
- Removed obsolete duplicated release-environment preparation and automatic tag
  selection in favor of tested helpers and explicit operator decisions.

### Security

- Strengthened defense-in-depth safeguards across application, service, build,
  and release boundaries. Technical details are intentionally omitted from the
  public changelog; no data migration is required for these changes.
- Release publication now fails before creating public artifacts when its notes
  have not passed both automated disclosure controls and explicit human review.

### Upgrade Notes

- Rebuild the customized application images so the updated runtime and
  dependency set is installed. The guarded update validates existing operator
  configuration without rewriting deployment-specific values.
- Preserve all existing installation paths, persistent volumes, databases, and
  data directories. This release introduces no storage relocation or database
  schema migration.
- The container-management interface remains encrypted by default. Install an
  operator-managed certificate matching the deployment name when
  browser-trusted access is required.
- Review any legacy configuration that enables application debug behavior; the
  production update guard now rejects that setting before container recreation.

### Verification

- The final source is required to pass the complete native Linux unit,
  integration, installation, workflow-contract, lint, type, dead-code, and
  documentation matrix with full measured Python coverage and no missed lines.
- Release acceptance includes dynamic authentication, authorization, image
  access, plugin, database, cache, monitoring, container-management, temporary
  storage, persistence, restart, and upgrade checks on the deployed stack.
- The GitHub release, source checksum, manifest, image digest, embedded notes,
  OCI metadata, stored Docker analysis, and live deployment revision are
  verified against the same final commit before publication is complete.

[Unreleased]: https://github.com/ZMB-UZH/omero-docker-extended/compare/1.1.0-main.1...HEAD
[1.1.0-main.1]: https://github.com/ZMB-UZH/omero-docker-extended/compare/1.0.1-main.1...1.1.0-main.1
