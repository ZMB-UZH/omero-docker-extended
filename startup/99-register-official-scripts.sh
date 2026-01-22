#!/usr/bin/env bash
set -euo pipefail

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"
OMERO_HOST="localhost"
OMERO_PORT="4064"
SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"
MAX_PARALLEL=4

: "${ROOTPASS:?ROOTPASS must be set}"

echo "[OMERO scripts] Waiting for OMERO.server JVM to start..."

until pgrep -f "omero.server.Server" >/dev/null 2>&1
do
    sleep 2
done

echo "[OMERO scripts] OMERO.server JVM detected"

echo "[OMERO scripts] Waiting for OMERO.server to be fully ready..."

"${OMERO_BIN}" admin status \
        -s "${OMERO_HOST}" \
        -p "${OMERO_PORT}" \
        -u root \
        -w "${ROOTPASS}" \
        --wait \
        </dev/null \
        >/dev/null 2>&1

echo "[OMERO scripts] OMERO.server is ready"

echo "[OMERO scripts] Glacier2 is ready"

echo "[OMERO scripts] Collecting already registered scripts..."

REGISTERED_SCRIPTS="$(
    "${OMERO_BIN}" script list \
        -s "${OMERO_HOST}" \
        -p "${OMERO_PORT}" \
        -u root \
        -w "${ROOTPASS}" \
        --sudo root \
        </dev/null \
        | awk -F'|' '{print $2}' \
        | sed 's/^ *//;s/ *$//' \
        | sed 's/\.py$//'
)"

export OMERO_BIN
export OMERO_HOST
export OMERO_PORT
export ROOTPASS
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
        -s "${OMERO_HOST}" \
        -p "${OMERO_PORT}" \
        -u root \
        -w "${ROOTPASS}" \
        "${script}" \
        </dev/null
}

export -f upload_one

echo "[OMERO scripts] Parallel upload (max ${MAX_PARALLEL})"

find "${SCRIPTS_DIR}" -type f -name "*.py" \
    | sort \
    | xargs -n 1 -P "${MAX_PARALLEL}" -I {} \
        bash -c 'upload_one "$@"' _ {}

echo "[OMERO scripts] Registration finished"
