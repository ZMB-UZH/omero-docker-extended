# GitHub Code Scanning Runbook

This project enables automated security scanning via `.github/workflows/security-code-scanning.yml`. All scanners produce SARIF output uploaded to the GitHub Security tab.

## Active scanners

| Scanner | Type | Scope | Free |
|---|---|---|---|
| CodeQL | SAST | Python, JavaScript/TypeScript | Yes |
| Trivy | Vuln/misconfig/secret scan | Filesystem (dependencies, configs, secrets) | Yes |
| Semgrep | SAST | 1000+ rules (Django, shell, Python patterns) | Yes |
| Bandit | Python security | Hardcoded creds, injection, unsafe calls | Yes |
| Hadolint | Dockerfile lint | All 8 Dockerfiles (matrix strategy) | Yes |
| DevSkim | Security patterns | Cross-language pattern matching (Microsoft) | Yes |
| OSV Scanner | Dependency vulns | Google OSV vulnerability database | Yes |
| OSSF Scorecard | Supply-chain | Branch protection, pinning, CI security | Yes |

## Trigger model

- **Push** to `main` or `alpha`: full scan.
- **Pull requests** targeting `main` or `alpha`: full scan.
- **Weekly schedule** (Monday 03:23 UTC): catches newly disclosed CVEs.
- **Manual dispatch**: incident response or post-remediation verification.

## Repository requirements

1. **Settings > Security & analysis**: enable Code scanning, Dependabot alerts, Secret scanning.
2. **Actions permissions**: allow workflow runs and SARIF upload.
3. OSSF Scorecard runs only on push/schedule (not PRs) and publishes results via OIDC.

## Alert inventory

Last updated: 2026-03-15. Total open alerts: **995**.

### Summary by severity

| Severity | Count | Triage guidance |
|---|---|---|
| Critical | 2 | Immediate action required. Merge blocker. |
| High | 59 | Fix within 7 days. Merge blocker for new code. |
| Error | 51 | Review and remediate promptly. |
| Medium | 38 | Fix within 30 days. |
| Warning | 192 | Review during regular maintenance cycles. |
| Low | 8 | Address opportunistically. |
| Note | 645 | Informational. Address during related refactoring. |

### Summary by scanner

| Scanner | Count | Primary finding categories |
|---|---|---|
| Bandit | 588 | Assert usage (B101), bare except (B112), hardcoded temps (B108), subprocess (B603) |
| DevSkim | 131 | HTTP without TLS (DS137138), localhost references (DS162092), tokens in tests (DS173237) |
| Semgrep | 112 | Raw SQL queries, CSRF exempt views, credential logging, urllib usage, Dockerfile USER |
| CodeQL | 86 | Path injection, log injection, cleartext logging, SSRF, stack trace exposure |
| Scorecard | 40 | Unpinned dependencies, token permissions, branch protection, maintenance signals |
| Hadolint | 22 | Root USER in Dockerfiles, unhealthchecked images, unpinned packages, shell lint |
| Trivy | 16 | Root user in images, missing HEALTHCHECK, apt-get update without install |

### Critical and high findings

#### Critical (2 alerts) — immediate action required

| ID | Rule | File | Description |
|---|---|---|---|
| — | `py/partial-ssrf` | `omeroweb_admin_tools/views/index_view.py` | Partial server-side request forgery |
| — | `py/partial-ssrf` | `omeroweb_omp_plugin/services/ai_assist.py` | Partial server-side request forgery |

#### High (59 alerts)

