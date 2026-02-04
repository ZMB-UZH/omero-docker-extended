#!/usr/bin/env bash
set -euo pipefail

echo "===== RESET OMERO RUNTIME STATE (KEEPING /OMERO + DB) ====="

OMERO_HOME="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' | sort -V | tail -n 1)"

if [[ -z "${OMERO_HOME}" ]]; then
    echo "FATAL: Could not locate extracted OMERO.server directory."
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
