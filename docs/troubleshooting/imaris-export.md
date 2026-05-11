# Troubleshooting Imaris Export

This guide is the primary incident playbook for Imaris export failures in this
repository. Use it before attempting speculative code changes.

## Quick Triage Matrix

| Symptom | Likely class of failure | First check |
| --- | --- | --- |
| Imaris login loops back to `/webclient/login/` after POST | OMERO.web auth/session handling bug in the standalone connector | Inspect [`XTOmeroConnector.py`](../../omero_imaris_connector/XTOmeroConnector.py) and verify the client is not overriding the `Cookie` header |
| Export job stays in `RUNNING` with `status=waiting_for_processor` | OMERO.server `Processor-0` missing, failed, or blocked | Run `omero admin diagnostics` in the server container |
| Export job starts but no file ever appears | OMERO CLI launch path or ImarisConvert failure | Launch `IMS_Export.py` directly with `omero script launch` |
| OMERO converter job fails and Blitz logs `Cannot read configuration: omero.ims.export.dir` | Processor script subprocess did not receive the trusted IMS export environment | Verify the running `omero/processor.py` allowlist contains `OMERO_IMS_EXPORT_DIR` and `CONFIG_omero_managed_dir` |
| Job fails immediately with script-not-found | Script registration/bootstrap problem | Check `omero script list` and bootstrap logs |
| Export succeeds but attachment/annotation fails | Group permissions issue during post-export attachment | Check script output and server logs for `ReadOnlyGroupSecurityViolation` |
| IMS export/download succeeds but the file does not open in the existing Imaris window | Windows-side XT runtime mismatch, missing live Imaris handle, or unverified file-open handoff | Confirm the final IMS handoff reports an exact current-file match or a visible loaded dataset; enable `IMARIS_OMERO_CONNECTOR_ENABLE_ICEPY=true` only when testing the optional IcePy bridge |
| Selected Image export downloads but Imaris shows only a transient scene object or no pixels | Selected-image export was submitted through the XT file-open bridge or the main Imaris executable instead of Imaris File Converter | The `Imaris` converter must submit the tracked OMERO.web OME-TIFF export to discovered `ImarisFileConverter.exe`, matching a manual drag/drop onto the Imaris icon |
| A `Volume` object appears in Imaris but the exported IMS is not visibly opened | File-open returned or changed scene state without proving the downloaded IMS became visible | Treat this as failed handoff; inspect log lines after `Using Imaris handle type=...` for current-file or visible-dataset verification |

## Failure History Captured Here

These failures occurred during real debugging on 2026-03-11 and 2026-05-11 and
should be treated as known incident patterns, not hypotheticals.

### 1. OMERO.web authentication regression

Observed behavior:

- login `POST` returned `200`,
- `sessionid` cookie was present,
- the final URL still redirected back to `/webclient/login/?url=%2Fwebclient%2F`.

Root cause:

- the standalone Imaris connector manually injected its own `Cookie` header,
- that bypassed normal cookie-jar behavior and dropped the authenticated Django
  session on the redirect back to `/webclient/`.

Fix:

- remove manual `Cookie` header injection from [`XTOmeroConnector.py`](../../omero_imaris_connector/XTOmeroConnector.py),
- keep normal session/cookie-jar handling,
- keep CSRF and referer handling intact.

### 2. `waiting_for_processor` while `Processor-0` was actually down

Observed behavior:

- login and API calls succeeded,
- export request started,
- status polling stayed on `waiting_for_processor`,
- worker logs showed `NoProcessorAvailable ... processorCount = 0`.

Root cause:

- `Processor-0` was not running,
- OMERO.server startup was hitting a temp-lock permission failure under the
  legacy OMERO temp namespace,
- stale temp directories were owned by `systemd-coredump`,
- `runProcessor.py` failed while creating its lock file.

Evidence:

- `omero admin diagnostics` showed the processor missing before the fix,
- `master.err` showed `PermissionError` from
  `omero.util.temp_files.TempFileManager()`,
- filesystem ownership under `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp/...`
  was wrong.

Fix:

- [`startup/10-server-bootstrap.sh`](../../startup/10-server-bootstrap.sh)
  now prepares a clean runtime temp slot under
  `${OMERO_TMP_PATH}/${OMERO_CLI_USER}/tmp/runtime*`,
- it exports `TMPDIR`, `OMERO_TMPDIR`, `OMERO_TEMPDIR`, `OMERO_USERDIR`,
  `OMERO_SESSIONDIR`, and the service-user identity variables,
- it repoints the legacy OMERO temp path to that clean runtime slot before
  OMERO CLI/bootstrap work runs.

### 3. `runScript()` reported `NoProcessorAvailable` even after `Processor-0` recovered

Observed behavior:

- `omero admin diagnostics` later showed `Processor-0 active`,
- `omero script params <script_id>` succeeded,
- `omero script launch <script_id> Image_ID=<id>` succeeded from both the
  server container and the `omeroweb` container with an image explicitly chosen
  for this diagnostic,
- the Celery worker code path using `ScriptService.runScript()` still reported
  `NoProcessorAvailable`.

Root cause:

- the callback/process-handle based `runScript()` path was brittle in this
  environment even when the export script itself was runnable,
- the OMERO CLI launch path from the `omeroweb` container was the only
  repeatedly validated execution path.

Fix:

- [`omero_imaris_connector/tasks.py`](../../omero_imaris_connector/tasks.py)
  now launches exports through `omero script launch` as the primary execution
  path,
- the previous `runScript()` fallback path is no longer used by the Celery
  worker.

### 4. Export succeeded but file attachment could still fail in a restricted group

Observed behavior:

- `IMS_Export.py` produced `Export_Path` and `Export_Name`,
- server logs also showed `ReadOnlyGroupSecurityViolation` when trying to attach
  the exported file as a file annotation.

Interpretation:

- conversion succeeded,
- the attachment step failed because of OMERO permissions in that group,
- download can still work if the plugin returns the generated export path.

This is not the same failure as `waiting_for_processor`.

### 5. CLI launch worked only when it used the requesting user's OMERO session

Observed behavior:

- the worker launched `omero script launch` immediately,
- the CLI completed,
- the script returned `Message=Image 4 not found` when the launch used the
  job-service OMERO session.

Root cause:

- the job-service session used by the worker did not have the same effective
  image visibility as the requesting user session for this export,
- the standalone connector was already passing the requesting user's OMERO
  session key into the task,
- the Import plugin now uses independent admin-created background sessions for
  OMERO CLI imports so it does not depend on the browser's live session.

Fix:

- prefer the requesting user's OMERO session key for `omero script launch`
  whenever one is available,
- fall back to the job-service session only if no user session key was provided.

### 6. IMS downloaded successfully but standalone XT still could not open it in the current Imaris session

Observed behavior:

- the standalone connector logged successful OMERO login, export, and IMS download,
- the XT log then showed `Imaris application handle is not available`,
- Windows-side logs also showed `Imaris XT bridge import failed ... IcePy ...`,
- when a direct executable fallback was temporarily enabled, it opened a new Imaris session instead of reusing the running one.

Root cause:

- opening an `.ims` file is native in Imaris,
- opening it in the already running Imaris session from the standalone XT connector requires a live XT handle,
- that handle depends on the official Imaris XT Python bridge,
- the affected Windows host was running the connector under Python `3.9.9`, while official Imaris XT support is restricted to Python `2.7` or `3.7`,
- the standalone connector must therefore avoid startup-time syntax and annotation
  constructs that exclude Python `3.7` or `3.9`, because those failures happen
  before the GUI or XT diagnostics can open.

Operational rule:

- the standalone connector requires Windows 10 or newer and checks this before
  setting the console title, collecting XT diagnostics, or opening Tk. If the
  running Windows version cannot be verified as Windows 10 or newer, startup
  stops and writes the reason to the command-line/log surface instead of
  opening the GUI.
- the standalone connector first tries to open the exported file through the live
  Imaris XT handle so the existing session is reused,
