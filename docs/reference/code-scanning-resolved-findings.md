# Code Scanning — Resolved Findings Ledger

This document catalogs the **1 845 code scanning alerts** that have been identified, triaged, and resolved across the project's lifetime. Its purpose is twofold:

1. **Institutional memory** — so the same classes of issues are never reintroduced.
2. **Agent directive** — AI agents modifying this codebase must consult this ledger before writing new code. Every pattern listed below has been fixed at least once; introducing the same pattern again is a regression.

> **Canonical reference**: `docs/operations/code-scanning.md` tracks _open_ alerts and triage SLAs. This file tracks _closed_ alerts and the lessons they teach.

## How to use this document

- **Before writing new code**: scan the "Prevention rules" column for the category of code you are writing (path handling, logging, SQL, file I/O, HTTP responses, Dockerfiles, shell scripts).
- **When a scanner flags new code**: look up the rule ID in the tables below. If a prevention rule exists, apply it. If the finding is a known false positive, document it per the suppression policy in `docs/operations/code-scanning.md`.
- **After fixing a batch of alerts**: add a row to the timeline at the bottom and update counts.

---

## Closed alerts by scanner

| Scanner | Closed alerts | Share |
|---|---:|---:|
| Bandit | 753 | 40.8 % |
| CodeQL | 521 | 28.2 % |
| Semgrep | 221 | 12.0 % |
| DevSkim | 208 | 11.3 % |
| Scorecard | 91 | 4.9 % |
| Trivy | 35 | 1.9 % |
| Hadolint | 16 | 0.9 % |
| **Total** | **1 845** | **100 %** |

---

## Resolved finding categories — full catalog

### Python — assertions and control flow

| Rule ID | Count | Root cause | Fix applied | Prevention rule |
|---|---:|---|---|---|
| `B101` | 492 | `assert` used in production code where it can be stripped by `python -O` | Replaced with `if not condition: raise ValueError(...)` in production code. In test code, left as-is (scanner configured to skip B101 in test dirs). | **Never use `assert` for runtime validation in production code.** Use `if/raise`. `assert` is only acceptable in test files. |
| `py/empty-except` | 107 | Empty `except` blocks (bare `pass` or `continue`) swallowing errors silently | Added `logger.debug("...", exc_info=True)` before `continue`/`pass` | **Every except block must either log, re-raise, or explicitly handle.** No silent swallowing. |
| `B112` | 22 | `try/except/continue` without logging | Added debug logging before `continue` | Same as above. |
| `B110` | 35 | `try/except/pass` without logging | Added debug logging before `pass` | Same as above. |
| `py/unnecessary-lambda` | 15 | `lambda x: str(x)` instead of `str` | Replaced with direct function reference | **Lambdas must add logic** beyond calling a single function with the same arguments. |
| `py/uninitialized-local-variable` | 11 | Variable read before assignment on some code paths | Initialized with sentinel before branching | **Initialize all locals before branching constructs.** |
| `py/call/wrong-arguments` | 5 | Function called with wrong argument count | Fixed call signatures | **Match function signatures exactly.** |
| `py/pythagorean` | 7 | `sqrt(a**2 + b**2)` numerical instability | Replaced with `math.hypot(a, b)` | **Use `math.hypot()` for Euclidean distance.** |

### Python — dead code and imports

| Rule ID | Count | Root cause | Fix applied | Prevention rule |
|---|---:|---|---|---|
| `py/unused-import` | 32 | Import statements referencing symbols not used in the module | Removed unused imports; added to `__all__` for intentional re-exports | **Remove imports immediately when unused.** For re-exports, add to `__all__`. |
| `py/unused-global-variable` | 15 | Module-level variables assigned but never read | Removed dead assignments or added to `__all__` | **No dead assignments at module scope.** |
| `py/unused-local-variable` | 12 | Local variables assigned then never referenced | Used `_` for discarded tuple positions; removed unused assignments | **Use `_` for discarded values.** Remove write-only variables. |
| `py/multiple-definition` | 9 | Same variable assigned in separate branches causing shadowing | Consolidated initialization before the branch | **Initialize once before the branch, assign in each arm.** |
| `js/unused-local-variable` | 5 | Unused JS variables in Django templates | Removed dead JS declarations | **No unused const/let declarations in template JS.** |

### Python — security: injection and data exposure

