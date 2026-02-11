#!/usr/bin/env bash
set -euo pipefail

OMERO_SERVER_ROOT="/opt/omero/server"

if [[ ! -d "${OMERO_SERVER_ROOT}" ]]; then
    echo "ERROR: OMERO server root not found at ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

mapfile -t VENV_DIRS < <(find "${OMERO_SERVER_ROOT}" -maxdepth 1 -mindepth 1 -type d -name 'venv*' | sort -V)

if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then
    echo "ERROR: No OMERO virtual environments found under ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

for venv_dir in "${VENV_DIRS[@]}"; do
    python_bin="${venv_dir}/bin/python"
    if [[ ! -x "${python_bin}" ]]; then
        echo "ERROR: Invalid OMERO virtual environment (missing python): ${venv_dir}" >&2
        exit 1
    fi

    echo "Validating pkg_resources availability in ${venv_dir}"
    "${python_bin}" - <<'PY'
import pkg_resources
print(f"pkg_resources import check succeeded: {pkg_resources.__file__}")
PY

done
