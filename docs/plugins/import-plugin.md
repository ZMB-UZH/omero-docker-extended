# Import Plugin Guide (`omeroweb_import`)

## Purpose

The Import plugin manages staged file upload and controlled import into OMERO, including job lifecycle tracking, SEM-EDX spectrum processing, file attachment support, and configurable upload behavior.

Related docs:

- `import-plugin-workflow.md`
- `omero-web-zarr-plugin.md`
- `omero-web-zarr-workflow.md`

## Main capabilities

- Upload session creation and browser-to-server file transfer.
- Automatic chunked transfer for large files so multi-GB uploads do not depend on a single oversized HTTP request.
- Capability-driven external clients can reuse the same chunked upload/import
  contract by calling `/omeroweb_import/start/` with a file manifest and
  `dataset_name_override`. That path imports the selected folder into OMERO
  root as one Dataset named by the override instead of distributing files by
  upload-path heuristics.
- The XT OMERO connector requires Windows 10 or newer before opening its GUI.
  Startup blocks with a command-line/log message when the Windows version cannot
  be verified as supported. Its folder-import flow provides a typed path field
  plus a `Select` button that opens the standard Tk native directory chooser
  (`tkinter.filedialog.askdirectory`) with `mustexist=true`, then uses ordinary
  HTTPS requests. It does not depend on Explorer automation, PowerShell,
  COM-only pickers, or a Windows 11-only shell API.
- OMERO CLI-based import with configurable batching and concurrency.
- OMERO CLI import and import preflight checks run with `--depth 15` so directory-backed formats can be scanned deeper than the OMERO CLI default.
- OMERO CLI keepalive hardening for long-running imports via `OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS` (default `30` seconds).
- Long-running OMERO CLI imports use `OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS` with a 24-hour default so very large structured datasets are not aborted by a short plugin-side subprocess timeout.
- Browser uploads preserve the full relative path tree under `_staged/` so OMERO/Bio-Formats can see real directory-backed formats instead of flattened basenames.
- Logical import planning follows OMERO/Bio-Formats dry-run grouping output instead of a format allowlist: package-style directories are imported through the staged package root that OMERO groups, while ordinary folders still import file-by-file.
- Heavy import planning for grouped formats is deferred to the background import worker after the final upload response returns, so large `.zarr` dry-run scans do not block a Gunicorn request long enough to trigger worker timeouts.
- Request-path dataset preparation now prefers the background logical import-unit plan that OMERO/Bio-Formats already produced, so dataset creation stays aligned with grouped/package imports across formats instead of relying on raw upload-path heuristics.
- This preflight planning happens even when browser-side compatibility checking is disabled. With compatibility disabled, the background thread persists logical import units only; it does not run the first-batch compatibility scan, and the next request-owned poll/import step prepares any missing Dataset targets from that persisted plan before the import thread starts.
- Background imports run under independent server-created OMERO sessions for the importing user, scoped to the user's active group at upload start. They do not reuse the browser's live OMERO.web session, so imports continue safely even if the user logs out or the browser session ends.
- When a request-path poll/import step does not pre-create every target Dataset in time, the background import worker now uses the same independent user-session model for dataset creation instead of trying to impersonate the user through `job-service`. This keeps grouped imports working without reviving the old browser-session-disconnect failure mode.
- Grouped logical-package imports pass the logical upload-root name to OMERO CLI with `-n`, so internal header filenames reported by OMERO/Bio-Formats do not need a post-import OMERO API rename against the user's browser session.
- Grouped-directory cleanup is conservative: the plugin only collapses cleanup to a staged directory root when the OMERO-reported group covers the full uploaded subtree under that root.
- Browser compatibility polling intentionally has no fixed five-minute deadline; the UI keeps waiting for server-side status changes so large `.zarr` and other directory-backed imports do not fail client-side while the backend is still healthy.
- OMERO.web should run Gunicorn with a long request timeout (for example `OMERO_WEB_WSGI_ARGS=... --timeout 7200`) so slow chunk uploads are not killed by the WSGI worker before the browser-side 2-hour upload timeout expires.
- OMERO CLI dry-run scan timeouts are controlled by `OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS` (default example `7200`) instead of a short hardcoded deadline, so large `.zarr` compatibility/planning scans can finish in the background.
- Automatic detection and skipping of non-importable files is limited to operating-system and filesystem junk (for example `Thumbs.db`, `.DS_Store`, recycle-bin metadata); all other files are handed to OMERO/Bio-Formats unchanged.
- **Native Zarr routing and validation**: the plugin parses candidate `.zarr`
  stores with the upstream `ome-zarr` Python runtime first and only routes to
  the native branch when Bio-Formats reports the staged `.zarr` as
  incompatible and `ome-zarr` recognizes a layout that the installed
  `omero-cli-zarr` runtime can actually import. Today that means pure OME-NGFF
  image stores and `bioformats2raw.layout=3` image stores. Unsupported
  recognized layouts such as OME-Zarr plates, wells, sparse
  `bioformats2raw` series sets, or stores that the current render stack cannot
  address safely are rejected explicitly instead of being guessed from
  filenames or hand-parsed metadata.
