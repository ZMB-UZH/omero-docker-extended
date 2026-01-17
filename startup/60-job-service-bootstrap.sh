#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Create job-service user automatically (if missing) and ensure it is a member
# of all groups so it can run background jobs safely across plugins.
#
# This MUST run inside the OMERO.server container (OMERO CLI available).
# -----------------------------------------------------------------------------

OMERO_SERVER_HOST="${OMERO_SERVER_HOST:-localhost}"
OMERO_SERVER_PORT="${OMERO_SERVER_PORT:-4064}"

ROOTPASS="${ROOTPASS:-}"
JOB_USER="${OMERO_JOB_SERVICE_USERNAME:-job-service}"
JOB_PASS="${OMERO_JOB_SERVICE_PASS:-}"

if [[ -z "${ROOTPASS}" ]]; then
    echo "ERROR: ROOTPASS is not set; cannot bootstrap ${JOB_USER}." >&2
    exit 1
fi

if [[ -z "${JOB_PASS}" ]]; then
    echo "ERROR: OMERO_JOB_SERVICE_PASS is not set; cannot bootstrap ${JOB_USER}." >&2
    exit 1
fi

OMERO_DIR="$(ls -d /opt/omero/server/OMERO.server-* 2>/dev/null | sort -V | tail -n 1)"
if [[ -z "${OMERO_DIR}" ]]; then
    echo "ERROR: Cannot locate OMERO.server directory under /opt/omero/server/OMERO.server-*." >&2
    exit 1
fi
OMERO_BIN="${OMERO_DIR}/bin/omero"

# Wait for OMERO.server to accept logins
echo "Waiting for OMERO.server at ${OMERO_SERVER_HOST}:${OMERO_SERVER_PORT}..."
for i in $(seq 1 90); do
    if "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" user list >/dev/null 2>&1; then
        echo "OMERO.server is ready."
        break
    fi
    sleep 2
    if [[ "${i}" -eq 90 ]]; then
        echo "ERROR: OMERO.server not ready after waiting." >&2
        exit 1
    fi
done

# Create user if missing
if "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" user info --user-name "${JOB_USER}" >/dev/null 2>&1; then
    echo "User ${JOB_USER} already exists."
else
    echo "Creating user ${JOB_USER}..."
    "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" user add "${JOB_USER}" Job Service --group-name user

    # Set password non-interactively
    echo "Setting password for ${JOB_USER}..."
    printf '%s\n%s\n' "${JOB_PASS}" "${JOB_PASS}" | "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" user password "${JOB_USER}"
fi

# Ensure job-service is a member of ALL groups (so jobs can switch group contexts safely)
echo "Ensuring ${JOB_USER} is in all groups..."
"${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" group list \
    | while read -r gid gname rest; do
        if [[ "${gid}" =~ ^[0-9]+$ ]] && [[ -n "${gname}" ]]; then
            "${OMERO_BIN}" -s "${OMERO_SERVER_HOST}" -p "${OMERO_SERVER_PORT}" -u root -w "${ROOTPASS}" group adduser "${JOB_USER}" --name "${gname}" >/dev/null 2>&1 || true
        fi
      done

echo "job-service bootstrap complete."
