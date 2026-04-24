---
name: frontend-preview
description: Preview HTML/CSS/JS changes in Django plugin templates with the pinned host-side Vite/Vitest toolchain, then validate live in OMERO.web.
origin: repo-local skill for AI agent frontend preview and DOM/browser validation
---

# Frontend Preview

Use this skill to visually validate plugin HTML/CSS/JS changes and add repeatable DOM or browser checks before live OMERO.web validation. Use only the pinned wrapper:

```bash
python3 tools/frontend_preview_tooling.py bootstrap
python3 tools/frontend_preview_tooling.py vite -- ...
python3 tools/frontend_preview_tooling.py vitest -- ...
python3 tools/frontend_preview_tooling.py playwright -- ...
```

Do not install ad-hoc frontend tooling inside the repository.

## Scope

- Use for plugin `static/` or `templates/` edits, layout/responsive checks, controls, modals, saved-state UI, and narrow frontend regressions.
- Do not use for backend-only changes or as final acceptance. Rebuild or redeploy and test the live OMERO.web page afterward.

## Tooling contract

- Host Node.js must satisfy `tools/frontend_preview_tooling_manifest.json`; the wrapper checks this before installing.
- If bootstrap reports an old or missing Node.js, install or activate a compatible host Node.js first, then rerun once. Do not keep retrying the same failing wrapper command.
- The wrapper installs exact pinned versions into `${XDG_CACHE_HOME:-$HOME/.cache}/omero-agent-frontend-preview`, or `OMERO_AGENT_FRONTEND_TOOLING_DIR` when set.
- The wrapper does **not** install dependencies into the repository.
- Config assets live at `.agents/skills/frontend-preview/agents/vite_django_preview.config.mjs` and `.agents/skills/frontend-preview/agents/vitest_django_preview.config.mjs`; both expect the wrapper's cache-backed tool directory.

## Target setup

Bootstrap once, then set and verify the target before Vite or Vitest:

```bash
python3 tools/frontend_preview_tooling.py bootstrap --json
export REPO_ROOT="$(git rev-parse --show-toplevel)"
export PLUGIN_ROOT="$REPO_ROOT/omeroweb_tools"
export PREVIEW_TEMPLATE="enhanced_search.html"
test -d "$PLUGIN_ROOT"
test -f "$PLUGIN_ROOT/templates/$(basename "$PLUGIN_ROOT")/$PREVIEW_TEMPLATE"
```

`PLUGIN_ROOT` may point at any plugin directory such as `omeroweb_import`, `omeroweb_omp_plugin`, `omeroweb_admin_tools`, or `omero_web_zarr`. Set `OMERO_STATIC_ROOT` only to an existing OMERO static directory when the target template references OMERO `3rdparty/` assets; do not guess a repo path.

## Commands

```bash
python3 tools/frontend_preview_tooling.py vite -- \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vite_django_preview.config.mjs"
```

The preview uses the `django-template-strip` middleware to strip Django template tags and serve plugin assets.

```bash
python3 tools/frontend_preview_tooling.py vitest -- \
  --run \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vitest_django_preview.config.mjs"
```

Useful knobs:

- `VITEST_INCLUDE=/absolute/or/glob/**/*.vitest.mjs` to point at a narrow temporary test file
- `VITEST_BROWSER=1` to enable Vitest Browser Mode
- `VITEST_BROWSER_NAME=chromium` to pick the Playwright browser instance
- `VITEST_BROWSER_HEADLESS=0` to run browser mode visibly while debugging

```bash
export VITEST_BROWSER=1
export VITEST_INCLUDE="/tmp/enhanced-search.browser.vitest.mjs"
python3 tools/frontend_preview_tooling.py vitest -- \
  --run \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vitest_django_preview.config.mjs"
```

```bash
python3 tools/frontend_preview_tooling.py playwright -- install chromium
```

Install Playwright browsers only when Browser Mode needs them.

## Recommended workflow

1. Bootstrap the pinned host-side tooling once per host or after version changes.
2. Select and validate `PLUGIN_ROOT` plus `PREVIEW_TEMPLATE`.
3. Use Vite preview for fast layout and spacing checks.
4. Add narrow Vitest DOM or Browser Mode checks for risky interaction logic.
5. Rebuild or redeploy the affected runtime and verify the live OMERO.web page in a real browser session.

## Limitations

- Django template logic is still stripped in preview mode.
- CSRF-protected POST endpoints and OMERO-backed data do not work in preview mode by themselves.
- Browser Mode validates the preview environment, not a fully authenticated OMERO session.
- Final acceptance still requires a live browser check against the served page.

## Read next

- `docs/reference/ai-agent-runtime-playbook.md` for Docker rebuild and live validation guidance
- `docs/reference/ai-agent-skills.md` for the shared skill catalog