- **Pinned native Zarr toolchain**: the `omeroweb` image installs
  `omero-cli-zarr`, `bioformats2raw`, and `ome-zarr` from explicit
  env-driven build args loaded from `env/omeroserver.env`
  (`OMERO_CLI_ZARR_VERSION`, `BIOFORMATS2RAW_VERSION`,
  `OME_ZARR_PY_VERSION`) so native Zarr behavior stays reproducible and
  upgrades remain deliberate. The tracked example env now pins `ome-zarr` to
  `0.15.0`. That upstream release deprecates legacy writer targets (`v01` to
  `v03`), but this repo uses `ome-zarr` only for detection and read-side
  inspection while the normalization write path stays repo-local, so the
  upgrade remains an environment/build decision rather than an in-code writer
  contract change.
- **Zarr pre-flight scan and routing persistence**: the Bio-Formats dry-run
  (`omero import -f`) is still used for all non-zarr imports and for `.zarr`
  compatibility planning. When that dry-run says the staged `.zarr` is
  compatible, the import stays on the standard Bio-Formats path. When it is
  incompatible but `ome-zarr` recognizes a supported image layout, the plugin
  persists that native-routing decision into the logical import unit so the
  background import worker does not need to rescan the same store before
  importing it.
- **Native OME-NGFF pass-through with ephemeral normalization**: supported
  native OME-Zarr layouts keep their logical image structure intact for
  `omero zarr import`; the plugin does not flatten multiscales or hardcode
  layout rewrites. The only mutations happen on the disposable server-readable
  copy used for managed-repository handoff: if the referenced image arrays are
  Blosc-compressed, the plugin rewrites those image-array chunks to gzip on
  that copy only, chunk-by-chunk, so the current OMERO render stack can
  generate thumbnails reliably without changing the user's staged source tree
  or touching non-image groups such as tables. Additionally, if the store's
  multiscale pyramid downsamples the z-axis between levels, which is common in
  EM volume converters, the normalization step regenerates pyramid levels with
  XY-only downsampling using ``local_mean``. That matches the approach used by
  ``ome-zarr-py``'s ``Scaler.local_mean`` and napari's dimension-aware
  multiscale level selection. This prevents blurry z-slices in 2D viewers like
  Vizarr that select resolution level based on XY viewport zoom. Full-resolution
  data (level 0) is never modified.
- **Zarr import naming reconciliation**: when importing a `.zarr` directory,
  the plugin always passes a stable logical name to OMERO CLI via `-n` so
  Bio-Formats does not fall back to an internal chunk coordinate. For
  NGFF-converter outputs and native OME-Zarr imports, the plugin then
  reconciles imported image names against the original source filename and
  OME-Zarr multiscale names when that metadata is available, instead of leaving
  generic series paths such as `0/0`.
