# Documentation Index

Central navigation hub for all project documentation. Start here, then follow links to deeper content.

## 1. Architecture

- `architecture/system-overview.md` -- runtime components, plugin architecture, configuration model, security notes
- `../ARCHITECTURE.md` -- layer model, dependency boundaries, data flow patterns, security model

## 2. Deployment

- `deployment/quickstart.md` -- step-by-step first deployment guide
- `deployment/configuration.md` -- environment files, plugin registration, Celery config, reverse proxy

## 3. Plugin Guides

- `plugins/omp-plugin.md` -- filename parsing, metadata annotation, AI-assisted regex, variable sets
- `plugins/omp-plugin-workflow.md` -- end-to-end OMP workflow, parser configuration, job execution, annotation lifecycle
- `plugins/import-plugin.md` -- staged upload, OMERO CLI import, SEM-EDX parsing, job lifecycle
- `plugins/import-plugin-workflow.md` -- end-to-end import workflow, native OME-Zarr routing, managed-repository handoff
- `plugins/admin-tools-plugin.md` -- log exploration, resource monitoring, storage analytics, diagnostics
- `plugins/admin-tools-workflow.md` -- quota enforcement lifecycle, log exploration pipeline, resource monitoring proxy
- `plugins/imaris-connector-plugin.md` -- async Imaris export, Celery worker, OMERO CLI launch path
- `plugins/imaris-connector-workflow.md` -- Celery task dispatch, script execution, status polling, download
- `plugins/omero-web-zarr-plugin.md` -- store-backed OME-Zarr preview, rendering, raw/preview endpoint contracts, downloads
- `plugins/omero-web-zarr-workflow.md` -- request/response workflow for preview-safe Vizarr browsing and store-backed downloads

## 4. Plugin Help

- `help/omeroweb_omp_plugin_help.md` -- end-user help for Filename & Metadata Manager
- `help/omeroweb_import_help.md` -- end-user help for Import plugin
- `help/omeroweb_admin_tools_help.md` -- end-user help for Admin Tools

## 5. Operations

- `operations/monitoring.md` -- Prometheus, Grafana, Loki, Alloy, exporters, dashboards, alerts
- `operations/installation-permissions.md` -- ownership, modes, writable paths, and install/update/bootstrap permission model
- `operations/postgres-maintenance.md` -- VACUUM ANALYZE, REINDEX CONCURRENTLY, cron schedule
- `operations/code-scanning.md` -- GitHub code scanning workflow, SARIF uploads, triage and rollout guidance
- `RELIABILITY.md` -- startup determinism, health checks, incident classes
- `SECURITY.md` -- secrets management, image pinning, input validation, access control, post-build vulnerability scanning, security hardening

## 6. Planning and Design

- `DESIGN.md` -- design principles: explicit contracts, modularity, environment-driven config
- `FRONTEND.md` -- Django template patterns, plugin-scoped UI, asset management
- `PLANS.md` -- planning model for changes (PR-level, execution plans, debt tracking)
- `PRODUCT_SENSE.md` -- user personas, reliability over speed, operational impact awareness
- `QUALITY_SCORE.md` -- quality scorecard by domain with grades and improvement targets
- `design-docs/index.md` -- design document catalog
- `design-docs/acquisition-metadata-search-options.md` -- feasibility study and three options for OMERO.web acquisition-metadata search
- `exec-plans/active/knowledge-base-bootstrap.md` -- active execution plan
- `exec-plans/active/repo-feature-capability-roadmap.md` -- grounded roadmap of candidate new product and platform capabilities
- `exec-plans/active/repo-quality-skills-hooks-actions.md` -- skills, git hooks, GitHub Actions, and repo settings to raise quality
- `exec-plans/active/repo-improvements-and-fixes-backlog.md` -- prioritized backlog of concrete fixes and maintainability work
- `exec-plans/tech-debt-tracker.md` -- known technical debt items
- `product-specs/index.md` -- product specification catalog
- `product-specs/new-user-onboarding.md` -- new user onboarding product specification

## 7. Troubleshooting

- `troubleshooting/common.md` -- service health, plugin routes, uploads, admin tools, database, Docker
- `troubleshooting/branding-logo-fallback.md` -- login-logo fallback rules, repository logo recovery, and measured before/after validation
- `troubleshooting/imaris-export.md` -- auth regressions, processor diagnostics, CLI validation, recovery

## 8. Reference

- `reference/service-endpoints.md` -- infrastructure ports, plugin routes, proxy forwarding
- `reference/release-notes.md` -- release history and change documentation template
- `generated/db-schema.md` -- generated schema artifacts (reserved)
- `references/design-system-reference-llms.txt` -- agent-facing design system notes
- `references/docker-compose-llms.txt` -- agent-facing Docker Compose reference notes