| Rule | Count | Affected files | Description |
|---|---|---|---|
| `py/path-injection` | 20 | `job_storage.py`, `core_functions.py`, `index_view.py` | Uncontrolled data in path expressions |
| `py/log-injection` | 13 | `views.py`, `image_service.py`, `core_functions.py` | Log injection via unsanitized input |
| `py/clear-text-logging-sensitive-data` | 8 | `ai_assist.py`, `connection_service.py`, `import_service.py`, `core_functions.py` | Sensitive data in log output |
| `DS002` (Trivy) | 7 | All Dockerfiles except `omero-celery-worker` | Image runs as root user |
| `missing-user-entrypoint` (Semgrep) | 5 | `crowdsec`, `firewall-bouncer`, `path-usage-exporter`, `pg-maintenance`, `redis-sysctl-init` Dockerfiles | No USER directive before ENTRYPOINT |
| `last-user-is-root` (Semgrep) | 4 | `omero-server.Dockerfile`, `omero-web.Dockerfile` | Last USER directive is root |
| `py/overly-permissive-file` | 3 | `storage_quotas.py`, `IMS_Export.py` | File created with overly permissive mode |
| `py/regex-injection` | 1 | `filename_parser.py` | User-controlled data in regex pattern |

#### Error (51 alerts)

| Rule | Count | Affected files | Description |
|---|---|---|---|
| `sqlalchemy-execute-raw-query` (Semgrep) | 31 | `omp_plugin/data_store.py`, `upload/data_store.py` | Raw SQL via SQLAlchemy execute |
| `DS173237` (DevSkim) | 8 | Test files | Token-like strings in test source |
| `subprocess-injection` (Semgrep) | 2 | `delete_plugin_view.py` | User input reaching subprocess call |
| `SC2261` (Hadolint) | 1 | `omero-web.Dockerfile` | Shell syntax issue |

### Medium findings (38 alerts)

| Rule | Count | Description |
|---|---|---|
| `PinnedDependenciesID` (Scorecard) | 32 | Unpinned GitHub Actions, Dockerfiles, or pip installs |
| `py/stack-trace-exposure` | 4 | Exception details exposed to users |
| `SecurityPolicyID` (Scorecard) | 1 | No SECURITY.md in repository root |
| `FuzzingID` (Scorecard) | 1 | No fuzzing integration detected |

### Warning findings (192 alerts)

| Rule | Count | Description |
|---|---|---|
| `DS137138` (DevSkim) | 77 | HTTP URLs without TLS (internal Docker network traffic) |
| `csrf-exempt` (Semgrep) | 29 | Django views decorated with `@csrf_exempt` |
| `logger-credential-leak` (Semgrep) | 20 | Logger calls that may include credential-adjacent variables |
| `B108` (Bandit) | 13 | Hardcoded `/tmp` paths |
| `B603` (Bandit) | 12 | `subprocess.call` with shell=False (informational) |
| `B311` (Bandit) | 12 | `random` module usage (non-cryptographic) |
| `B310` (Bandit) | 10 | URL open with variable input |
| `dynamic-urllib-use` (Semgrep) | 10 | Dynamic URL construction with urllib |
| Other | 9 | Hadolint DL3003/DL3018/DL3008/DL3002, Bandit B308/B703/B103, CodeQL warnings |

### Note/informational findings (645 alerts)

| Rule | Count | Description |
|---|---|---|
| `B101` (Bandit) | 489 | Use of `assert` statements (appropriate in test code) |
| `DS162092` (DevSkim) | 46 | Localhost references (expected in Docker-internal configs) |
| `B112` (Bandit) | 18 | `try/except/continue` patterns |
| `B105` (Bandit) | 11 | Hardcoded password-like variable names (mostly test fixtures) |
| `B404` (Bandit) | 9 | Import of `subprocess` module |
| `SC2012` (Hadolint) | 9 | Use of `ls` in Dockerfile RUN (prefer `find`) |
| Other | 63 | Unused imports/variables, empty except, mixed returns, shell quoting |

## Triage guidance

### Severity-based SLA

| Severity | Response SLA | Merge policy |
|---|---|---|
| Critical | 24 hours | Block all merges until resolved |
| High | 7 days | Block merges introducing new high findings |
| Medium | 30 days | Track in sprint backlog |
| Warning | Next maintenance cycle | Address during related work |
| Note | Opportunistic | Fix during refactoring of affected code |

### Known acceptable risks

Some findings are expected in this architecture and do not require remediation:

