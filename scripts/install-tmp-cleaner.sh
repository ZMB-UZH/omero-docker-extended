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

systemd_quote() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '"%s"' "$value"
}

render_unit() {
    local source_file="$1"
    local dest_file="$2"
    local text tmp_file

    text="$(< "$source_file")"
    text="${text//__TMP_CLEANER_BIN__/$(systemd_quote "$TMP_CLEANER_BIN")}"
    text="${text//__OMERO_TMP_PATH__/$(systemd_quote "$OMERO_TMP_DIR")}"

    tmp_file="$(mktemp)"
    printf '%s\n' "$text" > "$tmp_file"
    install -D -m 0644 "$tmp_file" "$dest_file"
    rm -f "$tmp_file"
}

replace_managed_units() {
    "${SYSTEMCTL_BIN}" disable --now \
        omero-tmp-cleaner.timer \
        omero-tmp-cleaner.service >/dev/null 2>&1 || true
    rm -f \
        "${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.service" \
        "${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.timer"
}

main() {
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
install -D -m 0755 "${SCRIPT_DIR}/omero-tmp-cleaner.sh" "$TMP_CLEANER_BIN"
echo "  Installed: ${TMP_CLEANER_BIN}"

# ---------------------------------------------------------------------------
# Step 2: Install systemd units
# ---------------------------------------------------------------------------
echo "[2/4] Installing systemd units..."
service_src="${SCRIPT_DIR}/omero-tmp-cleaner.service"
timer_src="${SCRIPT_DIR}/omero-tmp-cleaner.timer"

service_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.service"
timer_dst="${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.timer"

replace_managed_units
render_unit "${service_src}" "${service_dst}"
install -m 0644 "${timer_src}" "${timer_dst}"

"${SYSTEMCTL_BIN}" daemon-reload

echo "  Installed: ${service_dst}"
echo "  Installed: ${timer_dst}"

# ---------------------------------------------------------------------------
# Step 3: Enable + start timer
# ---------------------------------------------------------------------------
echo "[3/4] Enabling and starting timer..."
"${SYSTEMCTL_BIN}" reset-failed omero-tmp-cleaner.service omero-tmp-cleaner.timer >/dev/null 2>&1 || true
"${SYSTEMCTL_BIN}" enable omero-tmp-cleaner.timer
"${SYSTEMCTL_BIN}" start omero-tmp-cleaner.timer
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
echo "  sudo ${TMP_CLEANER_BIN} --tmp-dir ${OMERO_TMP_DIR}  # Run manually"
echo ""
echo "To uninstall:"
echo "  sudo systemctl disable --now omero-tmp-cleaner.timer"
echo "  sudo rm ${SYSTEMD_SYSTEM_DIR%/}/omero-tmp-cleaner.{service,timer}"
echo "  sudo rm ${TMP_CLEANER_BIN}"
echo "  sudo systemctl daemon-reload"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
