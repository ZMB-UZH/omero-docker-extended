#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# SAFETY GUARD
#
# This script can hammer the Script service + Param parsing at startup and can
# starve Processor-* -> omero.NoProcessorAvailable.
#
# Only run when explicitly enabled:
#   OMERO_REGISTER_OFFICIAL_SCRIPTS=1
# -----------------------------------------------------------------------------
OMERO_REGISTER_OFFICIAL_SCRIPTS="${OMERO_REGISTER_OFFICIAL_SCRIPTS:-0}"
if [[ "${OMERO_REGISTER_OFFICIAL_SCRIPTS}" != "1" ]]; then
    echo "[OMERO scripts] OMERO_REGISTER_OFFICIAL_SCRIPTS=${OMERO_REGISTER_OFFICIAL_SCRIPTS} (not 1) -> skipping."
    exit 0
fi

(
set -euo pipefail

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"
LOGFILE="/opt/omero/server/register-official-scripts.log"

MAX_PARALLEL="${MAX_PARALLEL:-1}"

# ... KEEP THE REST OF YOUR SCRIPT EXACTLY AS-IS ...
# (no other changes except removing the trailing background '&')

echo "[OMERO scripts] Official script registration started (MAX_PARALLEL=${MAX_PARALLEL})"
echo "[OMERO scripts] Log: ${LOGFILE}"

) >> "${LOGFILE}" 2>&1
