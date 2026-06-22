#!/usr/bin/env bash
# =============================================================================
# install-quota-enforcer.sh — Install the OMERO host-side quota enforcer
#
# Sets up systemd timer + service for ext4 project-quota enforcement.
# Compatible with Ubuntu 26.04 LTS and Debian 13 (Trixie).
#
# Usage:
#   sudo ./install-quota-enforcer.sh /path/to/OMERO/data
#
# Example:
#   sudo ./install-quota-enforcer.sh /data/OMERO
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_SYSTEM_DIR="${SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
DEFAULTS_FILE="${OMERO_QUOTA_DEFAULTS_FILE:-/etc/default/omero-quota-enforcer}"

# shellcheck source=scripts/omero-host-service-lib.sh
source "${SCRIPT_DIR}/omero-host-service-lib.sh"

# Print usage text. Inputs: shell arguments and environment. Output: command status and side effects.
usage() {
    echo "Usage: $0 <OMERO_DATA_DIR>" >&2
    echo "  OMERO_DATA_DIR: Path to the OMERO data directory on the host" >&2
    echo "                  (same as OMERO_USER_DATA_PATH in installation_paths.env)" >&2
}

# Render unit. Inputs: shell arguments and environment. Output: stdout text and command status.
render_unit() {
    local source_file="$1"
    local dest_file="$2"

    omero_render_systemd_unit \
        "${source_file}" \
        "${dest_file}" \
        DEFAULTS_FILE "${defaults_file}" \
        ENFORCER_PATH "${enforcer_dst}" \
        OMERO_DATA_DIR "${OMERO_DATA_DIR}" \
        QUOTA_STATE_FILE "${state_file}"
}

# Replace managed units. Inputs: shell arguments and environment. Output: command status and side effects.
replace_managed_units() {
    omero_replace_systemd_units \
        "${SYSTEMCTL_BIN}" \
        "${SYSTEMD_SYSTEM_DIR}" \
        omero-quota-enforcer.timer \
        omero-quota-enforcer.path \
        omero-quota-enforcer.service
}

# Install required packages. Inputs: shell arguments and environment. Output: command status and side effects.
install_required_packages() {
    omero_install_missing_deb_packages e2fsprogs quota python3 util-linux
}

