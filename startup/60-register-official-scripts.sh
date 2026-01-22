#!/usr/bin/env bash
set -euo pipefail

OMERO_CLI="/opt/omero/server/OMERO.server/bin/omero"
SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"

echo "[OMERO scripts] Waiting for OMERO.server to be ready..."

# Wait until OMERO responds
until "${OMERO_CLI}" admin status >/dev/null 2>&1; do
    sleep 3
done

echo "[OMERO scripts] Registering official scripts (idempotent)"

"${OMERO_CLI}" script upload --recursive "${SCRIPTS_DIR}"

echo "[OMERO scripts] Script registration complete"
