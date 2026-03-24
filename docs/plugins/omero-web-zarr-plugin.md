# OMERO.web Zarr Plugin Guide (`omero_web_zarr`)

## Purpose

`omero_web_zarr` provides authenticated OMERO.web access to OME-Zarr image data and adds a store-backed rendering path for images whose source of truth is an external managed-repository Zarr store.

It serves two complementary URL contracts:

- the **raw NGFF contract**, which exposes the original managed-repository store as faithfully as possible for validation and standards-oriented tooling;
- the **preview URL contract**, which gives OMERO.web preview launchers a stable authenticated Vizarr source without falling back to the classic OMERO preview widget for store-backed images.

## Main capabilities

- Expose managed-repository OME-Zarr stores through authenticated OMERO.web endpoints under `/zarr/`.
- Provide a right-panel preview for store-backed images that opens Vizarr against the preview-safe endpoint instead of the classic OMERO preview viewport.
- Override OMERO.web image-data, thumbnail, and region-render responses for store-backed images so they do not depend on OMERO RenderingEngine pyramid files.
- Keep the raw Zarr endpoint available for NGFF validation and tooling that needs the original multiscale structure.
- Provide store-backed downloads:
  - original Zarr store as a zip archive,
  - consolidated metadata manifest,
  - OME-TIFF export generated directly from the managed store.
- Preserve stock OMERO.web behavior for non-store-backed images.

## Key invariants

- **No filename heuristics**: store-backed detection is based on `Image.details.externalInfo.lsid` resolving to a local Zarr store, not on image names.
- **No hardcoded dataset keys**: dataset paths are taken from the store's root `multiscales[].datasets[].path` metadata. Stores using `0`, `1`, `2`, `s0`, `s1`, `s2`, or other valid dataset names are handled through the same code path.
- **Raw and preview contracts stay separate**:
  - raw routes expose the underlying store structure;
  - preview routes use the same store-backed NGFF payload while keeping a preview-specific URL namespace for OMERO.web launchers.
- **Non-Zarr images remain untouched**: the integration overrides activate only for store-backed images.

## Raw vs preview behavior

### Raw Zarr endpoint

Use the raw endpoint when the client needs the exact managed-repository store structure:

- NGFF validation
- standards inspection
- debugging store metadata
- tooling that understands the original multiscale layout

Raw routes preserve the original dataset keys and metadata documents from the managed store.

### Preview-safe endpoint

Use the preview endpoint for browser viewing:

- right-panel preview for store-backed images
- Vizarr launched from OMERO.web

For non-store-backed images, the preview routes do not attempt preview-level remapping. They delegate to the raw synthetic OMERO-backed NGFF responses because there is no managed-store multiscale tree to filter.

For store-backed images, preview routes forward the same `.zattrs`, `.zgroup`, `.zarray`, and chunk payloads that the raw endpoint serves. The preview path exists so OMERO.web can target a dedicated preview/Vizarr namespace without changing the underlying store contract.

## Rendering model

For store-backed images, the plugin can render directly from the managed Zarr store:

- thumbnails
- preview images
- tile-region responses
- JPEG/PNG/TIFF image responses used by OMERO.web viewers

This avoids the fragile dependency on classic OMERO RenderingEngine pyramid files for external Zarr-backed images.

For non-store-backed images, the plugin does not replace OMERO.web rendering.

## Launcher behavior

The `/zarr/vizarr/` and `/zarr/validator/` routes serve a thin OMERO-hosted launcher page:

- the initial HTML shell is fetched from the upstream static app origin and cached briefly in-process;
- a `<base href="...">` tag is injected so the browser resolves the app's relative assets correctly;
- root-relative `source=` parameters are normalized client-side against the browser's actual origin before the upstream app reads them, so reverse-proxy public HTTPS origins are preserved without server-side URL guessing;
- static asset requests are redirected to the upstream origin instead of proxying every JS/CSS/font request through Gunicorn workers.

This keeps launcher behavior generic while avoiding worker starvation from synchronous per-asset proxying.

The plugin also decorates OMERO.web channel metadata from Zarr display metadata where available, including:

- channel names,
- visibility,
- colors,
- contrast limits.

## Download behavior

Store-backed images receive dedicated download actions:

- **Download original**: zip of the managed-repository Zarr store
- **Download original metadata**: JSON manifest of all metadata documents in the store
- **Create OME-TIFF**: direct OME-TIFF export generated from the managed Zarr arrays

These routes are independent of OMERO RenderingEngine and therefore work even when classic RE-based export paths are not valid for the image.

## Hardware acceleration

Vizarr runs in the browser and uses client-side WebGL when the browser and workstation allow it. That means GPU acceleration is a client/browser capability, not an OMERO server capability.

The server-side store-backed render/export path in `omero_web_zarr` remains CPU-side.

## Configuration touchpoints

Relevant OMERO.web configuration lives in `env/omeroweb.env` / `env/omeroweb_example.env`:

- `CONFIG_omero_web_apps`
- `CONFIG_omero_web_open__with`
- `CONFIG_omero_web_ui_right__plugins`

The preview integration depends on `omero_web_zarr` being registered both as an installed OMERO.web app and as a right-panel plugin entry.

## Related docs

- `import-plugin.md` -- import-side native OME-Zarr routing and managed-repository handoff
- `import-plugin-workflow.md` -- end-to-end import workflow with native Zarr routing
- `omero-web-zarr-workflow.md` -- request/response workflow for preview, rendering, and downloads
