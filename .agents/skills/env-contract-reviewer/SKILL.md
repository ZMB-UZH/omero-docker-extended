---
name: env-contract-reviewer
description: Review environment-driven configuration changes so they stay template-backed, typed, documented, and free of hard-coded runtime values.
origin: repo-local skill informed by ECC v1.10.0 workflow patterns
---

# Env Contract Reviewer

Use this skill whenever a change touches env files, config loaders, startup scripts, Compose wiring, or installation paths.

## Rules

- All configuration is environment-driven.
- Never hard-code paths, credentials, ports, or endpoints in committed code.
- Treat `env/*_example.env` and `installation_paths_example.env` as the canonical tracked contract.
- Never create, edit, overwrite, or delete `env/omero_secrets.env`.
- Prefer `omero_plugin_common.env_utils` for typed Python config loading.
- Treat shell env parsing as a security boundary: config must be parsed as data, never executed as shell code.

## Required change pattern

1. Add the variable to the correct tracked example env file.
2. Load it in the correct `config.py` or startup script using the existing helper pattern.
3. Reference the correct env file constant in validation or error messages.
4. Update `docs/deployment/configuration.md` when the contract changes.
5. Keep `docker-compose.yml` minimal; do not duplicate env defaults inline.

## Drift to catch

- compose `args:` or fallback values duplicating tracked env templates
- config values added only in code, not in templates
- installation-specific absolute paths in tests
- shell loaders that use `eval`, `source`, or command substitution on tracked env content
- mismatched variable naming relative to existing OMERO property conventions

## Fast verification

```bash
python3 tools/lint_docs_structure.py
ruff check <touched-python-files>
ruff format --check <touched-python-files>
python3 -m py_compile <touched-python-files>
bash -n <touched-shell-scripts>
```
