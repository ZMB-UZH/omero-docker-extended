# GitHub Code Scanning Runbook

This project enables automated security scanning via `.github/workflows/security-code-scanning.yml`. All scanners produce SARIF output uploaded to the GitHub Security tab.

GitHub-native code scanning is the committed repository scanning gate here.
Retired third-party scanning integrations are intentionally not part of the
tracked workflow set. DeepSource may be queried as external API inventory when
a DeepSource credential is explicitly available, but it must not introduce a
repo-file config, private credential, workflow gate, or replacement
source-of-truth alert count. The README DeepSource badge is display-only. Its
`token=` URL parameter is the badge-rendering URL parameter copied from the
repository's DeepSource **Settings > Badges** page, not an API key or private
credential.

DeepSource repo-file configuration is retired for this repository. Do not
search for, create, restore, or edit `.deepsource.toml`. A GitHub PAT is not a
DeepSource API credential; start scanner triage from the GitHub code-scanning
API, GitHub Actions logs, and this runbook instead.

The repository also includes a `security-delta` job inside `.github/workflows/security-code-scanning.yml`. That job fails when a pull request introduces any open code-scanning alert or when a default-branch security scan creates new open alerts.

The current advanced CodeQL setup uses `build-mode: none` for the Python and JavaScript/TypeScript matrix, which matches GitHub's interpreted-language guidance and avoids an unnecessary `autobuild` step. The same workflow also enables CodeQL dependency caching, and the Bandit job restores and stores `pip` downloads keyed to `.github/requirements/security-code-scanning.txt`.

Do not narrow scanner scope to improve scores. New path filters, rule skips,
ignored globs, SARIF cleanup categories, or workflow trigger filters require
documented false-positive or runtime-scope proof, an audit-log line that shows
what is excluded, and a contract test.

The current allowed scanner-scope exclusions are: Bandit production/test split
with test-only `B101`/`B106` skips, global Bandit informational `B603`/`B404`
skips, DevSkim `DS162092` for container-internal localhost infrastructure,
Super-Linter exclusion of vendored `third_party` upstream references, and
generated runtime data directories that must never be tracked or scanned as
source.

## CodeQL File-Count Coverage

CodeQL file totals are extractor/database source counts, not a count of every
tracked repository file. The workflow now prints the tracked language
candidates before CodeQL initialization so a lower GitHub UI count can be
explained from the run log instead of guessed.

- Python: the current repo has 315 tracked `.py` implementation files and 33
  tracked `.pyi` type stubs. A `315/348` CodeQL count means the implementation
  files were included and type stubs were not counted as Python source; stubs
  are still covered by Ruff/Mypy contracts. The earlier `310/343` UI count had
  the same meaning before three tracked Python files were added.
- JavaScript/TypeScript: the current repo has 8 tracked JS-family files. The 2
  files under `.agents/skills/frontend-preview/agents/` are tool config files
  audited by workflow logs and repo lint/tests; the 6 application/test JS files
  are the expected CodeQL product-surface candidates.
- Do not force non-source stubs or agent-tool config files into CodeQL only to
  make the numerator equal the denominator. First prove an implementation file
  is missing from the CodeQL candidate audit, then adjust the workflow.

Official references: GitHub documents CodeQL workflow options including
`build-mode: none`, and CodeQL publishes the supported language and framework
matrix. Use the GitHub Actions run log for this workflow when investigating
scanner coverage.

## Local workflow parity gate

Run the locally reproducible workflow gates before committing or pushing changes:

```bash
python3 tools/run_local_workflow_gates.py --setup --profile ci
```

This installs Python-backed workflow tools into an ignored local environment from the same hash-pinned requirement files used by GitHub Actions, then runs the docs, Ruff, Mypy, Vulture, split test, coverage, and Bandit gates. Use `--profile all` when Docker is available and you also need the pinned Super-Linter container gate.

Some GitHub-only behavior cannot be made fully identical on the host: SARIF
upload, CodeQL hosted analysis, OIDC publishing, repository Scorecard checks,
OSV reusable workflow publishing, and Codecov upload still require the actual
GitHub workflow result. Do not present the local gate as a replacement for the
GitHub security workflow; use it to catch reproducible failures before push.
The tests workflow pins the Codecov CLI version instead of using Codecov's
`latest` default; update that pin only after verifying the replacement
version's published signature.

## Active scanners

