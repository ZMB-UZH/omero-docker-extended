#!/usr/bin/env bash
#
# 00-check-and-fix-permissions.sh
# Validate and optionally fix writable runtime paths required by OMERO.
#

set -euo pipefail

echo "========================================="
echo "[PERMISSIONS] Checking OMERO runtime paths"
echo "========================================="
echo

OMERO_DIR="${OMERO_DIR:-/OMERO}"
CERTS_DIR="${CERTS_DIR:-${OMERO_DIR}/certs}"
SERVER_VAR_DIR="${SERVER_VAR_DIR:-/opt/omero/server/OMERO.server/var}"
SERVER_LOG_DIR="${SERVER_LOG_DIR:-${SERVER_VAR_DIR}/log}"

CURRENT_UID="$(id -u)"
CURRENT_GID="$(id -g)"
CURRENT_USER="$(id -un)"

check_writable_dir() {
    local path="$1"
    local label="$2"
    local hint_var="$3"
    local fix_hint="$4"

    if [[ ! -d "${path}" ]]; then
        echo "[PERMISSIONS] ERROR: ${label} directory does not exist: ${path}" >&2
        echo "[PERMISSIONS] ERROR: Verify the bind mount configured by ${hint_var}." >&2
        exit 1
    fi

    local owner_uid owner_gid
    owner_uid="$(stat -c '%u' "${path}" 2>/dev/null || echo "unknown")"
    owner_gid="$(stat -c '%g' "${path}" 2>/dev/null || echo "unknown")"

    echo "[PERMISSIONS] ${label}: ${path} (owner UID=${owner_uid}, GID=${owner_gid})"

    if touch "${path}/.permission_test" 2>/dev/null; then
        rm -f "${path}/.permission_test"
        echo "[PERMISSIONS] ✓ ${label} is writable"
        return 0
    fi

    echo "[PERMISSIONS] ✗ ${label} is NOT writable by current user"

    if chown -R "${CURRENT_UID}:${CURRENT_GID}" "${path}" 2>/dev/null; then
        echo "[PERMISSIONS] ✓ Changed ownership of ${label} to ${CURRENT_UID}:${CURRENT_GID}"
    else
        echo "[PERMISSIONS] ✗ Cannot change ownership for ${label} (likely non-root container user)."
    fi

    chmod -R u+rwX "${path}" 2>/dev/null || true

    if touch "${path}/.permission_test" 2>/dev/null; then
        rm -f "${path}/.permission_test"
        echo "[PERMISSIONS] ✓ ${label} writable after fix attempt"
        return 0
    fi

    echo "[PERMISSIONS] ERROR: ${label} remains non-writable: ${path}" >&2
    echo "[PERMISSIONS] ACTION: ${fix_hint}" >&2
    exit 1
}

echo "[PERMISSIONS] Current user: ${CURRENT_USER} (UID=${CURRENT_UID}, GID=${CURRENT_GID})"

check_writable_dir \
    "${OMERO_DIR}" \
    "OMERO user data" \
    "OMERO_USER_DATA_PATH" \
    "Set ownership on host path to ${CURRENT_UID}:${CURRENT_GID} and permissions u+rwX before starting containers."

if [[ ! -d "${CERTS_DIR}" ]]; then
    echo "[PERMISSIONS] Creating certificate directory: ${CERTS_DIR}"
    mkdir -p "${CERTS_DIR}"
    chmod 0750 "${CERTS_DIR}"
fi

check_writable_dir \
    "${CERTS_DIR}" \
    "OMERO certificates" \
    "OMERO_USER_DATA_PATH" \
    "Ensure ${CERTS_DIR} exists and is writable by UID ${CURRENT_UID}."

check_writable_dir \
    "${SERVER_VAR_DIR}" \
    "OMERO server var" \
    "OMERO_SERVER_VAR_PATH" \
    "Set ownership on OMERO_SERVER_VAR_PATH to ${CURRENT_UID}:${CURRENT_GID} and restart."

if [[ ! -d "${SERVER_LOG_DIR}" ]]; then
    echo "[PERMISSIONS] Creating server log directory: ${SERVER_LOG_DIR}"
    mkdir -p "${SERVER_LOG_DIR}"
fi

check_writable_dir \
    "${SERVER_LOG_DIR}" \
    "OMERO server logs" \
    "OMERO_SERVER_LOGS_PATH" \
    "Set ownership on OMERO_SERVER_LOGS_PATH to ${CURRENT_UID}:${CURRENT_GID} and restart."

echo
echo "[PERMISSIONS] ✓✓✓ All runtime permission checks passed ✓✓✓"
echo "========================================="
