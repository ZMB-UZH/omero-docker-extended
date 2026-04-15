import { promises as fs } from 'node:fs';
import { basename, dirname, extname, resolve } from 'node:path';
import { createRequire } from 'node:module';

const requireFromPreviewDir = createRequire(resolve(process.cwd(), 'package.json'));
const { defineConfig } = requireFromPreviewDir('vite');

const REPO_ROOT = resolve(process.env.REPO_ROOT || process.cwd());
const PLUGIN_ROOT = resolve(process.env.PLUGIN_ROOT || `${REPO_ROOT}/omeroweb_import`);
const OMERO_STATIC_ROOT = process.env.OMERO_STATIC_ROOT
  ? resolve(process.env.OMERO_STATIC_ROOT)
  : null;
const PREVIEW_TEMPLATE = process.env.PREVIEW_TEMPLATE || 'index.html';
const PLUGIN_NAME = basename(PLUGIN_ROOT);
const TEMPLATE_ROOT = resolve(PLUGIN_ROOT, 'templates', PLUGIN_NAME);
const EXTRA_FS_ALLOW = Array.from(
  new Set(
    [
      ...(process.env.PREVIEW_EXTRA_FS_ALLOW || '')
        .split(':')
        .map((entry) => entry.trim())
        .filter(Boolean),
      ...(process.env.VITEST_INCLUDE || '')
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean)
        .map((entry) => {
          const wildcardIndex = entry.search(/[*?[{]/);
          const concretePath = wildcardIndex === -1 ? entry : entry.slice(0, wildcardIndex);
          return concretePath ? dirname(resolve(concretePath)) : '';
        })
        .filter(Boolean),
    ].map((entry) => resolve(entry)),
  ),
);

const MIME_TYPES = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.gif', 'image/gif'],
  ['.htm', 'text/html; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.jpeg', 'image/jpeg'],
  ['.jpg', 'image/jpeg'],
  ['.js', 'application/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.mjs', 'application/javascript; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.webp', 'image/webp'],
]);

const pathIsInside = (candidate, parent) => {
  const resolvedCandidate = resolve(candidate);
  const resolvedParent = resolve(parent);
  return (
    resolvedCandidate === resolvedParent || resolvedCandidate.startsWith(`${resolvedParent}/`)
  );
};

const resolveTemplatePath = (requestPath) => {
  const relativePath = requestPath === '/' ? PREVIEW_TEMPLATE : requestPath.replace(/^\/+/, '');
  const candidate = resolve(TEMPLATE_ROOT, relativePath);
  return pathIsInside(candidate, TEMPLATE_ROOT) ? candidate : null;
};

const resolveStaticAssetPath = (assetPath) => {
  const relativePath = assetPath.replace(/^\/+/, '');
  if (!relativePath) {
    return null;
  }
  if (relativePath.startsWith('3rdparty/')) {
    if (!OMERO_STATIC_ROOT) {
      return null;
    }
    const candidate = resolve(OMERO_STATIC_ROOT, relativePath);
    return pathIsInside(candidate, OMERO_STATIC_ROOT) ? candidate : null;
  }
  const firstSegment = relativePath.split('/')[0];
  if (!firstSegment) {
    return null;
  }
  const candidate = resolve(REPO_ROOT, firstSegment, 'static', relativePath);
  return pathIsInside(candidate, REPO_ROOT) ? candidate : null;
};

const replaceJsonScript = (_match, scriptId) =>
  `<script id="${scriptId}" type="application/json">{}</script>`;

const transformTemplateHtml = (html) =>
  html
    .replace(/\{%\s*load\s+static\s*%}/g, '')
    .replace(/\{%\s*static\s+'([^']+)'\s*%}/g, (_match, assetPath) => {
      return `/__preview_static__/${assetPath}`;
    })
    .replace(/\{%\s*url\s+'[^']+'[^%]*%}/g, '#')
    .replace(/\{\{[^}]+\|json_script:"([^"]+)"\s*\}\}/g, replaceJsonScript)
    .replace(/\{\{\s*[^}]+\|yesno:"true,false"\s*\}\}/g, 'false')
    .replace(/\{\{\s*[^}]+\|default:"[^"]*"\|safe\s*\}\}/g, '{}')
    .replace(/\{\{\s*[^}]+\|default_if_none:''[^}]*\}\}/g, '')
    .replace(/\{\{\s*[^}]+\|date:'[^']*'\s*\}\}/g, '')
    .replace(/\{\{\s*[^}]+\}\}/g, '')
    .replace(/\{%[^%]*%\}/g, '')
    .replace(/\sclass="root-user-blocked"/g, '');

const sendFile = async (response, filePath) => {
  const fileBuffer = await fs.readFile(filePath);
  const contentType = MIME_TYPES.get(extname(filePath).toLowerCase()) || 'application/octet-stream';
  response.setHeader('Content-Type', contentType);
  response.end(fileBuffer);
};

export default defineConfig({
  root: REPO_ROOT,
  publicDir: false,
  server: {
    host: '127.0.0.1',
    port: 5173,
    open: false,
    fs: {
      allow: [
        REPO_ROOT,
        PLUGIN_ROOT,
        ...(OMERO_STATIC_ROOT ? [OMERO_STATIC_ROOT] : []),
        ...EXTRA_FS_ALLOW,
      ],
    },
    watch: {
      ignored: ['!**/*.html', '!**/*.css', '!**/*.js'],
    },
  },
  plugins: [
    {
      name: 'django-template-preview-middleware',
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          try {
            const requestPath = (request.url || '/').split('?')[0];
            if (requestPath.startsWith('/__preview_static__/')) {
              const assetPath = requestPath.replace('/__preview_static__/', '');
              const resolvedPath = resolveStaticAssetPath(assetPath);
              if (!resolvedPath) {
                response.statusCode = 404;
                response.end('Preview asset not found.');
                return;
              }
              await sendFile(response, resolvedPath);
              return;
            }
            if (!(requestPath === '/' || requestPath.endsWith('.html'))) {
              next();
              return;
            }
            const templatePath = resolveTemplatePath(requestPath);
            if (!templatePath) {
              response.statusCode = 404;
              response.end('Preview template not found.');
              return;
            }
            const rawHtml = await fs.readFile(templatePath, 'utf-8');
            const transformedHtml = transformTemplateHtml(rawHtml);
            const html = await server.transformIndexHtml(requestPath, transformedHtml);
            response.setHeader('Content-Type', 'text/html; charset=utf-8');
            response.end(html);
          } catch (error) {
            next(error);
          }
        });
      },
    },
  ],
});
