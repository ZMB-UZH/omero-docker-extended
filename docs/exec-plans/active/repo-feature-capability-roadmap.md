# Execution Plan: Repo Feature and Capability Roadmap

## Goal

Define a pragmatic, repo-grounded roadmap of new product and platform capabilities for this OMERO distribution. The focus is on high-value features that fit the existing architecture, use the current plugin and operations surface, and avoid speculative work that is not supported by the codebase.

## Survey Basis

This roadmap is based only on repository evidence already present in the workspace, including:

- `README.md` and `ARCHITECTURE.md` for scope, topology, and dependency boundaries.
- `docs/index.md`, `docs/QUALITY_SCORE.md`, `docs/PLANS.md`, `docs/PRODUCT_SENSE.md`, `docs/RELIABILITY.md`, and `docs/SECURITY.md` for stated priorities and constraints.
- `docs/plugins/*.md` for plugin-specific capabilities and gaps.
- `docs/design-docs/acquisition-metadata-search-options.md` for a prior feasibility study and design direction.
- `env/omeroserver_example.env`, `env/omeroweb_example.env`, and `env/omero-celery_example.env` for current runtime features and configurable controls.
- `.github/workflows/*.yml` and `.github/dependabot.yml` for current quality automation and supply-chain coverage.
- Major plugin and service code in `omeroweb_omp_plugin/`, `omeroweb_import/`, `omeroweb_admin_tools/`, `omero_imaris_connector/`, and `omero_plugin_common/`.

No external product research is assumed beyond what is already captured in the repository.

## Current Platform Baseline

The current platform is already strong in a few specific areas:

- OMERO is deployed as a multi-container stack with pinned images, environment-driven configuration, health checks, and separate core and plugin databases.
- The OMP plugin already supports filename parsing, AI-assisted regex help, annotation writes, variable-set persistence, rate limiting, and plugin-owned cleanup.
- The Import plugin already supports staged uploads, chunked transfer, OMERO CLI import, grouped import planning, SEM-EDX support, and long-running compatibility handling.
- The Admin Tools plugin already exposes Loki log search, Grafana and Prometheus proxying, resource monitoring, storage analytics, quota management, and diagnostics.
- The Imaris connector already has Celery-backed async execution, OMERO CLI launch, job-service support, and export-download plumbing.
- The repo already has docs structure linting, security code scanning, Dependabot, and a meaningful set of regression tests.

The roadmap below builds on those foundations rather than replacing them.

## Recommended Features

### 1. Universal metadata search inside OMERO.web

Status: implemented in the Tools plugin as `Enhanced search`.

Why it fits: regular users can opt in to a user-scoped metadata index for their own images, while OMERO visibility is rechecked before results are shown.

Main dependency or risk: keep extraction explicit, compact, and scope-filtered so indexed metadata stays searchable without cross-user leakage.

### 2. Saveable and shareable import profiles

Why it fits: the Import plugin already persists user settings and special-method settings, and the repo repeatedly emphasizes environment-driven, reproducible behavior.

Enabling building blocks already present: `omeroweb_import/services/data_store.py`, `omeroweb_import/views/user_settings_view.py`, `omeroweb_import/views/special_method_settings_view.py`, and the grouped import planning logic.

Main dependency or risk: profile versioning. Import profiles need schema evolution rules so future upload changes do not break old saved settings.

### 3. Import preflight report before upload commit

Why it fits: large imports are already a first-class concern, and the current codebase spends significant effort on compatibility scanning, format detection, and timeout control.

Enabling building blocks already present: `omeroweb_import/views/core_functions.py`, `omeroweb_import/services/import_management/workflow_service.py`, `_build_import_units`, and the long-running scan timeout controls in `env/omeroweb_example.env`.

Main dependency or risk: response time. The preflight report must stay asynchronous or narrowly bounded so it does not reintroduce Gunicorn timeout failures.

### 4. Import job replay and retry controls

