#!/usr/bin/env bash
set -euo pipefail

echo "[OMERO scripts] Waiting for OMERO.server to be ready..."

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"
SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"

# Wait until OMERO responds
until "${OMERO_BIN}" version >/dev/null 2>&1; do
    sleep 2
done

echo "[OMERO scripts] Registering official scripts (one-time)"

find "${SCRIPTS_DIR}" -type f -name "*.py" | while read -r script; do
    echo "[OMERO scripts] Uploading: ${script}"
    "${OMERO_BIN}" script upload \
        --official \
        "${script}"
done

echo "[OMERO scripts] Registration complete"
