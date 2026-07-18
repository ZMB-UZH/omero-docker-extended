# Technical Debt Tracker

Known technical debt items. Review before planning new work to avoid compounding existing debt.

| Item                                                                                | Priority | Owner      | Status |
| ----------------------------------------------------------------------------------- | -------- | ---------- | ------ |
| Add dynamic full-stack startup/live validation for OMP and Import workflows         | High     | Unassigned | Open   |
| Add focused edge-case coverage when refactoring large OMP and Import modules        | Medium   | Unassigned | Open   |
| Define SLO targets for OMERO.web response time and import success rate              | Medium   | Unassigned | Open   |
| Add Prometheus alert rules for critical service failures                            | Medium   | Unassigned | Open   |
| Expand automated linting coverage for docs references and cross-links               | Medium   | Unassigned | Open   |
| Add plan template for multi-service operational changes                             | Medium   | Unassigned | Open   |
| Add plugin-specific application metrics (job counts, parse times, import durations) | Medium   | Unassigned | Open   |
| Implement automated secret rotation tooling                                         | Low      | Unassigned | Open   |

## Conventions

- **Priority**: High (blocks quality improvement), Medium (improves reliability/maintainability), Low (nice to have).
- **Status**: Open, In Progress, Done.
- When completing an item, move the row to `docs/exec-plans/completed/README.md` with the resolution and related commit, workflow run, release note, or explicitly requested pull request.
