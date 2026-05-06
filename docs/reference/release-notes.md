# Release Notes

## 2026-05-06 Imaris XT Connector UI Refresh

### Highlights

- Added a timed password reveal control to the standalone XT connector while
  keeping passwords out of autosave settings and clearing the visible password
  field after successful login.
- Restored converter selection as an autosaved setting and persisted converter
  changes immediately when `Autosave settings` is enabled.
- Reworked folder export so `Export folder to OMERO` always opens the native
  folder chooser before `Confirm folder export`; the typed path is only the
  first export chooser location hint for a session.
- Added draggable Projects, Datasets, and Images panel splitters with bounded
  proportional widths and removed refresh-time action-button repaint flicker.
- Wired the connector info button to a modal version, author, and as-is
  disclaimer dialog.

### Validation Focus

- Focused standalone connector unit coverage for password handling, autosaved
  converter settings, folder-export chooser ordering, bounded panel resizing,
  and refresh action-button state.
- Tk/Xvfb layout verification for minimum-width behavior and visible widget
  alignment.

## 2026-04-26 Documentation Audit Refresh

This refresh audited the documentation set against the current repository code,
tests, workflows, and scanner runbooks.

### Highlights

- Updated OMERO.web supervisord topology docs to match the four declared
  programs in `supervisord.conf`.
- Moved the completed knowledge-base bootstrap plan from active planning into
  completed execution-plan history.
- Updated planning, quality, and backlog docs to use current-default-branch
  change records instead of routine branch/PR language.
- Refreshed code-scanning guidance so historical critical/high findings are not
  mistaken for current open file-level alerts.
- Updated plugin-database documentation for OMP, Import, and Tools enhanced
  search data stores.
- Corrected Import plugin upload configuration docs to use the current
  `OMERO_WEB_UPLOAD_*` environment contract and the shared `OMERO_TMP_PATH`
  runtime subtree.
- Refreshed the Python acceleration design note's tracked file and line counts
  against the current repository tree.
- Removed routine pull-request triggers and hard-coded `main` branch filters
  from checked-in workflows; workflow jobs now rely on the current default
  branch guard.

### Validation Focus

- Documentation structure and required index links.
- Regression checks for scanner snapshot wording and topology facts.
- Markdown linting and workflow-local gates before accepting the change.

## Current Documentation Refresh

This release restructures project documentation for public consumption and maintainability.

### Highlights

- Consolidated non-root Markdown documents into `docs/`.
- Replaced ad hoc historical narratives with implementation-level documentation.
- Added plugin-specific operation guides for each OMERO.web plugin package.
- Added architecture, deployment, operations, troubleshooting, and endpoint references.

### Documentation Principles Applied

- public-safe language,
- no personal incident details,
- explicit operational guidance,
- consistent structure for future updates.

## Future Update Template

For future releases, record:

1. Feature additions and behavior changes.
2. Backward compatibility notes.
3. Configuration migrations (if any).
4. Test and rollout validation summary.
