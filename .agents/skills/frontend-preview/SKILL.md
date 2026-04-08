---
name: frontend-preview
description: Spin up a temporary Vite dev server to preview HTML/CSS/JS changes in Django plugin templates without rebuilding Docker. AI-agent-only skill for visual validation.
origin: repo-native
---

# Frontend Preview (Vite)

Use this skill when you need to **visually validate** HTML, CSS, or JavaScript changes in plugin templates before committing. This avoids blind edits and eliminates the Docker rebuild cycle for frontend-only iterations.

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

## Setup (one-time per session)

Create a minimal Vite project in a temporary directory. Do NOT install Vite inside the repository.

```bash
PREVIEW_DIR=$(mktemp -d /tmp/vite-preview-XXXXXX)
cd "$PREVIEW_DIR"
npm init -y
npm install vite@8.0.7
```

Create a `vite.config.js` that serves the plugin's static and template files:

```bash
cat > "$PREVIEW_DIR/vite.config.js" << 'VITEEOF'
import { defineConfig } from 'vite';
import { resolve } from 'path';

// Set PLUGIN_ROOT to the plugin directory you're previewing.
// Example: /opt/omero/omeroweb_import
const PLUGIN_ROOT = process.env.PLUGIN_ROOT || '/opt/omero/omeroweb_import';
const PLUGIN_NAME = PLUGIN_ROOT.split('/').pop();

export default defineConfig({
  root: resolve(PLUGIN_ROOT, 'templates', PLUGIN_NAME),
  publicDir: resolve(PLUGIN_ROOT, 'static', PLUGIN_NAME),
  server: {
    port: 5173,
    open: false,
    watch: {
      // Watch both templates and static directories
      ignored: ['!**/*.html', '!**/*.css', '!**/*.js'],
    },
  },
  // Rewrite Django template tags to prevent Vite parse errors
  plugins: [
    {
      name: 'django-template-strip',
      transformIndexHtml(html) {
        return html
          // Replace {% static '...' %} with relative paths
          .replace(/\{%\s*static\s+'([^']+)'\s*%\}/g, '/$1')
          // Replace {% url '...' %} with # placeholders
          .replace(/\{%\s*url\s+'[^']+'\s*%\}/g, '#')
          // Replace {{ ... }} template variables with safe placeholders
          .replace(/\{\{[^}]+\|json_script:"[^"]+"\s*\}\}/g,
            '<script id="placeholder" type="application/json">[]</script>')
          .replace(/\{\{\s*[^}]+\|yesno:"true,false"\s*\}\}/g, 'true')
          .replace(/\{\{\s*[^}]+\|default:"[^"]*"\|safe\s*\}\}/g, '{}')
          .replace(/\{\{\s*[^}]+\|default_if_none:''[^}]*\}\}/g, '')
          .replace(/\{\{\s*[^}]+\}\}/g, '')
          // Remove {% load ... %}, {% csrf_token %}, {% if %}, {% endif %}, etc.
          .replace(/\{%[^%]*%\}/g, '');
      },
    },
  ],
});
VITEEOF
```

## Usage

Start the preview server pointing at the plugin you're editing:

```bash
cd "$PREVIEW_DIR"
PLUGIN_ROOT=/opt/omero/omeroweb_import npx vite 2>&1 &
VITE_PID=$!
echo "Vite preview running on http://localhost:5173 (PID: $VITE_PID)"
```

The server watches for file changes. Edit CSS, HTML, or JS in the real plugin directory and the browser refreshes automatically.

## Available plugins

| Plugin | PLUGIN_ROOT |
| --- | --- |
| Import | `/opt/omero/omeroweb_import` |
| OMP | `/opt/omero/omeroweb_omp_plugin` |
| Admin Tools | `/opt/omero/omeroweb_admin_tools` |
| Imaris Connector | `/opt/omero/omeroweb_imaris_connector` |
| Web Zarr | `/opt/omero/omero_web_zarr` |

## Limitations

- Django template logic (`{% if %}`, `{% for %}`, login checks) is stripped. The preview shows the full UI unconditionally.
- CSRF-protected POST endpoints will not work. Use this for layout and styling only.
- Server-rendered data (project lists, user settings, job status) is replaced with empty placeholders.
- The preview runs outside Docker, so container-only paths and OMERO connections are unavailable.

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