- IcePy-backed native bridge probing is disabled by default. When
  `IMARIS_OMERO_CONNECTOR_ENABLE_ICEPY` is unset or false, startup does not run
  standalone `IcePy` diagnostics, native bridge probing, alternate-Python
  discovery, or fresh-session bridge launch. Direct in-process `ImarisLib`
  access is used only when Imaris has already loaded that module into the XT
  Python process; the connector does not import Bitplane's native IcePy stack
  into an arbitrary Python process. If the direct handle is unavailable, the
  connector uses the bounded helper-runner path for the numeric XT application
  id before download/conversion and before the final file handoff. If the handle
  remains unavailable, the log reports only that the direct handle could not be
  resolved and suppresses disabled optional-bridge dependency details,
- when `IMARIS_OMERO_CONNECTOR_ENABLE_ICEPY` is explicitly set to `1`, `true`,
  `yes`, or `on`, native Imaris bridge compatibility is probed in the background
  as the dialog opens, and the connector must not start server-side conversion
  unless the final IMS can be opened through a native Imaris bridge path,
- when the optional IcePy bridge is enabled, stale native bridge probe results
  are revalidated before expensive server-side IMS exports, so a lost Imaris
  session handle fails before transferring large IMS files,
- the `OMERO` IMS path must not launch a second Imaris session, call
  `Imaris.exe` directly, or use the Windows file association as a fallback,
- if no live XT handle is available, fail explicitly and fix the local Imaris XT
  bridge/runtime path resolution,
- do not install extra Python packages on the Imaris workstation for this
  connector. It must remain a single-file, standard-library script and use only
  the Imaris XT bridge files that are already shipped with Imaris,
- if the optional IcePy bridge is enabled and the configured Python cannot load
  Imaris' native `IcePy`, the connector may use the Windows Python launcher to
  find another already-installed Python that can load the same native Imaris
  bridge and call the Imaris file-open API on the live Imaris application id.
  This is still same-session native opening; it is not a file association or
  `Imaris.exe` launch.
- the OMERO.web Host field accepts only a hostname or IP address. Operators
  must not include `http://`, `https://`, a path, query string, username, or
  port in Host; the `Use HTTPS` checkbox and Port field are the single source of
  truth for the connection scheme and port.
- OMERO.web login, project loading, converter capability probing, and folder
  export capability probing run off the Tk UI thread. The main connector window
  stays responsive while the status indicator is busy, and the final browser
  list, converter selector, folder-export button, autosave controls, and status
  text are updated together on the UI thread after the verified connection
  setup completes.
- after a successful OMERO.web login, the connector probes converter
  capabilities before enabling load actions. `OMERO` is shown first only when
  the current server exposes the connector IMS export capability endpoint with
  the current `omero_imaris_connector_v1` flag. Older or standard OMERO.web
  deployments that do not return the explicit capabilities JSON are treated as
  not OMERO-capable. `Imaris` remains independent of that custom endpoint and is
  shown when an installed `ImarisFileConverter.exe` is discoverable next to the
  cached or discovered `Imaris.exe`. The first startup records the discovered
  `Imaris.exe` path in `.imaris_omero_connector/settings.env` as `IMARIS_EXE`;
  later startups check that saved path first and avoid registry/vendor-directory
  scans when it still points to an existing executable. Converter detection does
  not run native IcePy bridge probing. For `OMERO`,
  the pre-download readiness check still verifies a live same-session IMS open
  path before server-side conversion starts. For `Imaris`, the pre-download
  readiness check verifies only that the installed Imaris File Converter can be
  discovered before requesting the standard selected Image export.
- OMERO-generated IMS handoff success is stricter than a successful
  `FileOpen`, `OpenFile`, or `LoadFile` method return. The connector accepts an
  IMS open only when Imaris reports the downloaded file as the exact current
  file, or when the call produces a loaded dataset with positive dimensions and
  that dataset is accepted by `SetDataSet` or `SetImage(0, ...)` for the current
  session. The dataset path covers Imaris APIs where current-file metadata is
  absent or does not update even though the loaded data can be made visible. A
  bare method return, a transient scene object, or a generic image-count change
  is not enough for IMS success. The `Imaris` converter does not download
  original/raw files; it submits only connector-tracked selected Image exports
  from the standard OMERO.web Image export endpoint to the discovered
  `ImarisFileConverter.exe`.
