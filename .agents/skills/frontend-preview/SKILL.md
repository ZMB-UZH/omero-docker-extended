---
name: frontend-preview
description: Spin up a temporary Vite dev server to preview HTML/CSS/JS changes in Django plugin templates without rebuilding Docker. AI-agent-only skill for visual validation.
origin: repo-local skill for AI agent visual validation
---

# Frontend Preview (Vite)

Use this skill when you need to **visually validate** HTML, CSS, or JavaScript changes in plugin templates before committing. This avoids blind edits and eliminates the Docker rebuild cycle for frontend-only iterations.

## Related docs

- `docs/plugins/import-plugin.md` for the import plugin UI structure
- `docs/reference/ai-agent-runtime-playbook.md` for Docker rebuild guidance

## When to activate

- Editing `styles.css`, `upload.js`, or `index.html` in any plugin's `static/` or `templates/` directory
- Adjusting layout, spacing, colors, or responsive behavior
- Adding new UI panels, modals, or form controls (e.g. the NGFF converter settings panel)
- Debugging CSS specificity or visibility issues

## When NOT to use

- Backend-only changes (Python views, services, tests)
- Changes that require a running OMERO server or Django session (authentication, CSRF, API calls)
- Final validation (always rebuild Docker and test live for that)

## Prerequisites

Node.js 18+ must be available on the host. If not installed:

```bash
# Check
node --version 2>/dev/null || echo "Node.js not installed"

# Install via nvm (does not require root)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.bashrc
nvm install 20
```

Do not assume `corepack` is available just because `node`, `npm`, and `npx`
are. Use plain `npm` commands unless you have already verified `corepack
--version` on the host.

## Setup (one-time per session)

Create a minimal Vite project in a temporary directory. Do NOT install Vite inside the repository.
Use a Vite version that matches the host's Node runtime:

```bash
PREVIEW_DIR=$(mktemp -d /tmp/vite-preview-XXXXXX)
cd "$PREVIEW_DIR"
npm init -y
VITE_VERSION=$(node - <<'NODE'
const [major, minor] = process.versions.node.split('.').map(Number);
if (major > 22 || (major === 22 && minor >= 12) || (major === 20 && minor >= 19)) {
  process.stdout.write('8.0.7');
} else {
  process.stdout.write('5.4.19');
}
NODE
)
npm install "vite@${VITE_VERSION}"
```

## Usage

Start the preview server pointing at the plugin you're editing.
Do **not** point Vite directly at raw Django templates; instead use the repo-local middleware config that preprocesses Django tags before Vite sees the HTML. It replaces the old inline `django-template-strip` transform with a reusable middleware path:

```bash
cd "$PREVIEW_DIR"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
PLUGIN_ROOT="${PLUGIN_ROOT:-$REPO_ROOT/omeroweb_import}"
PLUGIN_NAME="$(basename "$PLUGIN_ROOT")"
PREVIEW_TEMPLATE="${PREVIEW_TEMPLATE:-index.html}"
if [[ "$PREVIEW_TEMPLATE" == "auto" ]]; then
  PREVIEW_TEMPLATE="$(find "$PLUGIN_ROOT/templates/$PLUGIN_NAME" -maxdepth 1 -name '*.html' | sort | head -n 1 | xargs basename)"
fi
npx vite \
  --config "$REPO_ROOT/.agents/skills/frontend-preview/agents/vite_django_preview.config.mjs" \
  2>&1 &
VITE_PID=$!
echo "Vite preview running on http://localhost:5173 (PID: $VITE_PID)"
```

The preview middleware reads the live template file on each request, resolves `{% static %}` assets from the repo, and strips Django control tags before Vite parses the page. CSS/JS edits in the source plugin update immediately. For template edits, reload the page after saving.

If the page depends on built shared assets under `3rdparty/`, export `OMERO_STATIC_ROOT` explicitly before starting Vite so the preview can serve them from the live installation's static tree:

```bash
export OMERO_STATIC_ROOT="/path/to/omero_web_var/static"
```

For plugins with multiple HTML files, set `PREVIEW_TEMPLATE` explicitly, for example:

```bash
PREVIEW_TEMPLATE=enhanced_search.html
```

## Available plugins

| Plugin | PLUGIN_ROOT |
| --- | --- |
| Import | `$REPO_ROOT/omeroweb_import` |
| OMP | `$REPO_ROOT/omeroweb_omp_plugin` |
| Admin Tools | `$REPO_ROOT/omeroweb_admin_tools` |
| Imaris Connector | `$REPO_ROOT/omeroweb_imaris_connector` |
| Web Zarr | `$REPO_ROOT/omero_web_zarr` |

## Limitations

- Django template logic (`{% if %}`, `{% for %}`, login checks) is stripped. The preview is for layout and interaction wiring, not authoritative data rendering.
- CSRF-protected POST endpoints will not work. Use this for layout and styling only.
- Server-rendered data (project lists, user settings, job status) is replaced with empty placeholders unless you inject sample state manually in the browser.
- The preview runs outside Docker, so container-only paths and OMERO connections are unavailable.
- Ready-made widgets that bind directly to focused inputs, especially datepickers,
  can look fine in preview while still breaking manual typing in the live app.
  When typed input is part of the requirement, follow preview with a real browser
  check against the rebuilt container and test the actual keyboard path, not only
  click selection.
- Compound controls that combine a text field with an adjacent trigger button can
  also fail only in the live layout if CSS min-width or overflow causes the
  input hitbox to overlap the trigger. In the live browser, always test both
  that keyboard typing persists and that the trigger button is actually
  clickable without forced clicks.

## Cleanup

```bash
kill $VITE_PID 2>/dev/null
rm -rf "$PREVIEW_DIR"
```

## Relationship to Docker rebuild

This skill is for **rapid iteration** on visual changes. Once satisfied with the preview, always:

1. Rebuild Docker: `docker compose build omeroweb`
2. Recreate container: `docker compose up -d omeroweb`
3. Verify in the live environment with a real browser session
