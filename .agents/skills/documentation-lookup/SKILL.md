---
name: documentation-lookup
description: Use current official documentation and release notes for OMERO, Django, Docker, Python, PostgreSQL, monitoring tools, and AI harnesses instead of memory.
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/documentation-lookup/SKILL.md
---

# Documentation Lookup

Use this skill whenever the answer depends on current library, framework, image, workflow, or harness behavior.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/documentation-lookup/SKILL.md` for the generic documentation-first workflow.

## When to activate

- OMERO configuration, CLI, or plugin behavior
- Django, Python, Docker, Compose, PostgreSQL, Grafana, Loki, Alloy, or Prometheus questions
- GitHub Actions version pinning or workflow syntax
- Codex, Claude Code, or MCP configuration questions
- Any request using words like "latest", "current", "today", or "most recent"

## Source priority

1. This repository's own docs and tests
2. Official upstream docs
3. Official release notes, tags, or changelogs
4. Official source repositories
5. Broader web sources only when the above are insufficient

## Repo-specific source map

- Repository policy and navigation: `AGENTS.md`, `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, `docs/index.md`
- Security policy: `docs/reference/ai-agent-security-prevention-playbook.md`
- Live scanning state: `docs/operations/code-scanning.md`
- Closed finding history: `docs/reference/code-scanning-resolved-findings.md`
- Deployment and env contract: `docs/deployment/configuration.md`, `env/*_example.env`, `installation_paths_example.env`

## Official upstream sources to prefer

- OMERO docs and the OMERO config glossary
- OpenMicroscopy and OME GitHub repositories/releases
- Django docs
- Python docs
- Docker and Compose docs
- PostgreSQL docs
- Grafana, Loki, Alloy, and Prometheus docs
- GitHub Docs and GitHub Actions release pages
- Official OpenAI docs for Codex-specific behavior

## Rules

- Redact secrets before sending any query to docs or web tools.
- Include exact versions or dates when they matter.
- If a fact could have changed recently, verify it instead of guessing.
- If the docs do not fully answer the question, say what is still uncertain.
- Do not treat unofficial blog posts as authoritative when official docs exist.

## Good outcomes

- The final answer cites the exact upstream contract it relies on.
- The answer distinguishes repo-local behavior from upstream behavior.
- The answer does not invent defaults, version numbers, or CLI flags.
