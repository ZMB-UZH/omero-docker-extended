# Frontend Guidance

This repository extends OMERO.web via Django plugin packages. Each plugin provides its own templates, static assets, and URL routing.

## Plugin UI architecture

Each plugin has a self-contained frontend under its own namespace:

- Templates: `<plugin_package>/templates/<plugin_package>/`
- Static assets (CSS/JS): `<plugin_package>/static/<plugin_package>/`
- URL routing: `<plugin_package>/urls.py`

Plugins register in OMERO.web via `CONFIG_omero_web_apps` in `env/omeroweb.env` and appear as top-level links via `CONFIG_omero_web_ui_top__links`.

## Current plugin UIs

- **OMP Plugin** (`/omeroweb_omp_plugin/`): project/dataset selector, variable configuration, parsing preview, job progress, settings management. Template: `index.html` with extensive JavaScript for AJAX interactions.
- **Import Plugin** (`/omeroweb_import/`): upload session management, file transfer, import progress, SEM-EDX method settings. Template: `index.html` with `upload.js` for file handling.
- **Tools Plugin** (`/omeroweb_tools/`): Admin-Tools-style landing page plus the `Enhanced search` workspace for regular users. Templates: `index.html`, `enhanced_search.html`. Shares structural CSS with Admin Tools but keeps plugin-scoped styles and user-only behavior.
- **Admin Tools** (`/omeroweb_admin_tools/`): multi-page interface with tabs for logs, resource monitoring, storage, and server diagnostics. Templates: `index.html`, `logs.html`, `resource_monitoring.html`, `storage.html`, `server_database_testing.html`. Embeds Grafana iframes via proxy endpoints.
- **OMERO.web Zarr** (`/zarr/`): authenticated OME-Zarr preview and raw/preview endpoint integration. Templates: `image_preview.html`, `right_plugin.preview.js.html`, plus an OMERO.web toolbar include override.
- **Imaris Connector**: API-only endpoint (`/imaris-export/`), no dedicated UI template.

## Development conventions

- Keep templates and URL wiring plugin-scoped. Do not modify OMERO.web core templates.
- CSS goes in plugin-specific static directories, not in shared locations.
- Views return `JsonResponse` for AJAX endpoints and `render()` for page loads.
- Use `@login_required` decorator (from `omeroweb.decorators`) for all views that need authentication.
- The admin tools plugin uses root-only guards for administrator surfaces; the Tools plugin uses `require_non_root_user` on mutating endpoints and blocks root users from executing the regular-user workflow.
- When changing UI workflows, include a validation plan in `docs/exec-plans/active/`.
- Document user-facing behavior changes in the relevant `docs/plugins/` guide.
- For host-side Vite/Vitest preview tooling, use
  `tools/frontend_preview_tooling.py`. It installs the wrapper under
  `${XDG_CACHE_HOME:-$HOME/.cache}/omero-agent-frontend-preview` unless
  `OMERO_AGENT_FRONTEND_TOOLING_DIR` is set, and installs pinned Node.js under
  `${XDG_DATA_HOME:-$HOME/.local/share}/omero-agent-node/...` unless
  `OMERO_AGENT_NODE_DIR` is set.
