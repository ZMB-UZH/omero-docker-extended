# Frontend Guidance

This repository extends OMERO.web via Django plugin packages. Each plugin provides its own templates, static assets, and URL routing.

## Plugin UI architecture

Each plugin has a self-contained frontend under its own namespace:

- Templates: `omeroweb_<name>/templates/omeroweb_<name>/`
- Static assets (CSS/JS): `omeroweb_<name>/static/omeroweb_<name>/`
- URL routing: `omeroweb_<name>/urls.py`

Plugins register in OMERO.web via `CONFIG_omero_web_apps` in `env/omeroweb.env` and appear as top-level links via `CONFIG_omero_web_ui_top__links`.

## Current plugin UIs

- **OMP Plugin** (`/omeroweb_omp_plugin/`): project/dataset selector, variable configuration, parsing preview, job progress, settings management. Template: `index.html` with extensive JavaScript for AJAX interactions.
- **Upload Plugin** (`/omeroweb_upload/`): upload session management, file transfer, import progress, SEM-EDX method settings. Template: `index.html` with `upload.js` for file handling.
- **Admin Tools** (`/omeroweb_admin_tools/`): multi-page interface with tabs for logs, resource monitoring, storage, and server diagnostics. Templates: `index.html`, `logs.html`, `resource_monitoring.html`, `storage.html`, `server_database_testing.html`. Embeds Grafana iframes via proxy endpoints.
- **Imaris Connector**: API-only endpoint (`/imaris-export/`), no dedicated UI template.

## Development conventions

- Keep templates and URL wiring plugin-scoped. Do not modify OMERO.web core templates.
- CSS goes in plugin-specific static directories, not in shared locations.
- Views return `JsonResponse` for AJAX endpoints and `render()` for page loads.
- Use `@login_required` decorator (from `omeroweb.decorators`) for all views that need authentication.
- The admin tools plugin uses `_require_root_user()` to restrict access to OMERO root accounts.
- When changing UI workflows, include a validation plan in `docs/exec-plans/active/`.
- Document user-facing behavior changes in the relevant `docs/plugins/` guide.
