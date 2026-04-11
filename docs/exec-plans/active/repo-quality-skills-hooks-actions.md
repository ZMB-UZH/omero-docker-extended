# Execution Plan: Repo Quality Skills, Hooks, and Actions

## Goal

Define a practical quality-improvement stack for this repository that makes
agent work, local development, and GitHub automation more consistent and less
error-prone. The plan is intentionally grounded in the current repo state:
there is already docs validation, split-test CI, Ruff, Vulture, super-linter,
security scanning, Dependabot, and extensive plugin/runtime code, but there is
not yet a deployment-smoke or dedicated shell/workflow-lint layer that covers
the infrastructure-heavy parts of this repo.

## Observed Baseline

- Documentation structure is enforced by `tools/lint_docs_structure.py` and a dedicated docs workflow.
- Security scanning is already present through `security-code-scanning.yml`, with CodeQL, Trivy, Semgrep, Bandit, Hadolint, DevSkim, OSV Scanner, and Scorecard.
- Dependabot exists, but coverage is narrow: pip updates only for `omeroweb_omp_plugin`, plus Docker updates at the repo root and `/docker`.
- The checked-in workflows now include `tests.yml`, which runs the split pytest suites, plus dedicated `ruff.yml`, `vulture.yml`, and `super-linter.yml` gates.
- The repo already has a visible local hook and lint surface through `.pre-commit-config.yaml` and `.ruff.toml`, but it still lacks broader checked-in hooks for shell/workflow linting and related fast infrastructure checks.
- The codebase is large and operationally sensitive: Docker Compose, startup scripts, OMERO session handling, plugin databases, and runtime bootstrap logic all need deterministic behavior.
- The existing security scan notes still call out meaningful classes of findings, including path injection, log injection, raw SQL usage, `@csrf_exempt` views, subprocess-injection review points, and Dockerfile USER issues.
- Workflow hygiene is stronger than before: GitHub Actions are pinned by commit SHA, but the repo still relies on manual review instead of a dedicated workflow-policy or `actionlint` lane.
- The repo already documents a precise split-pytest policy in `AGENTS.md`, and `tests.yml` now enforces it directly.
- The code-scanning runbook still provides the evidence basis for supply-chain and policy hardening work, even though the root `SECURITY.md` and action-SHA pinning gaps have been fixed in-tree.

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

These should be local, fast, and deterministic. They are meant to fail early before a pull request is opened. Existing Ruff and docs hooks are already in place; the items below focus on the remaining gaps.

| Hook | What it should run | Why it matters here | Priority |
| --- | --- | --- | --- |
| `pre-commit:docs-structure` | `python3 tools/lint_docs_structure.py` | The repo already enforces docs structure; this is the obvious first local guardrail. | Now |
| `pre-commit:python-compile` | `python3 -m py_compile` on changed Python files | Useful fallback when the full Django or OMERO runtime is not available locally. | Now |
| `pre-commit:shell-lint` | `bash -n` plus `shellcheck` for changed `.sh` files | Startup and install scripts are critical-path logic, not helper scripts. | Now |
| `pre-commit:workflow-lint` | `actionlint` and YAML validation for `.github/workflows/*.yml` | Workflow breakage is costly and currently only caught after push. | Now |
| `pre-commit:dockerfile-lint` | `hadolint` on changed Dockerfiles | The repo already treats Dockerfiles as security-sensitive infrastructure code. | Now |
| `pre-commit:secret-surface` | block edits and commits of operator-managed secrets and runtime-only env files | The repo explicitly forbids AI edits to `env/omero_secrets.env` and relies on example files as canonical templates. | Now |
| `pre-push:split-pytest` | run only the relevant test directory, one suite at a time | `AGENTS.md` explicitly requires split pytest execution to avoid conftest cross-contamination. | Next |
| `pre-push:docs-drift` | check for stale plugin names, stale topology facts, and missing env-file guidance | The repo has already fixed compose-command and service-count drift once, while stale `omeroweb_upload` references still remain. | Next |
| `pre-push:compose-contract` | lightweight compose and workflow sanity checks when Docker or env templates change | Compose failures in this repo often come from env interpolation and runtime permissions, not syntax alone. | Next |

## Recommended GitHub Actions

