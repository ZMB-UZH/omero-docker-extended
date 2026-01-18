#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Ensure OMERO SSL certificates include Docker hostname (omeroserver)
# This is REQUIRED for secure BlitzGateway connections from OMERO.web.
#
# This block is:
# - idempotent
# - safe on existing systems
# - automatic (no manual steps)
# -----------------------------------------------------------------------------

CERT_DIR="/OMERO/certs"
CERT_PEM="${CERT_DIR}/server.pem"

NEED_REGEN=0

if [ ! -f "${CERT_PEM}" ]; then
    echo "[CERT] server.pem missing – will generate certificates"
    NEED_REGEN=1
else
    # Check whether certificate already includes DNS:omeroserver
    if ! openssl x509 -in "${CERT_PEM}" -noout -text | grep -q "DNS:omeroserver"; then
        echo "[CERT] server.pem does not include DNS:omeroserver – regenerating"
        NEED_REGEN=1
    fi
fi

if [ "${NEED_REGEN}" -eq 1 ]; then
    echo "[CERT] Generating OMERO certificates with SANs: localhost, omeroserver"

    rm -f "${CERT_DIR}/server."* || true

    /opt/omero/server/OMERO.server/bin/omero certificates \
        --overwrite \
        --hostname localhost \
        --san DNS:localhost,DNS:omeroserver

    echo "[CERT] Certificate generation complete"
else
    echo "[CERT] Existing certificates already valid – no regeneration needed"
fi