| Scanner        | Type                                 | Scope                                                 | Free |
| -------------- | ------------------------------------ | ----------------------------------------------------- | ---- |
| CodeQL         | SAST                                 | Python, JavaScript/TypeScript                         | Yes  |
| Trivy          | Vuln/misconfig/secret/license scan   | Filesystem (dependencies, configs, secrets, licenses) | Yes  |
| Semgrep        | SAST                                 | 1000+ rules (Django, shell, Python patterns)          | Yes  |
| Bandit         | Python security                      | Hardcoded creds, injection, unsafe calls              | Yes  |
| Hadolint       | Dockerfile lint                      | All 8 Dockerfiles (matrix strategy)                   | Yes  |
| DevSkim        | Security patterns                    | Cross-language pattern matching (Microsoft)           | Yes  |
| OSV Scanner    | Dependency vulns                     | Google OSV vulnerability database                     | Yes  |
| OSSF Scorecard | Supply-chain                         | Branch protection, pinning, CI security               | Yes  |

## Trigger model

- **Push** to `main`: full scan.
- **Pull requests** targeting `main`: full scan.
- **Weekly schedule** (Monday 03:23 UTC): catches newly disclosed CVEs.
- **Manual dispatch**: incident response or post-remediation verification.
- Every job in `.github/workflows/security-code-scanning.yml` is additionally gated with the current default-branch context, so non-default refs can create workflow runs but do not consume runner minutes.

## Scanner Sources And Logs

- Alert inventory: GitHub REST API, scoped to `state=open` and `branch=main`.
- GitHub REST API version: query `https://api.github.com/versions` and use the newest supported version for the current request; do not pin stale dates.
- Workflow logs: GitHub Actions run logs for `security-code-scanning.yml`.
- Local config: `.github/workflows/security-code-scanning.yml`, scanner config files it references, and committed test contracts.
- Retired source: `.deepsource.toml`; do not look for it or recreate it.
- DeepSource counts: only report them after a successful DeepSource API or CLI query using a DeepSource credential. A GitHub PAT is insufficient; without DeepSource auth, report the count as unavailable, not zero. Distinguish grouped issues from issue occurrences. Check `latest_commit_oid`; if it does not match the commit under review, label the count as a lagged snapshot.

Useful GitHub Actions log commands:

```bash
command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
gh run list --workflow security-code-scanning.yml --branch main --limit 5
gh run view <run-id> --log-failed
gh run view <run-id> --job <job-id> --log
```

Useful GitHub code-scanning API command:

```bash
python3 tools/scanner_inventory.py github-code-scanning \
  --repository ZMB-UZH/omero-docker-extended \
  --branch main
```

Useful DeepSource count command:

```bash
python3 tools/scanner_inventory.py deepsource \
  --repository gh/ZMB-UZH/omero-docker-extended
```

Useful DeepSource grouped-issue detail command:

```bash
python3 tools/scanner_inventory.py deepsource-issues \
  --repository gh/ZMB-UZH/omero-docker-extended
```

`tools/scanner_inventory.py` reads tokens from `GITHUB_TOKEN` or
`DEEPSOURCE_TOKEN` when present; otherwise it prompts without echo on a TTY.
Each API request defaults to a 120-second timeout; use `--request-timeout N`
only when a scanner API is slower than that, then report the value used.
Never paste PATs into command arguments, remotes, repo files, or logs.
If a GitHub PAT or DeepSource API key is required and unavailable, ask the user
for the exact credential immediately and pause for input. Do not keep retrying
commands that cannot authenticate; continue only independent local tasks that do
not need that credential.
GitHub HTTPS Git operations require a PAT or credential manager, never an
account password. For TTY pushes, use:

```bash
python3 tools/git_push_with_pat.py origin main
```

This helper disables stale GitHub credential helpers for the command and keeps
the PAT out of argv, remotes, logs, temp files, and long-lived git config.
In non-TTY agent shells, set a short-lived `GITHUB_TOKEN` only for that helper
invocation instead of retrying the prompt path.
If a documented scanner command or helper causes a proven avoidable retry/error
loop, first establish the correct scanner workflow end to end, then update the
runbook or tool concisely with regression coverage.

## Repository requirements

1. **Settings > Security & analysis**: enable Code scanning, Dependabot alerts, Secret scanning.
2. **Actions permissions**: allow workflow runs and SARIF upload.
3. OSSF Scorecard runs only on push/schedule (not PRs) and publishes results via OIDC.

## Alert inventory

