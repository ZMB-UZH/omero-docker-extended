#!/usr/bin/env bash
set -euo pipefail

OMERO="/opt/omero/server/OMERO.server/bin/omero"

echo "Waiting for OMERO server to become available..."

until $OMERO admin status >/dev/null 2>&1; do
    sleep 2
done

VENV_PY="$(ls -d /opt/omero/server/venv* | sort -V | tail -n 1)/bin/python"

if [[ ! -x "${VENV_PY}" ]]; then
    echo "FATAL: OMERO venv python not found: ${VENV_PY}"
    exit 1
fi

echo "Setting OMERO script python to: ${VENV_PY}"

$OMERO config set omero.scripts.python "${VENV_PY}"

echo "OMERO script python configured successfully."
