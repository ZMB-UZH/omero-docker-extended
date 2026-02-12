#!/usr/bin/env bash
################################################################################
# OMERO.web Bootstrap Script
################################################################################
#
# PURPOSE:
#   Prepares the OMERO.web logging environment before OMERO.web starts.
#   This script is critical for preventing zarr/numcodecs initialization 
#   failures caused by unwritable log directories.
#
# WHAT IT DOES:
#   1. Checks if log directory (from CONFIG_omero_web_logdir or default) exists
#   2. Verifies log directory is writable by current user (omero-web)
#   3. Creates parent directory for default log location if needed
#   4. Replaces default log directory with symlink to configured log directory
#      (unless it's already mounted as a filesystem)
#
# WHY THIS IS NEEDED:
#   - The omeroweb container mounts host log directories at specific paths
#   - If these directories don't have correct permissions, zarr fails on import
#   - The symlink ensures all OMERO.web logging goes to the mounted volume
#   - This runs BEFORE Python imports, preventing permission errors
#
# WHEN IT RUNS:
#   - Executed by custom entrypoint before supervisord starts
#   - Runs as omero-web user (not root)
#   - Depends on omero-data-init to have already fixed host directory permissions
#
# PREREQUISITES:
#   - omero-data-init service must complete successfully first
#   - Host directories must be mounted with correct permissions (UID 1000)
#   - CONFIG_omero_web_logdir environment variable (optional override)
#
################################################################################
set -euo pipefail

log_dir="${CONFIG_omero_web_logdir:-/tmp/omero-web-logs}"
default_log_dir="/opt/omero/web/OMERO.web/var/log"

mkdir -p "${log_dir}"

if [[ ! -d "${log_dir}" || ! -w "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: log directory is not writable: ${log_dir}" >&2
    exit 1
fi

mkdir -p "$(dirname "${default_log_dir}")"

if [[ -L "${default_log_dir}" ]]; then
    current_target="$(readlink "${default_log_dir}")"
    if [[ "${current_target}" == "${log_dir}" ]]; then
        echo "[web-bootstrap] OMERO.web default log symlink already points to ${log_dir}"
        exit 0
    fi
fi

if mountpoint -q "${default_log_dir}"; then
    echo "[web-bootstrap] WARNING: ${default_log_dir} is a mounted filesystem; skipping symlink replacement."
    exit 0
fi

rm -rf "${default_log_dir}"
ln -s "${log_dir}" "${default_log_dir}"

echo "[web-bootstrap] OMERO.web log directory ready: ${log_dir}"