Last live API refresh: **2026-04-24**.

GitHub reported **4 open alerts on `main`** at the time of the latest refresh used for this runbook update. The current closed-alert total lives in `docs/reference/code-scanning-resolved-findings.md`.

DeepSource reported **4 grouped issues**, **137 issue occurrences**, and
**0 dependency vulnerability occurrences** for the default branch during the
same refresh. The API `latest_commit_oid` was
`748e4964d2b1bde124b3b00982c392247b725c8e`, the pushed default-branch
revision when this snapshot was taken.

These numbers are dynamic. Do **not** trust stale prose, screenshots, or memory when doing remediation work. Re-query the GitHub code-scanning API at the start of every remediation batch and again after the push that is expected to close alerts.

### Document ownership

To prevent documentation drift:

- Use this runbook for **live** open-alert totals, refresh dates, SLAs, and remediation workflow.
- Use `docs/reference/ai-agent-security-prevention-playbook.md` for canonical coding patterns, concrete bad/good examples, external best-practice links, and anti-drift rules.
- Use `docs/reference/code-scanning-resolved-findings.md` for **closed-history** counts, hotspot files, and per-rule lessons.
- Use `AGENTS.md` and `docs/index.md` only to route agents to the correct document. They should not duplicate volatile alert totals.

### Mandatory agent workflow

1. Pull the latest open-alert total and exact alert list from the GitHub API before editing any code. Do not look for `.deepsource.toml`; it is not a valid scanner source in this repository.
2. If scanner output is unclear, inspect the matching GitHub Actions run logs before editing code.
3. Read the matching section in `docs/reference/ai-agent-security-prevention-playbook.md` before you code.
4. Pull the closed-alert history from `docs/reference/code-scanning-resolved-findings.md` and copy the matching prevention rule into your working notes before you start coding.
5. Fix root causes, not scanner strings. Avoid suppressions unless you can prove a false positive and document that proof.
6. Prefer the narrowest safe rewrite that removes the vulnerable pattern at the helper boundary so sibling call sites inherit the fix.
7. Re-run targeted tests for every touched package, plus repo-wide `ruff check`, `ruff format --check`, and `python3 tools/lint_docs_structure.py` when those tools are available in the active environment.
8. After pushing, confirm all GitHub workflows are green and refresh the live GitHub alert total. Do not assume a local fix cleared an alert until GitHub reports it.
9. When DeepSource auth is available, query DeepSource for the pushed commit and compare grouped issues plus issue occurrences against the pre-push baseline. If either count increased, run `deepsource-issues`, fix the regression root cause, rerun targeted tests, push again, and repeat this verification.

### Live by-tool snapshot

| Scanner   | Open alerts |
| --------- | ----------: |
| Scorecard | 4           |
| **Total** | **4**       |

2026-04-22 Docker `USER` remediation note: GitHub closed the Trivy `DS002`,
Semgrep `last-user-is-root`, and Hadolint `DL3002` alerts on
`docker/omero-server.Dockerfile` and `docker/omero-web.Dockerfile` after the
default-branch security workflow for commit
`d28baff97a64bb95bbb3b69ba10b91bea4df5db2` completed successfully. The fix
defaults both images to their application users and keeps the required root
bootstrap as an explicit Compose handoff for mounted runtime-path
reconciliation.

At the 2026-04-24 refresh after the successful default-branch security
workflow, the 4 remaining alerts were repository-level Scorecard findings with
no file location: `MaintainedID`, `CodeReviewID`, `CIIBestPracticesID`, and
`BranchProtectionID`. The previous CodeQL file-level findings in
`XTOmeroConnector.py` and the transient Semgrep transport findings from the
first remediation push were no longer open.

### Historical snapshots below

The detailed severity and scanner tables that follow capture the earlier **2026-03-31 pre-remediation snapshot** and are kept for trend analysis only. The live totals above are the authoritative starting point for new remediation work.

### Summary by severity

| Severity | Count | Triage guidance                                                                                             |
| -------- | ----- | ----------------------------------------------------------------------------------------------------------- |
| Critical | 2     | Immediate action required. Merge blocker.                                                                   |
| High     | 59    | Fix within 7 days. Merge blocker for new code.                                                              |
| Error    | 51    | Review and remediate promptly.                                                                              |
| Medium   | 38    | Fix within 30 days.                                                                                         |
| Warning  | 192   | Review during regular maintenance cycles.                                                                   |
| Low      | 8     | Address opportunistically.                                                                                  |
| Note     | ~20   | Informational. Most eliminated by scanner config (B101 test-only, DS162092 infra, B603/B404 informational). |

