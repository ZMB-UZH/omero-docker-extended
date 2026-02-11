#!/usr/bin/env bash
#
# 00-check-and-fix-permissions.sh
# Automatically check and fix /OMERO directory permissions
# This ensures the container can write to /OMERO even if host permissions are wrong
#

set -euo pipefail

echo "========================================="
echo "[PERMISSIONS] Checking /OMERO directory"
echo "========================================="
echo

OMERO_DIR="/OMERO"
CERTS_DIR="/OMERO/certs"
CURRENT_UID="$(id -u)"
CURRENT_GID="$(id -g)"
CURRENT_USER="$(id -un)"

# Check if /OMERO exists
if [ ! -d "${OMERO_DIR}" ]; then
    echo "[PERMISSIONS] ERROR: ${OMERO_DIR} directory does not exist!" >&2
    echo "[PERMISSIONS] ERROR: Volume mount may be missing or incorrect." >&2
    exit 1
fi

echo "[PERMISSIONS] Current user: ${CURRENT_USER} (UID=${CURRENT_UID}, GID=${CURRENT_GID})"
echo "[PERMISSIONS] Checking ${OMERO_DIR}..."

# Check current ownership
OMERO_OWNER_UID=$(stat -c '%u' "${OMERO_DIR}" 2>/dev/null || echo "unknown")
OMERO_OWNER_GID=$(stat -c '%g' "${OMERO_DIR}" 2>/dev/null || echo "unknown")

echo "[PERMISSIONS] Current ownership: UID=${OMERO_OWNER_UID}, GID=${OMERO_OWNER_GID}"

# Test if writable
if touch "${OMERO_DIR}/.permission_test" 2>/dev/null; then
    rm -f "${OMERO_DIR}/.permission_test"
    echo "[PERMISSIONS] ✓ ${OMERO_DIR} is already writable"
else
    echo "[PERMISSIONS] ✗ ${OMERO_DIR} is NOT writable by current user"
    echo "[PERMISSIONS] Attempting to fix permissions..."
    
    # Try to fix ownership (this will only work if we have permission)
    if chown -R "${CURRENT_UID}:${CURRENT_GID}" "${OMERO_DIR}" 2>/dev/null; then
        echo "[PERMISSIONS] ✓ Successfully changed ownership to ${CURRENT_UID}:${CURRENT_GID}"
    else
        echo "[PERMISSIONS] ✗ Cannot change ownership (not running as root or directory is owned by different user)"
        echo "[PERMISSIONS]"
        echo "[PERMISSIONS] REQUIRED ACTION ON HOST:"
        echo "[PERMISSIONS]   sudo chown -R ${CURRENT_UID}:${CURRENT_GID} /opt/omero/omero_data/omero_user_data"
        echo "[PERMISSIONS]   sudo chmod -R u+rwX /opt/omero/omero_data/omero_user_data"
        echo "[PERMISSIONS]"
        echo "[PERMISSIONS] Then restart container: docker-compose down && docker-compose up -d"
        echo "[PERMISSIONS]"
        exit 1
    fi
    
    # Try to fix permissions
    if chmod -R u+rwX "${OMERO_DIR}" 2>/dev/null; then
        echo "[PERMISSIONS] ✓ Successfully set permissions"
    else
        echo "[PERMISSIONS] ⚠ Could not set all permissions, but may still work"
    fi
    
    # Verify fix worked
    if ! touch "${OMERO_DIR}/.permission_test" 2>/dev/null; then
        echo "[PERMISSIONS] ERROR: Still cannot write to ${OMERO_DIR} after fix attempt" >&2
        exit 1
    fi
    rm -f "${OMERO_DIR}/.permission_test"
    echo "[PERMISSIONS] ✓ Write test successful after fix"
fi

# Ensure certs directory exists with correct permissions
if [ ! -d "${CERTS_DIR}" ]; then
    echo "[PERMISSIONS] Creating ${CERTS_DIR}..."
    mkdir -p "${CERTS_DIR}"
    chmod 0750 "${CERTS_DIR}"
    echo "[PERMISSIONS] ✓ Created ${CERTS_DIR}"
else
    echo "[PERMISSIONS] ✓ ${CERTS_DIR} already exists"
fi

# Verify certs directory is writable
if ! touch "${CERTS_DIR}/.permission_test" 2>/dev/null; then
    echo "[PERMISSIONS] ERROR: ${CERTS_DIR} is not writable" >&2
    exit 1
fi
rm -f "${CERTS_DIR}/.permission_test"

echo "[PERMISSIONS] ✓ ${CERTS_DIR} is writable"
echo
echo "[PERMISSIONS] ✓✓✓ All permission checks passed ✓✓✓"
echo "========================================="
