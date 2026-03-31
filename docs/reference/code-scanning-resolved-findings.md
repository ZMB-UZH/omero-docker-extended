# Code Scanning — Resolved Findings Ledger

This document catalogs the **2 011 closed code scanning alerts** that have been identified, triaged, and resolved across the project's lifetime. Its purpose is twofold:

1. **Institutional memory** — so the same classes of issues are never reintroduced.
2. **Agent directive** — AI agents modifying this codebase must consult this ledger before writing new code. Every pattern listed below has been fixed at least once; introducing the same pattern again is a regression.

> **Canonical reference**: `docs/operations/code-scanning.md` tracks _open_ alerts and triage SLAs. This file tracks _closed_ alerts and the lessons they teach.
> **Live refresh note**: The counts in this document were refreshed from the GitHub code-scanning API on **2026-03-31**. Re-query the API before acting on exact totals.

## How to use this document

- **Before writing new code**: scan the "Prevention rules" column for the category of code you are writing (path handling, logging, SQL, file I/O, HTTP responses, Dockerfiles, shell scripts).
- **When a scanner flags new code**: look up the rule ID in the tables below. If a prevention rule exists, apply it. If the finding is a known false positive, document it per the suppression policy in `docs/operations/code-scanning.md`.
- **After fixing a batch of alerts**: add a row to the timeline at the bottom and update counts.

## 2026-03-31 API refresh — authoritative snapshot

GitHub reported the following branch-level totals when this ledger was refreshed:

| State | Alerts |
|---|---:|
| Open on `main` (pre-remediation snapshot for this pass) | 123 |
| Closed on `main` | 2 011 |

### Closed alerts by scanner

| Scanner | Closed alerts | Share |
|---|---:|---:|
| Bandit | 794 | 39.5 % |
| CodeQL | 555 | 27.6 % |
| Semgrep OSS | 273 | 13.6 % |
| devskim | 226 | 11.2 % |
| Scorecard | 101 | 5.0 % |
| Trivy | 43 | 2.1 % |
| Hadolint | 19 | 0.9 % |
| **Total** | **2 011** | **100 %** |

### Closed-alert themes derived from all 2 011 closed alerts

| Theme | Representative rules | Closed alerts | What the fixes taught us |
|---|---|---:|---|
| Assertions and swallowed exceptions | `B101`, `py/empty-except`, `B110`, `B112` | 659 | Production code must not rely on `assert`, and silent `except` blocks are treated as defects, not style issues. |
| SQL and query construction | `sqlalchemy-execute-raw-query`, `B608` | 178 | Query text and user data must be separated consistently, even in tests and helper layers. |
| Logging and user-data exposure | `py/log-injection`, `py/clear-text-logging-sensitive-data`, `py/stack-trace-exposure`, `logger-credential-leak` | 256 | Log every failure usefully, but never echo credentials, session keys, raw URLs, or exception text back to users. |
| Filesystem and path safety | `py/path-injection`, `py/overly-permissive-file`, `insecure-file-permissions`, `B108` | 157 | Every path must stay anchored under an allowlisted root, and every created file/dir must use the minimum viable mode. |
| Workflow and supply-chain pinning | `PinnedDependenciesID`, `DS173237`, `DS162092` | 178 | CI/workflow changes need the same rigor as application code: pin actions, document accepted false positives, and avoid brittle secrets patterns. |
| Django response and CSRF issues | `csrf-exempt`, `direct-use-of-httpresponse` | 48 | Prefer templated or structured responses, and make CSRF-compatible request paths the default instead of opting out. |
| Imports, dead code, and low-signal regressions | `py/unused-import`, `py/unused-global-variable`, `py/unused-local-variable`, `py/unnecessary-lambda`, `py/import-and-import-from` | 82 | Cleanup findings are not noise. They usually signal a refactor that drifted away from the real runtime contract. |
| Dockerfile and shell hygiene | `DS137138`, `DS026`, `DS002`, `SC2012`, `DL3008`, `DL3018`, `ifs-tampering` | 225 | Docker and shell fixes must respect the deployment architecture, but they still need explicit health, pinning, quoting, and privilege reasoning. |

### Hotspot files from the full closed-alert history

