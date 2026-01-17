#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# job-service bootstrap (NON-BLOCKING)
#
# IMPORTANT:
# The OMERO.server container runs /startup/*.sh BEFORE Glacier2 starts listening
# on port 4064. If we "wait for 4064" in foreground, we deadlock startup and
# OMERO never starts.
#
# Therefore:
# - On first invocation, this script spawns a background worker and exits 0.
# - The background worker waits for OMERO (4064) and performs the bootstrap.
#
# Logs:
#   /opt/omero/server/OMERO.server/var/log/job-service-bootstrap.log
# -----------------------------------------------------------------------------

OMERO_SERVER_HOST="${OMERO_SERVER_HOST:-localhost}"
OMERO_SERVER_PORT="${OMERO_SERVER_PORT:-4064}"

ROOTPASS="${ROOTPASS:-}"
JOB_USER="${OMERO_JOB_SERVICE_USERNAME:-job-service}"
JOB_PASS="${OMERO_JOB_SERVICE_PASS:-}"

OMERO_DIR="$(find /opt/omero/server \
    -maxdepth 1 \
    -type d \
    -name 'OMERO.server-*' \
    | sort -V \
    | tail -n 1)"
if [[ -z "${OMERO_DIR}" || ! -d "${OMERO_DIR}" ]]; then
    echo "ERROR: OMERO_DIR is invalid or not a directory: ${OMERO_DIR}" >&2
    exit 1
fi

OMERO_BIN="${OMERO_DIR}/bin/omero"

LOG_DIR="${OMERO_DIR}/var/log"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/job-service-bootstrap.log"
LOCK_FILE="/tmp/job-service-bootstrap.lock"

mkdir -p "${LOG_DIR}"

# --------------------------------------------------------------------------
# NON-BLOCKING LAUNCHER
# --------------------------------------------------------------------------
# Guard to prevent recursion: background worker sets JOB_SERVICE_BOOTSTRAP_WORKER=1
if [[ "${JOB_SERVICE_BOOTSTRAP_WORKER:-0}" != "1" ]]; then
    {
        echo "Scheduling job-service bootstrap in background (non-blocking)..."
        echo "Bootstrap log: ${LOG_FILE}"
    } >&2

    # Prevent spawning multiple workers if container restarts quickly
    (
        flock -n 9 || exit 0
        nohup env \
            JOB_SERVICE_BOOTSTRAP_WORKER=1 \
            OMERO_SERVER_HOST="${OMERO_SERVER_HOST}" \
            OMERO_SERVER_PORT="${OMERO_SERVER_PORT}" \
            ROOTPASS="${ROOTPASS}" \
            OMERO_JOB_SERVICE_USERNAME="${JOB_USER}" \
            OMERO_JOB_SERVICE_PASS="${JOB_PASS}" \
            /startup/99-job-service-bootstrap.sh >>"${LOG_FILE}" 2>&1 &
    ) 9>"${LOCK_FILE}" || true

    exit 0
fi

# --------------------------------------------------------------------------
# BACKGROUND WORKER (runs after OMERO starts)
# --------------------------------------------------------------------------
echo "job-service bootstrap worker started at $(date -Iseconds)"
echo "Target OMERO: ${OMERO_SERVER_HOST}:${OMERO_SERVER_PORT}"

if [[ -z "${ROOTPASS}" ]]; then
    echo "ERROR: ROOTPASS is not set; cannot bootstrap ${JOB_USER}." >&2
    exit 1
fi

if [[ -z "${JOB_PASS}" ]]; then
    echo "ERROR: OMERO_JOB_SERVICE_PASS is not set; cannot bootstrap ${JOB_USER}." >&2
    exit 1
fi

echo "Waiting for OMERO.server (Glacier2) to accept logins..."
for i in $(seq 1 180); do
    if "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" user list >/dev/null 2>&1; then
        echo "OMERO.server is ready."
        break
    fi
    sleep 2
    if [[ "${i}" -eq 180 ]]; then
        echo "ERROR: OMERO.server not ready after waiting. Bootstrap failed." >&2
        exit 1
    fi
done

# Create user if missing
if "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" user info --user-name "${JOB_USER}" >/dev/null 2>&1; then
    echo "User ${JOB_USER} already exists."
else
    echo "Creating user ${JOB_USER}..."
    "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" \
        user add "${JOB_USER}" Job Service --group-name user

    echo "Setting password for ${JOB_USER}..."
    printf '%s\n%s\n' "${JOB_PASS}" "${JOB_PASS}" | "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" \
        -u root -w "${ROOTPASS}" user password "${JOB_USER}"
fi

# Ensure job-service is a member of ALL groups (so jobs can switch group contexts safely)
echo "Ensuring ${JOB_USER} is in all groups..."
"${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" group list \
    | while read -r gid gname rest; do
        if [[ "${gid}" =~ ^[0-9]+$ ]] && [[ -n "${gname}" ]]; then
            "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" \
                group adduser "${JOB_USER}" --name "${gname}" >/dev/null 2>&1 || true
        fi
      done

echo "job-service bootstrap complete at $(date -Iseconds)"
exit 0
