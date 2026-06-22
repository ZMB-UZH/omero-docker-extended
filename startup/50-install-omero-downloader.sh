#!/bin/bash
set -euo pipefail

if [[ -z "${OMERO_DOWNLOADER_VERSION:-}" ]]; then
    echo "ERROR: OMERO_DOWNLOADER_VERSION is not set (expected from env/omeroserver.env)." >&2
    exit 1
fi
if [[ -z "${OMERO_DOWNLOADER_SHA256:-}" ]]; then
    echo "ERROR: OMERO_DOWNLOADER_SHA256 is not set (expected from env/omeroserver.env)." >&2
    exit 1
fi
if [[ "${#OMERO_DOWNLOADER_SHA256}" -ne 64 ]]; then
    echo "ERROR: OMERO_DOWNLOADER_SHA256 must be a 64-character SHA-256 digest." >&2
    exit 1
fi
case "${OMERO_DOWNLOADER_SHA256}" in
    *[!0123456789abcdefABCDEF]*)
        echo "ERROR: OMERO_DOWNLOADER_SHA256 must be a 64-character SHA-256 digest." >&2
        exit 1
        ;;
esac
if [[ -z "${OMERO_DOWNLOADER_SHA256}" ]]; then
    echo "ERROR: OMERO_DOWNLOADER_SHA256 must be a 64-character SHA-256 digest." >&2
    exit 1
fi

OMERO_DOWNLOADER_URL="https://github.com/ome/omero-downloader/releases/download/v${OMERO_DOWNLOADER_VERSION}/OMERO.downloader-${OMERO_DOWNLOADER_VERSION}-release.zip"
VERSION_FILE="/opt/omero/downloader/.version"

if [[ -f "${VERSION_FILE}" ]]; then
    INSTALLED_VERSION="$(cat "${VERSION_FILE}")"
else
    INSTALLED_VERSION=""
fi

if [[ "${INSTALLED_VERSION}" = "${OMERO_DOWNLOADER_VERSION}" && -x /opt/omero/downloader/download.sh ]]; then
    echo "OMERO.downloader ${OMERO_DOWNLOADER_VERSION} already installed."
    exit 0
fi

echo "Installing OMERO.downloader ${OMERO_DOWNLOADER_VERSION}..."
mkdir -p /opt/omero/downloader
curl -fsSL "${OMERO_DOWNLOADER_URL}" -o /tmp/omero-downloader.zip
printf '%s  %s\n' "${OMERO_DOWNLOADER_SHA256,,}" /tmp/omero-downloader.zip | sha256sum -c -
unzip -q /tmp/omero-downloader.zip -d /tmp
cp -a "/tmp/OMERO.downloader-${OMERO_DOWNLOADER_VERSION}/." /opt/omero/downloader/
chmod 0755 /opt/omero/downloader/download.sh
ln -sf /opt/omero/downloader/download.sh /usr/local/bin/omero-downloader
chown -R omero-server:omero-server /opt/omero/downloader
echo "${OMERO_DOWNLOADER_VERSION}" > "${VERSION_FILE}"
rm -rf /tmp/omero-downloader.zip "/tmp/OMERO.downloader-${OMERO_DOWNLOADER_VERSION}"
