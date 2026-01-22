#!/usr/bin/env bash
set -euo pipefail

OMERO_CLI="/opt/omero/server/OMERO.server/bin/omero"
SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"
MARKER="/opt/omero/server/.official_scripts_registered"

if [[ -f "${MARKER}" ]]; then
    echo "[OMERO scripts] Already registered, skipping"
    exit 0
fi

echo "[OMERO scripts] Registering official scripts (one-time)"

"${OMERO_CLI}" script upload --recursive "${SCRIPTS_DIR}"

touch "${MARKER}"
chown omero-server:omero-server "${MARKER}"

echo "[OMERO scripts] Registration done"
