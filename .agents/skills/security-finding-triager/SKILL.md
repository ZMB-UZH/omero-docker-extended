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
2. Classify the boundary: path/file, logging, SQL, outbound HTTP, CSRF/response, subprocess, Docker/workflow, or secrets.
3. Name the helper or boundary you will harden.
4. Name the regression tests you will run before editing code.
5. Fix the root cause, not the scanner string.
6. Re-run targeted tests, Ruff, and docs validation.
7. Refresh the live alert inventory again after the push that is expected to close the alert.

## Rules

- Prefer helper-boundary fixes over shallow call-site patches.
- Do not add suppressions unless the finding is a proven false positive and the proof is documented.
- Do not return raw exception text, credentials, internal paths, or topology in HTTP responses.
- Do not log unsanitized user input or credential-adjacent values.
- Do not guess that an alert is closed based on local reasoning alone.

## Good outcome

The remediation references the live runbook, follows the canonical prevention rule for that finding family, and lands with the narrowest correct regression tests.
