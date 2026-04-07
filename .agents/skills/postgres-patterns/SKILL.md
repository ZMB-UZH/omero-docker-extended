---
name: postgres-patterns
description: PostgreSQL guidance for the main OMERO database, plugin database, migrations, indexes, and maintenance contracts.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/postgres-patterns/SKILL.md
---

# PostgreSQL Patterns

Use this skill when changing SQL, schema behavior, plugin persistence, or maintenance logic.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/postgres-patterns/SKILL.md` for the generic PostgreSQL patterns.

## Repo overlay

- This repo has two PostgreSQL services with distinct responsibilities; do not blur OMERO core and plugin storage concerns.
- Keep SQL parameterized and avoid string-built queries.
- Review maintenance scripts and docs when changing index or table behavior that affects VACUUM, REINDEX, or backup assumptions.
- Use narrow regression tests or contract tests when changing persistence helpers.
