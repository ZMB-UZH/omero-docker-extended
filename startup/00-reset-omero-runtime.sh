#!/usr/bin/env bash
set -euo pipefail

echo "===== RESET OMERO RUNTIME STATE (KEEPING /OMERO + DB) ====="

# -------------------------------------------------------------------------
# SAFETY GUARD
#
# Deleting OMERO_HOME/var/master resets IceGrid runtime state (DESTRUCTIVE).
# This can break OMERO.grid services (including Processor-0 used by scripts).
#
# Only run this reset when explicitly requested:
#   OMERO_RESET_ICEGRID_MASTER=1
# -------------------------------------------------------------------------
if [[ "${OMERO_RESET_ICEGRID_MASTER:-0}" != "1" ]]; then
    echo "OMERO_RESET_ICEGRID_MASTER!=1 -> skipping IceGrid runtime reset."
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
    echo "Deleting stale IceGrid runtime..."
    rm -rf "${GRID_DIR}"
else
    echo "No IceGrid runtime found."
fi

echo "Runtime reset complete."
