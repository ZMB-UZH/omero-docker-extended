---
name: search-first
description: Research-before-coding workflow for OMERO Docker Extended. Check the repo, tests, official upstream docs, and release notes before writing new code.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/search-first/SKILL.md
---

# Search First

Use this skill before introducing new code, dependencies, wrappers, or automation.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/search-first/SKILL.md` for the generic research-before-coding workflow.

## When to activate

- Adding a new integration, helper, or dependency
- Changing Docker, OMERO, Django, Python, PostgreSQL, Grafana, Loki, or GitHub Actions behavior
- Fixing a bug where an upstream or in-repo solution may already exist
- Writing a refactor plan for a large file or subsystem

## Search order

1. Search this repository first with `rg`.
2. Route through `docs/reference/ai-agent-context-routing.md` and read the nearest tests, docs, and example env files.
3. Check official upstream docs and release notes.
4. Check upstream implementations or maintained references.
5. Only then decide whether to adopt, extend, or build custom logic.

## Repo rules

- Search the relevant package, service, or plugin directory first.
- Search `tests/` and package-local `*/tests/` before assuming coverage is missing.
- Search `docs/`, `README.md`, `ARCHITECTURE.md`, and `CLAUDE.md` for existing operating rules.
- Treat `env/*_example.env` and `installation_paths_example.env` as canonical contracts.
- Adopt when the existing pattern is already correct, extend when a thin repo wrapper is enough, and build custom only when the repo needs a stricter contract.
- Do not use background agents or subagents for research in this repo.
- Do not leak PATs, tokens, passwords, or internal URLs into web queries or docs tools.
- For security-sensitive facts, use primary sources only.
- For version-sensitive facts, cite the exact version, release tag, or document page used.