### Summary by scanner

| Scanner   | Count | Primary finding categories                                                               |
| --------- | ----- | ---------------------------------------------------------------------------------------- |
| Bandit    | 588   | Assert usage (B101), bare except (B112), hardcoded temps (B108), subprocess (B603)       |
| DevSkim   | 131   | HTTP without TLS (DS137138), localhost references (DS162092), tokens in tests (DS173237) |
| Semgrep   | 112   | Raw SQL queries, CSRF exempt views, credential logging, urllib usage, Dockerfile USER    |
| CodeQL    | 86    | Path injection, log injection, cleartext logging, SSRF, stack trace exposure             |
| Scorecard | 40    | Unpinned dependencies, token permissions, branch protection, maintenance signals         |
| Hadolint  | 22    | Root USER in Dockerfiles, unhealthchecked images, unpinned packages, shell lint          |
| Trivy     | 16    | Root user in images, missing HEALTHCHECK, apt-get update without install                 |

### Critical and high findings

#### Critical (2 alerts) — immediate action required

| ID  | Rule              | File                                        | Description                         |
| --- | ----------------- | ------------------------------------------- | ----------------------------------- |
| —   | `py/partial-ssrf` | `omeroweb_admin_tools/views/index_view.py`  | Partial server-side request forgery |
| —   | `py/partial-ssrf` | `omeroweb_omp_plugin/services/ai_assist.py` | Partial server-side request forgery |

#### High (59 alerts)

| Rule                                   | Count | Affected files                                                                                           | Description                              |
| -------------------------------------- | ----- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `py/path-injection`                    | 20    | `job_storage.py`, `core_functions.py`, `index_view.py`                                                   | Uncontrolled data in path expressions    |
| `py/log-injection`                     | 13    | `views.py`, `image_service.py`, `core_functions.py`                                                      | Log injection via unsanitized input      |
| `py/clear-text-logging-sensitive-data` | 8     | `ai_assist.py`, `connection_service.py`, `import_service.py`, `core_functions.py`                        | Sensitive data in log output             |
| `DS002` (Trivy)                        | 7     | All Dockerfiles except `omero-celery-worker`                                                             | Image runs as root user                  |
| `missing-user-entrypoint` (Semgrep)    | 5     | `crowdsec`, `firewall-bouncer`, `path-usage-exporter`, `pg-maintenance`, `redis-sysctl-init` Dockerfiles | No USER directive before ENTRYPOINT      |
| `last-user-is-root` (Semgrep)          | 4     | `omero-server.Dockerfile`, `omero-web.Dockerfile`                                                        | Last USER directive is root              |
| `py/overly-permissive-file`            | 3     | `storage_quotas.py`, `IMS_Export.py`                                                                     | File created with overly permissive mode |
| `py/regex-injection`                   | 1     | `filename_parser.py`                                                                                     | User-controlled data in regex pattern    |

#### Error (51 alerts)

| Rule                                     | Count | Affected files                                     | Description                         |
| ---------------------------------------- | ----- | -------------------------------------------------- | ----------------------------------- |
| `sqlalchemy-execute-raw-query` (Semgrep) | 31    | `omp_plugin/data_store.py`, `upload/data_store.py` | Raw SQL via SQLAlchemy execute      |
| `DS173237` (DevSkim)                     | 8     | Test files                                         | Token-like strings in test source   |
| `subprocess-injection` (Semgrep)         | 2     | `delete_plugin_view.py`                            | User input reaching subprocess call |
| `SC2261` (Hadolint)                      | 1     | `omero-web.Dockerfile`                             | Shell syntax issue                  |

### Medium findings (38 alerts)

| Rule                               | Count | Description                                                                                                                                |
| ---------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `PinnedDependenciesID` (Scorecard) | 32    | Unpinned GitHub Actions, Dockerfiles, or pip installs                                                                                      |
| `py/stack-trace-exposure`          | 4     | Exception details exposed to users                                                                                                         |
| `SecurityPolicyID` (Scorecard)     | 1     | Missing in the 2026-03-15 scan snapshot; resolved before the 2026-04-22 live refresh                                                       |
| `FuzzingID` (Scorecard)            | 1     | No fuzzing integration detected                                                                                                            |

### Warning findings (192 alerts)