- the local path field is the source of truth for loading images into Imaris
  and for the first folder-export chooser location hint only. For
  `Load images into Imaris`, downloaded IMS files and selected Image exports are
  stored directly in the exact selected or typed local path; the connector must
  not create per-image random or `img_<id>` subfolders under that path.
  Filename collision handling may add a deterministic suffix to the file name
  only when a file with the same name already exists. The path-row `Select`
  button opens the native Tk directory chooser, replaces the typed value only
  when the operator confirms a folder, and immediately verifies that Imaris can
  write there.
  Cancelling preserves the typed value. Typed paths must be structurally valid
  absolute local paths and are write-checked when `Load images into Imaris` is
  clicked.
- `Export folder to OMERO` always opens the native Tk directory chooser before
  showing the `Confirm folder export` prompt. On the first export attempt in a
  connector session, a background-validated typed local path may be used as the
  chooser's initial directory. Later export attempts use the last folder the
  operator selected in the export chooser, even if the path field changes.
  Folder export still rejects filesystem roots, malformed paths, and missing
  directories before starting uploads.
- while connected, the XT connector runs silent periodic read-only OMERO.web
  health checks. A transient failure is retried before the UI is changed; if
  all retries fail, the connector reports that the connection was lost, clears
  OMERO browser state, disables OMERO actions, and returns to the connect-ready
  state. Silent health checks and native bridge probes must not force
  synchronous Tk idle redraws or leave a busy cursor on the main-window
  background after they complete.
- `Load images into Imaris` is enabled only after a verified OMERO connection,
  an available converter, a structurally valid local path that is not known to
  be unwritable, and at least one selected entry in the Images panel are all
  present.
- `Autosave settings`, `Show log`, and `Search function` are pre-read before
  the standalone XT dialog renders. `Autosave settings` remains disabled until
  the OMERO login succeeds. `Show log` defaults to enabled for new users, is
  immediately written when toggled, and controls whether normal command-window
  log output is shown on the next startup. `Search function` defaults to
  disabled for new users and is persisted immediately when toggled. When enabled
  it shows local search fields for Projects, Datasets, and Images, each filtering
  the already-loaded panel by case-insensitive partial text without issuing
  additional OMERO requests. The path-row `Append to observed folders` checkbox
  is visible but intentionally not connected to any runtime behavior until the
  observed-folder integration is implemented. After a verified connection, the
  connector writes `.imaris_omero_connector/settings.env` under
  the detected user home with only host, port, username, HTTPS state, local
  path, selected converter, autosave state, show-log state, search-function
  state, the cached `IMARIS_EXE` path when discovered, and the connector
  version. The version value is refreshed silently on
  every standalone XT startup from the same version value shown by the info
  dialog. If an existing `settings.env` has no matching current version, the
  connector archives it as `settings.env.old` and creates a fresh settings
  file; existing generated backups are rotated upward as `settings.env.old2`,
  `settings.env.old3`, and continuing numeric suffixes before the current file
  is archived. The migration operates only on the generated
  `.imaris_omero_connector/settings.env` path and refuses symlinks or
  non-regular settings and backup files. Converter changes are written
  immediately when autosave is enabled. Passwords are never written to this
  connector settings file, are not retained by the authenticated OMERO.web
  client after a login attempt, and the visible password field clears after a
  successful login. The password reveal button is UI-only, defaults to hidden,
  and re-hides after 30 seconds. Settings load, parse, create, migrate, or
  write failures are logged through the connector diagnostic logger without
  aborting the dialog.
- the standalone XT diagnostic log is `XTOmeroConnector.log` in the same
  `.imaris_omero_connector` directory as `settings.env`, or in that intended
  directory when the settings file does not exist yet. The connector does not
  write its normal diagnostics to the operating-system temp directory. Visible
  command-window messages, including startup blocks, fatal fallbacks,
  console-close prompts, and transfer progress, are mirrored to that same log
  file. When `Show log` is disabled, the command window is hidden on supported
  Windows launches while the file log continues to be written. Accidental
  command-window `Ctrl+C` or `Ctrl+Break` is ignored and logged while the XT
  dialog is active, then the previous console signal handlers are restored when
  the entrypoint exits. Logs roll at 3 MiB with three bounded backups.
