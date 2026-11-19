# Environment changes during upgrades

Use the templates and environment checks from the release you are installing.
Keep your existing database, managed repository, and temporary storage paths.
Back up the databases, image data, and deployment settings before the upgrade.
Verify that you can restore those backups before proceeding. Keep configuration
backups private: they contain credentials.

## Settings by installed release

### Before `1.3.0-main.1`

- **Redis:** These releases used temporary storage by default. Follow the
  [Redis persistence migration](redis-persistence.md) before stopping an old
  Redis container that uses temporary storage. If you already use the target
  project's persistent Redis volume, retain it.
- **`installation_paths.env`:** If `OLLAMA_DATA_PATH` is missing, add it
  between `ALLOY_DATA_PATH` and `PG_MAINTENANCE_DATA_PATH`. Use a persistent
  location and keep the existing paths for other services.
- **`env/omeroweb.env`:** Set `ADMIN_TOOLS_GRAFANA_URL`,
  `ADMIN_TOOLS_LOKI_URL`, and `ADMIN_TOOLS_PROMETHEUS_URL` to the HTTPS
  endpoints in the target template for bundled monitoring. For external
  monitoring, use trusted HTTPS endpoints for your own services.

### `1.0.0-main.1`, `1.0.1-main.1`, and `1.1.0-main.1`

Add `BIOFORMATS2RAW_SHA256` in `env/omeroserver.env` if missing. Use the
checksum for the selected converter version. To adopt a new version from
the target template, update the version and checksum together.

### Additional changes for `1.0.0-main.1`

- **`env/omeroserver.env`:** Review the `OMERO_DOWNLOADER_*` and
  `BIOFORMATS_*` version/checksum pairs and the `IMARISCONVERT_*` and
  `IMARISWRITER_*` repository, ref, and commit settings.
- **`env/omeroweb.env`:** Set `CONFIG_omero_web_debug=false`. Review
  `OMERO_WEB_API_SERVER_PUBLIC_HOST` and
  `OMERO_WEB_API_SERVER_HOST_ALLOWLIST` for your existing access routes,
  plus the upload and Zarr limits. `template-check` lists the exact keys
  missing from your installation.

### From `1.3.0-main.1`

Retain the persistent Redis volume. Compare your files with the target
templates and apply only the changes needed for that upgrade.

### Rebuild the web image

The target uses OMERO.web 5.33.4. The published releases covered here use
5.31.1 or newer, so the session-store clearing step for 5.31.0 in the
[upstream upgrade guide](https://github.com/ome/omero-web/blob/v5.33.4/UPGRADING.md)
does not apply. Preserve Redis.

Set `WEB_TIFFFILE_VERSION=2026.11.16` in `env/omeroserver.env` before
rebuilding to use the updated web export dependency. Keep
`TIFFFILE_VERSION=2026.3.3` for the Python 3.11 server.

The installer generates `.env` from the deployment settings and retains the
supported options from `.env_example`. Do not overwrite an existing `.env`
with the example. Keep `env/omero_secrets.env` on the deployment host and out
of Git and release artifacts.

For a PostgreSQL 16 minor update, follow the
[database upgrade checks](postgres-maintenance.md#updating-postgresql-16)
before replacing either database container.

## Validate before stopping services

Run these checks against the target release's code with your existing
deployment environment files in place:

```bash
python3 tools/env_safety_guard.py check
python3 tools/env_safety_guard.py template-check
python3 tools/env_safety_guard.py runtime-env-check --skip-dot-env
```

Review the reported keys and make only the required changes in the applicable
files. Insert missing keys in the order shown by the target template. Keep
all unrelated settings and let the installer regenerate `.env` during the
update. Before running Compose manually, run
`python3 tools/env_safety_guard.py compose-guard` and
`python3 tools/env_safety_guard.py runtime-env-check`.

After startup, verify the database records, stored images, imports, and
monitoring. Replacing OMERO.server closes its existing login sessions. Users
sign in again even when Redis preserved their browser session records.
