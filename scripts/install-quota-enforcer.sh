#!/usr/bin/env bash
# =============================================================================
# install-quota-enforcer.sh — Install the OMERO host-side quota enforcer
#
# Sets up systemd timer + service for ext4 project-quota enforcement.
# Compatible with Ubuntu 24.04+ and Debian 13 (Trixie)+.
#
# Usage:
#   sudo ./install-quota-enforcer.sh /path/to/OMERO/data
#
# Example:
#   sudo ./install-quota-enforcer.sh /data/OMERO
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must run as root (use sudo)." >&2
    exit 1
fi

OMERO_DATA_DIR="${1:-}"
if [[ -z "$OMERO_DATA_DIR" ]]; then
    echo "Usage: $0 <OMERO_DATA_DIR>" >&2
    echo "  OMERO_DATA_DIR: Path to the OMERO data directory on the host" >&2
    echo "                  (same as OMERO_USER_DATA_PATH in installation_paths.env)" >&2
    exit 1
fi

OMERO_DATA_DIR="$(readlink -f "$OMERO_DATA_DIR")"
if [[ ! -d "$OMERO_DATA_DIR" ]]; then
    echo "ERROR: Directory does not exist: $OMERO_DATA_DIR" >&2
    exit 1
fi

echo "=== OMERO Quota Enforcer Installer ==="
echo ""
echo "OMERO data directory: $OMERO_DATA_DIR"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Check and install required packages
# ---------------------------------------------------------------------------
echo "[1/7] Checking required packages..."

missing_packages=()
for pkg in e2fsprogs quota; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        missing_packages+=("$pkg")
    fi
done

