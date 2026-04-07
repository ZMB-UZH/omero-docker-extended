---
name: django-patterns
description: "Django patterns for OMERO.web plugins: app boundaries, views, services, templates, and shared helper usage."
origin: ECC v1.10.0 adapted for OMERO Docker Extended
upstream: third_party/ecc-v1.10.0/skills/django-patterns/SKILL.md
---

# Django Patterns

Use this skill when changing OMERO.web plugin views, services, templates, routing, or Django app wiring.

## Upstream baseline

Start from `third_party/ecc-v1.10.0/skills/django-patterns/SKILL.md` for the generic Django architecture guidance.

## Repo overlay

- Each `omeroweb_*` plugin stays isolated and depends only on `omero_plugin_common`.
- Follow the existing layout: `apps.py`, `config.py`, `urls.py`, `views/`, `services/`, `strings/`, `templates/`, `static/`, `tests/`.
- Use request and env helpers from `omero_plugin_common` before adding plugin-local duplicates.
- Keep user-facing strings in `strings/errors.py` or `strings/messages.py` as functions, not inline literals.
- Update the matching plugin docs when routes or behavior change.
