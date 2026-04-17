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
- `plugins/tools-plugin.md` -- user-facing Tools launcher, enhanced-search indexing, saved queries, sync-state flow
- `plugins/admin-tools-plugin.md` -- log exploration, resource monitoring, storage analytics, diagnostics
- `plugins/admin-tools-workflow.md` -- quota enforcement lifecycle, log exploration pipeline, resource monitoring proxy
- `plugins/imaris-connector-plugin.md` -- async Imaris export, Celery worker, OMERO CLI launch path
- `plugins/imaris-connector-workflow.md` -- Celery task dispatch, script execution, status polling, download
- `plugins/omero-web-zarr-plugin.md` -- store-backed OME-Zarr preview, rendering, raw/preview endpoint contracts, downloads
- `plugins/omero-web-zarr-workflow.md` -- request/response workflow for preview-safe Vizarr browsing and store-backed downloads

## 4. Plugin Help

- `help/omeroweb_omp_plugin_help.md` -- end-user help for Filename & Metadata Manager
- `help/omeroweb_import_help.md` -- end-user help for Import plugin
- `../omeroweb_tools/templates/omeroweb_tools/help.html` -- HTML user help for Tools / Enhanced search
- `help/omeroweb_admin_tools_help.md` -- end-user help for Admin Tools

## 5. Operations

- `operations/monitoring.md` -- Prometheus, Grafana, Loki, Alloy, exporters, dashboards, alerts
- `operations/installation-permissions.md` -- ownership, modes, writable paths, and install/update/bootstrap permission model
- `operations/repository-sync-safety.md` -- safe cross-repository file sync rules, branch-history guardrails, and recovery steps for recent branch-root drift
- `operations/postgres-maintenance.md` -- VACUUM ANALYZE, REINDEX CONCURRENTLY, cron schedule
- `operations/code-scanning.md` -- GitHub code scanning workflow, SARIF uploads, triage and rollout guidance
- `operations/managed-repository-rca-2026-03-25.md` -- root cause analysis for managed repository path resolution incident (missing OMERO_DATA_DIR/OMERO_DIR)
- `RELIABILITY.md` -- startup determinism, health checks, incident classes
- `SECURITY.md` -- secrets management, image pinning, input validation, access control, post-build vulnerability scanning, security hardening

## 6. Planning and Design

- `DESIGN.md` -- design principles: explicit contracts, modularity, environment-driven config
- `FRONTEND.md` -- Django template patterns, plugin-scoped UI, asset management
- `PLANS.md` -- planning model for changes (PR-level, execution plans, debt tracking)
- `PRODUCT_SENSE.md` -- user personas, reliability over speed, operational impact awareness
- `QUALITY_SCORE.md` -- quality scorecard by domain with grades and improvement targets
- `design-docs/index.md` -- design document catalog
- `design-docs/acquisition-metadata-search-options.md` -- research-backed design study and five selective-index plans for OMERO.web acquisition-metadata search
- `design-docs/python-acceleration-options.md` -- investigation of automatic Python acceleration options, Cython limits, and ranked future paths for this repository
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

- `reference/ai-agent-context-routing.md` -- minimal task router for docs, code roots, skills, and split test lanes
- `reference/ai-agent-runtime-playbook.md` -- deep Git, Docker, OMERO CLI, testing, logging, and joined-session procedure for AI agents
- `reference/ai-agent-skills.md` -- harness-neutral catalog for repo-local AI-agent skills under `.agents/skills/`
- `reference/ai-agent-web-research-stack.md` -- safe public-web research, extraction, browser fallback, and source-audit pattern for AI agents
- `reference/ai-agent-integrations.md` -- platform adapter map for Copilot, Cursor, Claude, Gemini, shared skill loaders, and the single-session policy
- `reference/ai-agent-upstream-sources.md` -- pinned upstream provenance for ECC-derived local skills and vendored caveman prompt references
- `reference/ai-agent-security-prevention-playbook.md` -- canonical anti-regression security playbook for AI agents; external best-practice links, concrete examples, and document ownership rules
- `reference/plugin-help-page-style-guide.md` -- canonical user-help formatting, screenshot, collapse, and verification rules for plugin help pages
- `reference/service-endpoints.md` -- infrastructure ports, plugin routes, proxy forwarding
- `reference/release-notes.md` -- release history and change documentation template
- `reference/python-style-and-linting.md` -- Ruff formatter/lint policy, Vulture dead-code gate, CI workflow, pre-commit usage
- `reference/code-scanning-resolved-findings.md` -- resolved scanner history and per-rule prevention lessons from the full closed-alert set
- `generated/db-schema.md` -- generated schema artifacts (reserved)
- `references/design-system-reference-llms.txt` -- agent-facing design system notes
- `references/docker-compose-llms.txt` -- agent-facing Docker Compose reference notes