Why it fits: the Import plugin already stores job state, staged files, and terminal status, which is a good base for controlled retries after transient failures.

Enabling building blocks already present: `omero_plugin_common/tmp_cleanup.py`, `omeroweb_import/services/jobs/job_storage.py`, `omeroweb_import/views/index_view.py`, and the job lifecycle endpoints.

Main dependency or risk: idempotency. A retry path must not duplicate uploads, annotations, or datasets.

### 5. Import history and audit timeline

Why it fits: operators and scientists both need to understand what was imported, when, and why a job failed or succeeded.

Enabling building blocks already present: job JSON state, status polling, OMERO object lookup after CLI import, and the monitoring/logging stack.

Main dependency or risk: retention policy. Audit data needs a clear lifetime and storage location so it does not become another unbounded temp store.

### 6. Plugin-wide structured metrics

Why it fits: `docs/QUALITY_SCORE.md` explicitly calls out the absence of plugin-specific application metrics.

Enabling building blocks already present: Prometheus, Grafana, Loki, the Admin Tools observability surface, and the plugin request/job code paths.

Main dependency or risk: cardinality. Metrics must be low-cardinality and intentionally designed or they will overload Prometheus and Grafana queries.

### 7. End-to-end import outcome verification dashboard

Why it fits: the Import plugin already has rich job outcomes, and the repo already has Prometheus/Grafana dashboards and a root-only admin UI.

Enabling building blocks already present: `omeroweb_admin_tools/views/index_view.py`, `docs/operations/monitoring.md`, and the import job/result plumbing.

Main dependency or risk: signal quality. The dashboard must distinguish successful object creation from partial failures and late thumbnail or cleanup errors.

### 8. OMP annotation lifecycle and provenance view

Why it fits: the OMP plugin already tracks plugin-owned annotations via hashing, and users need a clearer way to inspect what was added and by which job.

Enabling building blocks already present: `omeroweb_omp_plugin/services/core.py`, `omeroweb_omp_plugin/views/delete_plugin_view.py`, `omeroweb_omp_plugin/views/job_view.py`, and hash-based ownership markers.

Main dependency or risk: provenance correctness. The UI must never overstate ownership or deleteability for annotations the plugin did not create.

### 9. AI-assisted parsing review workflow

Why it fits: the OMP plugin already offers AI-assisted regex help and provider credential storage, but the workflow can be made more reviewable and safer.

Enabling building blocks already present: `omeroweb_omp_plugin/services/ai_assist.py`, `omeroweb_omp_plugin/services/ai_providers.py`, `omeroweb_omp_plugin/views/ai_credentials_view.py`, and rate limiting.

Main dependency or risk: provider drift. The workflow should avoid coupling to one vendor or model naming scheme.

### 10. Acquisition and filename taxonomy templates

Why it fits: both OMP and Import depend on consistent user interpretation of file naming and metadata fields, and the repo already centers scientific nomenclature.

Enabling building blocks already present: REMBI-aligned defaults, variable-set storage, filename parsing utilities, and the documentation system.

Main dependency or risk: scope creep. Taxonomy templates should remain a starter kit, not a rigid ontology project.

### 11. Group-aware storage and quota policy recommendations

Why it fits: Admin Tools already calculates storage usage and manages quotas, but the current system still leaves operators to infer policy by hand.

Enabling building blocks already present: `omeroweb_admin_tools/services/storage_quotas.py`, quota reconciliation, `docs/operations/monitoring.md`, and storage analytics.

Main dependency or risk: false confidence. Any recommendation engine must be explicit about whether it is advisory or enforceable.

### 12. Better service health explanation for operators

Why it fits: the repo already has health checks, Docker inspection logic, and troubleshooting docs, but operators still need clearer failure classification.

Enabling building blocks already present: `docs/RELIABILITY.md`, `omeroweb_admin_tools/services/system_diagnostics.py`, blackbox probes, and compose health data.

Main dependency or risk: overfitting. Explanations should stay generic enough to survive environment differences.

### 13. CI quality gate expansion