- **Zarr managed-repository staging**: before `omero zarr import`, the plugin
  stages the directory into the standard OMERO managed repository at
  `${CONFIG_omero_managed_dir}` using the server-side
  `CONFIG_omero_fs_repo_path` template. The deployment contract requires
  `CONFIG_omero_managed_dir` to be an absolute path inside `${OMERO_DATA_DIR}`;
  relative values are rejected so staging cannot drift into the image
  filesystem. The staging step runs through an OMERO script on OMERO.server and
  is launched with an independent admin-backed helper session, so OMERO.web
  does not need direct write permission to the managed repository and Zarr
  imports land in the same repository namespace model as normal imports. The
  script reads OMERO's persisted server config (`omero.data.dir`,
  `omero.managed.dir`, `omero.fs.repo.path`) plus a bootstrap-written runtime
  state file under `OMERO.server/var/managed-zarr-runtime.env` for the
  env-derived shared temp root, instead of relying on hardcoded paths or
  browser session state. OMERO.web first creates a transient server-readable
  copy under `${OMERO_TMP_PATH}/omeroweb-import/managed-zarr-transfer`; upload
  and conversion stay in tmp/shared-transfer space, and the original `_staged/`
  upload tree remains private to `omero-web`. The managed repository is used
  only for the final persistent handoff immediately before `omero zarr import`.
  The OMERO.server helper renders the full configured repository template,
  creates or deletes only the rendered staging container and staged native-Zarr
  leaf through OMERO's managed-repository API instead of raw filesystem
  `mkdir` or `rmtree` calls, keeps the rendered template path traversal-only
  (`0711`), and keeps the staged `.zarr` tree service-readable (`0755`
  directories, `0644` files). That keeps the flow template-driven across old or
  custom repository layouts without giving `omero-web` direct write access or
  leaving behind unregistered managed-repository directories. If the helper
  encounters a rendered managed-repository path that already exists on disk but
  is missing from OMERO's repository metadata, it now fails fast with an
  explicit stale-registration error instead of letting the later `makeDir` call
  collapse into a generic repository exception.
- **Zarr helper startup retries**: if OMERO script processors are temporarily not ready, the managed-repository helper launch retries for `OMERO_WEB_UPLOAD_SCRIPT_START_TIMEOUT_SECONDS` with a sleep interval of `OMERO_WEB_UPLOAD_SCRIPT_START_RETRY_SECONDS` before the import is failed.
- **Native Zarr metadata finalization**: after `omero zarr import`, the plugin
  reopens each created Image through `externalInfo.lsid`, parses the source
  metadata with the installed `omero-cli-zarr` runtime, and persists canonical
  pixel sizes onto OMERO's `Pixels` object. This closes a real gap in the
  runtime's API-created image path, where renderable NGFF imports can still
  arrive without persisted `PhysicalSizeX/Y/Z`. The plugin also normalizes
  shorthand NGFF length units such as `nm` and `µm` before saving, because the
  installed runtime only resolves full OMERO enum names on that path.
- **Import success validation**: after every `omero import` or
  `omero zarr import` call, the plugin searches both stdout and stderr for
  imported OMERO object IDs (Image, Fileset, Plate, etc.), including
  `Created Image 123` style output from `omero zarr import`. For native Zarr
  imports it then verifies the created images against
  `Image.details.externalInfo.lsid` using the managed store path, exact match
  for pure NGFF image stores and path-prefix match for
  `bioformats2raw.layout` series imports, finalizes source-derived pixel
  metadata, and finally exercises thumbnail generation before reporting
  success.
- **Post-import web contract**: once a native store-backed image is imported successfully, OMERO.web access to the managed store is handled by `omero_web_zarr`. Raw NGFF routes remain available for validation, while browser-facing preview and Vizarr launch use the preview-safe endpoint contract so slice browsing does not accidentally traverse multiscale levels that downsample non-display axes.
- **Progress bar accuracy**: the orange import progress bar uses the higher of
  two signals, real `/proc/{pid}/io` monitoring and a time-based asymptotic
  estimate, and enforces a high-water mark so the bar never goes backwards: not
  on refresh, not when new files are added, not under any circumstance. On
  browser refresh, progress state is restored from localStorage and bars jump
  instantly to their previous position. The blue bar uses `Math.floor` and caps
  at 99% while any import is still active, only reaching 100% when all jobs
  have completed.
