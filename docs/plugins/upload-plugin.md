# Upload Plugin Guide (`omeroweb_upload`)

## Purpose

The upload plugin manages staged file upload and controlled import into OMERO, including job lifecycle tracking, SEM-EDX spectrum processing, file attachment support, and configurable upload behavior.

## Main capabilities

- Upload session creation and multipart file transfer.
- OMERO CLI-based import with configurable batching and concurrency.
- Automatic detection and skipping of non-importable files (OS metadata, companion XML in metadata directories) to match OMERO Insight behaviour.
- Job lifecycle: start, upload, import, confirm, prune.
- Job status polling for progress tracking.
- SEM-EDX spectrum parsing (EMSA format) with matplotlib visualization and genetic algorithm label placement.
- File attachment support: link related files (spectra, metadata) to imported images.
- Stale upload pruning with configurable age thresholds.
- User settings and special-method settings persistence in `database_plugin`.
- Project listing and root status checks.

## Key routes

| Route | Method | Purpose |
|---|---|---|
| `/omeroweb_upload/` | GET | Main upload page |
| `/omeroweb_upload/projects/` | GET | List accessible projects |
| `/omeroweb_upload/root-status/` | GET | Check if current user is OMERO root |
| `/omeroweb_upload/help/` | GET | Serve plugin help documentation (Markdown) |
| `/omeroweb_upload/start/` | POST | Create a new upload session (job) |
| `/omeroweb_upload/upload/<job_id>/` | POST | Transfer files to the job directory |
| `/omeroweb_upload/import/<job_id>/` | POST | Trigger OMERO CLI import for uploaded files |
| `/omeroweb_upload/confirm/<job_id>/` | POST | Confirm import completion |
| `/omeroweb_upload/prune/<job_id>/` | POST | Remove temporary upload files |
| `/omeroweb_upload/status/<job_id>/` | GET | Poll job status |
| `/omeroweb_upload/user-settings/save/` | POST | Save user upload preferences |
| `/omeroweb_upload/special-method-settings/save/` | POST | Save SEM-EDX method settings |
| `/omeroweb_upload/special-method-settings/load/` | GET | Load SEM-EDX method settings |
| `/omeroweb_upload/special-method-settings/delete/` | POST | Delete SEM-EDX method settings |

## Typical user workflow

1. Open upload page at `/omeroweb_upload/`.
2. Select target project and dataset.
3. Start upload session (creates job directory on tmpfs).
4. Transfer files to the job-specific upload endpoint.
5. Trigger import step (OMERO CLI `import` with batching).
6. For SEM-EDX data: spectrum files are parsed, visualized, and attached to imported images.
7. Confirm import and monitor status until terminal state.
8. Prune temporary upload assets once processing is complete.

## Code structure

```
omeroweb_upload/
├── views/
│   ├── index_view.py                  # Main page, project listing, job lifecycle endpoints
│   ├── core_functions.py              # Job management, import orchestration, SEM-EDX processing
│   ├── user_settings_view.py          # User preference persistence
│   ├── special_method_settings_view.py # SEM-EDX method configuration
│   └── utils.py                       # Request parsing helpers
├── services/
│   ├── compat.py                      # Backward compatibility wrapper
│   ├── data_store.py                  # PostgreSQL persistence (user settings, method settings)
│   ├── jobs/job_storage.py            # Job file I/O with portalocker
│   ├── omero/connection_service.py    # OMERO connection and file attachment
│   ├── omero/dataset_service.py       # Dataset and project management
│   ├── omero/import_service.py        # OMERO CLI import with batching
│   ├── omero/sem_edx_parser.py        # EMSA spectrum parsing, matplotlib visualization, GA labels
│   └── upload_management/workflow_service.py  # Upload workflow orchestration
├── constants.py                       # Upload batch size, paths, environment config
├── strings/errors.py                  # All error message functions
├── strings/messages.py                # All user-facing message functions
├── utils/file_helpers.py              # File path resolution, directory creation, sanitization
└── utils/omero_helpers.py             # Backward-compatible OMERO helper exports
```

## SEM-EDX processing

The upload plugin includes specialized support for SEM-EDX (Scanning Electron Microscopy - Energy Dispersive X-ray) data:

- Parses EMSA/MSA format spectrum files with metadata extraction.
- Generates matplotlib spectrum visualizations with element identification.
- Uses a genetic algorithm for optimal label placement on spectrum plots.
- Attaches generated spectrum images as OMERO file annotations on imported images.
- Configurable per-user via special method settings.

## Operational controls

Configuration values in `env/omeroweb.env`:

| Variable | Purpose |
|---|---|
| `UPLOAD_CONCURRENT_LIMIT` | Maximum simultaneous upload jobs |
| `UPLOAD_BATCH_SIZE` | Files per import batch |
| `UPLOAD_CLEANUP_INTERVAL` | How often cleanup runs (seconds) |
| `UPLOAD_CLEANUP_AGE_THRESHOLD` | Minimum age before stale cleanup (seconds) |
| `OMERO_UPLOAD_PATH` | Host path for temporary upload storage |

## Operator checklist

- Ensure temporary upload paths are writable by the container user.
- Monitor cleanup behavior to avoid stale disk growth (check job directories on tmpfs).
- Validate imports on representative datasets (including SEM-EDX if used).
- Confirm plugin database connectivity for settings persistence.
- Confirm plugin settings are persisted and reloaded correctly across sessions.
- Review OMERO.web logs for import errors or timeout issues.
