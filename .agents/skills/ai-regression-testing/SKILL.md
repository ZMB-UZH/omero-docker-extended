---
name: ai-regression-testing
description: Catch AI-style regressions with narrow contract tests, split pytest lanes, and sandbox-path checks before and after fixes.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/ai-regression-testing/SKILL.md
---

# AI Regression Testing

Use this skill when an AI agent has changed helpers, views, startup scripts, workflows, or data-flow boundaries that are easy to "fix" incompletely.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/ai-regression-testing/SKILL.md` for the general anti-blind-spot workflow.

## Repo overlay

- Prefer narrow regression tests that lock the exact contract that broke.
- Check both the main path and any paired boundary path used by this repo, especially host-vs-container, request-vs-service-account, shared-helper-vs-caller, and raw-vs-preview variants.
- For command helpers, test oversized single-line stdout/stderr, timeout paths, and checked-error paths.
- For env/config parsing, test hostile inputs and prove config is treated as data, not executable shell.
- Run split `pytest` suites separately; use `.agents/skills/plugin-regression-triager/` to choose the narrowest correct lane.
- For shell/bootstrap fixes, add or update contract tests under `tests/` when possible and use `bash -n` as a quick syntax gate.
- For security regressions, read the mandatory security documents first and do not rely on scanner text alone.
