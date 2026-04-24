# AI Agent Security Prevention Playbook

This is the repository's **primary anti-regression security playbook for AI agents**.

Use it together with:

- `AGENTS.md` for the repo entry contract and mandatory read order.
- `docs/operations/code-scanning.md` for the **live** open-alert inventory, SLAs, and remediation workflow.
- `docs/reference/code-scanning-resolved-findings.md` for the **closed-alert history** and per-rule lessons learned.

This playbook exists because repeated AI edit rounds can otherwise reintroduce the same vulnerabilities in slightly different forms. Its job is to turn the repository's full closed-alert history and external best practices into **one canonical set of coding rules** with concrete examples.

## Document ownership and anti-drift rules

Use each document for one purpose only:

- `AGENTS.md`: routing and mandatory prerequisites. It should not duplicate volatile alert totals.
- `docs/operations/code-scanning.md`: live open-alert totals, refresh dates, SLAs, and remediation process.
- `docs/reference/code-scanning-resolved-findings.md`: closed-alert totals, hotspot history, and per-rule prevention lessons.
- `docs/reference/ai-agent-security-prevention-playbook.md`: normative coding rules, bad/good examples, stop signs, and external best-practice links.
- `docs/index.md`: links only.

If two docs seem to disagree:

- Prefer this playbook for coding patterns.
- Prefer `docs/operations/code-scanning.md` for live open-alert counts and batch workflow.
- Prefer `docs/reference/code-scanning-resolved-findings.md` for resolved-history facts and hotspot files.

Do not copy the same long bad/good example into multiple docs. Link here instead.

## External best-practice references

These sources were used to shape the rules below:

- OWASP Path Traversal: <https://owasp.org/www-community/attacks/Path_Traversal>
- OWASP File Upload Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html>
- OWASP Logging Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html>
- OWASP Error Handling Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html>
- OWASP SQL Injection Prevention Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html>
- OWASP Server Side Request Forgery Prevention Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html>
- OWASP Cross-Site Request Forgery Prevention Cheat Sheet: <https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html>
- Python `tempfile` docs: <https://docs.python.org/3/library/tempfile.html>
- Python `os.replace()` docs: <https://docs.python.org/3/library/os.html#os.replace>
- Python `subprocess` security considerations: <https://docs.python.org/3/library/subprocess.html#security-considerations>
- Dockerfile best practices: <https://docs.docker.com/develop/develop-images/dockerfile_best-practices/>
- GitHub personal access token guidance: <https://docs.github.com/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>
- GitHub Actions hardening guidance: <https://docs.github.com/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions>

## What the closed-alert history says

The latest full closed-history API refresh, summarized in `docs/reference/code-scanning-resolved-findings.md`, shows that the highest-recurrence families are not random noise; they identify the exact places where AI agents tend to drift:

| Rule family                                                        | Closed alerts | What future agents must assume                                                                                            |
| ------------------------------------------------------------------ | ------------: | ------------------------------------------------------------------------------------------------------------------------- |
| `B101`                                                             | 492           | Production/runtime validation must not rely on `assert`; tests may.                                                       |
| `sqlalchemy-execute-raw-query` / `B608`                            | 178 total     | Raw SQL is a repeat hotspot. Treat every query boundary as hostile until parameterized.                                   |
| `DS137138`                                                         | 147           | Internal Docker-network HTTP is common here; document accepted false positives instead of weakening architecture blindly. |
| `py/log-injection`                                                 | 123           | Any unsanitized user string in logs will eventually regress.                                                              |
| `py/empty-except` / `B110` / `B112`                                | 167 total     | Silent exception handling is recurrent, not incidental.                                                                   |
| `PinnedDependenciesID`                                             | 99            | Workflow and supply-chain drift is persistent unless pinning is mandatory.                                                |
| `B108` / `py/path-injection`                                       | 145 total     | File and path handling must go through hardened helpers, not local one-offs.                                              |
| `py/stack-trace-exposure` / `py/clear-text-logging-sensitive-data` | 113 total     | Internal error detail and secret leakage recur together.                                                                  |
| `csrf-exempt` / direct `HttpResponse` issues                       | 48 total      | Browser-facing shortcuts become security debt quickly.                                                                    |

## Mandatory pre-edit workflow

Before editing security-relevant code:

1. Identify the boundary class: path/file, logging/error, SQL, HTTP/SSRF, CSRF/response, subprocess/shell, Docker/workflow, or secrets.
2. Read the matching section in this playbook.
3. Read the matching rule family in `docs/reference/code-scanning-resolved-findings.md`.
4. Name the helper or boundary you will harden. Prefer one helper-level rewrite over many shallow call-site patches.
5. Name the regression tests you will add before you touch code.
6. Decide how you will prove no credential, session, stack trace, or internal path leaks to the user or logs.
7. After the change, run the narrowest fast tests first, then the runtime-complete verification path if available.
8. After pushing, confirm GitHub workflows are green, refresh the live GitHub code-scanning count, and when DeepSource auth is available compare grouped issues plus issue occurrences against the pre-push baseline. Do not infer closure from local reasoning alone.