# Verify project quota support. Inputs: shell arguments and environment. Output: command status and side effects.
verify_project_quota_support() {
    local fs_type mount_point block_device mount_options

    IFS=$'\t' read -r fs_type mount_point block_device mount_options \
        < <(omero_mount_context "${OMERO_DATA_DIR}")

    if [[ "${fs_type}" != "ext4" ]]; then
        echo "  WARNING: Filesystem is '${fs_type}', not ext4." >&2
        echo "  Project quotas only work on ext4. Continuing installation." >&2
        return 0
    fi

    if omero_mount_options_include "${mount_options}" prjquota \
        || omero_mount_options_include "${mount_options}" project; then
        echo "  Filesystem at ${mount_point} is mounted with project quotas."
    else
        echo "  WARNING: Filesystem at ${mount_point} is not mounted with prjquota." >&2
        echo "  Add 'prjquota' to /etc/fstab and remount:" >&2
        echo "    sudo mount -o remount,prjquota ${mount_point}" >&2
        echo "  Continuing installation." >&2
    fi

    if [[ "${block_device}" = /dev/* ]] && command -v tune2fs >/dev/null 2>&1; then
        if tune2fs -l "${block_device}" 2>/dev/null | grep -q "Filesystem features:.*project"; then
            echo "  ext4 'project' feature is enabled on ${block_device}."
        else
            echo "  WARNING: ext4 'project' feature is not enabled on ${block_device}." >&2
            echo "  Enable it with: sudo tune2fs -O project ${block_device}" >&2
        fi
    fi
}

# Install enforcer script. Inputs: shell arguments and environment. Output: command status and side effects.
install_enforcer_script() {
    local enforcer_src src_sha256

    enforcer_src="${SCRIPT_DIR}/omero-quota-enforcer.sh"
    OMERO_INSTALLATION_PATH="${OMERO_INSTALLATION_PATH:-${SCRIPT_DIR%/}/..}"
    OMERO_INSTALLATION_PATH="$(readlink -f -- "${OMERO_INSTALLATION_PATH}")"
    enforcer_dst="${OMERO_INSTALLATION_PATH%/}/scripts/omero-quota-enforcer.sh"

    src_sha256="$(omero_install_verified "${enforcer_src}" "${enforcer_dst}" 0755)"
    echo "  Installed: ${enforcer_dst} (sha256=${src_sha256})"
}

# Write defaults file. Inputs: shell arguments and environment. Output: command status and side effects.
write_defaults_file() {
    local quoted_data_dir quoted_managed_root quoted_min_quota
    local quoted_project_id_min quoted_projects_file quoted_projid_file quoted_state_file

    defaults_file="${DEFAULTS_FILE}"
    if [[ -f "${defaults_file}" ]]; then
        echo "  ${defaults_file} already exists; preserving existing configuration."
        return 0
    fi

    quoted_data_dir="$(omero_environment_quote "${OMERO_DATA_DIR}")"
    quoted_state_file="$(omero_environment_quote "${OMERO_DATA_DIR}/.admin-tools/group-quotas.json")"
    quoted_managed_root="$(omero_environment_quote "${OMERO_DATA_DIR}/ManagedRepository")"
    quoted_projects_file="$(omero_environment_quote "${OMERO_DATA_DIR}/.admin-tools/quota/projects")"
    quoted_projid_file="$(omero_environment_quote "${OMERO_DATA_DIR}/.admin-tools/quota/projid")"
    quoted_project_id_min="$(omero_environment_quote "200000")"
    quoted_min_quota="$(omero_environment_quote "0.10")"

    install -d -m 0755 "$(dirname -- "${defaults_file}")"
    cat > "${defaults_file}" <<DEFAULTS
# OMERO Quota Enforcer configuration
# Generated by install-quota-enforcer.sh on $(date -Iseconds)

# Path to the OMERO data directory on the host
OMERO_DATA_DIR=${quoted_data_dir}

# Quota state JSON (written by omeroweb container, read by this enforcer)
QUOTA_STATE_FILE=${quoted_state_file}

# Managed repository root
MANAGED_REPO_ROOT=${quoted_managed_root}

# Project-ID mapping files
PROJECTS_FILE=${quoted_projects_file}
PROJID_FILE=${quoted_projid_file}
PROJECT_ID_MIN=${quoted_project_id_min}

# Minimum quota value in GB
MIN_QUOTA_GB=${quoted_min_quota}
DEFAULTS
    echo "  Created: ${defaults_file}"
}

# Prepare admin tools directory. Inputs: shell arguments and environment. Output: command status and side effects.
prepare_admin_tools_dir() {
    install -d -m 0750 "${OMERO_DATA_DIR}/.admin-tools"
    install -d -m 0700 "${OMERO_DATA_DIR}/.admin-tools/quota"

    # The omeroweb bootstrap assigns the runtime UID/GID on container start.
    # The host installer only guarantees that quota paths are never
    # world-writable while still remaining readable by the root enforcer.
    state_file="${OMERO_DATA_DIR}/.admin-tools/group-quotas.json"
    if [[ -f "${state_file}" ]]; then
        chmod 0600 "${state_file}"
    else
        install -m 0600 /dev/null "${state_file}"
    fi

    echo "  Created: ${OMERO_DATA_DIR}/.admin-tools/ (mode 0750)"
    echo "  Created: ${OMERO_DATA_DIR}/.admin-tools/quota/ (mode 0700)"
    echo "  Ensured private quota state: ${state_file} (mode 0600)"
}

# Install systemd units. Inputs: shell arguments and environment. Output: command status and side effects.
install_systemd_units() {
    local service_dst timer_dst path_dst

    service_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-quota-enforcer.service"
    timer_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-quota-enforcer.timer"
    path_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-quota-enforcer.path"

    replace_managed_units
    render_unit "${SCRIPT_DIR}/omero-quota-enforcer.service" "${service_dst}"
    install -D -m 0644 "${SCRIPT_DIR}/omero-quota-enforcer.timer" "${timer_dst}"
    render_unit "${SCRIPT_DIR}/omero-quota-enforcer.path" "${path_dst}"

    "${SYSTEMCTL_BIN}" daemon-reload
    "${SYSTEMCTL_BIN}" reset-failed \
        omero-quota-enforcer.service \
        omero-quota-enforcer.timer \
        omero-quota-enforcer.path >/dev/null 2>&1 || true
    "${SYSTEMCTL_BIN}" enable omero-quota-enforcer.timer
    "${SYSTEMCTL_BIN}" start omero-quota-enforcer.timer
    "${SYSTEMCTL_BIN}" enable omero-quota-enforcer.path
    "${SYSTEMCTL_BIN}" start omero-quota-enforcer.path

    echo "  Installed and enabled: omero-quota-enforcer.timer (60s reconciliation)"
    echo "  Installed and enabled: omero-quota-enforcer.path  (inotify-triggered updates)"
}

# Write marker file. Inputs: shell arguments and environment. Output: command status and side effects.
write_marker_file() {
    local marker_file

    marker_file="${OMERO_DATA_DIR}/.admin-tools/quota-enforcer-installed"
    cat > "${marker_file}" <<MARKER
# This file is automatically written by install-quota-enforcer.sh.
# Its presence tells the omeroweb container that the host-side quota enforcer
# is installed and the Quotas tab in Admin Tools should be enabled.
# Do NOT delete this file unless you want to disable quota enforcement.
installed_at="$(date -Iseconds)"
omero_data_dir="${OMERO_DATA_DIR}"
MARKER
    echo "  Written: ${marker_file}"
}

# Execute the command entrypoint. Inputs: shell arguments and environment. Output: command status and side effects.
main() {
omero_require_root

if [[ $# -ne 1 ]]; then
    usage
    exit 1
fi

OMERO_DATA_DIR="$(omero_canonical_existing_dir "$1" "OMERO_DATA_DIR")"

echo "=== OMERO Quota Enforcer Installer ==="
echo ""
echo "OMERO data directory: ${OMERO_DATA_DIR}"
echo ""

echo "[1/7] Checking required packages..."
install_required_packages

echo "[2/7] Verifying ext4 project quota support..."
verify_project_quota_support

echo "[3/7] Installing enforcer script..."
install_enforcer_script

echo "[4/7] Creating configuration..."
write_defaults_file

echo "[5/7] Creating admin-tools directory..."
prepare_admin_tools_dir

echo "[6/7] Installing systemd units..."
install_systemd_units

echo "[7/7] Writing quota enforcer marker..."
write_marker_file

echo ""
echo "=== Installation complete ==="
echo ""
echo "The quota enforcer reacts to quota-state changes and reconciles every 60 seconds."
echo ""
echo "Useful commands:"
echo "  systemctl status omero-quota-enforcer.path     # Check file watcher status"
echo "  systemctl status omero-quota-enforcer.timer    # Check timer status"
echo "  journalctl -u omero-quota-enforcer.service     # View enforcement logs"
echo "  sudo ${enforcer_dst}  # Run manually"
echo ""
echo "To uninstall:"
echo "  sudo systemctl disable --now omero-quota-enforcer.timer omero-quota-enforcer.path"
echo "  sudo rm ${SYSTEMD_SYSTEM_DIR%/}/omero-quota-enforcer.{service,timer,path}"
echo "  sudo systemctl daemon-reload"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
