# GitHub Code Scanning Runbook

This project enables GitHub code scanning via a dedicated workflow:

- `.github/workflows/security-code-scanning.yml`

The workflow is designed for deterministic, environment-agnostic scanning and uploads SARIF findings into the GitHub Security tab.

## What is enabled

1. **CodeQL static analysis**
   - Languages: `python`, `javascript-typescript`
   - Query suites: `security-extended`, `security-and-quality`
   - Triggers: push to `main`, pull requests, weekly schedule, manual dispatch
2. **Trivy filesystem scanning**
   - Scanners: vulnerabilities, misconfigurations, secrets
   - Severity gate: `CRITICAL,HIGH`
   - Output: SARIF uploaded to GitHub code scanning alerts

## Repository requirements

Before this workflow can publish results, ensure repository settings allow Security alerts:

1. In GitHub, open **Settings -> Security & analysis**.
2. Enable:
   - **Code scanning**
   - **Dependabot alerts**
   - **Secret scanning** (if available for your plan)
3. Ensure Actions permissions allow workflow runs and SARIF upload.

## Operating model

- **Pull request scanning**: catches new issues before merge.
- **Main branch scanning**: keeps baseline alerts fresh.
- **Weekly scheduled scan**: catches new CVEs in tracked dependencies/config patterns.
- **Manual dispatch**: supports incident response or after major dependency/image updates.

## Triage recommendations

1. Treat `CRITICAL` and `HIGH` alerts as merge blockers unless a documented risk exception exists.
2. Assign each alert to an owner and SLA (for example: critical within 24 hours, high within 7 days).
3. Track justified suppressions in version control with explicit rationale and expiry date.
4. Re-run manual scan after remediation and verify the alert closes.

## Hardening roadmap (recommended)

To improve signal and reduce mean time to remediate:

1. Add branch protection requiring `security-code-scanning / CodeQL (...)` checks on pull requests.
2. Add CI policy to fail builds when new unsuppressed `CRITICAL/HIGH` alerts are introduced.
3. Add pinned-action digest updates to your maintenance cadence.
4. Add image-level Trivy scans for each built Docker image as a separate workflow/job.
