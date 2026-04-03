# Selected ECC v1.9.0 vendor snapshot

This directory vendors the exact upstream ECC materials used as the source for the repo's ECC-derived AI-agent overlays.

## Source

- Repository: `affaan-m/everything-claude-code`
- Release: `v1.9.0`
- Commit: `29277ac273f294fd4804c35e43af9c8a5fc5ba9d`
- License: MIT (`LICENSE`)

## Scope

This is not a full ECC install.

It contains only the selected upstream skill files that are relevant to this repository:

- `ai-regression-testing`
- `context-budget`
- `deployment-patterns`
- `django-patterns`
- `django-security`
- `django-verification`
- `docker-patterns`
- `documentation-lookup`
- `postgres-patterns`
- `python-patterns`
- `python-testing`
- `search-first`
- `security-review`
- `tdd-workflow`
- `verification-loop`

The active repo-specific overlays live under `.agents/skills/`.
