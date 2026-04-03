---
applyTo: "**/*.py"
---

# Python and Django instructions

- Follow the dependency boundaries and testing rules in `AGENTS.md`.
- Check `.agents/skills/python-patterns/`, `.agents/skills/python-testing/`, `.agents/skills/django-patterns/`, `.agents/skills/django-security/`, and `.agents/skills/django-verification/` when relevant.
- Use `omero_plugin_common` helpers before inventing new shared utilities.
- Keep env access in `config.py` or the shared env helpers. Do not hard-code deployment-specific values.
- Use split `pytest` runs and `-p no:cacheprovider -W error`.
- Treat scanner regressions as defects; consult the security read order before changing sensitive code.
