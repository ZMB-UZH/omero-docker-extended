# Imaris Connector Plugin Guide (`omero_imaris_connector`)

## Purpose

This plugin provides OMERO image export to Imaris-compatible (.ims) format through a web endpoint backed by asynchronous Celery execution. It supports both synchronous and asynchronous request modes.

## Main capabilities

- Request-based export for a target OMERO image by ID.
- Asynchronous job mode with status polling URL (`job_id` + `status_url`).
- Synchronous wait mode with configurable timeout.
- Export artifact download response.
- OMERO ScriptService-based IMS export launch from the `omeroweb` container.
- Background exports prefer the requesting user's OMERO session connection and
  fall back to the job-service connection only when no user session is available.
- Direct validation path with `omero script launch` for incident debugging.
- Job-service account fallback for background execution when no user session
  is available.
- Optional OMERO connection overrides (host, port, secure) for advanced routing.

## Key route

| Route             | Method   | Purpose                                       |
| ----------------- | -------- | --------------------------------------------- |
| `/imaris-export/` | GET/POST | Start export, poll status, or download result |

## Request modes

- **Async mode** (`async=true`): returns `job_id` and `status_url` immediately. Client polls the status URL until completion, then retrieves the download.
- **Sync mode** (default): blocks until the export completes (up to `OMERO_IMS_EXPORT_TIMEOUT` seconds) and returns the result directly. Returns timeout/failure status if the export does not complete in time.

## Architecture

```text
Client request
    |
    v
omero_imaris_connector/views.py   (HTTP endpoint)
    |
    v
omero_imaris_connector/tasks.py   (Celery task: IMS or OME-TIFF export)
    |
    +--> _open_session_connection()    (join user's OMERO session)
    |    or _open_job_service_connection() (dedicated service account)
    |
    +--> IMS path: _find_script_id() and _run_script_via_omero_api()
    |
    +--> Imaris path: stage OME-TIFF under
        ${OMERO_TMP_PATH}/omero-imaris-connector/ome-tiff-source
```

The Celery worker runs inside the `omeroweb` container, managed by supervisord alongside OMERO.web.
IMS exports run through OMERO ScriptService on the already-established gateway
connection, so requester session keys are not passed through subprocess
arguments. Manual OMERO CLI diagnostics must still run as the OMERO.web runtime
user, not as root.
Requester-session background tasks detach on cleanup so the OMERO.web browser
session remains valid. Job-service tasks own their session and may hard-close it.

## Required runtime dependencies

- Redis broker/backend available and healthy.
- Celery worker running and consuming the configured queue (`OMERO_IMS_CELERY_QUEUE`).
- OMERO script `IMS_Export.py` registered in the OMERO script service (done by `startup/10-server-bootstrap.sh`).
- Valid OMERO session context for the requesting user, or job-service account configured.
- ImarisConvertBioformats installed on OMERO.server during the `omeroserver`
  image build. `startup/51-install-imarisconvert.sh` verifies the build artifact
  at container start.
- Bio-Formats JAR is downloaded and provisioned automatically at image build
  time by `startup/51-install-imarisconvert.sh` from OME Artifactory's
  versioned Maven artifact for `ome/bioformats_package`, verified against the
  repository-pinned `BIOFORMATS_SHA256` and the published `.sha256` checksum,
  and installed at
  `/opt/omero/imarisconvert/bioformats/bioformats_package.jar`. The same script
  also maintains an internal local repair copy at
  `/opt/omero/imarisconvert/artifacts/bioformats/bioformats_package.jar`;
  `IMS_Export.py` can restore from that copy but refuses ad-hoc runtime network
  download for security. The Bio-Formats version is controlled exclusively by
  `BIOFORMATS_VERSION` in `env/omeroserver.env`, and the accepted artifact is
  controlled by `BIOFORMATS_SHA256` in the same file.

## Environment variables

Defined in `env/omero-celery.env`:

