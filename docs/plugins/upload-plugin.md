# Upload Plugin Guide (`omeroweb_upload`)

## Purpose

The upload plugin manages staged file upload and controlled import into OMERO, including job lifecycle tracking, SEM-EDX spectrum processing, file attachment support, and configurable upload behavior.

## Main capabilities

- Upload session creation and browser-to-server file transfer.
- Automatic chunked transfer for large files so multi-GB uploads do not depend on a single oversized HTTP request.
- OMERO CLI-based import with configurable batching and concurrency.
- OMERO CLI import and import preflight checks run with `--depth 10` so directory-backed formats can be scanned deeper than the OMERO CLI default.
- OMERO CLI keepalive hardening for long-running imports via `OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS` (default `30` seconds).
- Browser uploads preserve the full relative path tree under `_staged/` so OMERO/Bio-Formats can see real directory-backed formats instead of flattened basenames.
- Logical import planning follows OMERO/Bio-Formats dry-run grouping output instead of a format allowlist: package-style directories are imported through the group header path that OMERO reports, while ordinary folders still import file-by-file.
- Target datasets are created from those logical import units immediately before import, not from raw staged member paths, so directory-backed formats land in one real dataset instead of generating orphaned images or empty internal datasets.
- After a grouped logical-package import succeeds, the plugin reconciles the imported OMERO image names against the logical upload root so internal header filenames reported by OMERO/Bio-Formats do not leak through as user-facing image names.
- Grouped-directory cleanup is conservative: the plugin only collapses cleanup to a staged directory root when the OMERO-reported group covers the full uploaded subtree under that root.
- Automatic detection and skipping of non-importable files is limited to operating-system and filesystem junk (for example `Thumbs.db`, `.DS_Store`, recycle-bin metadata); all other files are handed to OMERO/Bio-Formats unchanged.
- Job lifecycle: start, upload, import, confirm, prune.
- Job status polling for progress tracking.
- SEM-EDX spectrum parsing (EMSA format) with matplotlib visualization and genetic algorithm label placement.
- File attachment support: link related files (spectra, metadata) to imported images.
- Automatic temp cleanup: immediate deletion after successful import + host-side sweep deleting remnants older than 24h.
- User settings and special-method settings persistence in `database_plugin`.
- Project listing and root status checks.

## Host-side tmp cleaner (automatic)

Temporary artifacts live under `OMERO_TMP_PATH`.

Cleanup is performed by two mechanisms:

- **Immediate**: the upload payload directory for a job is deleted right after a successful import finishes (job JSON remains for UI status).
- **Sweep**: a host-side systemd timer (`omero-tmp-cleaner.timer`) runs periodically and deletes anything under `OMERO_TMP_PATH` older than 24 hours.

Useful commands (host):

- `systemctl status omero-tmp-cleaner.timer`
- `journalctl -u omero-tmp-cleaner.service`
- `sudo /usr/local/sbin/omero-tmp-cleaner --tmp-dir "$OMERO_TMP_PATH"`

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
| `OMERO_UPLOAD_PATH` | Host path for temporary upload storage |

The import step runs OMERO CLI with `HOME` and `XDG_CACHE_HOME` set to `${OMERO_UPLOAD_PATH}/.omero-cli-home` to guarantee writable cache space for OMERO.java downloads in non-root containers.

## Large-file behavior

- Small files continue to upload as normal multipart requests.
- Files larger than the browser-side request ceiling are sliced into bounded chunks before they are sent to `/omeroweb_upload/upload/<job_id>/`.
- The upload endpoint validates chunk offsets and file sizes and returns JSON errors for server-side failures, avoiding raw HTML error pages in the UI when possible.
- Upload session creation rejects duplicate normalized relative paths up front so mixed slash styles cannot collide onto the same staged target.
- This reduces exposure to reverse-proxy and app-server request-body limits for large microscopy datasets, but operators should still review any external proxy size and timeout settings used in front of OMERO.web.

## Operator checklist

- Ensure temporary upload paths are writable by the container user.
- Monitor cleanup behavior to avoid stale disk growth (check job directories on tmpfs).
- Validate imports on representative datasets (including SEM-EDX if used).
- Confirm plugin database connectivity for settings persistence.
- Confirm plugin settings are persisted and reloaded correctly across sessions.
- Review OMERO.web logs for import errors or timeout issues.
