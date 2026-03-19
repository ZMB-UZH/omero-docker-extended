# Upload Plugin Guide (`omeroweb_upload`)

## Purpose

The upload plugin manages staged file upload and controlled import into OMERO, including job lifecycle tracking, SEM-EDX spectrum processing, file attachment support, and configurable upload behavior.

## Main capabilities

- Upload session creation and browser-to-server file transfer.
- Automatic chunked transfer for large files so multi-GB uploads do not depend on a single oversized HTTP request.
- OMERO CLI-based import with configurable batching and concurrency.
- OMERO CLI import and import preflight checks run with `--depth 10` so directory-backed formats can be scanned deeper than the OMERO CLI default.
- OMERO CLI keepalive hardening for long-running imports via `OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS` (default `30` seconds).
- Long-running OMERO CLI imports use `OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS` with a 24-hour default so very large structured datasets are not aborted by a short plugin-side subprocess timeout.
- Browser uploads preserve the full relative path tree under `_staged/` so OMERO/Bio-Formats can see real directory-backed formats instead of flattened basenames.
- Logical import planning follows OMERO/Bio-Formats dry-run grouping output instead of a format allowlist: package-style directories are imported through the staged package root that OMERO groups, while ordinary folders still import file-by-file.
- Heavy import planning for grouped formats is deferred to the background import worker after the final upload response returns, so large `.zarr` dry-run scans do not block a Gunicorn request long enough to trigger worker timeouts.
- Request-path dataset preparation now prefers the background logical import-unit plan that OMERO/Bio-Formats already produced, so dataset creation stays aligned with grouped/package imports across formats instead of relying on raw upload-path heuristics.
- This preflight planning happens even when browser-side compatibility checking is disabled. With compatibility disabled, the background thread persists logical import units only; it does not run the first-batch compatibility scan, and the next request-owned poll/import step prepares any missing Dataset targets from that persisted plan before the import thread starts.
- Background workers must not reopen the importing user's live OMERO.web session from a stored `session_key`; once no browser request holds a live reference, closing that helper client can destroy the login session.
- Grouped logical-package imports pass the logical upload-root name to OMERO CLI with `-n`, so internal header filenames reported by OMERO/Bio-Formats do not need a post-import OMERO API rename against the user's browser session.
- Grouped-directory cleanup is conservative: the plugin only collapses cleanup to a staged directory root when the OMERO-reported group covers the full uploaded subtree under that root.
- Browser compatibility polling intentionally has no fixed five-minute deadline; the UI keeps waiting for server-side status changes so large `.zarr` and other directory-backed imports do not fail client-side while the backend is still healthy.
- OMERO.web should run Gunicorn with a long request timeout (for example `OMERO_WEB_WSGI_ARGS=... --timeout 7200`) so slow chunk uploads are not killed by the WSGI worker before the browser-side 2-hour upload timeout expires.
- OMERO CLI dry-run scan timeouts are controlled by `OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS` (default example `7200`) instead of a short hardcoded deadline, so large `.zarr` compatibility/planning scans can finish in the background.
- Automatic detection and skipping of non-importable files is limited to operating-system and filesystem junk (for example `Thumbs.db`, `.DS_Store`, recycle-bin metadata); all other files are handed to OMERO/Bio-Formats unchanged.
- **Zarr pre-flight scan and automatic re-compression**: before importing any `.zarr` directory, the plugin runs `omero import -f` (Bio-Formats dry-run) to verify the format is importable. If Bio-Formats finds 0 groups (e.g. gzip/zstd compression unsupported by JZarr), the plugin automatically re-compresses the zarr data to zlib (supported by JZarr) using the `numcodecs` library, then imports the converted copy. The temporary re-compressed zarr is deleted after import. Re-compression works at the chunk level (one chunk at a time, no full arrays loaded into memory), preserves the original directory structure and dimension separator (`/` or `.`), and handles any zarr layout — flat arrays, nested groups, bioformats2raw, or OME-NGFF. Arrays already using zlib are left untouched. This allows pure OME-NGFF zarrs (e.g. from `ome-zarr-py`) to be imported into OMERO's managed repository without user intervention.
- **Zarr directory import naming**: when importing a `.zarr` directory, the plugin always passes the directory name to OMERO CLI via `-n` so Bio-Formats does not fall back to an internal chunk coordinate as the image name.
- **Import success validation**: after every `omero import` call, the plugin searches both stdout and stderr for imported OMERO object IDs (Image, Fileset, Plate, etc.) — some formats emit IDs only on stderr. As a final fallback, the plugin queries the OMERO API to check whether an image matching the import name was created in the target dataset (using `detachOnDestroy` to avoid session destruction). If the CLI exits 0 but no objects are found anywhere, the import is reported as an error. If the CLI exits non-zero but objects are confirmed (via output or API), the import is treated as successful with a warning — preventing false failures for imports where OMERO committed the data before the CLI process errored.
- **Progress bar accuracy**: the orange import progress bar uses the higher of two signals (real `/proc/{pid}/io` monitoring and time-based asymptotic estimate) and enforces a high-water mark so the bar never goes backwards — not on refresh, not when new files are added, not under any circumstance. On browser refresh, progress state is restored from localStorage and bars jump instantly to their previous position. The blue bar uses `Math.floor` and caps at 99% while any import is still active, only reaching 100% when all jobs have completed.
- Job lifecycle: start, upload, import, confirm, prune.
- Job status polling for progress tracking.
- SEM-EDX spectrum parsing (EMSA format) with matplotlib visualization and genetic algorithm label placement.
- File attachment support: link related files (spectra, metadata) to imported images.
- Automatic temp cleanup: immediate deletion after successful import; failed imports retain their staged payload and job status for deferred cleanup after `OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS` (default `172800`, 48 hours).
- User settings and special-method settings persistence in `database_plugin`.
- Project listing and root status checks.