- the connection-panel info button opens a small modal dialog with the connector
  version, author, and as-is disclaimer. The dialog blocks interaction with the
  main connector window until closed.
- `Imaris` is shown only when an installed `ImarisFileConverter.exe` can be
  discovered from the cached or discovered Imaris installation path. This mode
  downloads the standard OMERO.web export for the selected OMERO Image ID and
  submits that tracked export to `ImarisFileConverter.exe`, matching the
  observed manual drag/drop behavior without opening a new full Imaris window.
  It must not use the main `Imaris.exe` as a fallback, `ImarisLib.FileOpen`,
  `OpenFile`, `LoadFile`, Windows file associations, archived originals, or
  source-file parsers for this selected-image path.
- for selected Image exports, success means the operating system accepted the
  `ImarisFileConverter.exe` launch request with the connector-tracked OMERO.web
  export as the file argument. This is intentionally different from the IMS
  same-session-verification contract.
- when multiple images are selected, the connector must finish every selected
  Image export or server-side IMS export before handing the prepared files to
  Imaris. The `OMERO` path then opens IMS files through the same-session
  file-open API. The `Imaris` path submits all tracked selected Image exports
  to one discovered Imaris File Converter launch so the converter receives the
  selection as one batch.
- the standalone browser refresh action re-queries projects, datasets, and
  images without keeping stale image selections. If the selected dataset no
  longer exists, datasets remain visible for the selected project and images are
  cleared. If the selected project no longer exists, the project list remains
  visible and datasets/images are cleared.
- connector diagnostics must not print CSRF tokens, session cookie values,
  passwords, or local user-profile paths. The user-selected local path is the
  storage target for connector-initiated downloads. The lower-level download
  helpers use `OMERO_IMARIS_EXPORT_DIR`, or an operating-system temporary
  directory when no explicit directory is supplied by a caller outside the GUI.
  The HTTP download buffer is bounded for memory safety and can be tuned with
  `OMERO_IMARIS_DOWNLOAD_CHUNK_BYTES` without changing file-format behavior.

### 7. OMERO converter failed after private config lookup replaced env handoff

Observed behavior:

- the standalone connector authenticated successfully, detected the `OMERO`
  converter, and started an IMS export job,
- the job switched from `RUNNING` to `FAILED`,
- Blitz logs showed `SecurityViolation: Cannot read configuration:
  omero.ims.export.dir`,
- Processor logs showed scripts launching with the server virtualenv Python,
  not the configured `omero.scripts.python` wrapper.

Root cause:

- the export script originally worked because it read the IMS export directory
  from process environment,
- a later hardening change moved the primary lookup to the private OMERO config
  key `omero.ims.export.dir`,
- user script sessions cannot read that private config key,
- the first attempted fix set `omero.scripts.python` to a wrapper that exported
  `OMERO_IMS_EXPORT_DIR`, but OMERO Processor's `find_launcher()` still used
  the raw server virtualenv Python in this runtime,
- OMERO Processor also copies only an explicit environment allowlist into script
  subprocesses, so `OMERO_IMS_EXPORT_DIR` and `CONFIG_omero_managed_dir` were
  stripped before `IMS_Export.py` ran.

Fix:

- [`docker/patch_omero_processor_env.py`](../../docker/patch_omero_processor_env.py)
  patches the installed OMERO Processor environment allowlist during the server
  image build,
- the allowlist now passes only the trusted, non-secret path variables required
  by the IMS export script: `OMERO_IMS_EXPORT_DIR` and
  `CONFIG_omero_managed_dir`,
- `IMS_Export.py` reads those environment values first and keeps
  `omero.ims.export.dir` only as an admin-readable diagnostic fallback,
- there is no hard-coded export directory fallback.

Verification:

```bash
docker compose exec omeroserver bash -lc \
  'grep -n "OMERO_IMS_EXPORT_DIR\\|CONFIG_omero_managed_dir" \
  /opt/omero/server/venv-*/lib/python*/site-packages/omero/processor.py \
  /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py'
```