| Rule                               | Count | Description                                                                  |
| ---------------------------------- | ----- | ---------------------------------------------------------------------------- |
| `DS137138` (DevSkim)               | 77    | HTTP URLs without TLS (internal Docker network traffic)                      |
| `csrf-exempt` (Semgrep)            | 29    | Django views decorated with `@csrf_exempt`                                   |
| `logger-credential-leak` (Semgrep) | 20    | Logger calls that may include credential-adjacent variables                  |
| `B108` (Bandit)                    | 13    | Hardcoded `/tmp` paths                                                       |
| `B603` (Bandit)                    | 12    | `subprocess.call` with shell=False (informational)                           |
| `B311` (Bandit)                    | 12    | `random` module usage (non-cryptographic)                                    |
| `B310` (Bandit)                    | 10    | URL open with variable input                                                 |
| `dynamic-urllib-use` (Semgrep)     | 10    | Dynamic URL construction with urllib                                         |
| Other                              | 9     | Hadolint DL3003/DL3018/DL3008/DL3002, Bandit B308/B703/B103, CodeQL warnings |

### Note/informational findings (~20 remaining)

Most Note-level findings have been resolved through a combination of code fixes and scanner configuration:

**Code fixes (55 alerts):** Removed dead code, unused imports/variables, added debug logging to empty except blocks, consolidated imports, replaced `ls` with `find` in Dockerfiles, removed unused JS variables.

**Scanner configuration (additional ~570 alerts):**

- Bandit split into production and test scans; `B101` (assert) and `B106` (test credentials) skipped only in test directories. The workflow also uploads a zero-result legacy `bandit` SARIF so GitHub code scanning can close stale alerts from the pre-split Bandit configuration without suppressing current `bandit-prod` or `bandit-test` results.
- `B603` (subprocess shell=False) and `B404` (subprocess import) skipped globally — purely informational, not vulnerabilities
- DevSkim `DS162092` (localhost references) excluded — all 46 are Docker healthchecks, startup scripts, and container-internal networking

| Rule                       | Original | Now | Resolution                                                                                                     |
| -------------------------- | -------- | --- | -------------------------------------------------------------------------------------------------------------- |
| `B101` (Bandit)            | 489      | 0   | **Eliminated** — test directories auto-discovered and excluded from production scan; B101 skipped in test scan |
| `DS162092` (DevSkim)       | 46       | 0   | **Eliminated** — excluded from DevSkim (Docker infrastructure)                                                 |
| `B603` (Bandit)            | 12       | 0   | **Eliminated** — skipped globally (shell=False is secure)                                                      |
| `B404` (Bandit)            | 9        | 0   | **Eliminated** — skipped globally (import is informational)                                                    |
| `B106` (Bandit)            | 2        | 0   | **Eliminated** — skipped in test directories only                                                              |
| `B112` (Bandit)            | 18       | 0   | **Resolved** — added debug logging before `continue`                                                           |
| `B110` (Bandit)            | 3        | 0   | **Resolved** — replaced `pass` with debug logging                                                              |
| `SC2012` (Hadolint)        | 9        | 0   | **Resolved** — replaced `ls` with `find`                                                                       |
| CodeQL py/js notes         | 28       | ~1  | **Mostly resolved** — unused code removed, imports fixed                                                       |
| `B311` (Bandit)            | 12       | 12  | Remaining — `random` for jitter/genetic algo, not crypto                                                       |
| `B105` (Bandit)            | 11       | 11  | Remaining — env var name constants, not actual passwords                                                       |
| `SC2016` (Hadolint)        | 3        | 3   | Remaining — single-quoted printf strings are intentional                                                       |
| `js/syntax-error` (CodeQL) | 1        | 1   | Remaining — Django template tag inside `<script>` block                                                        |

## Triage guidance

### Severity-based SLA

| Severity | Response SLA           | Merge policy                               |
| -------- | ---------------------- | ------------------------------------------ |
| Critical | 24 hours               | Block all merges until resolved            |
| High     | 7 days                 | Block merges introducing new high findings |
| Medium   | 30 days                | Track in sprint backlog                    |
| Warning  | Next maintenance cycle | Address during related work                |
| Note     | Opportunistic          | Fix during refactoring of affected code    |

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
8. **Dockerfile USER** (`DS002`, `missing-user-entrypoint`, `last-user-is-root`): Images should default to application users. If startup bind-mount reconciliation requires root, make root an explicit Compose handoff and drop privileges before long-running processes.

