# Execution Plan: Repo Quality Skills, Hooks, and Actions

## Goal

Define a practical quality-improvement stack for this repository that makes
agent work, local development, and GitHub automation more consistent and less
error-prone. The plan is intentionally grounded in the current repo state:
there is already a docs linter, security scanning workflow, Dependabot, and
extensive plugin/runtime code, but there is not yet a broad quality gate that
covers formatting, linting, tests, and workflow hygiene together.

## Observed Baseline

- Documentation structure is enforced by `tools/lint_docs_structure.py` and a dedicated docs workflow.
- Security scanning is already present through `security-code-scanning.yml`, with CodeQL, Trivy, Semgrep, Bandit, Hadolint, DevSkim, OSV Scanner, and Scorecard.
- Dependabot exists, but coverage is narrow: pip updates only for `omeroweb_omp_plugin`, plus Docker updates at the repo root and `/docker`.
- The repo has many tests, but CI does not currently show a general test matrix or per-package regression lane in the checked-in workflows.
- There is no visible repo-local hook framework such as pre-commit, no checked-in `.pre-commit-config.yaml`, `.editorconfig`, `pyproject.toml`, `pytest.ini`, `ruff.toml`, or `mypy.ini`, and no obvious unified formatting/lint policy in the repository root.
- The codebase is large and operationally sensitive: Docker Compose, startup scripts, OMERO session handling, plugin databases, and runtime bootstrap logic all need deterministic behavior.
- The existing security scan notes still call out meaningful classes of findings, including path injection, log injection, raw SQL usage, `@csrf_exempt` views, subprocess-injection review points, and Dockerfile USER issues.
- Workflow hygiene is uneven: pinned versions are common, but GitHub Actions use tag pins rather than commit SHA pins, and the repository still relies on manual conventions for several maintenance behaviors.
- The repo already documents a precise split-pytest policy in `AGENTS.md`, but the checked-in workflows do not enforce that policy automatically.
- The code-scanning runbook explicitly calls out Scorecard findings around action pinning and a missing root `SECURITY.md`, so the repo already has evidence for supply-chain and policy hardening work.

## Recommended Skills

These are repo-local or agent-facing capabilities that would improve the quality of future changes.

| Skill                            | Why this repo needs it                                                                                                                       | Typical trigger                                                | Priority |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | -------- |
| `docs-knowledge-maintainer`      | The repo treats docs as operational contract material, not optional prose. Cross-links, plan files, and operator guidance must stay current. | Any change to behavior, topology, env vars, or troubleshooting | Now      |
| `plugin-regression-triager`      | Tests are split across package-local suites and top-level regression tests. Choosing the wrong lane wastes time or produces false failures.  | Any plugin code change                                         | Now      |
| `omero-runtime-verifier`         | This repo has strict procedure around service users, container venvs, Loki-first log triage, and session-safe diagnostics.                   | Docker, OMERO CLI, or runtime debugging work                   | Now      |
| `security-finding-triager`       | The repo already carries an explicit code-scanning backlog. Someone needs to map scanner language back to real code and real risk.           | CodeQL/Semgrep/Bandit/Scorecard findings                       | Now      |
| `env-contract-reviewer`          | Configuration is intentionally environment-driven. Drift toward hard-coded paths, ports, or defaults is one of the main failure modes.       | Env file, startup, or compose changes                          | Now      |
| `session-lifecycle-reviewer`     | The Import and Imaris paths both rely on joined sessions, background work, and CLI launches that can accidentally kill live sessions.        | Joined session, background connection, or Celery work          | Now      |
| `import-pipeline-refactor-guide` | The import code is mid-transition between giant legacy modules and service-layer extraction. Refactors need a stable playbook.               | `omeroweb_import` refactor or cleanup PRs                      | Next     |
| `workflow-supply-chain-reviewer` | GitHub Actions, Dependabot, and security policy changes affect the repo's integrity even when app code is unchanged.                         | Workflow or Dependabot edits                                   | Next     |
| `incident-to-regression-test`    | The repo already values regression tests strongly. Every production fix should become a durable test rather than a one-off patch.            | Bugfixes after incidents or operator reports                   | Next     |
| `release-readiness-reviewer`     | Startup, Dockerfile, env-template, and docs changes need coordinated validation and release-note discipline.                                 | Alpha/main release prep                                        | Later    |

## Recommended Hooks

These should be local, fast, and deterministic. They are meant to fail early before a pull request is opened.

| Hook                         | What it should run                                                               | Why it matters here                                                                                                 | Priority |
| ---------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | -------- |
| `pre-commit:docs-structure`  | `python3 tools/lint_docs_structure.py`                                           | The repo already enforces docs structure; this is the obvious first local guardrail.                                | Now      |
| `pre-commit:python-compile`  | `python3 -m py_compile` on changed Python files                                  | Useful fallback when the full Django/OMERO runtime is not available locally.                                        | Now      |
| `pre-commit:shell-lint`      | `bash -n` plus `shellcheck` for changed `.sh` files                              | Startup and install scripts are critical-path logic, not helper scripts.                                            | Now      |
| `pre-commit:workflow-lint`   | `actionlint` and YAML validation for `.github/workflows/*.yml`                   | Workflow breakage is costly and currently only caught after push.                                                   | Now      |
| `pre-commit:dockerfile-lint` | `hadolint` on changed Dockerfiles                                                | The repo already treats Dockerfiles as security-sensitive infrastructure code.                                      | Now      |
| `pre-commit:secret-surface`  | block edits/commits of operator-managed secrets and runtime-only env files       | The repo explicitly forbids AI edits to `env/omero_secrets.env` and relies on example files as canonical templates. | Now      |
| `pre-push:split-pytest`      | run only the relevant test directory, one suite at a time                        | `AGENTS.md` explicitly requires split pytest execution to avoid conftest cross-contamination.                       | Next     |
| `pre-push:docs-drift`        | grep for stale plugin names, stale service counts, and missing env-file guidance | The repo already shows drift around `omeroweb_upload`, service counts, and compose command examples.                | Next     |
| `pre-push:compose-contract`  | lightweight compose/workflow sanity checks when Docker or env templates change   | Compose failures in this repo often come from env interpolation and runtime permissions, not syntax alone.          | Next     |

