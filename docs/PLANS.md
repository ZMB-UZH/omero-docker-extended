# Planning Model

How changes are planned, tracked, and completed in this repository.

## Change sizes

- **Small changes** (clear scope, one default-branch change): include plan bullets directly in the commit message, change summary, or verification notes.
- **Multi-step changes** (cross-cutting or release-sized): create an execution plan in `docs/exec-plans/active/` before starting work.
- **Exploratory/research**: document findings in `docs/design-docs/` and reference them in subsequent execution plans.

## Execution plans

Active plans live in `docs/exec-plans/active/`. Each plan includes:

1. **Goal**: what the change achieves and why.
2. **Steps**: ordered list of concrete implementation steps.
3. **Progress log**: updated as work proceeds (dates, outcomes, blockers).
4. **Decision log**: key choices made during implementation with rationale.

When a plan is complete, move it to `docs/exec-plans/completed/` with:

- Final outcomes and metrics.
- Follow-up items (captured in `docs/exec-plans/tech-debt-tracker.md` if needed).
- Links to related commits, workflow runs, releases, or explicitly requested pull requests.

## Technical debt

Known debt items are tracked in `docs/exec-plans/tech-debt-tracker.md` with priority, owner, and status. Review this file when planning new work to avoid compounding existing debt.

## Plan review

Plans for infrastructure changes (Docker, startup scripts, monitoring) or changes affecting multiple plugins should be reviewed before implementation begins. Document the approach in the plan and reference it in the change summary before the default-branch push or release.
