# Tools Plugin Guide (`omeroweb_tools`)

## Purpose

The Tools plugin provides a user-facing launcher for OMERO.web utilities that
should be available to ordinary users instead of root administrators. Its first
feature is `Enhanced search`, a PostgreSQL-backed, user-scoped search engine
for OMERO image metadata that is merged with OMERO's own built-in search
results.

## Main capabilities

- `Tools` landing page that mirrors the Admin Tools layout pattern for future
  expansion.
- `Enhanced search` UI with a compact search row, typed `Start date` /
  `End date` filters backed by a jQuery UI datepicker, async image previews,
  and OMERO-built-in plus universal-metadata search scopes.
- Combined-source searches run the plugin-index query and OMERO built-in
  search concurrently, using separate database and OMERO connection boundaries.
- Per-user opt-in metadata indexing for all images owned by the current
  user, saved immediately when the checkbox is toggled.
- Per-user saved queries, plus persisted per-user open/closed state for the
  metadata-index and saved-query panels.
- Sync-state tracking for the current user's metadata index.
- OMERO permission revalidation before search results are displayed.
- Scope filtering in the plugin database so one user's indexed metadata is not
  searched through another user's account.
- Regular-user access only; root is intentionally blocked from running the
  workflow.

## Hard data boundary

This plugin has a strict write boundary:

- OMERO metadata is read through the OMERO API only.
- Indexed rows, scope membership, sync state, and saved queries are written only
  to the plugin database (`database_plugin`) through the existing `OMP_DATA_*`
  connection settings.
- The core OMERO PostgreSQL database is not written by this feature.
- The plugin does not mirror search data into OMERO annotations or file
  attachments.

## Key routes

| Route | Method | Purpose |
| --- | --- | --- |
| `/omeroweb_tools/` | GET | Tools landing page |
| `/omeroweb_tools/root-status/` | GET | Check whether the current user is root |
| `/omeroweb_tools/enhanced-search/` | GET | Search UI and results page |
| `/omeroweb_tools/enhanced-search/sync/` | POST | Trigger index refresh for the current user's metadata index |
| `/omeroweb_tools/enhanced-search/sync-state/` | GET | Fetch current metadata-index sync state |
| `/omeroweb_tools/enhanced-search/settings/` | POST | Save current user's enhanced-search UI and indexing settings |
| `/omeroweb_tools/enhanced-search/saved-queries/save/` | POST | Save current query for the user |
| `/omeroweb_tools/enhanced-search/saved-queries/delete/` | POST | Delete a saved query |
| `/omeroweb_tools/enhanced-search/saved-queries/<int:query_id>/` | GET | Re-open a saved query |
| `/omeroweb_tools/help/` | GET | Render Tools HTML help |

## Code structure

```text
omeroweb_tools/
├── views/
│   ├── index_view.py      # Landing page, enhanced-search UI, sync/query APIs
│   └── help_view.py       # HTML help response
├── services/
│   ├── acquisition_metadata.py    # Metadata extraction for indexed documents
│   ├── enhanced_search_service.py # Query parsing, OMERO revalidation, sync flow
│   └── enhanced_search_store.py   # Plugin-database schema and CRUD
├── config.py              # Runtime config and celery config parsing
├── celery_app.py          # Dedicated Celery app for enhanced-search jobs
├── tasks.py               # Celery task wrapper
├── templates/omeroweb_tools/
│   ├── index.html
│   ├── enhanced_search.html
│   └── help.html
└── static/omeroweb_tools/styles.css
```

## Configuration

### `env/omeroweb.env`

Metadata indexing is opt-in per OMERO user. Once enabled in the UI, the plugin
automatically indexes OMERO.web-visible metadata for all images owned by that
user. Indexed rows remain in the plugin database, search queries are restricted
to the current user's scope membership, and search results are revalidated
through OMERO before display.
If the plugin database is unavailable while the page loads, the metadata
indexing checkbox is rendered disabled and unchecked, and the UI shows an
explicit database-access error instead of guessing the saved state.

Related runtime variables:

- `TOOLS_ENHANCED_SEARCH_INDEX_BATCH_SIZE`
- `TOOLS_ENHANCED_SEARCH_MAX_RESULTS`
- `TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS`
- `TOOLS_ENHANCED_SEARCH_SCHEMA_VERSION`

### `env/omero-celery.env`

Dedicated worker controls:

- `TOOLS_ENHANCED_SEARCH_USE_CELERY`
- `TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL`
- `TOOLS_ENHANCED_SEARCH_CELERY_BACKEND_URL`
- `TOOLS_ENHANCED_SEARCH_CELERY_QUEUE`
- `TOOLS_ENHANCED_SEARCH_CELERY_RESULT_EXPIRES`
- `TOOLS_ENHANCED_SEARCH_CELERY_TIME_LIMIT`
- `TOOLS_ENHANCED_SEARCH_CELERY_LOGLEVEL`
- `TOOLS_ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY`
- `TOOLS_ENHANCED_SEARCH_CELERY_MAX_RETRIES`
- `TOOLS_ENHANCED_SEARCH_CELERY_PREFETCH`

`TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL` and
`TOOLS_ENHANCED_SEARCH_CELERY_BACKEND_URL` take precedence. If either is unset,
the plugin reuses `OMERO_IMS_CELERY_BROKER_URL` or
`OMERO_IMS_CELERY_BACKEND_URL` before falling back to an empty value.

When celery mode is enabled, `supervisord.conf` starts
`tools-celery-worker`. When it is disabled, the plugin falls back to a local
background thread inside the `omeroweb` process.

## Indexing and query flow

1. A user opens `Tools > Enhanced search`.
2. The user enables universal metadata indexing for their account; the
   setting is written immediately to the plugin database and verified with a
   read-after-write check. The same per-user settings row stores the
   open/closed state of the metadata-index and saved-query panels.
3. The worker reads OMERO metadata for images owned by that user through a root
   gateway session and extracts normalized image, project/dataset, channel,
   instrument, objective, detector, PlaneInfo, annotation, original-metadata,
   and original-file-name attributes. PlaneInfo is read in bulk when supported
   by the installed OMERO gateway. Private file paths are not indexed.
4. The worker writes only to the plugin database tables for indexed documents,
   scope membership, sync state, and saved queries.
5. Search queries combine OMERO-index matches with plugin-database metadata
   matches from the current user's own scope according to the selected indexed
   source. In `All searchable sources`, the two source lookups run concurrently.
6. Matching image IDs are rehydrated through OMERO and filtered again by actual
   OMERO visibility before the UI renders the results.
7. The `Clear` control resets the search text, date filters, and rendered
   results in place without issuing a full browser navigation.

## Operator checklist

- Verify `OMP_DATA_*` points to the plugin database, not the OMERO database.
- Verify `ROOTPASS`, `OMEROHOST`, and `OMERO_PORT` are available to the
  `omeroweb` container for indexing reads.
- Verify `tools-celery-worker` is healthy when celery mode is enabled.
- Keep `TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS` aligned with how quickly
  newly imported image metadata should become searchable after a user
  revisits the page.
