#!/usr/bin/env bash

install_transcript_timestamp_utc() {
    if [ -n "${OMERO_INSTALL_TRANSCRIPT_TIMESTAMP:-}" ]; then
        printf '%s' "${OMERO_INSTALL_TRANSCRIPT_TIMESTAMP}"
        return 0
    fi

    date -u +%Y%m%dT%H%M%SZ
}

install_transcript_load_paths_env_value() {
    local env_file_path="$1"
    local variable_name="$2"
    local env_line=""

    if [ ! -r "${env_file_path}" ]; then
        return 1
    fi

    (
        while IFS= read -r env_line || [ -n "${env_line}" ]; do
            case "${env_line}" in
                ''|'#'*)
                    continue
                    ;;
                [A-Za-z_]*=*)
                    eval "${env_line}"
                    ;;
            esac
        done < "${env_file_path}"

        printf '%s' "${!variable_name:-}"
    )
}

install_transcript_resolve_final_path() {
    local source_name="$1"
    local env_file_path="$2"
    local preferred_data_path="${3:-}"
    local data_path=""
    local timestamp_utc=""

    if [ -n "${preferred_data_path}" ]; then
        data_path="${preferred_data_path}"
    else
        data_path="$(install_transcript_load_paths_env_value "${env_file_path}" "OMERO_DATA_PATH" || true)"
    fi

    if [ -z "${data_path}" ]; then
        return 1
    fi

    timestamp_utc="$(install_transcript_timestamp_utc)"
    printf '%s/installation_logs/%s_%s.log' "${data_path%/}" "${source_name}" "${timestamp_utc}"
}

install_transcript_publish_final_path_if_needed() {
    local source_name="$1"
    local env_file_path="$2"
    local preferred_data_path="${3:-}"
    local final_path=""
    local metadata_path="${OMERO_INSTALL_TRANSCRIPT_FINAL_PATH_FILE:-}"

    if [ "${OMERO_INSTALL_TRANSCRIPT_ACTIVE:-0}" != "1" ] || [ -z "${metadata_path}" ]; then
        return 0
    fi

    final_path="$(install_transcript_resolve_final_path "${source_name}" "${env_file_path}" "${preferred_data_path}" || true)"
    if [ -z "${final_path}" ]; then
        return 0
    fi

    mkdir -p "$(dirname "${metadata_path}")"
    printf '%s\n' "${final_path}" > "${metadata_path}"
    chmod 0600 "${metadata_path}" 2>/dev/null || true
    echo "Installation transcript will be saved to: ${final_path}"
}

install_transcript_record_text() {
    local text="${1:-}"

    if [ "${OMERO_INSTALL_TRANSCRIPT_MODE:-}" != "tee" ] || [ -z "${OMERO_INSTALL_TRANSCRIPT_TMP_LOG:-}" ]; then
        return 0
    fi

    printf '%s' "${text}" >> "${OMERO_INSTALL_TRANSCRIPT_TMP_LOG}"
}

install_transcript_record_line() {
    local text="${1:-}"

    if [ "${OMERO_INSTALL_TRANSCRIPT_MODE:-}" != "tee" ] || [ -z "${OMERO_INSTALL_TRANSCRIPT_TMP_LOG:-}" ]; then
        return 0
    fi

    printf '%s\n' "${text}" >> "${OMERO_INSTALL_TRANSCRIPT_TMP_LOG}"
}

install_transcript_build_reexec_command() {
    local mode="$1"
    local script_path="$2"
    shift 2

    local -a cmd=(
        env
        "OMERO_INSTALL_TRANSCRIPT_ACTIVE=1"
        "OMERO_INSTALL_TRANSCRIPT_MODE=${mode}"
        "OMERO_INSTALL_TRANSCRIPT_TIMESTAMP=${OMERO_INSTALL_TRANSCRIPT_TIMESTAMP}"
        "OMERO_INSTALL_TRANSCRIPT_TMP_LOG=${OMERO_INSTALL_TRANSCRIPT_TMP_LOG}"
        "OMERO_INSTALL_TRANSCRIPT_FINAL_PATH_FILE=${OMERO_INSTALL_TRANSCRIPT_FINAL_PATH_FILE}"
        "OMERO_INSTALL_TRANSCRIPT_SOURCE_NAME=${OMERO_INSTALL_TRANSCRIPT_SOURCE_NAME}"
        bash
        "${script_path}"
    )

    if [ "$#" -gt 0 ]; then
        cmd+=("$@")
    fi

    printf '%q ' "${cmd[@]}"
}

