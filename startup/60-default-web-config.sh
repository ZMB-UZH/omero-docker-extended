#!/usr/bin/env bash
# Override omero.web.server_list with OMEROHOST if set.

set -euo pipefail

resolve_omero_bin() {
    local explicit="${OMERO_WEB_OMERO_BIN:-${OMERO_BIN:-}}"
    local venv_dir=""

    if [[ -n "${explicit}" ]]; then
        printf '%s\n' "${explicit}"
        return 0
    fi

    if command -v omero >/dev/null 2>&1; then
        command -v omero
        return 0
    fi

    if [[ -n "${OMERO_WEB_VENV:-}" && -x "/opt/omero/web/${OMERO_WEB_VENV}/bin/omero" ]]; then
        printf '%s\n' "/opt/omero/web/${OMERO_WEB_VENV}/bin/omero"
        return 0
    fi

    venv_dir="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"
    if [[ -n "${venv_dir}" && -x "${venv_dir}/bin/omero" ]]; then
        printf '%s\n' "${venv_dir}/bin/omero"
        return 0
    fi

    echo "ERROR: Could not resolve OMERO CLI for default OMERO.web config bootstrap" >&2
    return 1
}

omero_bin="$(resolve_omero_bin)"
omero_host="${OMEROHOST:-}"

if [[ -n "${omero_host}" ]]; then
    "${omero_bin}" config set omero.web.server_list "[[\"${omero_host}\", 4064, \"omero\"]]"
fi
