# Quality Scorecard

Current quality assessment by domain. Scores range from 1 (critical gaps) to 5 (production-excellent).

- **Deployment reproducibility**: score `4`, target `5`. Automated installation
  script, pinned versions, and env templates. CI validates docs structure. Gap:
  no automated integration test suite for full deployment.
- **Plugin maintainability**: score `4`, target `5`. Consistent plugin layout,
  shared library, typed env helpers, and broad OMP/Import regression suites.
  Gap: deployment/live integration coverage and continued large-module
  reduction.
- **Operational clarity**: score `4`, target `5`. Full monitoring stack
  (Prometheus, Grafana, Loki, Alloy), 4 dashboards, and admin tools plugin.
  Gap: no documented SLO targets or alert rules.
- **Documentation legibility**: score `4`, target `5`. Structured docs with
  CI-enforced linting and progressive disclosure via `AGENTS.md`. Gap: continue
  expanding troubleshooting coverage.
- **Security posture**: score `4`, target `5`. `no-new-privileges` on all
  containers, env-based secrets, rate limiting, and input validation. Gap: no
  automated secret rotation tooling.
- **Database maintenance**: score `5`, target `5`. Automated VACUUM ANALYZE
  (weekly) and REINDEX CONCURRENTLY (monthly) via pg-maintenance sidecar. Both
  databases covered.
- **Monitoring coverage**: score `4`, target `5`. Metrics for host, containers,
  databases, Redis, plus blackbox HTTP/TCP probes. Gap: no plugin-specific
  application metrics.

## Tracking rule

Update this table when major quality improvements or regressions land. Include the date plus the related commit, workflow run, release note, or explicitly requested pull request.

## Priority improvements

1. Add deployment-smoke and live integration validation for OMP and Import workflows.
2. Define SLO targets for OMERO.web response time and import success rate.
3. Add alert rules to Prometheus for critical service failures.
4. Expand troubleshooting docs for database-related failures.
