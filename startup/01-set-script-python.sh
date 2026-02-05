#!/usr/bin/env bash
set -euo pipefail

OMERO="/opt/omero/server/OMERO.server/bin/omero"

VENV_PY="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' | sort -V | tail -n 1)/bin/python"

if [[ ! -x "${VENV_PY}" ]]; then
    echo "FATAL: OMERO venv python not found: ${VENV_PY}"
    exit 1
fi

echo "Setting OMERO script python to: ${VENV_PY}"

$OMERO config set omero.scripts.python "${VENV_PY}"

echo "OMERO script python configured."
