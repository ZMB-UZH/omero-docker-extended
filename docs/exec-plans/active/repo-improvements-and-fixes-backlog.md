# Execution Plan: Repo Improvements and Fixes Backlog

## Goal

Create a prioritized, evidence-based backlog for the next tranche of repository and platform work. This plan is meant to be a decision aid, not an implementation log: each item should be concrete, tied to observed code or documentation, and ranked by operational or quality impact.

## Evidence Basis

This backlog is grounded in the current repository state and documentation:

- `docs/QUALITY_SCORE.md` already records missing plugin test coverage, missing SLOs, missing alert rules, and missing integration validation.
- `docs/exec-plans/tech-debt-tracker.md` repeats the same open debt items and adds docs linting, plugin metrics, secret rotation, and integration testing.
- `docs/operations/code-scanning.md` documents live security findings, including critical SSRF, path injection, log injection, raw SQL, and subprocess risks.
- `README.md`, `ARCHITECTURE.md`, and plugin guides show a large, multi-container deployment with four major plugins and a shared library.
- The codebase contains very large modules, especially `omeroweb_import/views/core_functions.py`, `omeroweb_admin_tools/views/index_view.py`, and `omeroweb_admin_tools/services/log_query.py`.
- Test distribution is uneven: some packages have focused coverage, but the biggest plugin modules have the most work and the repo still relies heavily on top-level regression tests.
- The GitHub workflow set now covers docs validation, tests, Ruff, Vulture, super-linter, and security scanning, but it still lacks deployment-style validation, dedicated shell/workflow linting, and broader docs-drift enforcement.
- The repository metadata and docs still show some drift and overlap, including inconsistent container counts and legacy references to the removed `omeroweb_upload` plugin.

## P0 Now

| Item                                                                             | Evidence                                                                                                                                                                      | Why it is P0                                                                                                |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Add targeted deployment and infrastructure validation lanes                      | `tests.yml` now enforces the split pytest suites, but the repo still has no workflow that builds changed Dockerfiles, smoke-tests startup wrappers, or validates deployment wiring. | Application correctness is gated, but infrastructure and rollout regressions can still bypass normal CI.   |
| Maintain SHA-pinned GitHub Actions and add workflow-policy linting              | The workflows are now pinned by full commit SHA, but there is still no dedicated `actionlint`/workflow-policy lane to keep them that way.                                   | Supply-chain hardening is only durable if the repo also detects drift back to weaker workflow hygiene.      |
| Keep root `SECURITY.md` and `docs/SECURITY.md` synchronized                      | The root `SECURITY.md` now exists and forwards GitHub-native surfaces to `docs/SECURITY.md`.                                                                                | Security-policy drift would break GitHub-native discoverability and create conflicting guidance.            |
| Close the documented critical SSRF findings                                      | The runbook records critical `py/partial-ssrf` findings in `omeroweb_admin_tools/views/index_view.py` and `omeroweb_omp_plugin/services/ai_assist.py`.                        | These are the highest-severity findings in the repo's own tracker.                                          |
| Triage and close the documented high-severity path/log/raw-SQL/subprocess issues | The runbook also records high or error-level findings for path injection, log injection, raw SQL, subprocess injection, and regex injection.                                  | These are active security/robustness risks in core workflow code.                                           |
| Fix docs drift around compose env-file usage                                     | `AGENTS.md` requires installation paths, secrets, and `env/omeroserver.env`, but some checked-in docs still show only a partial compose env-file set.                         | This can lead operators directly into failing commands.                                                     |
| Fix docs drift around service counts                                             | `AGENTS.md` says 17 containers, `README.md` says 19 runtime containers, and `ARCHITECTURE.md` says 20 containers.                                                             | Repo-local knowledge is supposed to be authoritative. Right now it disagrees with itself.                   |
| Finish the `omeroweb_upload` to `omeroweb_import` cleanup                        | Current tests and docs still reference `omeroweb_upload`, including `tests/test_omeroweb_startup_script_regressions.py` and `docs/troubleshooting/branding-logo-fallback.md`. | Partial rename state creates ambiguity for contributors and future automation.                              |
| Finish Import plugin canonicalization                                            | `omeroweb_import/views/index_view.py` still uses `from .core_functions import *` while a newer `services/` layout also exists.                                                | The import path is the biggest workflow and currently has split ownership.                                  |
| Add focused OMP and Import coverage where the repo already says it is missing    | `docs/QUALITY_SCORE.md` and `docs/exec-plans/tech-debt-tracker.md` both call out missing OMP and Import unit coverage.                                                        | These gaps are already acknowledged and affect the riskiest codepaths.                                      |

## P1 Next

