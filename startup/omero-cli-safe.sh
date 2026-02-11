#!/usr/bin/env bash
set -euo pipefail

: "${OMERO_BIN:?OMERO_BIN must be set before sourcing startup/omero-cli-safe.sh}"
OMERO_CLI_USER="${OMERO_CLI_USER:-omero-server}"

run_omero() {
    if [[ "$(id -u)" -ne 0 ]]; then
        "${OMERO_BIN}" "$@"
        return
    fi

    if ! id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        echo "FATAL: user '${OMERO_CLI_USER}' not found; cannot run OMERO CLI safely." >&2
        exit 1
    fi

    if command -v runuser >/dev/null 2>&1; then
        runuser -u "${OMERO_CLI_USER}" -- "${OMERO_BIN}" "$@"
        return
    fi

    if command -v su >/dev/null 2>&1; then
        local cmd=()
        local part
        for part in "${OMERO_BIN}" "$@"; do
            cmd+=("$(printf '%q' "${part}")")
        done
        su -s /bin/bash "${OMERO_CLI_USER}" -c "${cmd[*]}"
        return
    fi

    echo "FATAL: neither runuser nor su is available to drop root before running OMERO CLI." >&2
    exit 1
}