| Rule ID | Count | Root cause | Fix applied | Prevention rule |
|---|---:|---|---|---|
| `py/log-injection` | 120 | User-controlled data interpolated into log messages without sanitization | Wrapped all user values with `sanitize_log_value()` | **Always pass user input through `sanitize_log_value()` before logging.** Newlines and control characters in logs enable log injection. |
| `py/clear-text-logging-sensitive-data` | 53 | Passwords, tokens, or session keys appearing in log output | Redacted sensitive fields before logging; used `sanitize_url_for_logging()` for URLs | **Never log credentials.** Redact passwords, API keys, and session tokens before any log call. |
| `py/stack-trace-exposure` | 52 | Exception tracebacks returned in HTTP error responses | Returned generic error messages to clients; logged full traces server-side only | **Return generic error strings to users.** Log `exc_info=True` server-side. |
| `py/path-injection` | 39 | User-supplied filenames/paths used in `open()`, `os.path.join()` without containment | Added `path.resolve().relative_to(root)` checks; used `_resolve_managed_child_path()` | **Validate every user-supplied path** with `resolve()` + `relative_to(allowed_root)` before any filesystem operation. |
| `py/partial-ssrf` | 4 | URL construction with partially user-controlled components | Validated `scheme in {"http","https"}` and `netloc` against allowlists | **Validate URL scheme and host** before any outbound HTTP request. |
| `py/regex-injection` | 1 | User input compiled as regex pattern | Added length limit, unsafe-pattern blocklist, and try/except around `re.compile` | **Validate user-supplied regex** with length limits and pattern blocklists before compilation. |
| `py/overly-permissive-file` | 10 | `os.chmod` with 0o777, 0o666, 0o644 on sensitive files | Tightened to 0o640/0o750; documented cases where group/world read is architecturally required | **Use minimum required permissions.** 0o640 for files, 0o750 for directories. Document exceptions. |
| `B608` | 10 | SQL string concatenation in execute() calls | Refactored to use `psycopg2.sql.SQL` / `sql.Identifier` parameterization, or extracted safe helpers | **Never concatenate user data into SQL strings.** Use parameterized queries or `sql.SQL().format(sql.Identifier(...))`. |
| `B103` | 4 | `os.chmod` with permissive modes | Same as py/overly-permissive-file | Same as above. |

### Python — subprocess and randomness

| Rule ID | Count | Root cause | Fix applied | Prevention rule |
|---|---:|---|---|---|
| `B108` | 64 | Hardcoded `/tmp` paths | Replaced with `tempfile.mkdtemp()`, config-driven paths, or environment variables | **Use `tempfile` or configured paths**, not bare `/tmp`. |
| `B105` | 40 | Variable names matching password patterns (e.g., `PASSWORD_ENV = "OMERO_DB_PASS"`) | Documented as false positives — these hold env-var names, not credentials | **Acceptable when holding env-var names.** Do not rename to avoid the pattern. |
| `B311` | 37 | `random.uniform()` / `random.choice()` for non-security purposes | Left as-is — used for jitter and display randomization, not cryptography | **`random` is fine for non-security use.** Use `secrets` only for tokens/nonces. |
| `B607` | 23 | `subprocess.run` with partial executable path | Used full paths or validated existence | **Use full paths in subprocess calls** or verify the executable exists. |
| `B603` | 12 | `subprocess.run` with `shell=False` (informational) | Skipped in scanner config — `shell=False` IS the secure pattern | **Informational only.** `shell=False` is correct. |
| `B404` | 9 | `import subprocess` flagged as informational | Skipped in scanner config | **Informational only.** The import is not a vulnerability. |

### Semgrep — Django and web security

| Rule ID | Count | Root cause | Fix applied | Prevention rule |
|---|---:|---|---|---|
| `sqlalchemy-execute-raw-query` | 165 | Direct `execute("SELECT ...")` with string SQL | Extracted `_safe_query()` helpers; separated SQL composition from execution | **Separate SQL composition from execution.** Build SQL with `sql.SQL()` in a distinct function; call `execute()` only with the composed object. |
| `csrf-exempt` | 29 (open) | `@csrf_exempt` on Django views because JS doesn't send CSRF tokens | 29 remain open — requires coordinated template + view changes | **When adding new views**: add `X-CSRFToken` header in template JS and omit `@csrf_exempt`. |
| `direct-use-of-httpresponse` | 9 | `HttpResponse(string)` without escaping | Used `JsonResponse` for JSON; `format_html()` for HTML; explicit `content_type` | **Use `JsonResponse` for JSON data.** Use `format_html()` or `render()` for HTML. Set `content_type` explicitly. |
| `reflected-data-httpresponsebadrequest` | 2 | User input reflected in error message body | HTML-escaped user data; set `content_type="text/plain"` | **Escape all user data in error responses.** Use `text/plain` content type for error messages. |
| `avoid-mark-safe` | 1 | `mark_safe()` with manually-escaped content | Replaced with `format_html_join()` which auto-escapes | **Never use `mark_safe()`.** Use `format_html()` / `format_html_join()` instead. |
| `logger-credential-leak` | 23 | Logger calls including credential-adjacent variables | Redacted sensitive values before logging | Same as `py/clear-text-logging-sensitive-data` above. |
| `insecure-file-permissions` | 10 | Same underlying issue as `py/overly-permissive-file` | Same fixes | Same rule. |
| `ifs-tampering` | 4 | Shell scripts modifying `IFS` without restoring | Saved and restored `IFS` around parsing blocks | **Save/restore IFS** in shell scripts: `_old_IFS="$IFS"; IFS=...; ...; IFS="$_old_IFS"`. |

