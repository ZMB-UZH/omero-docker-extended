#!/usr/bin/env bash
set -euo pipefail

echo "[startup] Ensuring OMERO.server cert SAN includes localhost+omeroserver+IP SANs"

OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"

source /startup/omero-cli-safe.sh

CERT_DIR="/OMERO/certs"
SERVER_PEM="${CERT_DIR}/server.pem"

ensure_cert_directory_permissions() {
    if [[ "$(id -u)" -ne 0 ]]; then
        if [[ ! -d "${CERT_DIR}" || ! -w "${CERT_DIR}" ]]; then
            echo "[startup] ERROR: ${CERT_DIR} must exist and be writable when startup runs as non-root" >&2
            echo "[startup] ACTION: ensure host path mounted at /OMERO is writable by UID $(id -u)" >&2
            exit 1
        fi
        return
    fi

    if ! id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        echo "[startup] ERROR: OMERO CLI user '${OMERO_CLI_USER}' does not exist" >&2
        exit 1
    fi

    local target_uid target_gid
    target_uid="$(id -u "${OMERO_CLI_USER}")"
    target_gid="$(id -g "${OMERO_CLI_USER}")"

    mkdir -p "${CERT_DIR}"
    chown "${target_uid}:${target_gid}" "${CERT_DIR}"
    chmod 0750 "${CERT_DIR}"
}

need_regen=0

CONTAINER_IPV4="$(
    ip -4 addr show scope global 2>/dev/null \
        | awk '/inet /{sub(/\/.*/,"",$2); print $2; exit}' \
        || true
)"

SAN_VALUE="DNS:localhost,DNS:omeroserver,IP:127.0.0.1"
if [[ -n "${CONTAINER_IPV4}" && "${CONTAINER_IPV4}" != "127.0.0.1" ]]; then
    SAN_VALUE="${SAN_VALUE},IP:${CONTAINER_IPV4}"
fi

if [[ ! -f "${SERVER_PEM}" ]]; then
    echo "[startup] ${SERVER_PEM} missing -> regen"
    need_regen=1
else
    if ! openssl x509 -in "${SERVER_PEM}" -noout -text | grep -q "DNS:omeroserver"; then
        echo "[startup] SAN missing DNS:omeroserver -> regen"
        need_regen=1
    fi
    if ! openssl x509 -in "${SERVER_PEM}" -noout -text | grep -q "IP Address:127.0.0.1"; then
        echo "[startup] SAN missing IP Address:127.0.0.1 -> regen"
        need_regen=1
    fi
    if [[ -n "${CONTAINER_IPV4}" && "${CONTAINER_IPV4}" != "127.0.0.1" ]]; then
        if ! openssl x509 -in "${SERVER_PEM}" -noout -text | grep -q "IP Address:${CONTAINER_IPV4}"; then
            echo "[startup] SAN missing IP Address:${CONTAINER_IPV4} -> regen"
            need_regen=1
        fi
    fi
fi

if [[ "${need_regen}" -eq 1 ]]; then
    ensure_cert_directory_permissions

    echo "[startup] Removing old certs..."
    rm -f "${CERT_DIR}/server.key" \
          "${CERT_DIR}/server.pem" \
          "${CERT_DIR}/server.p12" \
          "${CERT_DIR}/ca.pem" \
          "${CERT_DIR}/ca.key" || true

    echo "[startup] Setting cert commonname + SAN and regenerating..."
    run_omero config set omero.certificates.commonname localhost
    run_omero config set omero.certificates.subjectAltName "${SAN_VALUE}"
    run_omero certificates

    echo "[startup] New cert SAN:"
    openssl x509 -in "${SERVER_PEM}" -noout -text | awk '/Subject Alternative Name/{print;getline;print}'
else
    echo "[startup] Cert SAN already OK"
fi
