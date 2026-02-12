# Upload Plugin Guide (`omeroweb_upload`)

## Purpose
The upload plugin manages staged file upload and controlled import into OMERO, including job lifecycle tracking and configurable upload behavior.

## Main Capabilities

- upload session creation and file transfer,
- import step execution and confirmation flow,
- job status polling,
- stale upload pruning,
- user and special-method settings persistence,
- project listing and root status checks.

## Key Routes

- `/omeroweb_upload/`
- `/omeroweb_upload/start/`
- `/omeroweb_upload/upload/<job_id>/`
- `/omeroweb_upload/import/<job_id>/`
- `/omeroweb_upload/confirm/<job_id>/`
- `/omeroweb_upload/prune/<job_id>/`
- `/omeroweb_upload/status/<job_id>/`
- `/omeroweb_upload/user-settings/save/`
- `/omeroweb_upload/special-method-settings/*`

## Typical User Workflow

1. Open upload page.
2. Start upload session.
3. Transfer files to job-specific upload endpoint.
4. Trigger import step.
5. Confirm import and monitor status until terminal state.
6. Prune temporary upload assets once complete.

## Operational Controls

Configuration values in `env/omeroweb.env` control:

- upload concurrency,
- batch size,
- cleanup intervals and age thresholds,
- temporary upload directory locations.

## Operator Checklist

- Ensure temporary upload paths are writable.
- Monitor cleanup behavior to avoid stale disk growth.
- Validate imports on representative datasets.
- Confirm plugin settings are persisted and reloaded correctly.
