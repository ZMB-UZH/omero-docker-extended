---
name: python-testing
description: Python testing guidance for split pytest lanes, contract tests, shell checks, and syntax-only fallbacks in this repo.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/python-testing/SKILL.md
---

# Python Testing

Use this skill when adding or selecting tests for Python and shell-adjacent changes.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/python-testing/SKILL.md` for the generic Python testing guidance.

## Repo overlay

- Follow the split-pytest rule from `AGENTS.md` and `.agents/skills/plugin-regression-triager/`.
- Prefer narrow regression tests that prove the exact contract being changed.
- Use `python3 -m py_compile` when full dependency-complete testing is blocked.
- Use `bash -n` for shell/bootstrap changes.
- Never weaken tests just to get green output.