- Job lifecycle: start, upload, import, confirm, prune.
- Job status polling for progress tracking.
- SEM-EDX spectrum parsing (EMSA format) with matplotlib visualization and genetic algorithm label placement.
- **NGFF converter (bioformats2raw)**: a special import workflow that converts
  uploaded files to OME-NGFF (zarr) format using `bioformats2raw` before
  importing into OMERO. The UI exposes all `bioformats2raw` settings
  (compression, tile size, resolutions, downsampling, workers, nested paths,
  HCS mode, etc.) and supports save/load/restore for user-specific presets
  via the `database_plugin`. The conversion runs server-side after upload
  and before the OMERO import. The resulting `.zarr` outputs are imported
  through the standard import pipeline.
- File attachment support: link related files (spectra, metadata) to imported images.
- Automatic temp cleanup: immediate deletion after successful import; failed imports retain their staged payload and job status for deferred cleanup after `OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS` (default `172800`, 48 hours).
- User settings and special-method settings persistence in `database_plugin`.
- Project listing and root status checks.

## Host-side tmp cleaner (automatic)

Temporary artifacts live under `OMERO_TMP_PATH`.

Cleanup is performed by two mechanisms:

- **Immediate**: the upload payload directory for a job is deleted right after a successful import finishes (job JSON remains for UI status).
- **Sweep**: a host-side systemd timer (`omero-tmp-cleaner.timer`) runs periodically and deletes anything under `OMERO_TMP_PATH` older than 24 hours by default. The Import plugin writes deferred-cleanup markers for failed jobs so their payload directory and job JSON are retained for 48 hours unless `OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS` overrides that window.

The installer replaces the repo-managed tmp-cleaner service and timer on every
run before enabling the current units, including stale unit drop-ins and
`.wants`/`.requires` dependency links, so old or corrupt unit definitions do
not remain active after updates. Unit rendering is shared through
`scripts/omero-host-service-lib.sh`, while the installed
`/usr/local/sbin/omero-tmp-cleaner` runtime remains standalone. The cleaner
protects namespace directories at the temp root and their `tmp/` subdirectories
but still removes stale root-level files and symlinks when they exceed the
configured age. The timer schedules from activation as well as from the last
service run, so reinstalling or restarting the timer always leaves a future
cleanup trigger.

Useful commands (host):

- `systemctl status omero-tmp-cleaner.timer`
- `journalctl -u omero-tmp-cleaner.service`
- `sudo /usr/local/sbin/omero-tmp-cleaner --tmp-dir "$OMERO_TMP_PATH"`

## Key routes

| Route                                            | Method | Purpose                                                  |
| ------------------------------------------------ | ------ | -------------------------------------------------------- |
| `/omeroweb_import/`                              | GET    | Main upload page                                         |
| `/omeroweb_import/projects/`                     | GET    | List accessible projects                                 |
| `/omeroweb_import/root-status/`                  | GET    | Check if current user is OMERO root                      |
| `/omeroweb_import/help/`                         | GET    | Serve plugin help documentation (Markdown)               |
| `/omeroweb_import/start/`                        | POST   | Create a new upload session (job)                        |
| `/omeroweb_import/upload/<job_id>/`              | POST   | Transfer files to the job directory                      |
| `/omeroweb_import/import/<job_id>/`              | POST   | Trigger OMERO CLI import for uploaded files              |
| `/omeroweb_import/confirm/<job_id>/`             | POST   | Confirm import completion                                |
| `/omeroweb_import/prune/<job_id>/`               | POST   | Remove temporary upload files                            |
| `/omeroweb_import/status/<job_id>/`              | GET    | Poll job status                                          |
| `/omeroweb_import/user-settings/save/`           | POST   | Save user upload preferences                             |
| `/omeroweb_import/special-method-settings/save/` | POST   | Save special method settings (SEM-EDX, NGFF converter)   |
| `/omeroweb_import/special-method-settings/load/` | POST   | Load special method settings (SEM-EDX, NGFF converter)   |

