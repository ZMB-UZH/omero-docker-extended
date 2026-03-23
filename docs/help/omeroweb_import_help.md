# OMERO.web Help — Import Plugin (`omeroweb_import`)

## Overview

The Import plugin provides staged browser-based upload into server-side storage, followed by controlled OMERO import. It supports project targeting, progress tracking, and optional special-method workflows.

## Intended users

- Regular OMERO users importing files into managed projects.
- Teams requiring predictable import behavior with clear progress visibility.

## Main workflow

1. Open Import plugin.
2. Select target project.
3. Optionally choose a special method profile.
4. Drag-and-drop files/folders or choose from storage.
5. Start upload.
6. Confirm import.
7. Monitor import status and review log lines.

## Key features

### Staged upload + import separation

- Upload and import are separate phases.
- This improves error isolation and operational visibility.
- Large files are transferred in smaller chunks rather than one oversized browser request.

### Native OME-Zarr handling

- Ordinary files and Bio-Formats-compatible layouts stay on the standard OMERO import path.
- When a `.zarr` store is not compatible with Bio-Formats but matches a supported image layout, the plugin can route it through the native OME-Zarr import path instead.
- Successful native imports are validated before the job is reported as complete.
- Store-backed images are then viewed in OMERO.web through the Zarr-aware preview/download path rather than the classic preview stack.

### Project targeting

- Imports are attached to selected project context.
- Validate project selection before confirming import.

### Progress and logs

- UI shows upload/import status and parsed event messages.
- Typical event types include import success/failure, attachment success/failure, and auto-skipped entries.

### User settings

- User preferences are saved through plugin settings.
- Special method settings are managed separately from base preferences.

## Special method uploads

When enabled, special method selection can alter upload/import behavior (for example, SEM-EDX-related handling).

Recommendations:

- Verify method selection before upload.
- Use explicit naming conventions for method-associated files.
- Review final import summary for skipped/failed entries.

## Troubleshooting

- **Project list unavailable**: verify OMERO session and permissions.
- **Upload stalls/fails**: check OMERO.web logs and any reverse proxy in front of OMERO.web; large files now use chunked transfer, so repeated failures usually indicate server-side limits or storage problems rather than browser batching.
- **Import failures**: inspect status log details; retry failed subsets.
- **OME-Zarr preview feels slower than expected**: some stores contain multiscale levels that downsample `z` as well as `x/y`. In those cases the browser preview intentionally stays on full resolution to keep slice browsing correct.
- **Unexpected auto-skip**: review compatibility rules and file naming/content assumptions.

## Best practices

- Use batch uploads with predictable folder structure.
- Keep file names deterministic and method-consistent.
- Run initial pilot imports before large production loads.
