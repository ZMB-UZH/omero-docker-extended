# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release
identifiers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Public entries are written for operators and users. They must not contain
credentials, personal or host-specific information, private infrastructure
details, or technical information that would enable misuse.

## [Unreleased]

## [1.1.1-main.1] - 2026-08-22

### Changed

- Updated OMERO.web to 5.33.0 with compatible Django and OMERO.py releases.
- Refreshed supported service, CI, and developer toolchain versions.
- Disabled unused Alloy telemetry.

### Fixed

- Prevented stale upgrade settings from selecting mismatched build artifacts.
- Restored native Zarr conversion with an isolated supported Java runtime.

### Upgrade Notes

- Rebuild the customized application images.
- No database migration or storage-layout change is required.

### Verification

- Passed automated CI, live deployment tests, and Docker image analysis.

## [1.1.0-main.1] - 2026-07-22

This release improves reliability, monitoring, and release integrity without
changing the supported OMERO application line or storage layout.

### Added

- Added reproducible release artifacts with checksums, an image manifest, SBOM,
  provenance, and Docker Scout analysis.

### Changed

- Updated Grafana to 13.1.1 and Alloy to 1.18.0; retained stable Ollama 0.32.1
  and OMERO.web 5.32.0.
- Standardized Linux storage, temporary-file, configuration, startup, and health
  checks for fresh installations and upgrades.
- Improved HTTPS container management and authenticated monitoring integration.

### Fixed

- Fixed IMS export processor startup, completion detection, and result handling.
- Fixed proxied Grafana dashboards and monitoring authentication.
- Fixed Zarr download compatibility with the supported Django 5.2 line.
- Fixed repeated-upgrade configuration drift and optional-setting handling.

### Security

- Strengthened application, container, build, and release safeguards. Technical
  details are intentionally omitted from public release notes.

### Upgrade Notes

- Rebuild the customized application images to install the updated runtime and
  dependencies.
- No database migration, storage relocation, or operator-value rewrite is
  required.

### Verification

- Passed Linux CI with 100% measured Python coverage, live deployment checks,
  and Docker Scout analysis.

[Unreleased]: https://github.com/ZMB-UZH/omero-docker-extended/compare/1.1.1-main.1...HEAD
[1.1.1-main.1]: https://github.com/ZMB-UZH/omero-docker-extended/compare/1.1.0-main.1...1.1.1-main.1
[1.1.0-main.1]: https://github.com/ZMB-UZH/omero-docker-extended/compare/1.0.1-main.1...1.1.0-main.1