| Variable                              | Purpose                                         | Example                |
| ------------------------------------- | ----------------------------------------------- | ---------------------- |
| `OMERO_IMS_USE_CELERY`                | Enable Celery-backed exports                    | `true`                 |
| `OMERO_IMS_USE_JOB_SERVICE_SESSION`   | Use job-service account instead of user session | `false`                |
| `OMERO_IMS_CELERY_BROKER_URL`         | Redis broker URL                                | `redis://redis:6379/2` |
| `OMERO_IMS_CELERY_BACKEND_URL`        | Redis result backend URL                        | `redis://redis:6379/2` |
| `OMERO_IMS_CELERY_QUEUE`              | Queue name (must match producer and worker)     | `imaris_export`        |
| `OMERO_IMS_CELERY_RESULT_EXPIRES`     | Result expiry in seconds                        | `7200`                 |
| `OMERO_IMS_CELERY_TIME_LIMIT`         | Task time limit in seconds                      | `7200`                 |
| `OMERO_IMS_CELERY_WORKER_CONCURRENCY` | Concurrent Imaris export workers                | `4`                    |
| `OMERO_IMS_CELERY_MAX_RETRIES`        | Broker connection retry count                   | `20`                   |
| `OMERO_IMS_CELERY_PREFETCH`           | Worker prefetch multiplier                      | `1`                    |
| `OMERO_IMS_EXPORT_TIMEOUT`            | Sync mode timeout in seconds                    | `3600`                 |
| `OMERO_IMS_EXPORT_POLL_INTERVAL`      | Status poll interval in seconds                 | `2.0`                  |
| `OMERO_IMS_SCRIPT_NAME`               | Export script name                              | `IMS_Export.py`        |

Defined in `env/omeroserver.env`:

| Variable               | Purpose                                                  | Example                                                            |
| ---------------------- | -------------------------------------------------------- | ------------------------------------------------------------------ |
| `BIOFORMATS_VERSION`   | Bio-Formats release version for `bioformats_package.jar` | `8.5.0`                                                            |
| `BIOFORMATS_SHA256`    | SHA-256 digest required for the Bio-Formats JAR          | `978093f2a4d0034f9581b19a5acd5a53c56d7b04b703865cd533aa953c92b1c2` |
| `OMERO_IMS_EXPORT_DIR` | IMS export output directory                              | `/OMERO/ImarisExports`                                             |

`OMERO_IMS_EXPORT_DIR` is required at runtime. OMERO Processor launches script
subprocesses from an explicit environment allowlist, so the server image patches
that allowlist to pass the trusted, non-secret path variables used by the IMS
export script: `OMERO_IMS_EXPORT_DIR` and `CONFIG_omero_managed_dir`. Startup
also installs a trusted `omero.scripts.python` wrapper and persists
`omero.ims.export.dir` as an admin-readable diagnostic fallback, but the normal
export path must not depend on a private OMERO config lookup from a user script
session. Startup validates `OMERO_IMS_EXPORT_DIR`, ensures the directory is
service-user writable, and writes that OMERO config key before the server
starts. Missing or invalid configuration fails fast instead of silently writing
IMS files to a hard-coded fallback directory.

The OMERO.web Celery task launches IMS exports through OMERO ScriptService.
Manual diagnostics can still resolve the `omero` CLI from explicit overrides
(`OMERO_WEB_OMERO_BIN`, then `OMERO_BIN`), then from the configured
`OMERO_WEB_ROOT`/`OMERO_WEB_VENV` contract and the newest versioned virtualenv
under `OMERO_WEB_ROOT`, and only then from `PATH`. This keeps updates across
versioned OMERO.web virtualenv names installation-agnostic.

Job-service account variables (in `env/omero-celery.env` or `env/omeroserver.env`):

- `OMERO_WEB_JOB_SERVICE_USERNAME` / `OMERO_JOB_SERVICE_USERNAME`
- `OMERO_WEB_JOB_SERVICE_PASS` / `OMERO_JOB_SERVICE_PASS`

