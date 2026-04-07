---
name: python-patterns
description: Python patterns for this repo's helpers, plugins, services, startup tooling, and environment-driven contracts.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/python-patterns/SKILL.md
---

# Python Patterns

Use this skill when writing or refactoring Python in plugin code, shared helpers, tests, or tooling.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/python-patterns/SKILL.md` for the generic Python guidance.

## Repo overlay

- Prefer explicit helper boundaries in `omero_plugin_common` over duplicated logic.
- Keep config loading typed and environment-driven.
- Avoid installation-specific absolute paths in committed code and tests unless the runtime contract explicitly requires them.
- Keep string constants and user-facing messages in the established strings modules where applicable.
- Use Ruff as the formatting and lint baseline.
