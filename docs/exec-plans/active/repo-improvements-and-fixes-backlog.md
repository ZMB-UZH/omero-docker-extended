# Execution Plan: Repo Improvements and Fixes Backlog

## Goal

Create a prioritized, evidence-based backlog for the next tranche of repository
and platform work. This plan is a decision aid, not an implementation log: each
item should be concrete, tied to observed code or documentation, and ranked by
operational or quality impact.

## Evidence Basis

This backlog is grounded in the current repository state and documentation:

- `docs/QUALITY_SCORE.md` records broad OMP and Import regression coverage, plus
  remaining gaps in deployment/live integration, SLOs, alert rules, plugin
  metrics, and secret rotation.
- `docs/exec-plans/tech-debt-tracker.md` tracks the same remaining operational
  quality gaps without treating OMP/Import as untested packages.
- `docs/operations/code-scanning.md` records the 2026-06-27 live GitHub
  snapshot: 3 open GitHub code-scanning alerts, all repository-level Scorecard
  findings with no file location. The last recorded external DeepSource
  snapshot remains 3 grouped issues / 109 occurrences from 2026-04-27.
  Refresh scanner counts before using this backlog for remediation decisions.
- `README.md`, `ARCHITECTURE.md`, and plugin guides show a large,
  multi-container deployment with five plugin packages and a shared library.
- The codebase contains very large modules, especially
  `omeroweb_import/views/core_functions.py`,
  `omeroweb_admin_tools/views/index_view.py`, and
  `omeroweb_admin_tools/services/log_query.py`.
- Test distribution is stronger than the original backlog stated: OMP has 19
  tracked test modules, Import has 37, and together they contain more than
  33,000 test-source lines. The remaining risk is deployment/live integration,
  edge-case coverage for touched giant modules, and service-boundary smoke
  validation.
- The GitHub workflow set covers docs validation, tests, Ruff, Vulture,
  Super-Linter workflow/Zizmor/Bash validation, release-time image builds, and
  a dedicated deployment-contract lane for Compose rendering, topology, image
  pins, and Buildx checks. It still lacks a dynamic full-stack startup lane and
  broader docs-drift enforcement.
- Remaining `omeroweb_upload` references are either historical archive entries,
  a startup compatibility alias, or tests proving that alias is normalized to
  `omeroweb_import`. Do not remove them as cleanup unless a migration removes
  the compatibility contract and updates its tests.

## P0 Now

| Item | Evidence | Why it is P0 |
| --- | --- | --- |
| Extend deployment contracts with a dynamic full-stack startup lane | `deployment-contracts.yml` validates Compose interpolation, profiles, topology, image pins, and all six local build definitions without mutating image tags. It does not start the complete service stack. | Static deployment drift is gated, but service-boundary startup failures still need runtime evidence. |
| Maintain SHA-pinned GitHub Actions and workflow-policy linting | Workflows are pinned by full commit SHA, and Super-Linter runs both GitHub Actions validation and Zizmor. | Supply-chain hardening lasts only if the repo keeps those checks current and detects drift back to weaker workflow hygiene. |
| Keep root `SECURITY.md` and `docs/SECURITY.md` synchronized | The root `SECURITY.md` forwards GitHub-native surfaces to `docs/SECURITY.md`. | Security-policy drift would break GitHub-native discoverability and create conflicting guidance. |
| Preserve the zero-added-alert gate and close remaining Scorecard governance findings | The live 2026-06-27 snapshot has no open file-level GitHub findings; remaining alerts are `CodeReviewID`, `CIIBestPracticesID`, and `BranchProtectionID`. | The current baseline is strong enough that new findings should be treated as regressions. |
| Add docs-drift guardrails for compose env-file usage | Manual compose examples are aligned on `installation_paths.env`, `env/omero_secrets.env`, and `env/omeroserver.env`, but the repo still lacks a dedicated drift-checking lane for that contract. | Operators rely on those commands directly, so future drift would become an operational outage. |
| Add docs-drift guardrails for service-count and supervisord topology facts | `README.md`, `ARCHITECTURE.md`, `AGENTS.md`, and `docs/references/docker-compose-llms.txt` track Compose counts; `supervisord.conf` now runs four managed programs. | Topology drift would mislead operators and future automation. |
| Protect broad OMP and Import coverage during refactors | Existing OMP and Import suites are substantial, but the largest modules still need focused edge-case tests when touched. | The repo should preserve current coverage strength while reducing giant-module risk. |

## P1 Next

