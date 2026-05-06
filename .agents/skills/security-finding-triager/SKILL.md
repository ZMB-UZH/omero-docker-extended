---
name: security-finding-triager
description: Triage code-scanning findings using the repo's live runbook, closed-history ledger, and canonical prevention playbook before editing security-sensitive code.
origin: repo-local skill informed by ECC v1.10.0 workflow patterns
---

# Security Finding Triager

Use this skill for any security-relevant code change or scanner-driven remediation.

## Mandatory read order

1. `docs/reference/ai-agent-security-prevention-playbook.md`
2. `docs/reference/code-scanning-resolved-findings.md`
3. `docs/operations/code-scanning.md`

## Mandatory workflow

1. Refresh the live alert inventory from GitHub before coding.
2. Use GitHub Actions logs for scanner runtime output when an alert lacks context.
3. Do not look for `.deepsource.toml`; DeepSource repo-file configuration is retired for this repository, and GitHub PATs do not authenticate to DeepSource.
   If DeepSource auth, subscription, repository access, or API availability is unavailable, report DeepSource counts as skipped or unavailable, not zero, and continue the rest of the local and GitHub workflow verification.
   If it is available, distinguish grouped issues from issue occurrences and check `latest_commit_oid`; if it does not match the commit under review, report the count as a lagged snapshot.
4. For GitHub HTTPS Git operations, use a PAT or credential manager, never an account password; use the socket-backed `tools/git_push_with_pat.py`, prompting on a TTY or setting short-lived `GITHUB_TOKEN` for non-TTY shells.
5. Keep scanner remediation on the current remote default branch unless the user explicitly names another branch; do not create branches or draft PRs just to run scanners.
6. If GitHub auth is required and no valid credential is available, ask for it immediately and pause; do not retry auth failures. DeepSource auth or subscription failures are non-blocking for the rest of verification: report the skipped/unavailable DeepSource status and continue the local and GitHub checks.
7. Classify the boundary: path/file, logging, SQL, outbound HTTP, CSRF/response, subprocess, Docker/workflow, or secrets.
8. Name the helper or boundary you will harden.
9. Name the regression tests you will run before editing code.
10. Fix the root cause, not the scanner string.
11. Re-run targeted tests, Ruff, and docs validation.
12. After every push, confirm GitHub workflows are green.
13. When DeepSource auth and repository access are available, compare grouped issues and issue occurrences for the pushed commit against the pre-push baseline; if either count increased, fetch grouped issue details and repeat the fix/test/push verification loop. If DeepSource is skipped or unavailable, keep the remaining workflow checks moving and report that DeepSource could not be compared.

## Rules

- Prefer helper-boundary fixes over shallow call-site patches.
- Do not add suppressions unless the finding is a proven false positive and the proof is documented.
- Do not return raw exception text, credentials, internal paths, or topology in HTTP responses.
- Do not log unsanitized user input or credential-adjacent values.
- Do not guess that an alert is closed based on local reasoning alone.

## Good outcome

The remediation references the live runbook, follows the canonical prevention rule for that finding family, and lands with the narrowest correct regression tests.
