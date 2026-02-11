#!/usr/bin/env bash
set -euo pipefail

echo "[CERT] Ensuring OMERO certificate SAN includes DNS:omeroserver"

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"

source /startup/omero-cli-safe.sh

CERT_DIR="/OMERO/certs"
CERT_PEM="${CERT_DIR}/server.pem"

NEED_REGEN=0

if [ ! -f "${CERT_PEM}" ]; then
    echo "[CERT] server.pem missing"
    NEED_REGEN=1
else
    if ! openssl x509 -in "${CERT_PEM}" -noout -text | grep -q "DNS:omeroserver"; then
        echo "[CERT] server.pem missing DNS:omeroserver"
        NEED_REGEN=1
    fi
fi

if [ "${NEED_REGEN}" -eq 1 ]; then
    echo "[CERT] Configuring OMERO certificate parameters"

    run_omero config set omero.certificates.commonname localhost
    run_omero config set omero.certificates.subjectAltName "DNS:localhost,DNS:omeroserver"

    echo "[CERT] Removing old certificates"
    rm -f "${CERT_DIR}/server."* || true

    echo "[CERT] Generating certificates via 'omero certificates'"
    run_omero certificates

    echo "[CERT] Certificate generation complete"
else
    echo "[CERT] Existing certificate already valid"
fi
