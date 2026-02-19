# Quality Scorecard

Current quality assessment by domain. Scores range from 1 (critical gaps) to 5 (production-excellent).

| Domain | Score | Target | Notes |
|---|---|---|---|
| Deployment reproducibility | 4 | 5 | Automated installation script, pinned versions, env templates. CI validates docs structure. Gap: no automated integration test suite for full deployment. |
| Plugin maintainability | 4 | 5 | Consistent plugin layout, shared library, typed env helpers. Gap: limited unit test coverage for OMP and Upload plugins. |
| Operational clarity | 4 | 5 | Full monitoring stack (Prometheus, Grafana, Loki, Alloy), 4 dashboards, admin tools plugin. Gap: no documented SLO targets or alert rules. |
| Documentation legibility | 4 | 5 | Structured docs with CI-enforced linting, progressive disclosure via AGENTS.md. Gap: continue expanding troubleshooting coverage. |
| Security posture | 4 | 5 | no-new-privileges on all containers, env-based secrets, rate limiting, input validation. Gap: no automated secret rotation tooling. |
| Database maintenance | 5 | 5 | Automated VACUUM ANALYZE (weekly) and REINDEX CONCURRENTLY (monthly) via pg-maintenance sidecar. Both databases covered. |
| Monitoring coverage | 4 | 5 | Metrics for host, containers, databases, Redis, plus blackbox HTTP/TCP probes. Gap: no plugin-specific application metrics. |

## Tracking rule

Update this table when major quality improvements or regressions land. Include the PR reference and date of the change.

## Priority improvements

1. Add plugin-level unit test coverage for OMP and Upload plugins.
2. Define SLO targets for OMERO.web response time and import success rate.
3. Add alert rules to Prometheus for critical service failures.
4. Expand troubleshooting docs for database-related failures.
