# Troubleshooting Imaris Export

This guide is the primary incident playbook for Imaris export failures in this
repository. Use it before attempting speculative code changes.

## Quick Triage Matrix

| Symptom | Likely class of failure | First check |
| --- | --- | --- |
| Imaris login loops back to `/webclient/login/` after POST | OMERO.web auth/session handling bug in the standalone connector | Inspect [`XTOmeroConnector.py`](../../XTOmeroConnector.py) and verify the client is not overriding the `Cookie` header |
| Export job stays in `RUNNING` with `status=waiting_for_processor` | OMERO.server `Processor-0` missing, failed, or blocked | Run `omero admin diagnostics` in the server container |
| Export job starts but no file ever appears | OMERO CLI launch path or ImarisConvert failure | Launch `IMS_Export.py` directly with `omero script launch` |
| Job fails immediately with script-not-found | Script registration/bootstrap problem | Check `omero script list` and bootstrap logs |
| Export succeeds but attachment/annotation fails | Group permissions issue during post-export attachment | Check script output and server logs for `ReadOnlyGroupSecurityViolation` |
| Export/download succeeds but the file does not open in the existing Imaris window | Windows-side XT runtime mismatch; no live Imaris handle was provided back to the standalone connector | Check the XT log for Python version and `ImarisLib` / `IcePy` import failures |

## Failure History Captured Here

These failures all occurred during real debugging on 2026-03-11 and should be
treated as known incident patterns, not hypotheticals.

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

- remove manual `Cookie` header injection from [`XTOmeroConnector.py`](../../XTOmeroConnector.py),
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
- it exports `TMPDIR`, `OMERO_TMPDIR`, and `OMERO_TEMPDIR`,
- it repoints the legacy OMERO temp path to that clean runtime slot before
  OMERO CLI/bootstrap work runs.

### 3. `runScript()` reported `NoProcessorAvailable` even after `Processor-0` recovered

Observed behavior:

- `omero admin diagnostics` later showed `Processor-0 active`,
- `omero script params <script_id>` succeeded,
- `omero script launch <script_id> Image_ID=<id>` succeeded from both the
  server container and the `omeroweb` container,
- the Celery worker code path using `ScriptService.runScript()` still reported
  `NoProcessorAvailable`.

Root cause:

- the callback/process-handle based `runScript()` path was brittle in this
  environment even when the export script itself was runnable,
- the OMERO CLI launch path from the `omeroweb` container was the only
  repeatedly validated execution path.

Fix:

- [`omeroweb_imaris_connector/tasks.py`](../../omeroweb_imaris_connector/tasks.py)
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

- the standalone connector first tries to open the exported file through the live
  Imaris XT handle so the existing session is reused,
- the standalone connector must not launch a second Imaris session, call
  `Imaris.exe` directly, or use the Windows file association as a fallback,
- if no live XT handle is available, fail explicitly and fix the local Imaris XT
  bridge/runtime path resolution,
- do not install extra Python packages on the Imaris workstation for this
  connector. It must remain a single-file, standard-library script and use only
  the Imaris XT bridge files that are already shipped with Imaris.

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

- inspect [`XTOmeroConnector.py`](../../XTOmeroConnector.py),
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
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero script list
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero script params 1301
docker compose exec omeroserver tail -n 200 /opt/omero/server/OMERO.server/var/log/register-official-scripts.log
```

`IMS_Export.py` must appear in the script list. If it does not:

- inspect script registration during bootstrap,
- verify the script file exists in the server image,
- inspect registration logs before touching the worker code.

### 6. Prove the export script independently of the web worker

First from the server container:

```bash
docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero script launch 1301 Image_ID=4
```

Then from the `omeroweb` container as the runtime user:

```bash
docker compose exec omeroweb bash -lc 'runuser -u omero-web -- env HOME=/opt/omero/web/OMERO.web/var OMERO_USERDIR=/tmp/omero-cli OMERO_SESSIONDIR=/tmp/omero-cli/sessions OMERO_TMPDIR=/tmp/omero-cli/tmp /opt/omero/web/venv-3.12/bin/omero -s omeroserver -p 4064 -u root -w "$ROOTPASS" script launch 1301 Image_ID=4'
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
2. browse projects, datasets, and images,
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
  `omeroweb`,
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