if [[ ${#missing_packages[@]} -gt 0 ]]; then
    echo "  Installing missing packages: ${missing_packages[*]}"
    apt-get update -qq
    apt-get install -y -qq "${missing_packages[@]}"
else
    echo "  All required packages are installed."
fi

# ---------------------------------------------------------------------------
# Step 2: Verify filesystem supports project quotas
# ---------------------------------------------------------------------------
echo "[2/7] Verifying ext4 project quota support..."

mount_point=""
fs_type=""
block_device=""
while read -r line; do
    parts=($line)
    if [[ ${#parts[@]} -lt 3 ]]; then continue; fi
    mp="${parts[1]}"
    ft="${parts[2]}"
    # Append trailing slash to both paths to ensure correct prefix matching.
    # Without this, mount point /data would incorrectly match /datafiles/OMERO.
    case "${OMERO_DATA_DIR%/}/" in
        "${mp%/}/"*)
            if [[ -z "$mount_point" ]] || [[ ${#mp} -gt ${#mount_point} ]]; then
                mount_point="$mp"
                fs_type="$ft"
                block_device="${parts[0]}"
            fi
            ;;
    esac
done < /proc/mounts

if [[ "$fs_type" != "ext4" ]]; then
    echo "  WARNING: Filesystem is '$fs_type', not ext4." >&2
    echo "  Project quotas only work on ext4. Continuing anyway..." >&2
fi

if [[ "$fs_type" == "ext4" ]]; then
    # Check prjquota mount option
    if mount | grep -qE "on ${mount_point} .*prjquota"; then
        echo "  Filesystem at $mount_point is mounted with prjquota."
    else
        echo "  WARNING: Filesystem at $mount_point is NOT mounted with prjquota." >&2
        echo "  You need to:" >&2
        echo "    1. Add 'prjquota' to mount options in /etc/fstab" >&2
        echo "    2. Remount: sudo mount -o remount,prjquota $mount_point" >&2
        echo "  Continuing installation..." >&2
    fi

    # Check project feature in superblock
    if [[ -n "$block_device" ]] && command -v tune2fs >/dev/null 2>&1; then
        if tune2fs -l "$block_device" 2>/dev/null | grep -q "project"; then
            echo "  ext4 'project' feature is enabled on $block_device."
        else
            echo "  WARNING: ext4 'project' feature is NOT enabled on $block_device." >&2
            echo "  Enable it with: sudo tune2fs -O project $block_device" >&2
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Step 3: Install the enforcer script
# ---------------------------------------------------------------------------
echo "[3/7] Installing enforcer script..."

enforcer_src="${SCRIPT_DIR}/omero-quota-enforcer.sh"
OMERO_INSTALLATION_PATH="${OMERO_INSTALLATION_PATH:-${SCRIPT_DIR%/}/..}"
OMERO_INSTALLATION_PATH="$(readlink -f "$OMERO_INSTALLATION_PATH")"
enforcer_dst="${OMERO_INSTALLATION_PATH%/}/scripts/omero-quota-enforcer.sh"

src_sha256="$(sha256sum "$enforcer_src" | awk '{print $1}')"
dst_sha256=""
if [[ -f "$enforcer_dst" ]]; then
    dst_sha256="$(sha256sum "$enforcer_dst" | awk '{print $1}')"
fi

if [[ -f "$enforcer_dst" ]] && [[ "$src_sha256" == "$dst_sha256" ]]; then
    echo "  Enforcer script already installed with matching SHA256; refreshing permissions only."
    chmod 0755 "$enforcer_dst"
else
    install -D -m 0755 "$enforcer_src" "$enforcer_dst"
    installed_sha256="$(sha256sum "$enforcer_dst" | awk '{print $1}')"
    if [[ "$installed_sha256" != "$src_sha256" ]]; then
        echo "ERROR: Enforcer script integrity check failed after install." >&2
        echo "ERROR: expected_sha256=$src_sha256 actual_sha256=$installed_sha256" >&2
        exit 1
    fi
fi
echo "  Installed: $enforcer_dst (sha256=$src_sha256)"

# ---------------------------------------------------------------------------
# Step 4: Create /etc/default configuration
# ---------------------------------------------------------------------------
echo "[4/7] Creating configuration..."

defaults_file="/etc/default/omero-quota-enforcer"
if [[ -f "$defaults_file" ]]; then
    echo "  $defaults_file already exists — preserving existing configuration."
else
    cat > "$defaults_file" <<DEFAULTS
# OMERO Quota Enforcer configuration
# Generated by install-quota-enforcer.sh on $(date -Iseconds)

# Path to the OMERO data directory on the host
OMERO_DATA_DIR="${OMERO_DATA_DIR}"

# Quota state JSON (written by omeroweb container, read by this enforcer)
QUOTA_STATE_FILE="${OMERO_DATA_DIR}/.admin-tools/group-quotas.json"

# Managed repository root
MANAGED_REPO_ROOT="${OMERO_DATA_DIR}/ManagedRepository"

# Project-ID mapping files
PROJECTS_FILE="${OMERO_DATA_DIR}/.admin-tools/quota/projects"
PROJID_FILE="${OMERO_DATA_DIR}/.admin-tools/quota/projid"
PROJECT_ID_MIN=200000

# Minimum quota value in GB
MIN_QUOTA_GB=0.10
DEFAULTS
    echo "  Created: $defaults_file"
fi

# ---------------------------------------------------------------------------
# Step 5: Create .admin-tools directory on the OMERO volume
# ---------------------------------------------------------------------------
echo "[5/7] Creating admin-tools directory..."

mkdir -p "${OMERO_DATA_DIR}/.admin-tools/quota"
# The .admin-tools directory must be writable by both:
# - the host-side enforcer (root)
# - the omeroweb container (non-root)
#
# DO NOT use sticky-bit (1777) here: it can break atomic replace (os.replace)
# if group-quotas.json ownership differs from the current writer UID.
# Use 0777 (world-writable, no sticky) to allow safe atomic updates.
chmod 0777 "${OMERO_DATA_DIR}/.admin-tools"
chmod 0777 "${OMERO_DATA_DIR}/.admin-tools/quota"

# Ensure the quota state file remains writable for the non-root omeroweb
# container user even when this installer is executed as root during upgrades.
#
# Without this permission repair, existing root-owned 0644 files can cause
# PermissionError in omeroweb when updating quotas, which leaves host-side
# enforcement on stale quota state.
state_file="${OMERO_DATA_DIR}/.admin-tools/group-quotas.json"
if [[ -f "$state_file" ]]; then
    chmod 0666 "$state_file"
else
    install -m 0666 /dev/null "$state_file"
fi

echo "  Created: ${OMERO_DATA_DIR}/.admin-tools/ (mode 0777)"
echo "  Ensured writable quota state: ${state_file} (mode 0666)"

# ---------------------------------------------------------------------------
# Step 6: Install and enable systemd units
# ---------------------------------------------------------------------------
echo "[6/7] Installing systemd units..."

# Update the service ReadWritePaths to match actual OMERO data directory
sed "s|ReadWritePaths=/OMERO|ReadWritePaths=${OMERO_DATA_DIR}|g" \
    "${SCRIPT_DIR}/omero-quota-enforcer.service" \
    > /etc/systemd/system/omero-quota-enforcer.service

cp "${SCRIPT_DIR}/omero-quota-enforcer.timer" /etc/systemd/system/omero-quota-enforcer.timer

# Update the path unit to watch the actual JSON file for instant updates
sed "s|PathModified=.*|PathModified=${state_file}|g" \
    "${SCRIPT_DIR}/omero-quota-enforcer.path" \
    > /etc/systemd/system/omero-quota-enforcer.path

systemctl daemon-reload
systemctl enable omero-quota-enforcer.timer
systemctl start omero-quota-enforcer.timer

systemctl enable omero-quota-enforcer.path
systemctl start omero-quota-enforcer.path

echo "  Installed and enabled: omero-quota-enforcer.timer (60s fallback/reconciliation)"
echo "  Installed and enabled: omero-quota-enforcer.path  (instant updates via inotify)"

# ---------------------------------------------------------------------------
# Step 7: Write marker file for container-side detection
# ---------------------------------------------------------------------------
echo "[7/7] Writing quota enforcer marker..."

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

echo ""
echo "=== Installation complete ==="
echo ""
echo "The quota enforcer is now triggered INSTANTLY upon changes, and runs a fallback sweep every 60 seconds."
echo ""
echo "Useful commands:"
echo "  systemctl status omero-quota-enforcer.path     # Check file watcher status"
echo "  systemctl status omero-quota-enforcer.timer    # Check timer status"
echo "  journalctl -u omero-quota-enforcer.service     # View enforcement logs"
echo "  sudo ${enforcer_dst}  # Run manually"
echo ""
echo "To uninstall:"
echo "  sudo systemctl disable --now omero-quota-enforcer.timer omero-quota-enforcer.path"
echo "  sudo rm /etc/systemd/system/omero-quota-enforcer.{service,timer,path}"
echo "  sudo systemctl daemon-reload"
