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

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must run as root (use sudo)." >&2
    exit 1
fi

OMERO_TMP_DIR="${1:-}"
if [[ -z "${OMERO_TMP_DIR}" ]]; then
    echo "Usage: $0 <OMERO_TMP_PATH>" >&2
    echo "  OMERO_TMP_PATH: Path to the OMERO temporary directory on the host" >&2
    exit 1
fi

OMERO_TMP_DIR="$(readlink -f "${OMERO_TMP_DIR}")"
if [[ ! -d "${OMERO_TMP_DIR}" ]]; then
    echo "ERROR: Directory does not exist: ${OMERO_TMP_DIR}" >&2
    exit 1
fi

echo "=== OMERO Tmp Cleaner Installer ==="
echo ""
echo "OMERO tmp directory: ${OMERO_TMP_DIR}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Install cleaner script
# ---------------------------------------------------------------------------
echo "[1/4] Installing cleaner script..."
install -m 0755 "${SCRIPT_DIR}/omero-tmp-cleaner.sh" /usr/local/sbin/omero-tmp-cleaner
echo "  Installed: /usr/local/sbin/omero-tmp-cleaner"

# ---------------------------------------------------------------------------
# Step 2: Install systemd units
# ---------------------------------------------------------------------------
echo "[2/4] Installing systemd units..."
service_src="${SCRIPT_DIR}/omero-tmp-cleaner.service"
timer_src="${SCRIPT_DIR}/omero-tmp-cleaner.timer"

service_dst="/etc/systemd/system/omero-tmp-cleaner.service"
timer_dst="/etc/systemd/system/omero-tmp-cleaner.timer"

sed "s|__OMERO_TMP_PATH__|${OMERO_TMP_DIR}|g" "${service_src}" > "${service_dst}"
install -m 0644 "${timer_src}" "${timer_dst}"

systemctl daemon-reload

echo "  Installed: ${service_dst}"
echo "  Installed: ${timer_dst}"

# ---------------------------------------------------------------------------
# Step 3: Enable + start timer
# ---------------------------------------------------------------------------
echo "[3/4] Enabling and starting timer..."
systemctl enable omero-tmp-cleaner.timer
systemctl start omero-tmp-cleaner.timer
echo "  Enabled: omero-tmp-cleaner.timer"

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
echo "  sudo /usr/local/sbin/omero-tmp-cleaner --tmp-dir ${OMERO_TMP_DIR}  # Run manually"
echo ""
echo "To uninstall:"
echo "  sudo systemctl disable --now omero-tmp-cleaner.timer"
echo "  sudo rm /etc/systemd/system/omero-tmp-cleaner.{service,timer}"
echo "  sudo rm /usr/local/sbin/omero-tmp-cleaner"
echo "  sudo systemctl daemon-reload"
