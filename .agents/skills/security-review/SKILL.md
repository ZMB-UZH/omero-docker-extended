---
name: security-review
description: Security review for uploads, filesystem paths, SQL, responses, subprocesses, Docker, workflows, and secrets in this repo.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/security-review/SKILL.md
---

# Security Review

Use this skill when reviewing or changing security-sensitive code outside a scanner-remediation-only workflow.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/security-review/SKILL.md` for the generic security checklist.

## Repo overlay

- Follow the mandatory security read order in `AGENTS.md`.
- Focus on helper and boundary correctness: file paths, uploads, SQL, subprocesses, Docker/workflows, outbound HTTP, logs, and HTTP responses.
- Focus on uploads, filesystem paths, SQL, responses, subprocesses, Docker, workflows, and secrets.
- Prefer root-cause fixes over suppressions or call-site patches.
- Treat env parsing and shell interpolation as security boundaries, not convenience helpers.
- Name the regression tests and validation steps before editing code.
- If the change touches workflows, refresh action pins from official sources first.
