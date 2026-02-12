# Imaris Connector Plugin Guide (`omeroweb_imaris_connector`)

## Purpose
This plugin provides OMERO image export to Imaris-compatible output through a web endpoint backed by asynchronous Celery execution.

## Main Capabilities

- request-based export for a target OMERO image,
- asynchronous job mode with status polling URL,
- synchronous wait mode with timeout handling,
- export artifact download response,
- optional OMERO connection overrides for advanced routing.

## Key Route

- `/imaris-export/`

## Request Modes

- **Async mode**: returns `job_id` and `status_url` for client polling.
- **Sync mode**: waits for completion (up to configured timeout) and returns output or timeout/failure status.

## Required Runtime Dependencies

- Redis broker/backend available.
- Celery worker running and consuming configured queue.
- OMERO script registration for IMS export script.
- Valid OMERO session context for request user.

## Core Environment Variables

Defined primarily in `env/omero-celery.env`:

- `OMERO_IMS_USE_CELERY`
- `OMERO_IMS_CELERY_BROKER_URL`
- `OMERO_IMS_CELERY_BACKEND_URL`
- `OMERO_IMS_CELERY_QUEUE`
- `OMERO_IMS_SCRIPT_NAME`
- timeout and retry controls

## Operator Checklist

- Confirm Celery worker process health.
- Confirm queue name consistency across producer/consumer.
- Confirm script availability in OMERO script service.
- Validate end-to-end export and download from a sample image.
