#!/usr/bin/env bash
set -euo pipefail

VENV_PY="$(ls -d /opt/omero/server/venv* | sort -V | tail -n 1)/bin/python"

echo "Setting OMERO script python to: ${VENV_PY}"

/opt/omero/server/OMERO.server/bin/omero config set omero.scripts.python "${VENV_PY}"