## Core rules with concrete examples

### 1. Path handling, uploads, and managed roots

Never allow untrusted path text to reach filesystem operations directly.

Bad:

```python
target = upload_root / request.POST["relative_path"]
target.parent.mkdir(parents=True, exist_ok=True)
with target.open("wb") as handle:
    handle.write(payload)
```

Good:

```python
normalized_path, normalize_error = _normalize_upload_relative_path(relative_path)
if normalize_error:
    return json_error(normalize_error, status=400)

target = _resolve_managed_child_parts(
    upload_root,
    PurePosixPath(normalized_path).parts,
    max_bytes=MAX_UPLOAD_STAGED_TARGET_BYTES,
)
target.parent.mkdir(parents=True, exist_ok=True)
with target.open("wb") as handle:
    handle.write(payload)
```

Required rules:

- Validate **every path part**, not just the final string.
- Reject empty parts, `.` , `..`, embedded `/`, and embedded `\`.
- Re-anchor under an allowlisted root **before** `open()`, `mkdir()`, `unlink()`, `rename()`, `stat()`, `shutil.*`, or `os.replace()`.
- Reject existing symlinked path segments when the path must stay within a managed tree.
- Enforce explicit length limits before filesystem operations.
- Canonicalize identifiers such as UUID job IDs before using them in filenames.
- Re-validate at each sink. A previously normalized path does not justify a later raw `Path(...) / user_text`.

Stop sign:

- If your safety argument depends only on `Path.resolve(strict=False)` over a path with non-existent trailing segments, stop. That is not enough by itself for this repository.

### 2. Atomic job files, temp files, and permissions

Never rewrite state files in place when concurrent readers/writers exist.

Bad:

```python
with open(job_path, "w", encoding="utf-8") as handle:
    json.dump(job_dict, handle)
```

Good:

```python
with portalocker.Lock(lock_path, "a+", timeout=timeout_seconds):
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=job_path.parent,
        delete=False,
    ) as handle:
        json.dump(job_dict, handle)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, job_path)
```

Required rules:

- Lock first when concurrent access is possible.
- Write the temporary file in the **same directory** as the final file so replacement stays atomic.
- Flush and `fsync()` the temp file before replacement.
- Use `os.replace()` for the commit step.
- Use the minimum viable mode (`0o640` files, `0o750` directories unless a documented runtime contract requires otherwise).
- In tests, prefer `tmp_path` or `tempfile`, not hardcoded `/tmp`.

### 3. Logging and user-visible errors

User strings in logs and raw exceptions in responses are separate but closely related regressions.

Bad:

```python
logger.warning("Upload failed for %s: %s", rel_path, exc)
return JsonResponse({"ok": False, "error": str(exc)}, status=500)
```

Good:

```python
logger.warning(
    "Upload failed for %s.",
    sanitize_log_value(rel_path),
    exc_info=True,
)
return JsonResponse(
    {"ok": False, "error": errors.unexpected_server_error_uploading_files()},
    status=500,
)
```

Required rules:

- Sanitize every user-controlled value before logging.
- Never log passwords, PATs, API keys, session keys, or raw credential-bearing URLs.
- Never return `str(exc)`, tracebacks, local paths, usernames, or service topology to the browser unless the product contract explicitly requires it.
- Use generic error bodies for clients and detailed logs on the server side only.
- Authentication and authorization failures should not leak whether a secret, user, or endpoint exists.

### 4. SQL and ORM boundaries

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

Required rules:

- Separate SQL structure from SQL data every time.
- Use parameterized queries or safe SQL composition helpers such as `psycopg2.sql.SQL` with `sql.Identifier` for identifiers.
- If raw SQL is unavoidable, isolate it in a helper with a narrow, typed interface.
- Do not "fix the alert" by moving string interpolation to a different helper. Remove the interpolation entirely.

### 5. Outbound HTTP and SSRF boundaries

Bad:

```python
response = urllib.request.urlopen(request.GET["url"])
```

Good:

```python
parsed = urlsplit(candidate_url)
if parsed.scheme not in {"http", "https"}:
    raise ValueError("Invalid scheme")
if parsed.hostname not in allowed_hosts:
    raise ValueError("Invalid host")