## Recommended GitHub Actions

The current workflows cover docs validation and security scanning, but quality would improve if the repository added a broader CI layer.

| Workflow                                          | What it should do                                                                                                                                                                         | Why it is grounded in this repo                                                      | Priority |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------- |
| `ci-fast.yml`                                     | run split tests for `tests/`, `omero_plugin_common/tests/`, `omeroweb_imaris_connector/tests/`, `omeroweb_admin_tools/tests/`, `omeroweb_omp_plugin/tests/`, and `omeroweb_import/tests/` | These exact suites are already prescribed in `AGENTS.md`.                            | Now      |
| `lint-fast.yml`                                   | run `python3 -m py_compile`, docs lint, and lightweight static checks on changed files                                                                                                    | The repo lacks a normal fast feedback loop outside docs/security workflows.          | Now      |
| `shell-and-workflow-lint.yml`                     | run `shellcheck`, `actionlint`, and YAML validation                                                                                                                                       | The repo has many shell and workflow files but no dedicated enforcement lane.        | Now      |
| `docker-smoke.yml`                                | build changed Dockerfiles and run targeted smoke/contract tests                                                                                                                           | Dockerfiles and startup wrappers are central to repo correctness.                    | Now      |
| `docs-drift.yml`                                  | catch stale plugin names, stale service counts, and missing index entries                                                                                                                 | Current repo state already shows this class of drift.                                | Now      |
| `security-code-scanning.yml` `security-delta` job | fail when new code-scanning alerts are introduced by the current security workflow run                                                                                                    | The security runbook already defines severity SLAs and merge expectations.           | Done     |
| `action-pin-policy.yml`                           | verify GitHub Actions are pinned to approved SHAs and least-privilege permissions                                                                                                         | Scorecard findings and tag-pinned actions already point to this gap.                 | Next     |
| `release-hygiene.yml`                             | require release-note/docs updates when startup, env, or operator behavior changes                                                                                                         | The repo says docs must change when behavior changes, but the rule is not automated. | Next     |
| `dependency-hygiene.yml`                          | validate Dependabot coverage and optionally inventory dependency surfaces                                                                                                                 | Dependabot exists but only covers a narrow subset of the repo.                       | Later    |
| `nightly-stack-validation.yml`                    | run a slower compose-level validation path on a schedule or manual dispatch                                                                                                               | The repo already notes the absence of a full deployment validation suite.            | Later    |

## Related Repo Settings

- Require `docs-knowledge-base`, `ci-fast`, and security scanning to pass before merge.
- Add branch protection for `main` and `alpha` if both are expected to accept production changes.
- Add `CODEOWNERS` coverage for `.github/workflows/`, `startup/`, `installation/`, `docker/`, `env/*_example.env`, and `docs/operations/`.
- Require review for changes to workflows, startup scripts, Dockerfiles, and environment templates.
- Limit GitHub token permissions in workflows to the minimum needed for each job.
- Pin GitHub Actions by commit SHA where practical.
- Add a root `SECURITY.md` that forwards to `docs/SECURITY.md` so GitHub-native security features can find it.
- Keep the repo-local doc index and plan tracker authoritative when new planning files are added.

## Recommended Order

1. Add `ci-fast.yml`, `lint-fast.yml`, and the local `pre-commit` hooks that mirror them.
2. Add `shell-and-workflow-lint.yml` and `docker-smoke.yml` so infrastructure changes stop bypassing normal CI.
3. Add docs-drift checks and the root `SECURITY.md` so repository policy matches what the docs already say.
4. Tighten workflow hygiene with SHA pinning, `CODEOWNERS`, and branch protection.
5. Expand Dependabot and add slower nightly or manual full-stack validation only after the fast lanes are stable.
6. Revisit the skill set after the automation layer lands and trim or merge skills based on real maintenance behavior.

## Progress Log

- 2026-03-22: Drafted the planning scope after surveying repository docs, workflows, plugin code, and existing quality trackers.
- 2026-03-22: Identified the current quality baseline: docs linting and security scanning exist, but there is no broad test/lint/hook layer yet.
- 2026-03-22: Expanded the plan into concrete skill, hook, workflow, and repo-setting recommendations tied to the checked-in gaps.

## Decision Log

- Use repository evidence, not generic best practices, as the basis for the recommendations.
- Keep repo-local hooks fast and deterministic so they can run before CI.
- Treat GitHub Actions as the enforcement layer and local hooks as the early warning layer.
- Prioritize changes that reduce regressions in startup scripts, plugin runtime behavior, and workflow hygiene before introducing more optional quality tooling.
