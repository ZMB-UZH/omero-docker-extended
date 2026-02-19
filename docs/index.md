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
- `plugins/upload-plugin.md` -- staged upload, OMERO CLI import, SEM-EDX parsing, job lifecycle
- `plugins/admin-tools-plugin.md` -- log exploration, resource monitoring, storage analytics, diagnostics
- `plugins/imaris-connector-plugin.md` -- async Imaris export, Celery worker, script processor retry

## 4. Operations

- `operations/monitoring.md` -- Prometheus, Grafana, Loki, Alloy, exporters, dashboards, alerts
- `operations/postgres-maintenance.md` -- VACUUM ANALYZE, REINDEX CONCURRENTLY, cron schedule
- `operations/code-scanning.md` -- GitHub code scanning workflow, SARIF uploads, triage and rollout guidance
- `RELIABILITY.md` -- startup determinism, health checks, incident classes
- `SECURITY.md` -- secrets management, image pinning, input validation, access control

## 5. Planning and Design

- `DESIGN.md` -- design principles: explicit contracts, modularity, environment-driven config
- `FRONTEND.md` -- Django template patterns, plugin-scoped UI, asset management
- `PLANS.md` -- planning model for changes (PR-level, execution plans, debt tracking)
- `PRODUCT_SENSE.md` -- user personas, reliability over speed, operational impact awareness
- `QUALITY_SCORE.md` -- quality scorecard by domain with grades and improvement targets
- `design-docs/index.md` -- design document catalog
- `exec-plans/active/knowledge-base-bootstrap.md` -- active execution plan
- `exec-plans/tech-debt-tracker.md` -- known technical debt items
- `product-specs/index.md` -- product specification catalog

## 6. Troubleshooting

- `troubleshooting/common.md` -- service health, plugin routes, uploads, admin tools, database, Docker
- `troubleshooting/imaris-export.md` -- Celery config, worker activity, script processors, recovery

## 7. Reference

- `reference/service-endpoints.md` -- infrastructure ports, plugin routes, proxy forwarding
- `reference/release-notes.md` -- release history and change documentation template
- `generated/db-schema.md` -- generated schema artifacts (reserved)
- `references/design-system-reference-llms.txt` -- agent-facing design system notes
- `references/docker-compose-llms.txt` -- agent-facing Docker Compose reference notes