| File | Closed alerts | Why future edits need extra care |
|---|---:|---|
| `omeroweb_admin_tools/tests/test_resource_monitoring.py` | 195 | Historical scanner-noise hotspot; test-only patterns must stay intentional and documented. |
| `omeroweb_import/views/core_functions.py` | 120 | Highest-risk application hotspot for path handling, logging, job storage, and import orchestration. |
| `omeroweb_omp_plugin/services/data_store.py` | 116 | Dense SQL/data-store logic with many prior raw-query and logging fixes. |
| `.github/workflows/security-code-scanning.yml` | 66 | Workflow edits can easily reintroduce supply-chain and pinning regressions. |
| `omeroweb_admin_tools/views/index_view.py` | 55 | Proxying, HTTP, and user-visible error handling converge here. |

## Agent prevention playbooks

These are the repository's **mandatory** security examples for AI agents. Follow the safe pattern unless you have a documented reason not to.

### 1. Path handling and staged uploads

Bad:

```python
target = upload_root / request.data["relative_path"]
with target.open("wb") as handle:
    handle.write(payload)
```

Good:

```python
target, path_error = _resolve_staged_target_path(upload_root, relative_path)
if path_error:
    return json_error(path_error, status=400)
with target.open("wb") as handle:
    handle.write(payload)
```

Rule: untrusted paths never reach `open()`, `mkdir()`, `unlink()`, `rename()`, or `shutil.*` until they have been normalized and re-anchored under an allowed root.

### 2. Logging untrusted values

Bad:

```python
logger.warning("Import failed for %s with session %s", rel_path, session_key)
```

Good:

```python
logger.warning(
    "Import failed for %s.",
    sanitize_log_value(rel_path),
)
```

Rule: log the event, not the secret. Any user-controlled value must be sanitized before logging, and any credential-adjacent value must be redacted entirely.

### 3. User-visible errors

Bad:

```python
return JsonResponse({"error": str(exc)}, status=500)
```

Good:

```python
logger.error("Import failed.", exc_info=sanitized_exc_info(exc))
return JsonResponse({"error": errors.unexpected_server_error_importing()}, status=500)
```

Rule: detailed exceptions belong in server logs, not in HTTP responses, HTML fragments, or JSON payloads returned to users.

### 4. SQL composition

Bad:

```python
cursor.execute(f"SELECT * FROM settings WHERE username = '{username}'")
```

Good:

```python
cursor.execute(
    "SELECT * FROM settings WHERE username = %s",
    (username,),
)
```

Rule: never concatenate user input into SQL. Use database parameterization or safe SQL-construction helpers every time.

### 5. Temporary paths and file permissions

Bad:

```python
export_path = "/tmp/demo.ims"
os.chmod(export_path, 0o777)
```

Good:

```python
export_path = tmp_path / "demo.ims"
os.chmod(export_path, 0o640)
```

Rule: tests must use `tmp_path`/`tempfile`, and production code must use repository-configured or environment-driven paths with minimum required permissions.

### 6. HTTP, SSRF, and internal services

Bad:

```python
urllib.request.urlopen(user_supplied_url)
```

Good:

```python
parsed = urlsplit(candidate_url)
if parsed.scheme not in {"http", "https"} or parsed.hostname not in allowed_hosts:
    raise ValueError("Invalid upstream target")
response = requests.get(candidate_url, timeout=timeout_seconds)
```

Rule: URL scheme, host, and method must be validated before any outbound request, even for internal Docker-network services.

### 7. Subprocess boundaries

Bad:

```python
subprocess.run(["omero", "delete", request.POST["object_ref"]], check=False)
```

Good:

```python
object_type, object_id = _parse_delete_target(request.POST["object_ref"])
subprocess.run(
    ["omero", "delete", f"{object_type}:{object_id}"],
    check=False,
)
```

Rule: parse and validate the untrusted parts first, then construct the subprocess arguments from typed values instead of passing raw request text through.

### 8. Workflow and Docker pinning

Bad:

```yaml
- uses: actions/checkout@v6
```

Good:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
```

Rule: workflow actions and base images must be pinned to audited immutable identifiers, not floating tags.

---

## Closed alerts by scanner

| Scanner | Closed alerts | Share |
|---|---:|---:|
| Bandit | 794 | 39.5 % |
| CodeQL | 555 | 27.6 % |
| Semgrep OSS | 273 | 13.6 % |
| devskim | 226 | 11.2 % |
| Scorecard | 101 | 5.0 % |
| Trivy | 43 | 2.1 % |
| Hadolint | 19 | 0.9 % |
| **Total** | **2 011** | **100 %** |

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
