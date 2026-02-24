# OMERO.web Help — Upload Plugin (`omeroweb_upload`)

## Overview

The Upload plugin provides staged browser-based upload into server-side storage, followed by controlled OMERO import. It supports project targeting, progress tracking, and optional special-method workflows.

## Intended users

- Regular OMERO users importing files into managed projects.
- Teams requiring predictable import behavior with clear progress visibility.

## Main workflow

1. Open Upload plugin.
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
- **Upload stalls/fails**: retry smaller batches and check network/session state.
- **Import failures**: inspect status log details; retry failed subsets.
- **Unexpected auto-skip**: review compatibility rules and file naming/content assumptions.

## Best practices

- Use batch uploads with predictable folder structure.
- Keep file names deterministic and method-consistent.
- Run initial pilot imports before large production loads.
