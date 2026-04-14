# Tools Plugin Guide (`omeroweb_tools`)

## Purpose

The Tools plugin provides a user-facing launcher for OMERO.web utilities that
should be available to ordinary users instead of root administrators. Its first
feature is `Enhanced search`, a selective PostgreSQL-backed search engine for
indexed acquisition metadata that is merged with OMERO's own built-in search
results.

## Main capabilities

- `Tools` landing page that mirrors the Admin Tools layout pattern for future
  expansion.
- `Enhanced search` UI with a compact search row, async image previews, and
  OMERO-built-in plus acquisition-index search scopes.
- Per-user opt-in acquisition indexing for all images owned by the current
  user.
- Per-user saved queries.
- Sync-state tracking for the current user's acquisition index.
- OMERO permission revalidation before search results are displayed.
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
| `/omeroweb_tools/enhanced-search/sync/` | POST | Trigger index refresh for the current user's acquisition index |
| `/omeroweb_tools/enhanced-search/sync-state/` | GET | Fetch current acquisition-index sync state |
| `/omeroweb_tools/enhanced-search/saved-queries/save/` | POST | Save current query for the user |
| `/omeroweb_tools/enhanced-search/saved-queries/delete/` | POST | Delete a saved query |
| `/omeroweb_tools/enhanced-search/saved-queries/<query_id>/` | GET | Re-open a saved query |
| `/omeroweb_tools/help/` | GET | Serve Markdown help |

## Code structure

```text
omeroweb_tools/
├── views/
│   ├── index_view.py      # Landing page, enhanced-search UI, sync/query APIs
│   └── help_view.py       # Markdown help response
├── services/
│   ├── acquisition_metadata.py    # Metadata extraction for indexed documents
│   ├── enhanced_search_service.py # Query parsing, OMERO revalidation, sync flow
│   └── enhanced_search_store.py   # Plugin-database schema and CRUD
├── config.py              # Runtime config and celery config parsing
├── celery_app.py          # Dedicated Celery app for enhanced-search jobs
├── tasks.py               # Celery task wrapper
├── templates/omeroweb_tools/
│   ├── index.html
│   └── enhanced_search.html
└── static/omeroweb_tools/styles.css
```

## Configuration

### `env/omeroweb.env`

Acquisition indexing is opt-in per OMERO user. Once enabled in the UI, the
plugin automatically indexes acquisition metadata for all images owned by that
user. The indexed rows remain private to the plugin database and search results
are revalidated through OMERO before display.

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
2. The user enables acquisition metadata indexing for their account.
3. The worker reads OMERO metadata for images owned by that user through a root gateway session and extracts
   selective search attributes.
4. The worker writes only to the plugin database tables for indexed documents,
   scope membership, sync state, and saved queries.
5. Search queries combine OMERO-index matches with plugin-database
   acquisition matches according to the selected indexed scope.
6. Matching image IDs are rehydrated through OMERO and filtered again by actual
   OMERO visibility before the UI renders the results.

## Operator checklist

- Verify `OMP_DATA_*` points to the plugin database, not the OMERO database.
- Verify `ROOTPASS`, `OMEROHOST`, and `OMERO_PORT` are available to the
  `omeroweb` container for indexing reads.
- Verify `tools-celery-worker` is healthy when celery mode is enabled.
- Keep `TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS` aligned with how quickly
  newly imported acquisition metadata should become searchable after a user
  revisits the page.
