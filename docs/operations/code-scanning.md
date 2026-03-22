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

Last updated: 2026-03-15. Total open alerts: **~940** pre-config, **~370** post-config (scanner configuration eliminates ~570 false positives).

### Summary by severity

| Severity | Count | Triage guidance |
|---|---|---|
| Critical | 2 | Immediate action required. Merge blocker. |
| High | 59 | Fix within 7 days. Merge blocker for new code. |
| Error | 51 | Review and remediate promptly. |
| Medium | 38 | Fix within 30 days. |
| Warning | 192 | Review during regular maintenance cycles. |
| Low | 8 | Address opportunistically. |
| Note | ~20 | Informational. Most eliminated by scanner config (B101 test-only, DS162092 infra, B603/B404 informational). |

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
| `SecurityPolicyID` (Scorecard) | 1 | Repository root `SECURITY.md` was missing in the 2026-03-15 scan snapshot; fixed in-tree now and should clear on the next workflow refresh |
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

### Note/informational findings (~20 remaining)

Most Note-level findings have been resolved through a combination of code fixes and scanner configuration:

**Code fixes (55 alerts):** Removed dead code, unused imports/variables, added debug logging to empty except blocks, consolidated imports, replaced `ls` with `find` in Dockerfiles, removed unused JS variables.

**Scanner configuration (additional ~570 alerts):**
- Bandit split into production and test scans; `B101` (assert) and `B106` (test credentials) skipped only in test directories. The workflow also uploads a zero-result legacy `bandit` SARIF so GitHub code scanning can close stale alerts from the pre-split Bandit configuration without suppressing current `bandit-prod` or `bandit-test` results.
- `B603` (subprocess shell=False) and `B404` (subprocess import) skipped globally — purely informational, not vulnerabilities
- DevSkim `DS162092` (localhost references) excluded — all 46 are Docker healthchecks, startup scripts, and container-internal networking

| Rule | Original | Now | Resolution |
|---|---|---|---|
| `B101` (Bandit) | 489 | 0 | **Eliminated** — test directories auto-discovered and excluded from production scan; B101 skipped in test scan |
| `DS162092` (DevSkim) | 46 | 0 | **Eliminated** — excluded from DevSkim (Docker infrastructure) |
| `B603` (Bandit) | 12 | 0 | **Eliminated** — skipped globally (shell=False is secure) |
| `B404` (Bandit) | 9 | 0 | **Eliminated** — skipped globally (import is informational) |
| `B106` (Bandit) | 2 | 0 | **Eliminated** — skipped in test directories only |
| `B112` (Bandit) | 18 | 0 | **Resolved** — added debug logging before `continue` |
| `B110` (Bandit) | 3 | 0 | **Resolved** — replaced `pass` with debug logging |
| `SC2012` (Hadolint) | 9 | 0 | **Resolved** — replaced `ls` with `find` |
| CodeQL py/js notes | 28 | ~1 | **Mostly resolved** — unused code removed, imports fixed |
| `B311` (Bandit) | 12 | 12 | Remaining — `random` for jitter/genetic algo, not crypto |
| `B105` (Bandit) | 11 | 11 | Remaining — env var name constants, not actual passwords |
| `SC2016` (Hadolint) | 3 | 3 | Remaining — single-quoted printf strings are intentional |
| `js/syntax-error` (CodeQL) | 1 | 1 | Remaining — Django template tag inside `<script>` block |

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
4. ~~Add a `SECURITY.md` to the repository root.~~ **Done in-tree**: the repository root now includes `SECURITY.md`, which points GitHub-native security surfaces at the canonical `docs/SECURITY.md` guidance. The Scorecard `SecurityPolicyID` finding should clear on the next workflow refresh.
5. ~~Add image-level vulnerability scans for each built Docker image.~~ **Done**: Docker Scout two-phase scanning (pre-build baseline + post-build report) covers all images in `docker-compose.yml` — both custom-built and third-party. Interactive installs default security hardening to enabled, vulnerability scanning remains opt-in, and the hardening pass preserves locale data while applying OS and Python package upgrades. See `docs/SECURITY.md`.
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

6. **Adding new plugins or test directories**: The Bandit workflow auto-discovers both scan targets and test directories at runtime. Any directory at the repo root matching `omero_*` or `omeroweb_*` that contains `__init__.py` is automatically included in the scan. Test directories named `tests/` or `test/` within those packages are auto-discovered and excluded from the production scan (and scanned separately with B101/B106 skipped). The repo-root `tests/` directory is also included in the test-only scan. **You do NOT need to update the workflow file** — discovery is fully dynamic. Just follow the naming convention.

7. **Commit message convention**: When fixing a security finding, use the commit message format:
   ```
   Fix <scanner>/<rule-id>: <brief description>
   ```
   Example: `Fix CodeQL/py/path-injection: validate upload path against managed root`