### Dockerfile and infrastructure

| Rule ID | Count | Root cause | Fix applied | Prevention rule |
|---|---:|---|---|---|
| `DS137138` | 129 | HTTP URLs without TLS in Docker configs | Internal Docker-network traffic — TLS at reverse proxy. Accepted. | **Expected for container-internal traffic.** TLS terminates at the reverse proxy. |
| `PinnedDependenciesID` | 89 | Unpinned GitHub Actions or Docker base images | Pinned actions to full commit SHAs; base images to exact tags | **Pin all actions to SHA; base images to exact tags.** Never use `:latest`. |
| `DS162092` | 46 | Localhost references in Docker healthchecks and networking | Excluded in DevSkim config — expected for Docker infrastructure | **Expected in Docker infrastructure.** No action needed. |
| `DS173237` | 33 | Token-like strings in test files | Documented as dummy credentials for unit tests | **Use obviously fake values** (`"test_password"`, `"dummy_token"`) in test fixtures. |
| `DS026` / `DS002` | 30 | Missing HEALTHCHECK / root user in Dockerfiles | Health checks in `docker-compose.yml`; root required for bind-mount volumes | **Add HEALTHCHECK in compose.** Document containers requiring root with inline comments. |
| `SC2012` | 9 | `ls` in Dockerfile RUN commands | Replaced with `find` | **Use `find` instead of `ls`** in Dockerfile RUN commands. |
| `DL3003` / `DL3008` / `DL3018` | 7 | WORKDIR/package pinning in Dockerfiles | Used WORKDIR; pinned where practical | **Use WORKDIR instead of cd.** Pin system packages where feasible. |

---

## Hotspot files (most alerts resolved)

These files have historically generated the most scanning alerts. Extra review attention is warranted when modifying them.

| File | Closed alerts | Primary issues |
|---|---:|---|
| `omeroweb_admin_tools/tests/test_resource_monitoring.py` | 195 | B101 (assert in tests — now scanner-excluded) |
| `omeroweb_omp_plugin/services/data_store.py` | 116 | Raw SQL (sqlalchemy-execute), credential logging |
| `omeroweb_import/views/core_functions.py` | 114 | Path injection, log injection, cleartext logging |
| `omeroweb_admin_tools/views/index_view.py` | 38 | urllib usage, CSRF exempt, HttpResponse |
| `omeroweb_omp_plugin/views/index_view.py` | 32 | mark_safe, HttpResponse, CSRF exempt |

---

## Resolution timeline

| Date | Open before | Fixed | Method | Key changes |
|---|---:|---:|---|---|
| 2026-03-15 | ~940 | ~570 | Scanner config | B101 test split, DS162092 exclusion, B603/B404 skip |
| 2026-03-16 | ~370 | ~170 | Code fixes | Log sanitization, empty-except logging, unused code removal |
| 2026-03-25 | ~200 | ~2 | Code fixes | SQL refactoring (_safe_query helper) |
| 2026-03-26 | 198 | 15 | Code fixes | Reflected-data escaping, mark_safe removal, B101→if/raise, permission tightening |
| 2026-03-26 | 183 | — | Current | Remaining: CSRF (29), path-injection (20), urllib (20), Dockerfile design (47), Scorecard (17) |

---

## Cross-references

- **Open alerts and triage SLAs**: `docs/operations/code-scanning.md`
- **Security policy and hardening**: `docs/SECURITY.md`
- **Scanner workflow**: `.github/workflows/security-code-scanning.yml`
- **AI agent coding guidelines**: `docs/operations/code-scanning.md` § "AI agent coding guidelines"
- **Agent working contract**: `AGENTS.md` § "Security scanning policy"
