# OMERO.web Zarr Plugin Guide (`omero_web_zarr`)

## Purpose

`omero_web_zarr` provides authenticated OMERO.web access to OME-Zarr image data and adds a store-backed rendering path for images whose source of truth is an external managed-repository Zarr store.

It serves two distinct contracts:

- the **raw NGFF contract**, which exposes the original managed-repository store as faithfully as possible for validation and standards-oriented tooling;
- the **preview contract**, which keeps browser viewing correct for slice browsing by exposing only viewer-safe multiscale levels and by bypassing classic OMERO rendering paths that are not reliable for these store-backed images.

## Main capabilities

- Expose managed-repository OME-Zarr stores through authenticated OMERO.web endpoints under `/zarr/`.
- Provide a right-panel preview for store-backed images that opens Vizarr against the preview-safe endpoint instead of the classic OMERO preview viewport.
- Override OMERO.web image-data, thumbnail, and region-render responses for store-backed images so they do not depend on OMERO RenderingEngine pyramid files.
- Keep the raw Zarr endpoint available for NGFF validation and tooling that needs the original multiscale structure.
- Provide store-backed downloads:
  - original Zarr store as a zip archive,
  - consolidated metadata manifest,
  - OME-TIFF export generated directly from the managed store.
- Preserve stock OMERO.web behavior for non-store-backed images, with one generic safeguard: if the current OMERO/Bio-Formats RenderingEngine fails while introspecting tile size, the image-data and tile-region paths fall back to the configured OMERO max tile length instead of failing the whole preview request.

## Key invariants

- **No filename heuristics**: store-backed detection is based on `Image.details.externalInfo.lsid` resolving to a local Zarr store, not on image names.
- **No hardcoded dataset keys**: dataset paths are taken from the store's root `multiscales[].datasets[].path` metadata. Stores using `0`, `1`, `2`, `s0`, `s1`, `s2`, or other valid dataset names are handled through the same code path.
- **Raw and preview contracts stay separate**:
  - raw routes expose the underlying store structure;
  - preview routes may renumber visible levels to `0..N-1`, but they still resolve those preview levels back to the underlying dataset keys from root metadata.
- **Viewer-safe multiscales only**: preview routes expose only levels that preserve non-display axes (`t`, `c`, `z`) so browser slice browsing does not silently jump onto a level that has downsampled the current plane axis.
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

- right-panel preview
- Vizarr launched from OMERO.web for store-backed images

The preview contract is intentionally conservative. If a multiscale level downsamples `z`, `c`, or `t`, it is excluded from preview. This prevents blurred or semantically wrong slice rendering in the browser.

For example, if an image has:

- `s0`: full-resolution `z/y/x`
- `s1..sN`: downsampled `z/y/x`

then preview can safely expose only the full-resolution level, even if the raw store contains many multiscale levels. That is a correctness rule, not a special case.

## Rendering model

For store-backed images, the plugin can render directly from the managed Zarr store:

- thumbnails
- preview images
- tile-region responses
- JPEG/PNG/TIFF image responses used by OMERO.web viewers

This avoids the fragile dependency on classic OMERO RenderingEngine pyramid files for external Zarr-backed images.

For non-store-backed images, the plugin does not replace OMERO.web rendering. It only adds a generic compatibility guard around tile-size discovery so Bio-Formats-backed Zarrs continue using the default OMERO.web preview path when that upstream call fails.

## Launcher behavior

The `/zarr/vizarr/` and `/zarr/validator/` routes serve a thin OMERO-hosted launcher page:

- the initial HTML shell is fetched from the upstream static app origin and cached briefly in-process;
- a `<base href="...">` tag is injected so the browser resolves the app's relative assets correctly;
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
