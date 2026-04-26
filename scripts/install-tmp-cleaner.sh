#!/usr/bin/env bash
# =============================================================================
# install-tmp-cleaner.sh — Install the OMERO host-side temporary cleanup service
#
# Installs:
#   - /usr/local/sbin/omero-tmp-cleaner
#   - /etc/systemd/system/omero-tmp-cleaner.service
#   - /etc/systemd/system/omero-tmp-cleaner.timer
#
# Compatible with Ubuntu 24.04+ and Debian 13 (Trixie)+.
#
# Usage:
#   sudo ./install-tmp-cleaner.sh <OMERO_TMP_PATH>
#
# Example:
#   sudo ./install-tmp-cleaner.sh /opt/omero/omero_temp
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_SYSTEM_DIR="${SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}"
LOCAL_SBIN_DIR="${LOCAL_SBIN_DIR:-/usr/local/sbin}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
TMP_CLEANER_BIN="${TMP_CLEANER_BIN:-${LOCAL_SBIN_DIR%/}/omero-tmp-cleaner}"

# shellcheck source=scripts/omero-host-service-lib.sh
source "${SCRIPT_DIR}/omero-host-service-lib.sh"

usage() {
    echo "Usage: $0 <OMERO_TMP_PATH>" >&2
    echo "  OMERO_TMP_PATH: Path to the OMERO temporary directory on the host" >&2
}

render_unit() {
    local source_file="$1"
    local dest_file="$2"

    omero_render_systemd_unit \
        "${source_file}" \
        "${dest_file}" \
        TMP_CLEANER_BIN "${TMP_CLEANER_BIN}" \
        OMERO_TMP_PATH "${OMERO_TMP_DIR}"
}

replace_managed_units() {
    omero_replace_systemd_units \
        "${SYSTEMCTL_BIN}" \
        "${SYSTEMD_SYSTEM_DIR}" \
        omero-tmp-cleaner.timer \
        omero-tmp-cleaner.service
}

install_cleaner_script() {
    local installed_sha

    installed_sha="$(
        omero_install_verified \
            "${SCRIPT_DIR}/omero-tmp-cleaner.sh" \
            "${TMP_CLEANER_BIN}" \
            0755
    )"
    echo "  Installed: ${TMP_CLEANER_BIN} (sha256=${installed_sha})"
}

install_systemd_units() {
    local service_dst timer_dst

    service_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.service"
    timer_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.timer"

    replace_managed_units
    render_unit "${SCRIPT_DIR}/omero-tmp-cleaner.service" "${service_dst}"
    install -D -m 0644 "${SCRIPT_DIR}/omero-tmp-cleaner.timer" "${timer_dst}"
    "${SYSTEMCTL_BIN}" daemon-reload

    echo "  Installed: ${service_dst}"
    echo "  Installed: ${timer_dst}"
}

enable_timer() {
    "${SYSTEMCTL_BIN}" reset-failed \
        omero-tmp-cleaner.service \
        omero-tmp-cleaner.timer >/dev/null 2>&1 || true
    "${SYSTEMCTL_BIN}" enable omero-tmp-cleaner.timer
    "${SYSTEMCTL_BIN}" start omero-tmp-cleaner.timer
    echo "  Enabled: omero-tmp-cleaner.timer"
}

main() {
omero_require_root

if [[ $# -ne 1 ]]; then
    usage
    exit 1
fi

OMERO_TMP_DIR="$(omero_canonical_existing_dir "$1" "OMERO_TMP_PATH")"

echo "=== OMERO Tmp Cleaner Installer ==="
echo ""
echo "OMERO tmp directory: ${OMERO_TMP_DIR}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Install cleaner script
# ---------------------------------------------------------------------------
echo "[1/4] Installing cleaner script..."
install_cleaner_script

# ---------------------------------------------------------------------------
# Step 2: Install systemd units
# ---------------------------------------------------------------------------
echo "[2/4] Installing systemd units..."
install_systemd_units

# ---------------------------------------------------------------------------
# Step 3: Enable + start timer
# ---------------------------------------------------------------------------
echo "[3/4] Enabling and starting timer..."
enable_timer

# ---------------------------------------------------------------------------
# Step 4: Helpful commands
# ---------------------------------------------------------------------------
echo "[4/4] Done."
echo ""
echo "=== Installation complete ==="
echo ""
echo "The tmp cleaner runs every 30 minutes and deletes artifacts older than 24 hours by default."
echo "Plugin-written deferred-cleanup markers can extend retention for specific paths when needed."
echo ""
echo "Useful commands:"
echo "  systemctl status omero-tmp-cleaner.timer     # Check timer status"
echo "  systemctl status omero-tmp-cleaner.service   # Check last run status"
echo "  journalctl -u omero-tmp-cleaner.service      # View cleanup logs"
echo "  sudo ${TMP_CLEANER_BIN} --tmp-dir ${OMERO_TMP_DIR}  # Run manually"
echo ""
echo "To uninstall:"
echo "  sudo systemctl disable --now omero-tmp-cleaner.timer"
echo "  sudo rm ${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.{service,timer}"
echo "  sudo rm ${TMP_CLEANER_BIN}"
echo "  sudo systemctl daemon-reload"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