| Item | Evidence | Why it is P1 |
| --- | --- | --- |
| Split `omeroweb_import/views/core_functions.py` into smaller modules or complete the service-layer migration | The file is over 5,000 lines and overlaps conceptually with `omeroweb_import/services/*`. | This is a major maintainability risk, but it should follow the P0 correctness gates. |
| Split `omeroweb_admin_tools/views/index_view.py` by concern | The file is over 2,200 lines and currently handles proxies, monitoring, storage, quotas, and diagnostics. | Large but stable enough to refactor after the immediate correctness and security work. |
| Split `omeroweb_omp_plugin/views/index_view.py` and `job_view.py` | OMP carries large view modules despite broad package-level regression coverage. | Refactoring here is safer when each touched path gets focused tests. |
| Add plugin-level metrics for jobs, parse time, import duration, and export duration | `docs/QUALITY_SCORE.md` and `docs/exec-plans/tech-debt-tracker.md` both call this out directly. | The observability stack is ready; the application layer is what is missing. |
| Define SLOs and alert rules for the platform | The same docs call out missing SLOs and alerts, and `docs/operations/monitoring.md` already lists recommended minimum alerts. | Strong value, but it depends on agreeing what "healthy" means first. |
| Expand the checked-in local hook layer | CI and `tools/run_local_workflow_gates.py` cover shell and workflow linting, while `.pre-commit-config.yaml` currently exposes only Ruff. | Fast optional hooks should mirror proven CI checks without duplicating the complete pre-push matrix. |
| Consolidate duplicated plugin-database persistence helpers | OMP, Import, and Tools each manage psycopg2 access and schema creation patterns. | Useful refactor, but not as urgent as shipping infrastructure validation. |
| Introduce explicit plugin-db migration and bootstrap ownership | Data-store modules currently create schema on demand during runtime paths. | This needs design care and should not be rushed into production code paths. |
| Centralize OMERO session and CLI helper logic | Import, Imaris, and startup paths all solve versions of venv, CLI, and session resolution. | Shared helpers will help, but only after the high-risk logic is well tested. |
| Expand dependency automation coverage | `.github/dependabot.yml` covers actions, CI Python locks, OMP Python dependencies, and Dockerfiles. Dependabot's Docker updater does not parse Compose manifests, so Compose and shell/env build versions still require explicit audited review. | This improves sustainability after the main CI and policy work is in place. |
| Expand docs linting from structure checks to broader drift checks | The current linter validates required paths and index tokens, but broader stale-name and topology drift still relies on narrower regression tests and manual review. | This will pay off once the next round of docs-drift fixes lands. |

## P2 Later

| Item | Evidence | Why it is P2 |
| --- | --- | --- |
| Add automated secret rotation support | This already exists in `docs/exec-plans/tech-debt-tracker.md` as a lower-priority item. | Valuable, but not before closing the current code and docs gaps. |
| Add a reusable execution-plan template for multi-service changes | The planning model exists, but the debt tracker still calls out a missing plan template. | Helpful process improvement, not an immediate platform risk. |
| Add fuzz or property-based testing for parser-like logic | `docs/operations/code-scanning.md` explicitly notes missing fuzzing integration. | Good long-term safety net after deterministic unit and integration lanes exist. |
| Add a broader full-deployment test suite with realistic service dependencies | The quality docs already note the absence of a full deployment validation suite. | Better as a second-stage quality investment after fast CI exists. |
| Continue reducing giant-module pressure through surgical refactors | Large files exist across Import, Admin Tools, OMP, and Imaris service code. | This should be continuous maintenance, not a disruptive rewrite. |
| Reduce local repo-status noise from helper-generated artifacts | Helper-created runtime artifacts can make local status harder to read if not ignored or cleaned. | Repo hygiene matters, but it is below correctness and operator-document accuracy. |
| Strengthen release-note and migration discipline | `docs/reference/release-notes.md` exists, but release hygiene is still mostly procedural rather than enforced. | Best added once CI, docs-drift checks, and branch policy are stable. |

## Recommended Delivery Order

1. Extend the deployment-contract lane with dynamic startup validation while preserving its non-mutating static checks.
2. Preserve the current no-new-file-level-alert baseline and close the remaining Scorecard governance findings.
3. Protect the highest-risk docs contracts: compose env-file commands, topology facts, supervisord process names, and intentional legacy aliases.
4. Preserve the canonical explicit Import surface while breaking up the biggest modules with focused edge-case tests.
5. Add plugin metrics, SLOs, and alert rules once the workflows and tests can keep them honest.
6. Land slower quality investments such as fuzzing, broader deployment suites, secret rotation, and release hygiene after the repo's baseline is stable.

## Progress Log

| Date       | Update                                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------------------------- |
| 2026-03-22 | Created the initial evidence-based backlog from repository docs, workflows, tests, and code structure.                     |
| 2026-03-22 | Expanded the backlog into explicit P0/P1/P2 items tied to named files, documented findings, and observed repository drift. |
| 2026-04-26 | Refreshed the backlog against current tests, scanner snapshots, intentional legacy aliases, and default-branch guidance.   |
| 2026-07-18 | Corrected workflow-linting and release evidence and documented Dependabot's Compose parsing limitation.                    |
| 2026-07-18 | Enabled Bash validation in Super-Linter and cleared the full ShellCheck 0.11.0 repository scan.                            |
| 2026-07-18 | Added non-mutating deployment contracts and removed superseded Import, CSRF, and debug-default backlog entries.            |

## Decision Log

- **2026-03-22**: Prioritize security closure, test coverage, and integration
  validation before broader refactors. These were the highest-leverage items and
  were directly supported by the then-current docs and code-scanning evidence.
- **2026-03-22**: Keep the backlog concrete but not implementation-specific.
  This preserves flexibility while still giving a usable plan for the next set
  of default-branch changes.
- **2026-03-22**: Treat docs drift as a first-class fix, not cleanup. In this
  repo, docs are operational contract material, so inconsistent counts and stale
  plugin names can mislead operators and future agents.
- **2026-04-26**: Stop treating historical scanner findings and intentional
  `omeroweb_upload` compatibility as active. The current code and scanner
  inventory show these are not open file-level GitHub findings or accidental
  stale names in the active product path.
