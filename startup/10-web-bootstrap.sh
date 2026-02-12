#!/usr/bin/env bash
################################################################################
# OMERO.web Bootstrap Script
################################################################################
#
# PURPOSE:
#   Ensures OMERO.web log directory is writable before OMERO.web starts.
#   This prevents zarr/numcodecs logging failures during Python module imports.
#
# CRITICAL CHANGE:
#   CONFIG_omero_web_logdir now points directly to the mounted volume:
#   /opt/omero/web/OMERO.web/var/log (not /tmp/omero-web-logs)
#   
#   This matches the volume mount in docker-compose.yml and ensures logs
#   persist on the host filesystem.
#
# WHAT IT DOES:
#   1. Verifies log directory (from CONFIG_omero_web_logdir) is writable
#   2. If directory is a mountpoint, confirms it's accessible
#   3. If directory doesn't exist, creates it
#   4. Exits with error if log directory cannot be made writable
#
# WHY THIS IS CRITICAL:
#   - zarr library logs during import (before OMERO.web is fully initialized)
#   - If log directory isn't writable, concurrent_log_handler fails
#   - This causes OMERO.web startup to crash with emit(record) errors
#
# DEPENDENCIES:
#   - omero-data-init must run first to set host directory permissions
#   - Volume must be mounted at CONFIG_omero_web_logdir path
#
################################################################################
set -euo pipefail

log_dir="${CONFIG_omero_web_logdir:-/opt/omero/web/OMERO.web/var/log}"

echo "[web-bootstrap] Checking OMERO.web log directory: ${log_dir}"

# Create log directory if it doesn't exist
mkdir -p "${log_dir}"

# Verify directory is writable
if [[ ! -d "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: Log directory does not exist and could not be created: ${log_dir}" >&2
    exit 1
fi

if [[ ! -w "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: Log directory is not writable: ${log_dir}" >&2
    echo "[web-bootstrap] This will cause zarr import to fail during OMERO.web startup" >&2
    echo "[web-bootstrap] Ensure omero-data-init has set correct permissions (UID:GID 1000:1000)" >&2
    ls -ld "${log_dir}" >&2 || true
    exit 1
fi

# Test write access
if ! touch "${log_dir}/.permission_test" 2>/dev/null; then
    echo "[web-bootstrap] ERROR: Cannot write to log directory: ${log_dir}" >&2
    ls -ld "${log_dir}" >&2 || true
    exit 1
fi

rm -f "${log_dir}/.permission_test"

if mountpoint -q "${log_dir}"; then
    echo "[web-bootstrap] Log directory is a mounted filesystem: ${log_dir}"
else
    echo "[web-bootstrap] Log directory is local (not mounted): ${log_dir}"
fi

echo "[web-bootstrap] ✓ OMERO.web log directory is ready and writable: ${log_dir}"