install_transcript_finalize() {
    local temp_log_path="$1"
    local metadata_path="$2"
    local source_name="$3"
    local env_file_path="$4"
    local final_path=""
    local final_dir=""
    local fallback_base="${TMPDIR:-/tmp}"

    if [ -r "${metadata_path}" ]; then
        final_path="$(head -n 1 "${metadata_path}" || true)"
    fi

    if [ -z "${final_path}" ]; then
        final_path="$(install_transcript_resolve_final_path "${source_name}" "${env_file_path}" "" || true)"
    fi

    if [ -z "${final_path}" ]; then
        final_path="${fallback_base%/}/${source_name}_$(install_transcript_timestamp_utc).log"
    fi

    final_dir="$(dirname "${final_path}")"
    install -d -m 0700 "${final_dir}"
    mv "${temp_log_path}" "${final_path}"
    chmod 0600 "${final_path}" 2>/dev/null || true
    rm -f "${metadata_path}" 2>/dev/null || true
    printf '%s\n' "${final_path}"
}

install_transcript_enable() {
    local env_file_path="$1"
    local script_path="$2"
    shift 2

    if [ "${OMERO_INSTALL_TRANSCRIPT_ACTIVE:-0}" = "1" ]; then
        return 0
    fi

    local source_name
    local temp_log_path=""
    local metadata_path=""
    local final_path=""
    local run_mode="tee"
    local rc=0

    source_name="$(basename "${script_path}")"
    temp_log_path="$(mktemp "${TMPDIR:-/tmp}/omero-install-transcript.XXXXXX.log")"
    metadata_path="$(mktemp "${TMPDIR:-/tmp}/omero-install-transcript-dest.XXXXXX.txt")"

    OMERO_INSTALL_TRANSCRIPT_TIMESTAMP="$(install_transcript_timestamp_utc)"
    OMERO_INSTALL_TRANSCRIPT_TMP_LOG="${temp_log_path}"
    OMERO_INSTALL_TRANSCRIPT_FINAL_PATH_FILE="${metadata_path}"
    OMERO_INSTALL_TRANSCRIPT_SOURCE_NAME="${source_name}"

    if command -v script >/dev/null 2>&1 && [ -t 0 ] && [ -t 1 ]; then
        local reexec_cmd=""
        local script_rc=0
        local tee_rc=0

        run_mode="script"
        reexec_cmd="$(install_transcript_build_reexec_command "${run_mode}" "${script_path}" "$@")"

        set +e
        script -qefc "${reexec_cmd}" /dev/null | tee "${temp_log_path}"
        script_rc="${PIPESTATUS[0]}"
        tee_rc="${PIPESTATUS[1]}"
        set -e

        rc="${script_rc}"
        if [ "${tee_rc}" -ne 0 ] && [ "${rc}" -eq 0 ]; then
            rc="${tee_rc}"
        fi
    else
        set +e
        env \
            OMERO_INSTALL_TRANSCRIPT_ACTIVE=1 \
            OMERO_INSTALL_TRANSCRIPT_MODE="${run_mode}" \
            OMERO_INSTALL_TRANSCRIPT_TIMESTAMP="${OMERO_INSTALL_TRANSCRIPT_TIMESTAMP}" \
            OMERO_INSTALL_TRANSCRIPT_TMP_LOG="${OMERO_INSTALL_TRANSCRIPT_TMP_LOG}" \
            OMERO_INSTALL_TRANSCRIPT_FINAL_PATH_FILE="${OMERO_INSTALL_TRANSCRIPT_FINAL_PATH_FILE}" \
            OMERO_INSTALL_TRANSCRIPT_SOURCE_NAME="${OMERO_INSTALL_TRANSCRIPT_SOURCE_NAME}" \
            bash "${script_path}" "$@" > >(tee "${temp_log_path}") 2>&1
        rc=$?
        set -e
    fi

    final_path="$(install_transcript_finalize "${temp_log_path}" "${metadata_path}" "${source_name}" "${env_file_path}")"
    echo "Saved installation transcript: ${final_path}"
    exit "${rc}"
}
