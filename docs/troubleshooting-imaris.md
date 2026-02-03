# Imaris Connector: Script Processor Troubleshooting

This guide focuses on diagnosing repeated `NoProcessorAvailable` retries and
`SecurityViolation: Cannot read configuration: omero.scripts.processors` errors.

## Symptoms

You may see:

- Repeated retries in `omeroweb` logs: `No OMERO script processor slot available`.
- `SecurityViolation: Cannot read configuration: omero.scripts.processors`.
- `omero.NoProcessorAvailable` in `Blitz-0.log`.
- Celery job polling stuck in `STARTED` with repeated log lines like
  `Polling Celery job ... state=STARTED`.

## Root causes to check

1. **Script processors not running**: OMERO.server requires script processors to
   execute scripts. If none are running, every script start will fail.
2. **Processor count set to 0**: `omero.scripts.processors=0` disables processors.
3. **Non-admin session**: The configuration value is restricted to admin sessions,
   so non-admin users receive `SecurityViolation` when trying to read it.
4. **Leaked ScriptProcess handles**: If clients never detach script handles, slots
   can be exhausted.
5. **Celery worker/queue mismatch**: IMS export uses a Celery task. If no worker is
   consuming the configured queue, jobs will remain in `STARTED`/`RECEIVED` and
   never complete.
6. **Missing Processor service in node descriptors**: If `Processor-0` is not
   listed in `omero.server.nodedescriptors`, script processes will not start.

## Diagnostic commands (Docker Compose)

> Replace `<compose>` with your compose binary (`docker compose` or `docker-compose`).

### 1) Confirm processor configuration (admin-only)

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config get omero.scripts.processors
```

Expected: a positive integer (>= 1). If `0`, set a value and restart:

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config set omero.scripts.processors 2
<compose> restart omeroserver
```

### 2) Check that script processors are running

```bash
<compose> exec omeroserver ps -ef | rg -i "omero.*script"
```

If no script processes are listed, ensure the server starts them (and that
`omero.scripts.processors` is not zero).

### 3) Verify script list availability (admin account)

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero script list
```

### 4) Inspect recent server/web logs

```bash
<compose> logs --since=10m omeroserver
<compose> logs --since=10m omeroweb
```

### 5) Verify the Processor service is enabled (node descriptors)

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config get omero.server.nodedescriptors
```

Expected: the descriptor includes `Processor-0` (or more). If missing, set it and
restart:

```bash
<compose> exec omeroserver \
  /opt/omero/server/OMERO.server/bin/omero config set omero.server.nodedescriptors \
  "master:Blitz-0,Tables-0,Indexer-0,PixelData-0,DropBox,MonitorServer,FileServer,Processor-0"
<compose> restart omeroserver
```

### 6) Check Celery worker health and queue configuration

Confirm that a Celery worker is running and listening to the same queue as
OMERO.web (default: `imaris_export`):

```bash
<compose> exec omeroweb env | rg -n "OMERO_IMS_CELERY_(QUEUE|BROKER|BACKEND)"
<compose> exec omeroweb python - <<'PY'
import os
print("OMERO_IMS_CELERY_QUEUE=", os.environ.get("OMERO_IMS_CELERY_QUEUE"))
print("OMERO_IMS_CELERY_BROKER_URL=", os.environ.get("OMERO_IMS_CELERY_BROKER_URL"))
print("OMERO_IMS_CELERY_BACKEND_URL=", os.environ.get("OMERO_IMS_CELERY_BACKEND_URL"))
PY
```

Then check the worker container and logs:

```bash
<compose> ps
<compose> logs --since=10m omero-celery-worker
```

If the worker is missing or is listening to a different queue, align
`OMERO_IMS_CELERY_QUEUE` across both OMERO.web and the Celery worker and restart
the services.

## Notes

- `SecurityViolation: Cannot read configuration: omero.scripts.processors` does
  **not** necessarily indicate a missing configuration; it can mean the session
  lacks admin privileges to read server configuration.
- If you are using a non-admin account in Imaris, configuration access will be
  denied even though script execution may still be possible once processors are
  running.
- Repeated `Unregistered servant: ProcessorCallback/...` messages in
  `Blitz-0.log` are expected when ScriptProcess handles are detached or cleaned
  up after starting scripts. These are cleanup logs and not a failure by
  themselves.
- If Celery jobs remain in `STARTED` but OMERO.server shows repeated
  `NoProcessorAvailable`, focus on script processor capacity first: without
  processors, the Celery task cannot start the export script and will continue
  to report `STARTED` while retrying.
- IMS export tasks use the job-service account by default. If you disable this
  by setting `OMERO_IMS_USE_JOB_SERVICE_SESSION=false`, ensure the end-user
  session is valid and has access to the target data.
