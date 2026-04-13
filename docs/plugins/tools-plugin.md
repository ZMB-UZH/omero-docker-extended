# Tools Plugin Guide (`omeroweb_tools`)

## Purpose

The Tools plugin provides a user-facing launcher for OMERO.web utilities that
should be available to ordinary users instead of root administrators. Its first
feature is `Enhanced search`, a selective PostgreSQL-backed search engine for
indexed microscopy metadata.

## Main capabilities

- `Tools` landing page that mirrors the Admin Tools layout pattern for future
  expansion.
- `Enhanced search` UI with free-text and fielded filters.
- Selective indexing of configured groups, projects, or datasets.
- Per-user saved queries.
- Sync-state tracking for each configured scope.
- Resumable indexing based on the last processed image ID for a scope.
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
| `/omeroweb_tools/enhanced-search/sync/` | POST | Trigger index refresh for one configured scope |
| `/omeroweb_tools/enhanced-search/sync-state/` | GET | Fetch current sync-state table |
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

`TOOLS_ENHANCED_SEARCH_SCOPES` is the authoritative allowlist. It is empty by
default and must be set explicitly:

```json
[
  {"type": "project", "id": 123, "label": "Microscope QA"},
  {"type": "dataset", "id": 456, "label": "Pilot import set"}
]
```

Related runtime variables:

- `TOOLS_ENHANCED_SEARCH_INDEX_BATCH_SIZE`
- `TOOLS_ENHANCED_SEARCH_MAX_RESULTS`
- `TOOLS_ENHANCED_SEARCH_SYNC_STALE_SECONDS`
- `TOOLS_ENHANCED_SEARCH_SCHEMA_VERSION`
- `TOOLS_ENHANCED_SEARCH_SCOPE_IMAGE_CAP`

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

When celery mode is enabled, `supervisord.conf` starts
`tools-celery-worker`. When it is disabled, the plugin falls back to a local
background thread inside the `omeroweb` process.

## Indexing and query flow

1. An operator defines explicit indexed scopes in `TOOLS_ENHANCED_SEARCH_SCOPES`.
2. A user opens `Tools > Enhanced search`.
3. The user triggers a scope refresh.
4. The worker reads OMERO metadata through a root gateway session and extracts
   selective search attributes.
5. The worker writes only to the plugin database tables for indexed documents,
   scope membership, sync state, and saved queries.
6. Search queries run against the plugin database first.
7. Matching image IDs are rehydrated through OMERO and filtered again by actual
   OMERO visibility before the UI renders the results.

## Operator checklist

- Keep scopes selective and intentional.
- Verify `OMP_DATA_*` points to the plugin database, not the OMERO database.
- Verify `ROOTPASS`, `OMEROHOST`, and `OMERO_PORT` are available to the
  `omeroweb` container for indexing reads.
- Verify `tools-celery-worker` is healthy when celery mode is enabled.
- Refresh indexed scopes after major import or metadata-ingestion changes.
