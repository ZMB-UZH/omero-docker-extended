#!/bin/bash
################################################################################
# OMERO Downloader Installation Script
################################################################################
#
# PURPOSE:
#   Installs OMERO.downloader CLI tool at container startup if not present
#   or if version has changed. This enables bulk download of OMERO data.
#
# WHAT IT DOES:
#   1. Validates OMERO_DOWNLOADER_VERSION is set
#   2. Checks if the correct version is already installed
#   3. Downloads and extracts OMERO.downloader from GitHub releases
#   4. Installs to /opt/omero/downloader with correct ownership
#   5. Creates symlink in /usr/local/bin for easy CLI access
#   6. Records installed version to avoid redundant installations
#
# WHY THIS RUNS AT STARTUP:
#   - Allows version to be changed without rebuilding container
#   - Installation requires write access to /opt (available at runtime)
#   - Download happens only once per version
#
# INSTALLATION LOCATION:
#   - Installation: /opt/omero/downloader/
#   - Symlink: /usr/local/bin/omero-downloader
#   - Version tracking: /opt/omero/downloader/.version
#
# CONFIGURATION:
#   - OMERO_DOWNLOADER_VERSION: Required (set in env/omeroserver.env)
#
# IDEMPOTENCY:
#   - Checks version file before downloading
#   - Skips if correct version already installed
#   - Safe to run multiple times
#
################################################################################
set -euo pipefail

if [[ -z "${OMERO_DOWNLOADER_VERSION:-}" ]]; then
    echo "ERROR: OMERO_DOWNLOADER_VERSION is not set (expected from env/omeroserver.env)." >&2
    exit 1
fi

OMERO_DOWNLOADER_URL="https://github.com/ome/omero-downloader/releases/download/v${OMERO_DOWNLOADER_VERSION}/OMERO.downloader-${OMERO_DOWNLOADER_VERSION}-release.zip"
VERSION_FILE="/opt/omero/downloader/.version"

if [[ -f "${VERSION_FILE}" ]]; then
    INSTALLED_VERSION="$(cat "${VERSION_FILE}")"
else
    INSTALLED_VERSION=""
fi

if [[ "${INSTALLED_VERSION}" == "${OMERO_DOWNLOADER_VERSION}" && -x /opt/omero/downloader/download.sh ]]; then
    echo "OMERO.downloader ${OMERO_DOWNLOADER_VERSION} already installed."
    exit 0
fi

echo "Installing OMERO.downloader ${OMERO_DOWNLOADER_VERSION}..."
mkdir -p /opt/omero/downloader
curl -fsSL "${OMERO_DOWNLOADER_URL}" -o /tmp/omero-downloader.zip
unzip -q /tmp/omero-downloader.zip -d /tmp
cp -a "/tmp/OMERO.downloader-${OMERO_DOWNLOADER_VERSION}/." /opt/omero/downloader/
chmod 0755 /opt/omero/downloader/download.sh
ln -sf /opt/omero/downloader/download.sh /usr/local/bin/omero-downloader
chown -R omero-server:omero-server /opt/omero/downloader
echo "${OMERO_DOWNLOADER_VERSION}" > "${VERSION_FILE}"
rm -rf /tmp/omero-downloader.zip "/tmp/OMERO.downloader-${OMERO_DOWNLOADER_VERSION}"
