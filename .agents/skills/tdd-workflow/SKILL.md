---
name: tdd-workflow
description: TDD guidance for repo changes using narrow regression tests, split pytest lanes, and docs updates as part of done-ness.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/tdd-workflow/SKILL.md
---

# TDD Workflow

Use this skill when adding features, fixing bugs, or refactoring behavior that should land with tests first or tests alongside the fix.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/tdd-workflow/SKILL.md` for the generic red-green-refactor workflow.

## Repo overlay

- Prefer narrow tests that lock the user-visible or helper-boundary contract first.
- Choose the relevant split pytest lane instead of broad test runs.
- For docs- or config-surface regressions, update the relevant docs and docs validation in the same change.
- Do not treat a change as done until verification is explicit and the correct docs are updated.
