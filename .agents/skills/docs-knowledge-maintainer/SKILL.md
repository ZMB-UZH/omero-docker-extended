---
name: docs-knowledge-maintainer
description: Keep repository documentation accurate when behavior, topology, env contracts, or troubleshooting procedures change.
origin: repo-local skill informed by ECC v1.10.0 workflow patterns
---

# Docs Knowledge Maintainer

Use this skill whenever code changes alter behavior, operating assumptions, or user-visible procedures.

## When to activate

- Service topology or Compose changes
- Dockerfile or startup-script changes
- New or changed environment variables
- Plugin route, workflow, or behavior changes
- Security or troubleshooting guidance updates

## Update order

1. Update the nearest deep doc first.
2. Update `docs/index.md` if a new document was introduced.
3. Update root docs only when the top-level contract changed.
4. Keep `AGENTS.md` as routing, not as an encyclopedia.

## Common routing

- Topology or container counts: `README.md`, `ARCHITECTURE.md`, `docs/references/docker-compose-llms.txt`
- Env contract: `docs/deployment/configuration.md`, `env/*_example.env`
- Plugin behavior: `docs/plugins/*.md`
- Runtime/debugging procedure: `AGENTS.md`, `CLAUDE.md`, `docs/troubleshooting/*.md`
- Security behavior: `docs/SECURITY.md`, `docs/operations/code-scanning.md`, `docs/reference/ai-agent-security-prevention-playbook.md`

## Drift to watch for

- stale service counts
- stale plugin names
- single-env `docker compose` examples missing `env/omero_secrets.env`
- root docs contradicting deep docs
- undocumented new runtime assumptions

## Required verification

```bash
python3 tools/lint_docs_structure.py
python3 -m unittest -v tests/test_lint_docs_structure.py
python3 -m pytest tests/test_repository_documentation_regressions.py -v -p no:cacheprovider -W error
```

## Good outcome

Operators, contributors, and AI agents can all find the changed contract from `docs/index.md` and the nearest deep doc without conflicting instructions.