## AI agent coding guidelines — preventing new findings

**These rules prevent introducing new code scanning alerts.** Follow them when writing or modifying code in this repository.

### Python code structure

1. **No unused imports.** Remove imports immediately when the symbol they provide is no longer referenced. Run CodeQL locally or inspect before committing.

2. **No bare `except:` or empty `except Exception: pass/continue`.** Every except block must either:
   - Log the exception at `logger.debug()` or higher, OR
   - Re-raise the exception, OR
   - Explicitly handle the error condition.
   Never silently swallow exceptions. Use `logger.debug("...", exc_info=True)` for low-priority catches.

3. **No unused variables.** If a function returns a tuple and you don't need all values, use `_` for discarded positions: `value, _, meta = some_call()`. Remove variables that are assigned but never read.

4. **No dead code.** Remove stub functions, unreachable branches, and commented-out code. Do not leave partial implementations at the end of files.

5. **Consistent imports.** Do not combine `import X` and `from X import Y` for the same module. Use one style:
   ```python
   # Preferred: from-import when using specific names
   from unittest import TestCase, mock, main as unittest_main
   # Not: import unittest + from unittest import mock
   ```

6. **No redundant imports inside functions.** If a module is imported at the top of the file, do not re-import it inside functions or test methods.

7. **Lambdas must add value.** Replace `lambda x: str(x)` with `str`, `lambda: object()` with `object`. Only use lambdas when they contain logic beyond calling a single function with the same arguments.

8. **Explicit returns.** Every code path in a function should return the same type. Do not mix explicit `return value` with implicit `return None` (falling off the end).

9. **Use `random` only for non-security purposes.** For jitter, shuffling, or display randomization, `random` is fine. For tokens, session IDs, nonces, or any security-sensitive value, use `secrets` or `os.urandom`.

10. **Environment variable names are not passwords.** Constants like `PASSWORD_ENV = "OMERO_DB_PASSWORD"` store the *name* of an env var, not a credential. Bandit B105 flags these — they are acceptable. Do not rename them to avoid the pattern; instead ensure actual secrets never appear in source code.

### JavaScript in Django templates

1. **No unused JS variables.** If you destructure or assign a value, use it. Remove `const x = ...` if `x` is never referenced.

2. **Django template tags in `<script>` blocks** will always trigger `js/syntax-error` from CodeQL. This is a known false positive. Minimize template logic inside JS blocks where possible, but do not restructure working code just to appease the scanner.

### Dockerfiles

1. **Use `find` instead of `ls` in RUN commands.** Replace `ls -d /path/glob*` with `find /path -maxdepth 1 -type d -name 'glob*'`. Replace `ls -la /path` with `find /path -maxdepth 1 -ls`.

2. **Single-quoted strings with `$` in printf/heredocs** are intentional when writing entrypoint scripts. SC2016 alerts on these are acceptable.

3. **Pin all base images and action versions.** Use exact tags or SHA digests, never `:latest`.

4. **Add `USER` directive** before `ENTRYPOINT`/`CMD` where possible. Document containers that require root (bind-mount permissions) with an inline comment.

### Exception handling patterns

```python
# WRONG — triggers B112 and py/empty-except
try:
    value = risky_call()
except Exception:
    continue

# CORRECT — log before continuing
try:
    value = risky_call()
except Exception:
    logger.debug("Failed to get value from risky_call")
    continue

# WRONG — bare pass
except Exception:
    pass

# CORRECT — explain why the exception is expected
except Exception:
    logger.debug("Expected failure in optional path, skipping")
```

### Test code

1. **`assert` in test code is correct.** Bandit B101 flags all `assert` usage. In test files (`tests/`, `*/tests/`), this is expected and acceptable.

2. **Dummy credentials in test fixtures** (B106) are acceptable. Use obviously fake values like `"test_password"` or `"dummy_token"`.

3. **Test files should import `from unittest import TestCase, mock`** — not both `import unittest` and `from unittest import mock`.

### What NOT to do to resolve findings

- **Do not suppress findings with inline comments** (`# nosec`, `# noqa`, `# type: ignore`) unless the finding is a verified false positive AND you document why.
- **Do not rename variables** to avoid pattern matching (e.g., renaming `password_env` to `pw_env` to dodge B105).
- **Do not remove `subprocess` imports** (B404) or change `shell=False` to avoid B603 — these are informational, not vulnerabilities.
- **Do not replace `assert` in tests** with `if/raise` just to satisfy B101.
- **Do not replace `random` with `secrets`** for non-security purposes (jitter, UI randomization) — `secrets` is slower and unnecessary.
- **Do not restructure Docker networking** to avoid localhost references (DS162092) — internal container communication uses localhost by design.
