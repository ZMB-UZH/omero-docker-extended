#!/usr/bin/env bash
set -euo pipefail

echo "===== RESET OMERO RUNTIME STATE (KEEPING /OMERO + DB) ====="

OMERO_HOME="$(ls -d /opt/omero/server/OMERO.server-* 2>/dev/null | sort -V | tail -n 1 || true)"

if [[ -z "${OMERO_HOME}" ]]; then
    echo "ERROR: Could not locate /opt/omero/server/OMERO.server-* directory." >&2
    exit 1
fi

echo "Detected OMERO_HOME=${OMERO_HOME}"

# 1) IceGrid master state (THIS is what causes ghost processors / stale descriptors)
rm -rf "${OMERO_HOME}/var/master" || true

# 2) Runtime cache/tmp/lock state (safe to wipe; rebuilt on startup)
rm -rf "${OMERO_HOME}/var/tmp" || true
rm -rf "${OMERO_HOME}/var/lock" || true
rm -rf "${OMERO_HOME}/var/run" || true

# 3) Optional: wipe server-side config.xml so 50-config.py re-creates it cleanly every time
# (Keep templates.xml etc.)
if [[ -f "${OMERO_HOME}/etc/grid/config.xml" ]]; then
    rm -f "${OMERO_HOME}/etc/grid/config.xml"
fi

# 4) Make sure var dirs exist (some images/scripts assume them)
mkdir -p "${OMERO_HOME}/var/log" "${OMERO_HOME}/var/tmp"

echo "Reset complete."
