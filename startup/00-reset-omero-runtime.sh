#!/usr/bin/env bash
set -euo pipefail

echo "===== RESET OMERO RUNTIME STATE (KEEPING /OMERO + DB) ====="

RESET_OMERO_RUNTIME="${RESET_OMERO_RUNTIME:-0}"
if [[ "${RESET_OMERO_RUNTIME}" != "1" ]]; then
    echo "RESET_OMERO_RUNTIME != 1 -> skipping runtime reset."
    echo "To enable: set RESET_OMERO_RUNTIME=1 for this container start."
    exit 0
fi

if [[ -d "/opt/omero/server/OMERO.server" ]]; then
    OMERO_HOME="/opt/omero/server/OMERO.server"
else
    OMERO_HOME="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' \
        ! -name '*.zip' \
        | sort -V | tail -n 1)"
fi

if [[ -z "${OMERO_HOME}" || ! -d "${OMERO_HOME}" ]]; then
    echo "ERROR: Could not detect a valid OMERO_HOME under /opt/omero/server" >&2
    ls -la /opt/omero/server >&2 || true
    exit 1
fi

echo "Detected OMERO_HOME=${OMERO_HOME}"

GRID_DIR="${OMERO_HOME}/var/master"

if [[ -d "${GRID_DIR}" ]]; then
    echo "Deleting IceGrid runtime at: ${GRID_DIR}"
    rm -rf "${GRID_DIR}"
else
    echo "No IceGrid runtime found at: ${GRID_DIR}"
fi

echo "Runtime reset complete."
