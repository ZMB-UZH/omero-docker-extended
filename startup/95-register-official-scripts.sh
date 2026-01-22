#!/usr/bin/env bash
set -euo pipefail

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"
SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"

echo "[OMERO scripts] Waiting for OMERO.server..."

# Wait until Glacier2 actually accepts commands
until "${OMERO_BIN}" version >/dev/null 2>&1; do
    sleep 2
done

echo "[OMERO scripts] Registering official scripts"

find "${SCRIPTS_DIR}" -type f -name "*.py" | while read -r script; do
    echo "[OMERO scripts] Uploading: ${script}"
    "${OMERO_BIN}" script upload \
        --official \
        --sudo root \
        "${script}"
done

echo "[OMERO scripts] Script registration complete"
