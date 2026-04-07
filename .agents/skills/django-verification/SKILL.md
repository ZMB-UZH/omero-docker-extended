---
name: django-verification
description: Verify Django and OMERO.web changes with the repo's split pytest model, docs gates, and targeted runtime checks.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/django-verification/SKILL.md
---

# Django Verification

Use this skill after Django or OMERO.web changes.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/django-verification/SKILL.md` for the generic Django verification flow.

## Repo overlay

- Use `.agents/skills/verification-loop/` as the top-level verification order.
- Choose the relevant plugin suite instead of running every package blindly.
- If host Python lacks Django, switch to the repo's documented fallback procedure rather than retrying the same failing command.
- Update plugin docs and route docs if user-facing behavior changed.