## Typical user workflow

1. Open upload page at `/omeroweb_import/`.
2. Select target project and dataset (or select a special method from the dropdown).
3. Start upload session (creates job directory on tmpfs).
4. Transfer files to the job-specific upload endpoint.
5. Trigger import step (OMERO CLI `import` with batching).
6. For SEM-EDX data: spectrum files are parsed, visualized, and attached to imported images.
7. For NGFF converter: uploaded files are converted to OME-NGFF zarr via `bioformats2raw` before OMERO import.
8. Confirm import and monitor status until terminal state.
9. Prune temporary upload assets once processing is complete.

## External client workflow

The same job lifecycle can be driven by external clients such as
`XTOmeroConnector.py`:

1. `POST /omeroweb_import/start/` with `files`, `compatibility_enabled`, and
   `dataset_name_override`.
2. Stream each file to `/omeroweb_import/upload/<job_id>/` with the existing
   chunked upload fields (`relative_path`, `chunk_start`, `chunk_end`,
   `file_size`, `is_last_chunk`).
3. `POST /omeroweb_import/import/<job_id>/` to start the OMERO-side import.
4. Poll `/omeroweb_import/status/<job_id>/` until `status=done` or
   `status=awaiting_confirmation`.
5. If `confirmation_required=true`, `POST /omeroweb_import/confirm/<job_id>/`
   and continue polling.

When `dataset_name_override` is present and no `project_id` is supplied, the
job imports into OMERO root as a single Dataset with the override value as its
name.

## Code structure

```text
omeroweb_import/
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
│   └── import_management/workflow_service.py  # Upload workflow orchestration
├── constants.py                       # Upload batch size, paths, environment config
├── strings/errors.py                  # All error message functions
├── strings/messages.py                # All user-facing message functions
├── utils/file_helpers.py              # File path resolution, directory creation, sanitization
└── utils/omero_helpers.py             # Backward-compatible OMERO helper exports
```

## SEM-EDX processing

The Import plugin includes specialized support for SEM-EDX (Scanning Electron Microscopy - Energy Dispersive X-ray) data:

- Parses EMSA/MSA format spectrum files with metadata extraction.
- Generates matplotlib spectrum visualizations with element identification.
- Uses a genetic algorithm for optimal label placement on spectrum plots.
- Attaches generated spectrum images as OMERO file annotations on imported images.
- Configurable per-user via special method settings.

## Operational controls

Configuration values in `env/omeroweb.env`:

| Variable                                           | Purpose                                                                                                                                                                                                                 |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OMERO_WEB_UPLOAD_CONCURRENCY`                     | Maximum simultaneous upload jobs                                                                                                                                                                                        |
| `OMERO_WEB_UPLOAD_BATCH_FILES`                     | Default files processed per import batch                                                                                                                                                                                |
| `OMERO_WEB_WSGI_ARGS`                              | Gunicorn arguments for OMERO.web; include a long `--timeout` for slow upload requests (default example: `--timeout 7200`)                                                                                               |
| `OMERO_WEB_UPLOAD_CLI_KEEPALIVE_SECONDS`           | OMERO CLI keepalive interval for long-running imports (default `30`)                                                                                                                                                    |
| `OMERO_WEB_UPLOAD_LOCAL_SCAN_TIMEOUT_SECONDS`      | Timeout for OMERO CLI dry-run compatibility/grouping scans (default `7200`)                                                                                                                                             |
| `OMERO_WEB_UPLOAD_IMPORT_TIMEOUT_SECONDS`          | Per-import subprocess timeout in seconds (default `86400`)                                                                                                                                                              |
| `OMERO_WEB_UPLOAD_SCRIPT_START_TIMEOUT_SECONDS`    | Total retry window when the server-side Zarr helper reports `NoProcessorAvailable`                                                                                                                                      |
| `OMERO_WEB_UPLOAD_SCRIPT_START_RETRY_SECONDS`      | Sleep interval between managed-repository helper launch retries                                                                                                                                                         |
| `OMERO_WEB_UPLOAD_ALTERNATIVE_ZARR_IMPORT`         | Enable the alternative native zarr import method for Bio-Formats-incompatible `.zarr` files (default `false`). When `false`, only the standard Bio-Formats import path is used and incompatible zarr files are skipped. |
| `OMERO_WEB_UPLOAD_NATIVE_ZARR_GZIP_LEVEL`          | Gzip level used when the disposable native-import copy must rewrite Blosc-backed image arrays for render-safe import                                                                                                    |
| `OMERO_WEB_UPLOAD_FAILED_IMPORT_RETENTION_SECONDS` | Failed-job deferred cleanup window (default `172800`)                                                                                                                                                                   |

Upload data, job JSON, compatibility scan state, CLI home, and native-Zarr
transfer state are derived from `OMERO_TMP_PATH` through
`omero_plugin_common.tmp_utils.get_plugin_tmp_dir()`. The active Import plugin
subtree is `${OMERO_TMP_PATH}/omeroweb-import/`, with purpose-specific
subdirectories such as `data/`, `jobs/`, `compat-check/`, and
`managed-zarr-transfer/`. `OMERO_IMPORT_PATH` may still appear in installation
path templates and safety guards as the derived legacy path record, but it is
not a plugin override and should not be used to move Import plugin runtime
state independently from `OMERO_TMP_PATH`.

The import step runs OMERO CLI with `HOME` and `XDG_CACHE_HOME` set under the
resolved Import plugin upload root (`data/.omero-cli-home`) to guarantee
writable cache space for OMERO.java downloads in non-root containers.
The managed-repository helper launch also requires `ROOTPASS` from `env/omero_secrets.env`, because OMERO.web starts that helper through an independent OMERO CLI login instead of reusing any browser session.

Build-time native Zarr version pins live in `env/omeroserver.env` / `env/omeroserver_example.env`:

| Variable                 | Purpose                                                                           |
| ------------------------ | --------------------------------------------------------------------------------- |
| `OMERO_CLI_ZARR_VERSION` | `omero-cli-zarr` runtime version baked into the `omeroweb` image                  |
| `BIOFORMATS2RAW_VERSION` | `bioformats2raw` runtime version baked into the `omeroweb` image                  |
| `OME_ZARR_PY_VERSION`    | `ome-zarr` (`ome-zarr-py`) parser/runtime version baked into the `omeroweb` image |

Zarr managed-repository staging also depends on shared server-side configuration from `installation_paths.env` and `env/omeroserver.env`:

| Variable                    | Purpose                                                                 |
| --------------------------- | ----------------------------------------------------------------------- |
| `OMERO_DATA_DIR`            | In-container OMERO data root that contains the managed repository mount |
| `CONFIG_omero_managed_dir`  | Absolute managed-repository root path inside `OMERO_DATA_DIR`           |
| `CONFIG_omero_fs_repo_path` | OMERO-managed repository path template used for per-user staging        |

## Large-file behavior

- Small files continue to upload as normal multipart requests.
- Files larger than the browser-side request ceiling are sliced into bounded chunks before they are sent to `/omeroweb_import/upload/<job_id>/`.
- The upload endpoint validates chunk offsets and file sizes and returns JSON errors for server-side failures, avoiding raw HTML error pages in the UI when possible.
- The final upload request no longer performs grouped dry-run dataset planning inline; that work runs in the background import worker so large structured uploads do not die at the HTTP worker timeout boundary.
- Before the background import starts, the request path pre-creates any missing dataset targets from the persisted logical import-unit plan when available; this keeps background workers off the live browser session while preserving grouped/package routing across formats.
- If request-path dataset preparation is missed or races with grouped import planning, the background worker recreates the missing Dataset targets through an independent user-owned OMERO session. It does not reuse the browser session and it must not rely on `job-service.suConn()` to impersonate the user.
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
