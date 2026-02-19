# Planning Model

How changes are planned, tracked, and completed in this repository.

## Change sizes

- **Small changes** (single PR, clear scope): include plan bullets directly in the pull request description.
- **Multi-step changes** (cross-cutting, multi-PR): create an execution plan in `docs/exec-plans/active/` before starting work.
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
- Links to related pull requests.

## Technical debt

Known debt items are tracked in `docs/exec-plans/tech-debt-tracker.md` with priority, owner, and status. Review this file when planning new work to avoid compounding existing debt.

## Plan review

Plans for infrastructure changes (Docker, startup scripts, monitoring) or changes affecting multiple plugins should be reviewed before implementation begins. Document the approach in the plan and reference it in the PR.
