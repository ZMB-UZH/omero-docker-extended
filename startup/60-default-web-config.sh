#!/usr/bin/env bash
# Override omero.web.server_list with OMEROHOST if set.

set -euo pipefail

# Resolve OMERO bin. Inputs: shell arguments and environment. Output: stdout text and command status.
resolve_omero_bin() {
    local explicit="${OMERO_WEB_OMERO_BIN:-${OMERO_BIN:-}}"
    local web_root="${OMERO_WEB_ROOT:-}"
    local configured_venv="${OMERO_WEB_VENV:-}"
    local configured_root=""
    local venv_dir=""

    if [[ -n "${explicit}" ]]; then
        printf '%s\n' "${explicit}"
        return 0
    fi

    if command -v omero >/dev/null 2>&1; then
        command -v omero
        return 0
    fi

    if [[ -z "${web_root}" ]]; then
        echo "ERROR: OMERO_WEB_ROOT is required for OMERO.web virtualenv discovery." >&2
        return 1
    fi

    if [[ -n "${configured_venv}" ]]; then
        if [[ "${configured_venv}" == /* ]]; then
            configured_root="${configured_venv}"
        else
            configured_root="${web_root%/}/${configured_venv}"
        fi
    fi

    if [[ -n "${configured_root}" && -x "${configured_root}/bin/omero" ]]; then
        printf '%s\n' "${configured_root}/bin/omero"
        return 0
    fi

    venv_dir="$(find "${web_root}" -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"
    if [[ -n "${venv_dir}" && -x "${venv_dir}/bin/omero" ]]; then
        printf '%s\n' "${venv_dir}/bin/omero"
        return 0
    fi

    echo "ERROR: Could not resolve OMERO CLI for default OMERO.web config bootstrap" >&2
    return 1
}

omero_bin="$(resolve_omero_bin)"
omero_host="${OMEROHOST:-}"
omero_port="${OMERO_PORT:-}"

case "${omero_port}" in
    ""|*[!0-9]*)
        echo "ERROR: OMERO_PORT must be an integer TCP port." >&2
        exit 1
        ;;
esac

if (( omero_port < 1 || omero_port > 65535 )); then
    echo "ERROR: OMERO_PORT must be between 1 and 65535." >&2
    exit 1
fi

if [[ -n "${omero_host}" ]]; then
    "${omero_bin}" config set omero.web.server_list "[[\"${omero_host}\", ${omero_port}, \"omero\"]]"
fi
