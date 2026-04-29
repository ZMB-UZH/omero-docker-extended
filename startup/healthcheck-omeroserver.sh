#!/usr/bin/env bash
set -euo pipefail

: "${ROOTPASS:?ROOTPASS is required for the OMERO.server healthcheck}"
: "${CONFIG_omero_managed_dir:?CONFIG_omero_managed_dir is required for the OMERO.server healthcheck}"
: "${OMERO_CLI_USER:?OMERO_CLI_USER is required for the OMERO.server healthcheck}"
: "${OMERO_CLI_HOST:?OMERO_CLI_HOST is required for the OMERO.server healthcheck}"
: "${OMERO_CLI_PORT:?OMERO_CLI_PORT is required for the OMERO.server healthcheck}"
: "${OMERO_TMPDIR:?OMERO_TMPDIR is required for the OMERO.server healthcheck}"
: "${OMERODIR:?OMERODIR is required for the OMERO.server healthcheck}"

case "${OMERO_CLI_PORT}" in
    ""|*[!0-9]*)
        echo "FATAL: OMERO_CLI_PORT must be an integer TCP port." >&2
        exit 1
        ;;
esac

if (( OMERO_CLI_PORT < 1 || OMERO_CLI_PORT > 65535 )); then
    echo "FATAL: OMERO_CLI_PORT must be between 1 and 65535." >&2
    exit 1
fi

resolve_omero_bin() {
    local candidate=""
    local server_root=""

    if [[ -n "${OMERO_BIN:-}" ]]; then
        [[ -x "${OMERO_BIN}" ]] || {
            echo "FATAL: OMERO_BIN is set but is not executable: ${OMERO_BIN}" >&2
            return 127
        }
        printf "%s\n" "${OMERO_BIN}"
        return 0
    fi

    server_root="$(dirname "${OMERODIR}")"
    for candidate in "${server_root}"/venv*/bin/omero "${OMERODIR}"/bin/omero; do
        [[ -x "${candidate}" ]] || continue
        printf "%s\n" "${candidate}"
        return 0
    done

    echo "FATAL: OMERO CLI executable not found from OMERODIR=${OMERODIR}" >&2
    return 127
}

resolve_cli_home() {
    local cli_home=""

    cli_home="$(getent passwd "${OMERO_CLI_USER}" | cut -d: -f6 2>/dev/null || true)"
    if [[ -z "${cli_home}" || ! -d "${cli_home}" ]]; then
        echo "FATAL: Could not resolve an existing HOME directory for ${OMERO_CLI_USER}" >&2
        return 1
    fi

    printf "%s\n" "${cli_home}"
}

normalize_dir_path() {
    local path="${1:?normalize_dir_path requires a path}"

    while [[ "${path}" != "/" && "${path%/}" != "${path}" ]]; do
        path="${path%/}"
    done
    printf "%s\n" "${path}"
}

omero_bin="$(resolve_omero_bin)"
cli_home="$(resolve_cli_home)"
server_root="$(dirname "${OMERODIR}")"

run_omero_cli() {
    local -a env_args=(
        HOME="${cli_home}"
        TMPDIR="${OMERO_TMPDIR}"
        OMERO_TMPDIR="${OMERO_TMPDIR}"
        OMERO_TEMPDIR="${OMERO_TMPDIR}"
    )

    if [[ -n "${OMERO_PASSWORD:-}" ]]; then
        env_args+=(
            OMERO_PASSWORD="${OMERO_PASSWORD}"
        )
    fi

    runuser -u "${OMERO_CLI_USER}" -- env \
        "${env_args[@]}" \
        "${omero_bin}" "$@"
}

if ! OMERO_PASSWORD="${ROOTPASS}" run_omero_cli -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" login -u root >/dev/null 2>/dev/null; then
    echo "FATAL: OMERO CLI login failed via configured service user ${OMERO_CLI_USER}" >&2
    exit 1
fi

expected_root="$(normalize_dir_path "${CONFIG_omero_managed_dir}")"
if ! actual_root="$(run_omero_cli config get omero.managed.dir 2>/dev/null | tr -d '\r\n')"; then
    echo "FATAL: failed to read omero.managed.dir via OMERO CLI" >&2
    exit 1
fi
if [[ -z "${actual_root}" ]]; then
    echo "FATAL: OMERO CLI returned an empty omero.managed.dir" >&2
    exit 1
fi
actual_root="$(normalize_dir_path "${actual_root}")"

if [[ "${actual_root}" != "${expected_root}" ]]; then
    echo "FATAL: omero.managed.dir drifted from expected value: expected=${expected_root} actual=${actual_root}" >&2
    exit 1
fi

bad_root="$(find "${server_root}" -type d -name ManagedRepository -print -quit 2>/dev/null || true)"
if [[ -n "${bad_root}" ]]; then
    echo "FATAL: unexpected image-local ManagedRepository detected at ${bad_root}" >&2
    exit 1
fi