Then run the standalone connector with converter `OMERO` and watch
`Processor-0.log` and `Blitz-0.log`. Healthy jobs log `Successfully exported
IMS` and must not log `Cannot read configuration: omero.ims.export.dir` for
that job. If `Cannot read configuration: omero.managed.dir` appears during an
otherwise successful job, the Processor allowlist is still missing
`CONFIG_omero_managed_dir` or the server was not recreated from the rebuilt
image.

## Standard Diagnostic Flow

Follow these steps in order. Do not skip directly to code changes.

### 1. Confirm OMERO.web login is actually healthy

The connector must finish login on `/webclient/`, not loop back to the login
page.

Expected signs:

- login `POST` reaches `/webclient/`,
- subsequent `/api/v0/...` requests return `200`,
- the connector reports a live `sessionid`.

If login loops:

- inspect [`XTOmeroConnector.py`](../../omero_imaris_connector/XTOmeroConnector.py),
- verify the connector is not forcing its own `Cookie` header,
- verify CSRF token extraction and referer handling are still present.

### 2. Confirm Celery worker visibility and queue alignment

```bash
docker compose exec omeroweb env | rg -n "OMERO_IMS_CELERY_(QUEUE|BROKER|BACKEND)"
docker compose logs --since=10m omeroweb
docker compose exec omeroweb tail -n 200 /opt/omero/web/logs/imaris-celery.out.log
docker compose exec omeroweb tail -n 200 /opt/omero/web/logs/imaris-celery.err.log
```

Look for:

- worker startup failures,
- queue mismatch,
- import errors inside the worker,
- repeated task retries with no terminal state.

### 3. Run OMERO server diagnostics

This is the fastest way to determine whether the processor service exists at
all.

```bash
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero admin diagnostics
```

Expected signs:

- `Processor-0 active`,
- OMERO temp directory points at a writable runtime path,
- no obvious service-start failures.

If `Processor-0` is absent, disabled, or failed:

```bash
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero config get omero.scripts.processors
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero config get omero.server.nodedescriptors
docker compose exec omeroserver tail -n 200 /opt/omero/server/OMERO.server/var/log/master.err
```

### 4. Check temp-path ownership and lock-file failures

If server logs mention `PermissionError`, `.lock`, `TempFileManager`, or
processor startup failure, inspect the temp tree:

```bash
docker compose exec omeroserver bash -lc 'find "${OMERO_TMP_PATH:-/opt/omero/omero_temp}/omero-server/tmp" -maxdepth 4 -ls | head -n 200'
```

Red flags:

- old directories owned by `systemd-coredump`,
- unwritable temp roots,
- stale legacy temp directories still targeted by OMERO.

If you see this pattern, verify the runtime temp-slot logic in
[`startup/10-server-bootstrap.sh`](../../startup/10-server-bootstrap.sh).

### 5. Confirm script registration

```bash
docker compose exec -T omeroserver bash -s <<'SH'
set -euo pipefail
runtime_user="${OMERO_CLI_USER:?OMERO_CLI_USER is required}"
runtime_home="$(getent passwd "$runtime_user" | awk -F: '{print $6}')"
: "${runtime_home:?runtime home not found}"
: "${OMERO_TMPDIR:?OMERO_TMPDIR is required}"
omero_bin=""
for candidate in "${SERVER_HOME:-}"/bin/omero /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do
  if [ -x "$candidate" ]; then omero_bin="$candidate"; break; fi
done
[ -n "$omero_bin" ] || { echo "OMERO CLI not found" >&2; exit 1; }
run_omero_cli() {
  env HOME="$runtime_home" USER="$runtime_user" LOGNAME="$runtime_user" \
    LNAME="$runtime_user" USERNAME="$runtime_user" TMPDIR="$OMERO_TMPDIR" \
    OMERO_TMPDIR="$OMERO_TMPDIR" OMERO_TEMPDIR="$OMERO_TMPDIR" \
    OMERO_USERDIR="$OMERO_TMPDIR/userdir" \
    OMERO_SESSIONDIR="$OMERO_TMPDIR/userdir/sessions" \
    runuser -p -m -u "$runtime_user" -- "$omero_bin" "$@"
}
script_id="$(
  run_omero_cli script list | awk '/IMS_Export[.]py/ {print $1; exit}'
)"
: "${script_id:?IMS_Export.py is not registered}"
run_omero_cli script params "$script_id"
SH
docker compose exec -T omeroserver bash -s <<'SH'
set -euo pipefail
log_path="${SERVER_HOME:-/opt/omero/server/OMERO.server}/var/log/register-official-scripts.log"
if [ -f "$log_path" ]; then
  tail -n 200 "$log_path"
else
  printf 'registration log not present at discovered path\n' >&2
fi
SH
```

