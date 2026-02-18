# Imaris Connector Plugin Guide (`omeroweb_imaris_connector`)

## Purpose

This plugin provides OMERO image export to Imaris-compatible (.ims) format through a web endpoint backed by asynchronous Celery execution. It supports both synchronous and asynchronous request modes.

## Main capabilities

- Request-based export for a target OMERO image by ID.
- Asynchronous job mode with status polling URL (`job_id` + `status_url`).
- Synchronous wait mode with configurable timeout.
- Export artifact download response.
- OMERO script processor availability detection with retry and backoff.
- Fast-fail when script processors are explicitly disabled (`omero.scripts.processors=0`).
- Job-service account support for background execution without user session dependency.
- Optional OMERO connection overrides (host, port, secure) for advanced routing.

## Key route

| Route | Method | Purpose |
|---|---|---|
| `/imaris-export/` | GET/POST | Start export, poll status, or download result |

## Request modes

- **Async mode** (`async=true`): returns `job_id` and `status_url` immediately. Client polls the status URL until completion, then retrieves the download.
- **Sync mode** (default): blocks until the export completes (up to `OMERO_IMS_EXPORT_TIMEOUT` seconds) and returns the result directly. Returns timeout/failure status if the export does not complete in time.

## Architecture

```
Client request
    │
    ▼
omeroweb_imaris_connector/views.py   (HTTP endpoint)
    │
    ▼
omeroweb_imaris_connector/tasks.py   (Celery task: run_ims_export_task)
    │
    ├─► _open_session_connection()    (join user's OMERO session)
    │   or _open_job_service_connection() (dedicated service account)
    │
    ├─► _find_script_id()            (locate IMS_Export.py in OMERO script service)
    │
    ├─► _run_script()                (execute with retry on NoProcessorAvailable)
    │
    └─► _wait_for_process()          (poll until completion, detach process handle)
```

The Celery worker runs inside the `omeroweb` container, managed by supervisord alongside OMERO.web.

## Required runtime dependencies

- Redis broker/backend available and healthy.
- Celery worker running and consuming the configured queue (`OMERO_IMS_CELERY_QUEUE`).
- OMERO script `IMS_Export.py` registered in the OMERO script service (done by `startup/10-server-bootstrap.sh`).
- Valid OMERO session context for the requesting user, or job-service account configured.
- ImarisConvertBioformats installed on OMERO.server (done by `startup/51-install-imarisconvert.sh`).

## Environment variables

Defined in `env/omero-celery.env`:

| Variable | Purpose | Example |
|---|---|---|
| `OMERO_IMS_USE_CELERY` | Enable Celery-backed exports | `true` |
| `OMERO_IMS_USE_JOB_SERVICE_SESSION` | Use job-service account instead of user session | `false` |
| `OMERO_IMS_CELERY_BROKER_URL` | Redis broker URL | `redis://redis:6379/2` |
| `OMERO_IMS_CELERY_BACKEND_URL` | Redis result backend URL | `redis://redis:6379/2` |
| `OMERO_IMS_CELERY_QUEUE` | Queue name (must match producer and worker) | `imaris_export` |
| `OMERO_IMS_CELERY_RESULT_EXPIRES` | Result expiry in seconds | `7200` |
| `OMERO_IMS_CELERY_TIME_LIMIT` | Task time limit in seconds | `7200` |
| `OMERO_IMS_CELERY_MAX_RETRIES` | Broker connection retry count | `20` |
| `OMERO_IMS_CELERY_PREFETCH` | Worker prefetch multiplier | `1` |
| `OMERO_IMS_EXPORT_TIMEOUT` | Sync mode timeout in seconds | `3600` |
| `OMERO_IMS_EXPORT_POLL_INTERVAL` | Status poll interval in seconds | `2.0` |
| `OMERO_IMS_SCRIPT_NAME` | Export script name | `IMS_Export.py` |
| `OMERO_IMS_SCRIPT_START_TIMEOUT` | Timeout for finding a free processor | `180` |
| `OMERO_IMS_SCRIPT_START_RETRY_INTERVAL` | Retry interval for processor search | `5` |

Job-service account variables (in `env/omero-celery.env` or `env/omeroserver.env`):
- `OMERO_WEB_JOB_SERVICE_USERNAME` / `OMERO_JOB_SERVICE_USERNAME`
- `OMERO_WEB_JOB_SERVICE_PASS` / `OMERO_JOB_SERVICE_PASS`

## Operator checklist

- Confirm Celery worker process health: `docker compose logs omeroweb | grep celery`
- Confirm queue name consistency across producer (`env/omero-celery.env`) and consumer (`startup/40-start-imaris-celery-worker.sh`).
- Confirm script availability: `docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero script list`
- Confirm script processor count is >0: `docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero config get omero.scripts.processors`
- Validate end-to-end export and download from a sample image.
- If using job-service mode, verify the job-service account exists in OMERO and credentials are correct.
- See `docs/troubleshooting/imaris-export.md` for diagnostic procedures.
