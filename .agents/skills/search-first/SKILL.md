---
name: search-first
description: Research-before-coding workflow for OMERO Docker Extended. Check the repo, tests, official upstream docs, and release notes before writing new code.
origin: ECC v1.9.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.9.0/skills/search-first/SKILL.md
---

# Search First

Use this skill before introducing new code, dependencies, wrappers, or automation.

## When to activate

- Adding a new integration, helper, or dependency
- Changing Docker, OMERO, Django, Python, PostgreSQL, Grafana, Loki, or GitHub Actions behavior
- Fixing a bug where an upstream or in-repo solution may already exist
- Writing a refactor plan for a large file or subsystem

## Mandatory search order

1. Search this repository first with `rg`.
2. Read the nearest tests, docs, and example env files.
3. Check official upstream docs and release notes.
4. Check existing upstream implementations or maintained references.
5. Only then decide whether to adopt, extend, or build custom logic.

## Repo-first checklist

- Search the relevant package, service, or plugin directory first.
- Search `tests/` and package-local `*/tests/` before assuming coverage is missing.
- Search `docs/`, `README.md`, `ARCHITECTURE.md`, and `CLAUDE.md` for existing operating rules.
- Treat `env/*_example.env` and `installation_paths_example.env` as canonical contracts.

## Primary sources for this repo

- OMERO product docs and the OMERO config glossary
- Official OMERO server/web Docker repos and release notes
- Django and Python standard-library docs
- Docker and Docker Compose docs
- PostgreSQL docs
- Grafana, Loki, Alloy, and Prometheus docs
- Official GitHub Actions releases/tags when touching workflows

## Decision rules

- Adopt: exact match, maintained upstream, fits repo contracts
- Extend: strong base exists but needs a thin repo-specific wrapper
- Build custom: no maintained fit exists or the repo needs a stricter contract

## Repo-specific constraints

- Do not use background agents or subagents for research in this repo.
- Do not leak PATs, tokens, passwords, or internal URLs into web queries or docs tools.
- For security-sensitive facts, use primary sources only.
- For version-sensitive facts, cite the exact version, release tag, or document page used.

## Anti-patterns

- Writing a new helper before searching `omero_plugin_common/`
- Adding new env variables without checking existing templates and config loaders
- Rewriting Docker/bootstrap logic without checking startup scripts and regression tests
- Treating stale memory as authoritative when the official docs or releases can be checked