`IMS_Export.py` must appear in the script list. If it does not:

- inspect script registration during bootstrap,
- verify the script file exists in the server image,
- inspect registration logs before touching the worker code.

### 6. Prove the export script independently of the web worker

Direct script launch needs a real Image. In a blank installation, create a
disposable verification image first or skip this launch check; never guess a
numeric ID.

First from the server container:

```bash
export IMAGE_ID=<image-id-created-or-explicitly-chosen-for-this-diagnostic>
docker compose exec -e IMAGE_ID -T omeroserver bash -s <<'SH'
set -euo pipefail
runtime_user="${OMERO_CLI_USER:?OMERO_CLI_USER is required}"
runtime_home="$(getent passwd "$runtime_user" | awk -F: '{print $6}')"
: "${runtime_home:?runtime home not found}"
: "${IMAGE_ID:?IMAGE_ID is required}"
: "${OMERO_TMPDIR:?OMERO_TMPDIR is required}"
omero_bin=""
for candidate in "${SERVER_HOME:-}"/bin/omero /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do
  if [ -x "$candidate" ]; then omero_bin="$candidate"; break; fi
done
[ -n "$omero_bin" ] || { echo "OMERO CLI not found" >&2; exit 1; }
run_omero_cli() {
  env HOME="$runtime_home" USER="$runtime_user" LOGNAME="$runtime_user" \
    LNAME="$runtime_user" USERNAME="$runtime_user" TMPDIR="$OMERO_TMPDIR" \
    OMERO_TMPDIR="$OMERO_TMPDIR" OMERO_TEMPDIR="$OMERO_TMPDIR" \
    OMERO_USERDIR="$OMERO_TMPDIR/userdir" \
    OMERO_SESSIONDIR="$OMERO_TMPDIR/userdir/sessions" \
    runuser -p -m -u "$runtime_user" -- "$omero_bin" "$@"
}
script_id="$(
  run_omero_cli script list | awk '/IMS_Export[.]py/ {print $1; exit}'
)"
: "${script_id:?IMS_Export.py is not registered}"
run_omero_cli script launch "$script_id" Image_ID="$IMAGE_ID"
SH
```

Then from the `omeroweb` container as the runtime user:

```bash
export SCRIPT_ID=<script-id-discovered-above>
export IMAGE_ID=<image-id-created-or-explicitly-chosen-for-this-diagnostic>
docker compose exec -e SCRIPT_ID -e IMAGE_ID -T omeroweb bash -s <<'SH'
set -euo pipefail
runtime_user="${OMERO_WEB_RUNTIME_USER:-${OMERO_WEB_RUN_USER:-omero-web}}"
runtime_home="$(getent passwd "$runtime_user" | awk -F: '{print $6}')"
: "${runtime_home:?runtime home not found}"
: "${SCRIPT_ID:?SCRIPT_ID is required}"
: "${IMAGE_ID:?IMAGE_ID is required}"
: "${OMEROHOST:?OMEROHOST is required}"
: "${OMERO_PORT:?OMERO_PORT is required}"
: "${ROOTPASS:?ROOTPASS is required}"
omero_bin=""
: "${OMERO_WEB_ROOT:?OMERO_WEB_ROOT is required}"
if [ -n "${OMERO_WEB_VENV:-}" ]; then
  case "$OMERO_WEB_VENV" in
    /*) candidate_roots="$OMERO_WEB_VENV" ;;
    *) candidate_roots="${OMERO_WEB_ROOT}/${OMERO_WEB_VENV}" ;;
  esac
else
  candidate_roots=""
fi
for root in $candidate_roots "$OMERO_WEB_ROOT"/venv*; do
  candidate="$root/bin/omero"
  if [ -x "$candidate" ]; then omero_bin="$candidate"; break; fi
done
[ -n "$omero_bin" ] || { echo "OMERO CLI not found" >&2; exit 1; }
cli_tmp="$(mktemp -d)"
trap 'rm -rf "$cli_tmp"' EXIT
env HOME="$runtime_home" USER="$runtime_user" LOGNAME="$runtime_user" \
  LNAME="$runtime_user" USERNAME="$runtime_user" OMERO_USERDIR="$cli_tmp" \
  OMERO_SESSIONDIR="$cli_tmp/sessions" OMERO_TMPDIR="$cli_tmp/tmp" \
  TMPDIR="$cli_tmp/tmp" OMERO_PASSWORD="$ROOTPASS" \
  runuser -p -m -u "$runtime_user" -- "$omero_bin" -s "$OMEROHOST" \
    -p "$OMERO_PORT" -u root script launch "$SCRIPT_ID" Image_ID="$IMAGE_ID"
SH
```