Why it fits: the repo already has docs linting and security scanning, but there is no general quality gate covering unit tests, formatting, and repository policy checks in one consistent place.

Enabling building blocks already present: `.github/workflows/docs-knowledge-base.yml`, `.github/workflows/security-code-scanning.yml`, and the existing regression suite.

Main dependency or risk: workflow sprawl. New checks should be composed carefully so CI stays understandable and fast enough to use regularly.

### 14. Pinned-dependency and action hygiene hardening

Why it fits: `docs/operations/code-scanning.md` and `.github/dependabot.yml` already show supply-chain awareness, but there is room for tighter GitHub hygiene.

Enabling building blocks already present: Dependabot, Scorecard, workflow files, and the existing pinning policy in docs.

Main dependency or risk: maintenance burden. Commit-SHA pinning and update automation need a clear ownership model or they will drift.

### 15. Guided onboarding and recovery flows

Why it fits: the repo already has onboarding docs, troubleshooting docs, and installation scripts. The next step is to turn those into more guided operator flows.

Enabling building blocks already present: `docs/product-specs/new-user-onboarding.md`, `docs/troubleshooting/common.md`, installation transcripts, and startup/bootstrap scripts.

Main dependency or risk: stale instructions. Any guided flow must remain synchronized with the installation and runtime scripts or it will become misleading.

## Strongest Near-Term Bets

These are the highest-confidence ideas because they line up most directly with code that already exists:

1. Universal metadata search inside OMERO.web.
   The Tools plugin now provides the first implementation; remaining work should focus on verification, performance, and operator visibility.
2. Import preflight report before upload commit.
   The import path already performs grouping, compatibility scanning, and timeout-aware planning. Exposing that work as a user-visible report would create immediate value without inventing a new subsystem.
3. Import job replay and retry controls.
   Job state, staged payloads, and deferred cleanup already exist. The missing piece is a supported recovery workflow rather than new storage machinery.
4. Plugin-wide structured metrics.
   The monitoring stack is already in place, and the repo's own quality docs explicitly call out missing plugin metrics. This is one of the fastest ways to improve both operator experience and future development safety.
5. OMP annotation lifecycle and provenance view.
   The plugin already computes ownership hashes and supports plugin-only deletion. A provenance UI is a natural extension that would make the existing behavior more trustworthy and easier to operate.

## Ideas To Delay Until the Foundation Work Lands

- Batch or project-level Imaris export should wait until the queue, retry, and observability story is stronger, otherwise it will amplify current operational blind spots.
- External integration events and webhook delivery should wait until import and export outcomes are modeled more consistently, or downstream systems will receive weak or ambiguous event semantics.
- Broad guided onboarding flows should follow the docs-drift cleanup work, or they will hard-code instructions that are already inconsistent across the repo.

## Recommended Sequencing

1. Prioritize features that reduce current pain in the core workflows: metadata search hardening, better import preflight, and import outcome verification.
2. Next, tighten operator visibility with structured metrics, health explanations, and quota guidance.
3. Then expand user-facing quality of life features around import profiles, OMP provenance, and AI-assisted parsing review.
4. Finally, push the broader repo-quality and supply-chain improvements, including CI quality gates and action/dependency hygiene.

The guiding rule is to ship workflow value before polishing the automation around it, while still keeping the automation strong enough to prevent regressions.

## Progress Log

- 2026-03-22: Created the first repo-grounded feature roadmap draft from the current docs, workflows, env templates, and plugin implementations.
- 2026-03-22: Added a near-term shortlist and explicit defer list so approval can focus on the strongest first-wave roadmap items.

## Decision Log

- Decision: keep the roadmap anchored to current repository evidence only. No external roadmap items were added unless the repo already pointed in that direction.
- Decision: include both user-facing capabilities and platform-quality features. This repo is a full deployment, so platform improvements are product features, not side work.
- Decision: avoid implementation detail. The goal is to identify the right work, not to pre-design code before the roadmap is approved.
