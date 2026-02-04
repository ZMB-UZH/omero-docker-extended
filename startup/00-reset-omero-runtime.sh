#!/usr/bin/env bash
set -euo pipefail

echo "===== RESET OMERO RUNTIME STATE (KEEPING /OMERO + DB) ====="

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
    echo "Deleting stale IceGrid runtime..."
    rm -rf "${GRID_DIR}"
else
    echo "No IceGrid runtime found."
fi

echo "Runtime reset complete."