Interpretation:

- if both fail, the server-side export path is broken,
- if both succeed but the web worker still hangs, the worker execution path is
  wrong,
- if only the server container succeeds, the `omeroweb` container runtime is
  missing something.

### 7. Inspect container package inventory when a stripped image is suspected

Use the helper script instead of guessing:

```bash
bash /opt/omero/helper_scripts_debian/docker_image_analysis.sh omeroserver:custom
bash /opt/omero/helper_scripts_debian/docker_image_analysis.sh omeroweb:custom
```

This script is the first-line package/version audit for container-build
problems. Use it to confirm:

- expected Python virtual environments exist,
- `omero-py`, `omero-metadata`, Java, HDF5, and Imaris-related dependencies are
  present,
- the image was not silently flattened or stripped in a way that removed needed
  runtime components.

### 8. Re-run the end-to-end connector workflow

After server-side checks pass:

1. log in through the standalone connector,
2. browse projects, datasets, and images, or confirm the empty-state behavior
   before creating disposable test data,
3. trigger an export,
4. poll until finished,
5. download the resulting file,
6. verify the output is actually an `.ims` file.

If this path still fails while direct CLI export works, the problem is in the
worker or connector glue code, not in the server-side export toolchain.

### 9. Compare session selection with the Import plugin

For OMERO CLI work, the Import plugin is the reference pattern:

- user-initiated OMERO CLI operations use the requesting user's OMERO session
  key,
- long-lived follow-up OMERO API work can use a separate job-service
  connection,
- do not substitute OMERO.web cookies for an OMERO session key,
- do not assume the job-service session sees exactly the same objects as the
  requesting user session.

## Known Good Signals

These indicate the system is healthy enough for export:

- connector login reaches `/webclient/`,
- `/api/v0/...` requests return `200`,
- Celery worker is running in `omeroweb`,
- `omero admin diagnostics` shows `Processor-0 active`,
- `omero script list` includes `IMS_Export.py`,
- `omero script launch ... Image_ID=<id>` succeeds in both `omeroserver` and
  `omeroweb` for an image created or explicitly selected for this diagnostic,
- the export returns `Export_Path` and `Export_Name`.

## Recovery Actions

1. Fix OMERO.web authentication first if login is looping.
2. Fix OMERO temp-path ownership and runtime temp-slot selection if
   `Processor-0` is down.
3. Restart OMERO.server after temp-path corrections.
4. Recheck `omero admin diagnostics` until `Processor-0 active` is present.
5. Validate `IMS_Export.py` directly with `omero script launch`.
6. Validate package inventory with
   `helper_scripts_debian/docker_image_analysis.sh` if the image contents are in
   doubt.
7. Re-run the standalone connector export end-to-end.

## What Not To Do

- Do not hard-code ports, hosts, credentials, or export paths.
- Do not assume `waiting_for_processor` means the script itself is broken.
- Do not assume the `omeroweb` container has the same working runtime as the
  server container without testing both.
- Do not change security settings just to make the export run.
- Do not remove CSRF or session protections from the connector to work around
  login issues.
