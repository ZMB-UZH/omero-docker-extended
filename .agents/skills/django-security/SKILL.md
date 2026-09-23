---
name: django-security
description: Django and OMERO.web security rules for views, uploads, responses, permissions, and admin-only surfaces.
origin: ECC v2.0.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v2.0.0/skills/django-security/SKILL.md
---

# Django Security

Use this skill when touching Django views, uploads, JSON responses, templates, or OMERO.web permissions.

## Upstream baseline

`third_party/ecc-v2.0.0/skills/django-security/SKILL.md` is provenance. Load upstream detail only when this overlay lacks task-specific guidance.

## Repo overlay

- Read the mandatory security documents in `AGENTS.md` before editing sensitive boundaries.
- Validate request data and uploaded content at the helper boundary, not only at the template or view edge.
- Do not leak raw exceptions, internal paths, credentials, or topology in HTTP responses.
- Preserve OMERO permission checks and plugin-specific authorization boundaries.
- Re-run targeted regression tests after hardening changes.
