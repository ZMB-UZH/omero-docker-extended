#!/usr/bin/env bash
set -euo pipefail

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"
SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"
MAX_PARALLEL=4

: "${OMERO_ROOT_PASSWORD:?OMERO_ROOT_PASSWORD must be set}"

echo "[OMERO scripts] Waiting for Glacier2 to be ready..."

until "${OMERO_BIN}" version \
        -u root \
        -w "${OMERO_ROOT_PASSWORD}" \
        >/dev/null 2>&1
do
    sleep 2
done

echo "[OMERO scripts] Collecting already registered scripts..."

REGISTERED_SCRIPTS="$(
    "${OMERO_BIN}" script list \
        -u root \
        -w "${OMERO_ROOT_PASSWORD}" \
        --sudo root \
        | awk -F'|' '{print $2}' \
        | sed 's/^ *//;s/ *$//' \
        | sed 's/\.py$//'
)"

export OMERO_BIN
export OMERO_ROOT_PASSWORD
export REGISTERED_SCRIPTS

upload_one() {
    script="$1"
    base="$(basename "${script}" .py)"

    if echo "${REGISTERED_SCRIPTS}" | grep -qx "${base}"; then
        echo "[OMERO scripts] Skipping: ${base}"
        return 0
    fi

    echo "[OMERO scripts] Uploading: ${base}"

    "${OMERO_BIN}" script upload \
        --official \
        --sudo root \
        -u root \
        -w "${OMERO_ROOT_PASSWORD}" \
        "${script}"
}

export -f upload_one

echo "[OMERO scripts] Parallel upload (max ${MAX_PARALLEL})"

find "${SCRIPTS_DIR}" -type f -name "*.py" \
    | sort \
    | xargs -n 1 -P "${MAX_PARALLEL}" -I {} \
        bash -c 'upload_one "$@"' _ {}

echo "[OMERO scripts] Registration finished"