| Item                                                                                                         | Evidence                                                                                                                                | Why it is P1                                                                                      |
| ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Split `omeroweb_import/views/core_functions.py` into smaller modules or complete the service-layer migration | The file is over 5,000 lines and overlaps conceptually with `omeroweb_import/services/*`.                                               | This is a major maintainability risk, but it should follow the P0 correctness gates.              |
| Split `omeroweb_admin_tools/views/index_view.py` by concern                                                  | The file is over 2,200 lines and currently handles proxies, monitoring, storage, quotas, and diagnostics.                               | Large but stable enough to refactor after the immediate correctness/security work.                |
| Split `omeroweb_omp_plugin/views/index_view.py` and `job_view.py`                                            | OMP carries large view modules and very light in-package coverage relative to its size.                                                 | Refactoring here becomes safer once tests are added.                                              |
| Add plugin-level metrics for jobs, parse time, import duration, and export duration                          | `docs/QUALITY_SCORE.md` and `docs/exec-plans/tech-debt-tracker.md` both call this out directly.                                         | The observability stack is ready; the application layer is what is missing.                       |
| Define SLOs and alert rules for the platform                                                                 | The same docs call out missing SLOs/alerts, and `docs/operations/monitoring.md` already lists recommended minimum alerts.               | Strong value, but it depends on agreeing what "healthy" means first.                              |
| Expand the local quality gate and checked-in hook layer                                                     | The repo now has `.pre-commit-config.yaml` and `.ruff.toml`, but it still lacks a broader checked-in hook story for shell/workflow linting and other fast local guards.      | This should follow the CI work so local and remote checks converge.                               |
| Consolidate duplicated plugin-database persistence helpers                                                   | Both OMP and Import implement their own psycopg2 loading, connection handling, and schema-creation patterns.                            | Useful refactor, but not as urgent as shipping tests and security fixes.                          |
| Introduce explicit plugin-db migration/bootstrap ownership                                                   | Data store modules currently create schema on demand during runtime paths.                                                              | This needs design care and should not be rushed into production code paths.                       |
| Centralize OMERO session and CLI helper logic                                                                | Import, Imaris, and startup paths all solve versions of venv/CLI/session resolution.                                                    | Shared helpers will help, but only after the high-risk logic is well tested.                      |
| Audit and reduce the broad `@csrf_exempt` surface                                                            | The codebase still has many write endpoints marked `@csrf_exempt` across OMP, Admin Tools, and Import.                                  | This is important, but the repo should first clarify which endpoints truly require the exemption. |
| Expand Dependabot and repo automation coverage                                                               | `.github/dependabot.yml` currently covers a narrow subset of ecosystems and paths.                                                      | This improves sustainability after the main CI and policy work is in place.                       |
| Expand docs linting from structure checks to drift checks                                                    | The current linter only validates required paths and index tokens, while the repo already exhibits stale names and inconsistent counts. | This will pay off once the first drift fixes land.                                                |

## P2 Later

| Item                                                                         | Evidence                                                                                                             | Why it is P2                                                                      |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Add automated secret rotation support                                        | This already exists in `docs/exec-plans/tech-debt-tracker.md` as a lower-priority item.                              | Valuable, but not before closing the current code and docs gaps.                  |
| Add a reusable execution-plan template for multi-service changes             | The planning model exists, but the debt tracker still calls out a missing plan template.                             | Helpful process improvement, not an immediate platform risk.                      |
| Add fuzz or property-based testing for parser-like logic                     | `docs/operations/code-scanning.md` explicitly notes missing fuzzing integration.                                     | Good long-term safety net after deterministic unit and integration lanes exist.   |
| Add a broader full-deployment test suite with realistic service dependencies | The quality docs already note the absence of a full deployment validation suite.                                     | Better as a second-stage quality investment after fast CI exists.                 |
| Continue reducing giant-module pressure through surgical refactors           | Large files exist across Import, Admin Tools, OMP, and Imaris service code.                                          | This should be continuous maintenance, not a disruptive rewrite.                  |
| Split dev/staging/prod examples or safer default examples                    | `env/omeroweb_example.env` still carries `CONFIG_omero_web_debug=true`, which is easy to copy into real deployments. | Worth fixing, but not before the repo's current correctness and security gaps.    |
| Reduce local repo-status noise from helper-generated artifacts               | The current worktree shows many helper-created `.project-pull.*` directories and runtime artifacts.                  | Repo hygiene matters, but it is below correctness and operator-document accuracy. |
| Strengthen release-note and migration discipline                             | `docs/reference/release-notes.md` exists, but release hygiene is still mostly procedural rather than enforced.       | Best added once CI, docs drift checks, and branch policy are stable.              |

## Recommended Delivery Order

1. Tighten the existing CI with deployment-smoke and workflow-policy lanes first, because they are the cheapest multiplier on every later change.
2. Close the active critical/high security findings with targeted regression coverage.
3. Fix the highest-risk docs drift: env-file commands, service counts, and stale plugin names.
4. Make the Import path canonical, then break up the biggest modules.
5. Add plugin metrics, SLOs, and alert rules once the workflows and tests can keep them honest.
6. Land slower quality investments such as fuzzing, broader deployment suites, secret rotation, and release hygiene after the repo's baseline is stable.

## Progress Log

| Date       | Update                                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------------------------- |
| 2026-03-22 | Created the initial evidence-based backlog from repository docs, workflows, tests, and code structure.                     |
| 2026-03-22 | Expanded the backlog into explicit P0/P1/P2 items tied to named files, documented findings, and observed repository drift. |

## Decision Log

| Date       | Decision                                                                                         | Rationale                                                                                                                                    |
| ---------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-03-22 | Prioritize security closure, test coverage, and integration validation before broader refactors. | These are the highest-leverage items and are directly supported by the current docs and code-scanning evidence.                              |
| 2026-03-22 | Keep the backlog concrete but not implementation-specific.                                       | This preserves flexibility while still giving a usable plan for the next set of PRs.                                                         |
| 2026-03-22 | Treat docs drift as a first-class fix, not cleanup.                                              | In this repo, docs are operational contract material, so inconsistent counts and stale plugin names can mislead operators and future agents. |
