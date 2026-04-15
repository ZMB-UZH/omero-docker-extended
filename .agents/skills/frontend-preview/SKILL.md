---
name: frontend-preview
description: Preview HTML/CSS/JS changes in Django plugin templates with the pinned host-side Vite/Vitest toolchain, then validate live in OMERO.web.
origin: repo-local skill for AI agent frontend preview and DOM/browser validation
---

# Frontend Preview (Vite + Vitest)

Use this skill when you need to **visually validate** HTML, CSS, or JavaScript changes in plugin templates before committing, and when you need a **repeatable DOM or browser test lane** for frontend regressions.

The repo now exposes a pinned host-side wrapper:

```bash
python3 tools/frontend_preview_tooling.py bootstrap
python3 tools/frontend_preview_tooling.py vite -- ...
python3 tools/frontend_preview_tooling.py vitest -- ...
python3 tools/frontend_preview_tooling.py playwright -- ...
```

Do not install ad-hoc frontend tooling inside the repository. The wrapper installs the pinned toolchain into a cache-backed host directory.

## Related docs

- `docs/reference/ai-agent-runtime-playbook.md` for Docker rebuild guidance
- `docs/reference/ai-agent-skills.md` for the shared skill catalog

## When to activate

- Editing `styles.css`, `upload.js`, or `index.html` in any plugin's `static/` or `templates/` directory
- Adjusting layout, spacing, colors, interactions, or responsive behavior
- Adding or debugging form controls, datepickers, modals, or saved-state UI
- Adding narrow DOM/browser regressions before a live browser check

## When NOT to use

- Backend-only changes (Python views, services, tests)
- Changes that require a real OMERO session for the primary validation
- Final validation on their own: always rebuild or redeploy and test the live page afterward

## Tooling contract

- Host Node.js must satisfy the pinned toolchain minimum. The wrapper checks that automatically.
- The wrapper reads `tools/frontend_preview_tooling_manifest.json` and installs the exact pinned versions into a cache-backed host directory.
- The default install location is `${XDG_CACHE_HOME:-$HOME/.cache}/omero-agent-frontend-preview`.
- Override that location with `OMERO_AGENT_FRONTEND_TOOLING_DIR=/path/to/cache`.
- The wrapper does **not** install dependencies into the repository.

Bootstrap and inspect the installed versions:

```bash
python3 tools/frontend_preview_tooling.py bootstrap --json
```

## Repo-provided config assets

- `.agents/skills/frontend-preview/agents/vite_django_preview.config.mjs`
- `.agents/skills/frontend-preview/agents/vitest_django_preview.config.mjs`

Both configs assume the wrapper is running from its cache-backed tool directory.

## Required environment variables

Set these before running Vite or Vitest:

```bash
export REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
export PLUGIN_ROOT="$REPO_ROOT/omeroweb_tools"
export OMERO_STATIC_ROOT="${OMERO_STATIC_ROOT:-$REPO_ROOT/omero-web/omero/static}"
export PREVIEW_TEMPLATE="enhanced_search.html"
```

`PLUGIN_ROOT` may point at any plugin directory such as `omeroweb_import`, `omeroweb_omp_plugin`, or `omeroweb_admin_tools`.

## Preview with Vite

Start the temporary preview server with the repo-provided config:

```bash
python3 tools/frontend_preview_tooling.py vite -- \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vite_django_preview.config.mjs"
```

The preview server listens on `http://127.0.0.1:5173` by default.

The preview uses the `django-template-strip` middleware to strip Django template tags and serves plugin assets through the preview middleware. Use it for layout, spacing, and quick interaction checks before you touch Docker.

## Run DOM tests with Vitest

Create or point to narrow test files and run them through the repo-provided Vitest config:

```bash
python3 tools/frontend_preview_tooling.py vitest -- \
  --run \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vitest_django_preview.config.mjs"
```

Optional environment knobs:

- `VITEST_INCLUDE=/absolute/or/glob/**/*.vitest.mjs` to point at a narrow temporary test file
- `VITEST_BROWSER=1` to enable Vitest Browser Mode
- `VITEST_BROWSER_NAME=chromium` to pick the Playwright browser instance
- `VITEST_BROWSER_HEADLESS=0` to run browser mode visibly while debugging

## Browser Mode

The Vitest config supports Browser Mode through `@vitest/browser-playwright`.

Example:

```bash
export VITEST_BROWSER=1
export VITEST_INCLUDE="/tmp/enhanced-search.browser.vitest.mjs"
python3 tools/frontend_preview_tooling.py vitest -- \
  --run \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vitest_django_preview.config.mjs"
```

If Playwright browsers are missing on the host, install them explicitly before relying on browser mode:

```bash
python3 tools/frontend_preview_tooling.py playwright -- install chromium
```

If you need a real authenticated OMERO session, fall back to the live browser workflow after the Docker or runtime update.

## Recommended workflow

1. Bootstrap the pinned host-side tooling once per host or after version changes.
2. Use Vite preview for fast layout and spacing checks.
3. Add narrow Vitest DOM or Browser Mode checks for the risky interaction logic you are changing.
4. Rebuild or redeploy the affected runtime.
5. Verify the live OMERO.web page in a real browser session.

## Limitations

- Django template logic is still stripped in preview mode.
- CSRF-protected POST endpoints and OMERO-backed data do not work in preview mode by themselves.
- Browser Mode still validates the preview environment, not the fully authenticated live OMERO page.
- Final acceptance still requires a live browser check against the served page.