- **B101 (assert in tests)**: 489 of 995 alerts. `assert` is correct in test code. Bandit flags all uses.
- **DS137138 (HTTP without TLS)**: Internal Docker network traffic between containers uses HTTP. TLS is terminated at the reverse proxy. These URLs are not exposed externally.
- **DS162092 (localhost references)**: Expected in Docker Compose configurations, Prometheus scrape targets, and test fixtures.
- **DS173237 (tokens in tests)**: Test files contain dummy tokens for unit testing. These are not real credentials.
- **B108 (hardcoded /tmp)**: OMERO uses a dedicated tmpfs mount at a configured path. Some references to `/tmp` are in container-internal contexts.
- **B603 (subprocess with shell=False)**: Informational — `shell=False` is the secure form of subprocess usage.
- **B404 (subprocess import)**: Informational — the import itself is not a vulnerability.
- **B311 (random module)**: Used for non-security-critical purposes (job IDs, jitter). Not used for cryptographic operations.
- **SC2012 (ls in Dockerfile)**: Cosmetic shell lint in Dockerfile RUN commands.

### Findings requiring investigation

These categories may contain genuine issues that should be reviewed:

1. **Critical SSRF** (`py/partial-ssrf`): Review URL construction in admin tools proxy and AI assist service to confirm inputs are validated against an allowlist.
2. **Path injection** (`py/path-injection`): Review all file path construction to confirm traversal prevention is in place.
3. **Log injection** (`py/log-injection`): Confirm all user-controlled values are sanitized before logging.
4. **Raw SQL** (`sqlalchemy-execute-raw-query`): Review parameterization of all SQLAlchemy execute calls.
5. **CSRF exempt** (`csrf-exempt`): Confirm each exempt view has alternative authentication (OMERO session tokens).
6. **Subprocess injection** (`subprocess-injection`): Review argument construction in delete views.
7. **Regex injection** (`py/regex-injection`): Review filename parser to confirm user input is escaped before regex compilation.
8. **Dockerfile USER** (`DS002`, `missing-user-entrypoint`, `last-user-is-root`): Some containers require root for bind-mount permissions. Document which require root and why.

## Hardening roadmap

1. Add branch protection requiring all security scanning checks to pass on pull requests.
2. Add CI policy to fail builds when new `CRITICAL` or `HIGH` alerts are introduced.
3. Pin all GitHub Actions to full commit SHAs (addresses 32 Scorecard `PinnedDependenciesID` findings).
4. Add a `SECURITY.md` to the repository root (addresses Scorecard `SecurityPolicyID`).
5. Add image-level Trivy scans for each built Docker image as a separate workflow job.
6. Evaluate adding fuzz testing for parser code (`filename_parser.py`, `sem_edx_parser.py`).

## AI agent maintenance instructions

**This file is the authoritative tracker for code scanning findings.** AI agents working on this repository must follow these rules:

1. **After fixing a vulnerability**: Update the alert counts in this file. Remove the finding from the relevant table if the fix eliminates all instances. Decrement counts if partial. Update the "Last updated" date.

2. **After removing or deleting code**: If the removed code was associated with findings listed here, update the counts and tables accordingly. Re-run the security workflow to verify closure.

3. **After adding new code**: If new code introduces patterns flagged by any scanner, document the finding here with its triage status (fix planned, acceptable risk, or false positive).

4. **Periodic refresh**: When running a full security scan, compare the live alert count from the GitHub API against this file. Update all tables to match current state. Use:
   ```bash
   curl -sL -H "Authorization: Bearer $GITHUB_TOKEN" \
     "https://api.github.com/repos/ZMB-UZH/omero-docker-extended/code-scanning/alerts?per_page=100&state=open&page=1"
   ```

5. **Never include exploitation details**: Document what the vulnerability is and where it is located. Do not include proof-of-concept code, payload examples, or step-by-step exploitation instructions.

6. **Commit message convention**: When fixing a security finding, use the commit message format:
   ```
   Fix <scanner>/<rule-id>: <brief description>
   ```
   Example: `Fix CodeQL/py/path-injection: validate upload path against managed root`