The current workflows already cover docs validation, split tests, Ruff, Vulture, super-linter, and security scanning. Quality would still improve if the repository added the missing infrastructure and drift-specific lanes below.

| Workflow | What it should do | Why it is grounded in this repo | Priority |
| --- | --- | --- | --- |
| change-aware test selection lane | skip or narrow expensive lanes based on touched paths while preserving the existing `tests.yml` split-suite contract | The repo already has the full split-test workflow; the missing piece is path-aware speed. | Next |
| lightweight local-quality mirror lane | run `python3 -m py_compile`, docs lint, and lightweight static checks on changed files | The repo has strong CI gates now, but local and changed-file feedback is still thinner. | Next |
| `shell-and-workflow-lint.yml` | run `shellcheck`, `actionlint`, and YAML validation | The repo has many shell and workflow files but no dedicated enforcement lane. | Now |
| `docker-smoke.yml` | build changed Dockerfiles and run targeted smoke and contract tests | Dockerfiles and startup wrappers are central to repo correctness. | Now |
| `docs-drift.yml` | catch stale plugin names, stale topology facts, and missing index entries | The repo already benefits from narrower docs-drift regression tests, but stale plugin-name cleanup and broader drift enforcement are still incomplete. | Now |
| `security-code-scanning.yml` `security-delta` job | fail when new code-scanning alerts are introduced by the current security workflow run | The security runbook already defines severity SLAs and merge expectations. | Done |
| `action-pin-policy.yml` | verify GitHub Actions stay pinned to approved SHAs and least-privilege permissions | SHA pinning is in place now, but the repo still lacks an automated guard against regression. | Next |
| `release-hygiene.yml` | require release-note and docs updates when startup, env, or operator behavior changes | The repo says docs must change when behavior changes, but the rule is not automated. | Next |
| `dependency-hygiene.yml` | validate Dependabot coverage and optionally inventory dependency surfaces | Dependabot exists but only covers a narrow subset of the repo. | Later |
| `nightly-stack-validation.yml` | run a slower compose-level validation path on a schedule or manual dispatch | The repo already notes the absence of a full deployment validation suite. | Later |

## Related Repo Settings

- Require `docs-knowledge-base`, `tests`, `ruff`, `vulture`, `super-linter`, and security scanning to pass before merge.
- Add branch protection for `main` and `alpha` if both are expected to accept production changes.
- Add `CODEOWNERS` coverage for `.github/workflows/`, `startup/`, `installation/`, `docker/`, `env/*_example.env`, and `docs/operations/`.
- Require review for changes to workflows, startup scripts, Dockerfiles, and environment templates.
- Limit GitHub token permissions in workflows to the minimum needed for each job.
- Pin GitHub Actions by commit SHA where practical.
- Keep the root `SECURITY.md` forwarding to `docs/SECURITY.md` intact so GitHub-native security features keep working.
- Keep the repo-local doc index and plan tracker authoritative when new planning files are added.

## Recommended Order

1. Add `shell-and-workflow-lint.yml`, `docker-smoke.yml`, and docs-drift checks so infrastructure changes stop bypassing the existing CI gates.
2. Add a change-aware test-selection or lightweight local-quality mirror lane to complement the already-present full `tests.yml` workflow.
3. Tighten workflow hygiene further with automated pin-policy checks, `CODEOWNERS`, and branch protection.
4. Expand Dependabot and add slower nightly or manual full-stack validation only after the infrastructure lanes are stable.
5. Revisit the skill set after the automation layer lands and trim or merge skills based on real maintenance behavior.

## Progress Log

- 2026-03-22: Drafted the planning scope after surveying repository docs, workflows, plugin code, and existing quality trackers.
- 2026-03-22: Identified the earlier quality baseline before the current `tests`, `ruff`, `vulture`, and `super-linter` workflows landed.
- 2026-03-22: Expanded the plan into concrete skill, hook, workflow, and repo-setting recommendations tied to the checked-in gaps.

## Decision Log

- Use repository evidence, not generic best practices, as the basis for the recommendations.
- Keep repo-local hooks fast and deterministic so they can run before CI.
- Treat GitHub Actions as the enforcement layer and local hooks as the early warning layer.
- Prioritize changes that reduce regressions in startup scripts, plugin runtime behavior, and workflow hygiene before introducing more optional quality tooling.