## Hardening roadmap

1. Add branch protection requiring all security scanning checks to pass on pull requests.
2. ~~Add CI policy to fail builds when new `CRITICAL` or `HIGH` alerts are introduced.~~ **Done**: the `security-delta` job in `.github/workflows/security-code-scanning.yml` now enforces a zero-added-alert policy for pull requests and flags newly created default-branch alerts after default-branch security scans.
3. Pin all GitHub Actions to full commit SHAs (addresses 32 Scorecard `PinnedDependenciesID` findings).
4. ~~Add a `SECURITY.md` to the repository root.~~ **Done in-tree**: the repository root now includes `SECURITY.md`, which points GitHub-native security surfaces at the canonical `docs/SECURITY.md` guidance. The Scorecard `SecurityPolicyID` finding is no longer open in the 2026-04-22 live refresh.
5. ~~Add image-level vulnerability scans for each built Docker image.~~
   **Done**: Docker Scout two-phase scanning (pre-build baseline + post-build
   report) covers all images in `docker-compose.yml`, both custom-built and
   third-party. Interactive installs default security hardening to enabled,
   vulnerability scanning remains opt-in, and the hardening pass preserves
   locale data while applying OS and Python package upgrades. See
   `docs/SECURITY.md`.
6. Evaluate adding fuzz testing for parser code (`filename_parser.py`, `sem_edx_parser.py`).

## AI agent maintenance instructions

**This file is the authoritative tracker for code scanning findings.** AI agents working on this repository must follow these rules:

1. **After fixing a vulnerability**: Update the alert counts in this file. Remove the finding from the relevant table if the fix eliminates all instances. Decrement counts if partial. Update the "Last updated" date.

2. **After removing or deleting code**: If the removed code was associated with findings listed here, update the counts and tables accordingly. Re-run the security workflow to verify closure.

3. **After editing GitHub Actions workflows**: Re-verify every touched GitHub Action or reusable workflow against its official GitHub Releases/Tags page, update to the latest published version available at edit time, and pin by full commit SHA. Treat stale action pins as maintenance defects, not optional follow-up.

4. **After adding new code**: If new code introduces patterns flagged by any scanner, document the finding here with its triage status (fix planned, acceptable risk, or false positive).

5. **Periodic refresh**: When running a full security scan, compare the live alert count from the GitHub API against this file. Update all tables to match current state. Use:

   Use the GitHub code-scanning API command above with `state=open` and
   `branch=main`.

6. **Never include exploitation details**: Document what the vulnerability is and where it is located. Do not include proof-of-concept code, payload examples, or step-by-step exploitation instructions.

7. **Adding new plugins or test directories**: The Bandit workflow
   auto-discovers both scan targets and test directories at runtime. Any
   directory at the repo root matching `omero_*` or `omeroweb_*` that contains
   `__init__.py` is automatically included in the scan. Test directories named
   `tests/` or `test/` within those packages are auto-discovered and excluded
   from the production scan, and scanned separately with B101/B106 skipped. The
   repo-root `tests/` directory is also included in the test-only scan. **You
   do NOT need to update the workflow file** because discovery is fully
   dynamic. Just follow the naming convention.

8. **Commit message convention**: When fixing a security finding, use the commit message format:

   ```text
   Fix <scanner>/<rule-id>: <brief description>
   ```

   Example: `Fix CodeQL/py/path-injection: validate upload path against managed root`

9. **Stale-count rule**: Never quote an open-alert total from memory or from this document alone. Always refresh it from the GitHub API first and include the refresh date in your notes or PR text.

## AI agent coding guidelines — preventing new findings

The canonical coding patterns, concrete bad/good examples, stop signs, and external best-practice links now live in `docs/reference/ai-agent-security-prevention-playbook.md`.

This runbook intentionally does **not** duplicate those examples anymore, because repeated duplication caused stale and contradictory guidance over time.

Use this runbook for:

- live open-alert counts and refresh dates
- triage SLA and remediation workflow
- accepted-risk / false-positive policy
- historical open-alert trend snapshots

Use `docs/reference/ai-agent-security-prevention-playbook.md` for:

- filesystem, upload, and atomic file-write rules
- logging, error-response, SQL, HTTP/SSRF, CSRF, subprocess, shell, Docker, workflow, and secret-handling rules
- concrete bad/good code examples
- documentation anti-drift benchmark criteria