## Host-side tmp cleaner (automatic)

Temporary artifacts live under `OMERO_TMP_PATH`.

Cleanup is performed by two mechanisms:

- **Immediate**: the upload payload directory for a job is deleted right after a successful import finishes (job JSON remains for UI status).
- **Sweep**: a host-side systemd timer (`omero-tmp-cleaner.timer`) runs periodically and deletes anything under `OMERO_TMP_PATH` older than 24 hours by default. The upload plugin writes deferred-cleanup markers for failed jobs so their payload directory and job JSON are retained for 48 hours unless `OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS` overrides that window.

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
| `OMERO_WEB_WSGI_ARGS` | Gunicorn arguments for OMERO.web; include a long `--timeout` for slow upload requests (default example: `--timeout 7200`) |
| `OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS` | OMERO CLI keepalive interval for long-running imports (default `30`) |
| `OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS` | Timeout for OMERO CLI dry-run compatibility/grouping scans (default `7200`) |
| `OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS` | Per-import subprocess timeout in seconds (default `86400`) |
| `OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS` | Failed-job deferred cleanup window (default `172800`) |

The import step runs OMERO CLI with `HOME` and `XDG_CACHE_HOME` set to `${OMERO_UPLOAD_PATH}/.omero-cli-home` to guarantee writable cache space for OMERO.java downloads in non-root containers.

## Large-file behavior

- Small files continue to upload as normal multipart requests.
- Files larger than the browser-side request ceiling are sliced into bounded chunks before they are sent to `/omeroweb_upload/upload/<job_id>/`.
- The upload endpoint validates chunk offsets and file sizes and returns JSON errors for server-side failures, avoiding raw HTML error pages in the UI when possible.
- The final upload request no longer performs grouped dry-run dataset planning inline; that work runs in the background import worker so large structured uploads do not die at the HTTP worker timeout boundary.
- Before the background import starts, the request path pre-creates any missing dataset targets from the persisted logical import-unit plan when available; this keeps background workers off the live browser session while preserving grouped/package routing across formats.
- Background compatibility and grouped-import dry-run scans now use the long env-driven `OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS` limit instead of a fixed 45-second ceiling.
- Upload session creation rejects duplicate normalized relative paths up front so mixed slash styles cannot collide onto the same staged target.
- This reduces exposure to reverse-proxy and app-server request-body limits for large microscopy datasets, but operators should still review any external proxy size and timeout settings used in front of OMERO.web.

## Operator checklist

- Ensure temporary upload paths are writable by the container user.
- Monitor cleanup behavior to avoid stale disk growth (check job directories on tmpfs).
- Validate imports on representative datasets (including SEM-EDX if used).
- Confirm plugin database connectivity for settings persistence.
- Confirm plugin settings are persisted and reloaded correctly across sessions.
- Review OMERO.web logs for import errors or timeout issues.