Local XT connector environment variables (read by
`omero_imaris_connector/XTOmeroConnector.py` in the client-side Imaris process):

| Variable | Purpose |
| --- | --- |
| `IMARIS_EXE` | Optional exact `Imaris.exe` candidate checked after saved connector settings |
| `IMARIS_HOME` | Optional Imaris installation directory containing `Imaris.exe` |
| `OMERO_WEB_HOST` / `OMERO_HOST` / `OMEROHOST` | Default host shown in the connector login dialog |
| `OMERO_WEB_PORT` / `OMERO_WEB_PUBLIC_PORT` / `OMERO_PORT` | Default port shown in the connector login dialog |
| `OMERO_USER` / `OMERO_USERNAME` | Default username shown in the connector login dialog |
| `OMERO_IMARIS_EXPORT_DIR` | Optional non-GUI download/export staging directory; the GUI selected local path remains authoritative |
| `OMERO_IMARIS_DOWNLOAD_CHUNK_BYTES` | Bounded HTTP download buffer size, default `8388608`, clamped to `65536`-`67108864` |
| `OMERO_IMARIS_UPLOAD_CHUNK_BYTES` | Bounded multipart upload buffer size, default `1048576`, clamped to `65536`-`67108864` |
| `OMERO_IMARIS_MULTI_DOWNLOAD_WORKERS` | Optional cap for parallel selected-image downloads |
| `OMERO_IMARIS_UNIQUE_DOWNLOAD_SUFFIX` | Force timestamped unique filenames for non-GUI downloads instead of replacing same-name files |
| `OMERO_IMARIS_HTTP_RETRY_ATTEMPTS` | Transient HTTP retry attempts, default `3`, clamped to `1`-`10` |
| `OMERO_IMARIS_HTTP_RETRY_DELAY_SECONDS` | Delay between transient HTTP retries, default `2.0`, clamped to `0.0`-`30.0` |
| `OMERO_IMARIS_REFRESH_TIMEOUT_SECONDS` | Timeout for each project/dataset/image refresh request, default `30`, clamped to `5`-`300` |
| `OMERO_IMARIS_REFRESH_RETRY_ATTEMPTS` | Refresh retry attempts, default `3`, clamped to `1`-`10` |
| `OMERO_IMARIS_REFRESH_RETRY_DELAY_SECONDS` | Delay between refresh retries, default `2.0`, clamped to `0.0`-`30.0` |
| `OMERO_IMARIS_HEALTH_PING_INTERVAL_SECONDS` | Read-only session health ping interval, default `30`, clamped to `5`-`3600` |
| `OMERO_IMARIS_HEALTH_PING_TIMEOUT_SECONDS` | Health ping timeout, default `10`, clamped to `2`-`120` |
| `OMERO_IMARIS_HEALTH_PING_RETRY_ATTEMPTS` | Failed health pings before declaring the connection lost, default `3`, clamped to `1`-`10` |
| `OMERO_IMARIS_HEALTH_PING_RETRY_DELAY_SECONDS` | Delay between failed health pings, default `1.0`, clamped to `0.0`-`30.0` |
| `IMARIS_OMERO_CONNECTOR_ENABLE_ICEPY` | Optional experimental native Imaris bridge flag; keep unset/false for normal XT operation |

## Operator checklist

- Confirm Celery worker process health: `docker compose logs omeroweb | grep celery`
- Confirm queue name consistency across producer (`env/omero-celery.env`) and consumer (`startup/40-start-imaris-celery-worker.sh`).
- Confirm script availability: `docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero script list`
- Confirm `Processor-0 active`: `docker compose exec omeroserver /opt/omero/server/OMERO.server/bin/omero admin diagnostics`
- Validate direct CLI export from both `omeroserver` and `omeroweb`
- Validate end-to-end export and download from a sample image.
- If using job-service mode, verify the job-service account exists in OMERO and credentials are correct.
- See `docs/troubleshooting/imaris-export.md` for diagnostic procedures.