response = requests.get(candidate_url, timeout=timeout_seconds)
```

Required rules:

- Validate scheme, host, port, and any path-prefix contract before the request.
- Use allowlists for internal service names and upstream hosts.
- Set timeouts explicitly.
- Do not let browser input supply a raw upstream URL when a typed service key or route identifier can be used instead.

### 6. Django responses, CSRF, and reflected data

Bad:

```python
@csrf_exempt
def save(request):
    return HttpResponse(request.POST["message"])
```

Good:

```python
def save(request):
    payload = {"ok": True, "message": _("Saved")}
    return JsonResponse(payload)
```

Required rules:

- Prefer `JsonResponse`, `render()`, and `format_html()` over raw `HttpResponse(string)`.
- Escape reflected user content or keep the response type `text/plain`.
- Prefer CSRF-compatible request flows with `X-CSRFToken`; do not add `@csrf_exempt` unless there is a documented, reviewed reason.
- When a CSRF exemption remains necessary, document the alternative authentication/control that makes the route safe.

### 7. Subprocesses and shell

Bad:

```python
subprocess.run(["omero", "delete", request.POST["target"]], check=False)
```

Good:

```python
object_type, object_id = _parse_delete_target(request.POST["target"])
subprocess.run(
    [OMERO_BIN, "delete", f"{object_type}:{object_id}"],
    check=False,
)
```

Required rules:

- Parse untrusted input into typed values before building command arguments.
- Prefer `shell=False`.
- Use full executable paths or verify the executable explicitly.
- In shell scripts, quote variables and restore `IFS` after temporary changes.
- Do not concatenate user text into shell snippets to silence a scanner. Redesign the interface instead.

### 8. Dockerfiles, workflows, and supply chain

Bad:

```yaml
- uses: actions/checkout@v6
```

Good:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
```

Required rules:

- Pin GitHub Actions to full commit SHAs.
- Pin base images to exact tags or digests; never use `:latest`.
- Run as a non-root user unless the runtime contract genuinely requires root. If root is required, document why inline.
- Treat workflow expressions, artifact names, branch names, and pull-request metadata as untrusted input.
- Do not put secrets into workflow YAML, checked-in example files, or generated docs.

### 9. Secrets, PATs, and AI-agent operational hygiene

Bad:

```bash
git remote set-url origin https://<token>@github.com/org/repo.git
```

Good:

```bash
read -s TOKEN
export TOKEN
# Use the token only for the current command or process, then unset it.
```

Required rules:

- Prefer GitHub App auth, platform credential helpers, or short-lived tokens over long-lived PATs.
- If a PAT must be used, prefer least-privilege and short-expiry tokens.
- Never place tokens in command lines that will be logged, in `git remote` URLs, in repository files, or in long-lived git config.
- Prefer interactive prompts, `read -s`, or short-lived environment variables.
- Remove any temporary credential-bearing files immediately after use.
- In committed tests, use obviously fake values only.

### 10. Tests that prevent real regressions

Bad tests only prove scanner appeasement. Good tests prove the runtime boundary.

Required rules:

- Add regression tests at the helper or boundary you hardened.
- Test the unsafe shape directly: traversal attempts, symlinked segments, credential-bearing log values, raw exception text, invalid upstream hosts, and overly-permissive modes.
- If the runtime-complete environment is unavailable, prove whether a failure is baseline or introduced before excluding it from the validation story.
- Keep tests host-agnostic: use `tmp_path`, fixture data, environment variables, and repo-relative discovery.

## Mandatory stop signs

Stop and redesign if any of these are true:

- You are about to call a filesystem API with user text that has not gone through a dedicated managed-path helper.
- You are about to return `str(exc)` or an internal path in an HTTP response.
- You are about to log a user string or credential-adjacent value without sanitization/redaction.
- You are about to use raw SQL string interpolation.
- You are about to let a request parameter control a full URL or subprocess argument shape.
- You are about to place a secret or PAT in a command line, repo file, workflow file, or git config.
- You are about to duplicate a live alert count or long bad/good example into a second doc instead of linking to the primary source.

## Documentation benchmark for future edits

Before merging any security-document change, check these criteria:

1. **Freshness**: live counts in `docs/operations/code-scanning.md` were refreshed from the GitHub API on the same date the doc claims.
2. **Single-source ownership**: live counts appear only in the runbook; resolved-history counts appear only in the ledger; bad/good examples live only here.
3. **Routing**: `AGENTS.md` references this playbook near the top, and `docs/index.md` links to it.
4. **Coverage**: the top recurring rule families from the closed-alert history all map to a section in this document.
5. **No stale numeric drift**: `AGENTS.md` and `docs/index.md` contain no hardcoded historical alert totals.
6. **Verification story**: the doc update explains how future agents should prove fixes instead of only how to appease scanners.
