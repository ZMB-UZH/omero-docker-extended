#!/usr/bin/env bash
################################################################################
# OMERO.web Bootstrap Script
################################################################################
#
# PURPOSE:
#   Ensures OMERO.web log directory is writable before OMERO.web starts.
#   This prevents zarr/numcodecs logging failures during Python module imports.
#
# CRITICAL CHANGE:
#   CONFIG_omero_web_logdir now points directly to the mounted volume:
#   /opt/omero/web/OMERO.web/var/log (not /tmp/omero-web-logs)
#   
#   This matches the volume mount in docker-compose.yml and ensures logs
#   persist on the host filesystem.
#
# WHAT IT DOES:
#   1. Verifies log directory (from CONFIG_omero_web_logdir) is writable
#   2. If directory is a mountpoint, confirms it's accessible
#   3. If directory doesn't exist, creates it
#   4. Exits with error if log directory cannot be made writable
#
# WHY THIS IS CRITICAL:
#   - zarr library logs during import (before OMERO.web is fully initialized)
#   - If log directory isn't writable, concurrent_log_handler fails
#   - This causes OMERO.web startup to crash with emit(record) errors
#
# DEPENDENCIES:
#   - omero-data-init must run first to set host directory permissions
#   - Volume must be mounted at CONFIG_omero_web_logdir path
#
################################################################################
set -euo pipefail

log_dir="${CONFIG_omero_web_logdir:-/opt/omero/web/OMERO.web/var/log}"

echo "[web-bootstrap] Checking OMERO.web log directory: ${log_dir}"


configure_docker_socket_access() {
    local docker_socket="${ADMIN_TOOLS_DOCKER_SOCKET:-/var/run/docker.sock}"
    local target_user="${OMERO_WEB_RUNTIME_USER:-omero-web}"

    if [[ ! -S "${docker_socket}" ]]; then
        echo "[web-bootstrap] Docker socket not present at ${docker_socket}; skipping socket group bootstrap"
        return
    fi

    if [[ "$(id -u)" -ne 0 ]]; then
        echo "[web-bootstrap] Running unprivileged; cannot adjust docker socket group membership"
        return
    fi

    local socket_gid
    socket_gid="$(stat -c '%g' "${docker_socket}")"
    if [[ -z "${socket_gid}" ]]; then
        echo "[web-bootstrap] ERROR: Failed to resolve docker socket gid from ${docker_socket}" >&2
        exit 1
    fi

    local socket_group
    socket_group="$(getent group "${socket_gid}" | cut -d: -f1 || true)"
    if [[ -z "${socket_group}" ]]; then
        socket_group="docker-host"
        if getent group "${socket_group}" >/dev/null 2>&1; then
            socket_group="docker-host-${socket_gid}"
        fi
        groupadd -g "${socket_gid}" "${socket_group}"
        echo "[web-bootstrap] Created group ${socket_group} with gid ${socket_gid} for docker socket access"
    fi

    if ! id -nG "${target_user}" | tr ' ' '\012' | grep -qx "${socket_group}"; then
        usermod -aG "${socket_group}" "${target_user}"
        echo "[web-bootstrap] Added ${target_user} to group ${socket_group} (gid ${socket_gid})"
    else
        echo "[web-bootstrap] ${target_user} already in docker socket group ${socket_group}"
    fi
}


# Create log directory if it doesn't exist
mkdir -p "${log_dir}"

# Verify directory is writable
if [[ ! -d "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: Log directory does not exist and could not be created: ${log_dir}" >&2
    exit 1
fi

if [[ ! -w "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: Log directory is not writable: ${log_dir}" >&2
    echo "[web-bootstrap] This will cause zarr import to fail during OMERO.web startup" >&2
    echo "[web-bootstrap] Ensure omero-data-init has set correct permissions (UID:GID 1000:1000)" >&2
    ls -ld "${log_dir}" >&2 || true
    exit 1
fi

# Test write access
if ! touch "${log_dir}/.permission_test" 2>/dev/null; then
    echo "[web-bootstrap] ERROR: Cannot write to log directory: ${log_dir}" >&2
    ls -ld "${log_dir}" >&2 || true
    exit 1
fi

rm -f "${log_dir}/.permission_test"

if mountpoint -q "${log_dir}"; then
    echo "[web-bootstrap] Log directory is a mounted filesystem: ${log_dir}"
else
    echo "[web-bootstrap] Log directory is local (not mounted): ${log_dir}"
fi

echo "[web-bootstrap] ✓ OMERO.web log directory is ready and writable: ${log_dir}"

# ── Ensure .admin-tools directory is writable for quota state persistence ──
omero_data_dir="${OMERO_DATA_DIR:-/OMERO}"
admin_tools_dir="${omero_data_dir}/.admin-tools"
if [[ -d "${admin_tools_dir}" ]]; then
    if [[ ! -w "${admin_tools_dir}" ]]; then
        echo "[web-bootstrap] WARNING: ${admin_tools_dir} is not writable; attempting chmod 0777"
        chmod 0777 "${admin_tools_dir}" 2>/dev/null || \
            echo "[web-bootstrap] WARNING: Could not fix permissions on ${admin_tools_dir}. Quota state persistence may fail." >&2
    fi
else
    echo "[web-bootstrap] ${admin_tools_dir} does not exist yet; it will be created when the quota enforcer is installed"
fi

configure_docker_socket_access
