---
name: security-review
description: Security review for uploads, filesystem paths, SQL, responses, subprocesses, Docker, workflows, and secrets in this repo.
origin: ECC v2.0.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v2.0.0/skills/security-review/SKILL.md
---

# Security Review

Use this skill when reviewing or changing security-sensitive code outside a scanner-remediation-only workflow.

## Upstream baseline

## Repo overlay

- Start from `third_party/ecc-v2.0.0/skills/security-review/SKILL.md` and follow the mandatory security read order in `AGENTS.md`.
- Focus on helper and boundary correctness: uploads, filesystem paths, SQL, responses, subprocesses, Docker/workflows, outbound HTTP, logs, and secrets.
- Prefer root-cause fixes over suppressions or call-site patches.
- Treat env parsing and shell interpolation as security boundaries, not convenience helpers.
- Name the regression tests and validation steps before editing code.
- If the change touches workflows, refresh action pins from official sources first.
- Codex Security multi-worker scans are on-demand only: spawn the minimum required scanner workers only when explicitly requested and required; keep remediation, validation, reconciliation, commits, pushes, and releases in the parent session.

## 2026-06 remediation reminders

- Canonicalize and reject symlinked state, upload, Zarr, and host-control paths before file I/O, chmod/chown, or subprocess handoff.
- Enforce server-side byte, file, line, element, label, chunk, and array limits for uploads, Zarr, OME-Zarr, and SEM-EDX parsing.
- Preserve OMERO requester ownership: use validated requester sessions or independent admin-created user sessions, not broad fallbacks.
- Keep CSRF and sanitized proxy responses; never expose raw upstream errors, internal URLs, credentials, stack traces, or topology.
- Keep monitoring/management loopback-only and do not mount `/var/run/docker.sock` by default.
- Pin images/downloads by digest/checksum, actions by full SHA, and release carriers with SBOM/provenance plus Docker Scout on the pushed tag.
