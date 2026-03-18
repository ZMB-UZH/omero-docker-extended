#!/usr/bin/env bash

log() {
    echo "[server-bootstrap] $*"
}

require_positive_integer_env_var() {
    local var_name="$1"
    local value="${!var_name-}"

    if [[ -z "${value+x}" ]]; then
        echo "ERROR: Required environment variable '${var_name}' is not set." >&2
        exit 1
    fi

    if [[ -z "${value}" ]]; then
        echo "ERROR: Required environment variable '${var_name}' is empty." >&2
        exit 1
    fi

    if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Required environment variable '${var_name}' must be a positive integer, got '${value}'." >&2
        exit 1
    fi

    if (( value <= 0 )); then
        echo "ERROR: Required environment variable '${var_name}' must be greater than 0, got '${value}'." >&2
        exit 1
    fi
}

OMERO_DIR="${OMERO_DIR:-/OMERO}"
CERTS_DIR="${CERTS_DIR:-${OMERO_DIR}/certs}"
SERVER_HOME="${SERVER_HOME:-/opt/omero/server/OMERO.server}"
SERVER_VAR_DIR="${SERVER_VAR_DIR:-${SERVER_HOME}/var}"
SERVER_LOG_DIR="${SERVER_LOG_DIR:-${SERVER_VAR_DIR}/log}"
REPO_ROOT_SYNC_STATUS_FILE="${SERVER_VAR_DIR}/repo-root-sync.status"
resolve_omero_bin() {
    local configured_bin="${OMERO_BIN:-}"
    if [[ -n "${configured_bin}" ]]; then
        if [[ -x "${configured_bin}" ]]; then
            printf "%s\n" "${configured_bin}"
            return 0
        fi
        echo "ERROR: OMERO_BIN is set but not executable: ${configured_bin}" >&2
        exit 1
    fi

    local candidate=""
    local server_root=""
    server_root="${SERVER_HOME%/*}"
    for candidate in "${server_root}"/venv*/bin/omero "${SERVER_HOME}"/bin/omero; do
        if [[ -x "${candidate}" ]]; then
            printf "%s\n" "${candidate}"
            return 0
        fi
    done

    for candidate in /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do
        if [[ -x "${candidate}" ]]; then
            printf "%s\n" "${candidate}"
            return 0
        fi
    done

    if command -v omero >/dev/null 2>&1; then
        command -v omero
        return 0
    fi

    echo "ERROR: Could not auto-detect an executable OMERO CLI binary. Set OMERO_BIN explicitly." >&2
    exit 1
}

OMERO_BIN="$(resolve_omero_bin)"
OMERO_CLI_USER="${OMERO_CLI_USER:-omero-server}"

resolve_server_venv_python() {
    local server_root=""
    local candidate=""

    server_root="${SERVER_HOME%/*}"
    for candidate in "${server_root}"/venv*/bin/python; do
        if [[ -x "${candidate}" ]]; then
            printf "%s\n" "${candidate}"
            return 0
        fi
    done

    echo "ERROR: Could not auto-detect an executable OMERO virtualenv python. Set SERVER_HOME explicitly." >&2
    exit 1
}

trim_whitespace() {
    printf "%s" "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

run_omero() {
    if [[ "$(id -u)" -ne 0 ]]; then
        "${OMERO_BIN}" "$@"
        return
    fi

    if ! id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        echo "FATAL: user '${OMERO_CLI_USER}' not found; cannot run OMERO CLI safely." >&2
        exit 1
    fi

    # Resolve HOME for the CLI user.  runuser without --login does NOT
    # change HOME, so the OMERO CLI would inherit root's HOME (/root) and
    # try to write session files to /root/omero/sessions/ — which the
    # omero-server user cannot access.  The installation script avoids this
    # by explicitly exporting HOME="/tmp".  We replicate that here so that
    # runtime sync commands behave identically to installation-time ones.
    local cli_home=""
    cli_home="$(getent passwd "${OMERO_CLI_USER}" | cut -d: -f6 2>/dev/null || echo "/tmp")"
    if [[ -z "${cli_home}" ]] || [[ ! -d "${cli_home}" ]]; then
        cli_home="/tmp"
    fi

    local -a env_args=(
        HOME="${cli_home}"
    )

    if [[ -n "${TMPDIR:-}" ]]; then
        env_args+=(
            TMPDIR="${TMPDIR}"
            OMERO_TMPDIR="${OMERO_TMPDIR:-}"
            OMERO_TEMPDIR="${OMERO_TEMPDIR:-}"
        )
    fi

    if [[ -n "${ICE_CONFIG:-}" ]]; then
        env_args+=(
            ICE_CONFIG="${ICE_CONFIG}"
        )
    fi

    # CRITICAL: runuser strips environment variables. We must EXPLICITLY pass them all.
    runuser -u "${OMERO_CLI_USER}" -- env \
        "${env_args[@]}" \
        "${OMERO_BIN}" "$@"
}

write_cli_keepalive_config() {
    local keepalive_seconds="${1:?BUG: write_cli_keepalive_config requires keepalive seconds}"
    local base_config="${ICE_CONFIG:-}"
    local target_dir="${TMPDIR:-/tmp}"
    local config_path=""
    local owner_uid=""
    local owner_gid=""

    if ! [[ "${keepalive_seconds}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Invalid OMERO CLI keepalive value: ${keepalive_seconds}" >&2
        return 1
    fi

    if (( keepalive_seconds <= 0 )); then
        return 1
    fi

    mkdir -p "${target_dir}" || {
        echo "ERROR: Could not prepare CLI keepalive directory: ${target_dir}" >&2
        return 1
    }

    config_path="$(mktemp "${target_dir%/}/omero-cli-ice.XXXXXX.cfg")" || {
        echo "ERROR: Could not create temporary ICE_CONFIG under ${target_dir}" >&2
        return 1
    }
    chmod 0600 "${config_path}" 2>/dev/null || true

    if [[ -n "${base_config}" ]]; then
        if [[ -r "${base_config}" ]]; then
            cat "${base_config}" > "${config_path}"
            if [[ -s "${config_path}" ]]; then
                printf '\n' >> "${config_path}"
            fi
        else
            log "WARN: Existing ICE_CONFIG is not readable; ignoring base config: ${base_config}"
        fi
    fi

    printf 'omero.keep_alive=%s\n' "${keepalive_seconds}" >> "${config_path}"

    if [[ "$(id -u)" -eq 0 ]] && id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        owner_uid="$(id -u "${OMERO_CLI_USER}")"
        owner_gid="$(id -g "${OMERO_CLI_USER}")"
        chown "${owner_uid}:${owner_gid}" "${config_path}" || {
            echo "ERROR: Could not hand temporary ICE_CONFIG to ${OMERO_CLI_USER}: ${config_path}" >&2
            rm -f "${config_path}" 2>/dev/null || true
            return 1
        }
    fi

    printf '%s\n' "${config_path}"
}

run_omero_with_keepalive() {
    local keepalive_seconds="${1:?BUG: run_omero_with_keepalive requires keepalive seconds}"
    shift

    local had_ice_config=0
    local previous_ice_config="${ICE_CONFIG:-}"
    local generated_ice_config=""
    local rc=0

    if [[ -n "${ICE_CONFIG+x}" ]]; then
        had_ice_config=1
    fi

    if [[ "${keepalive_seconds}" =~ ^[0-9]+$ ]] && (( keepalive_seconds > 0 )); then
        generated_ice_config="$(write_cli_keepalive_config "${keepalive_seconds}")" || return 1
        export ICE_CONFIG="${generated_ice_config}"
    fi

    run_omero "$@" || rc=$?

    if [[ -n "${generated_ice_config}" ]]; then
        rm -f "${generated_ice_config}" 2>/dev/null || true
    fi

    if [[ "${had_ice_config}" -eq 1 ]]; then
        export ICE_CONFIG="${previous_ice_config}"
    else
        unset ICE_CONFIG || true
    fi

    return "${rc}"
}

ensure_tmpdir_permissions() {
    local requested_owner="$1"
    local tmp_root="${OMERO_TMP_PATH:-}"
    local expected_tmp_dir=""
    local legacy_tmp_dir="$(dirname "${SERVER_HOME}")/omero/tmp"
    local runtime_tmp_dir=""
    if [[ -z "${tmp_root}" ]]; then
        echo "ERROR: OMERO_TMP_PATH is required for server bootstrap temp files but is not set." >&2
        exit 1
    fi

    expected_tmp_dir="${tmp_root%/}/${requested_owner}/tmp"

    if [[ -e "${tmp_root}" && ! -d "${tmp_root}" ]]; then
        echo "ERROR: OMERO tmp root exists but is not a directory: ${tmp_root}" >&2
        exit 1
    fi

    if ! mkdir -p "${expected_tmp_dir}"; then
        echo "ERROR: Failed to create OMERO temp directory: ${expected_tmp_dir}" >&2
        if [[ -d "${tmp_root}" ]]; then
            ls -ld "${tmp_root}" >&2 || true
        fi
        echo "ERROR: Ensure OMERO_TMP_PATH is executable and writable for both OMERO.server and OMERO.web users." >&2
        exit 1
    fi

    if [[ "$(id -u)" -eq 0 ]]; then
        chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" "${expected_tmp_dir}"
        chmod 0777 "${expected_tmp_dir}"
    fi

    if [[ ! -d "${expected_tmp_dir}" ]]; then
        echo "ERROR: OMERO temp directory missing after creation attempt: ${expected_tmp_dir}" >&2
        exit 1
    fi

    if [[ ! -w "${expected_tmp_dir}" ]]; then
        echo "ERROR: OMERO temp directory is not writable: ${expected_tmp_dir}" >&2
        ls -ld "${expected_tmp_dir}" >&2 || true
        exit 1
    fi

    prepare_runtime_tmp_dir() {
        local candidate_dir="$1"
        local candidate_omero_py_dir="${candidate_dir}/omero"
        local candidate_omero_py_user_dir="${candidate_dir}/omero_${requested_owner}"

        mkdir -p "${candidate_dir}" || return 1

        if [[ "$(id -u)" -eq 0 ]]; then
            chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" "${candidate_dir}" 2>/dev/null || true
            chmod 0777 "${candidate_dir}" 2>/dev/null || true
        fi

        if [[ ! -w "${candidate_dir}" ]]; then
            log "WARN: Candidate runtime temp directory is not writable: ${candidate_dir}"
            ls -ld "${candidate_dir}" >&2 || true
            return 1
        fi

        rm -rf "${candidate_omero_py_dir}" "${candidate_omero_py_user_dir}" "${candidate_dir}/omero_${requested_owner}"_* 2>/dev/null || true

        if [[ -d "${candidate_omero_py_user_dir}" ]] && [[ "$(id -u)" -eq 0 ]]; then
            log "WARN: Root cleanup of ${candidate_omero_py_user_dir} incomplete. Retrying as ${requested_owner}."
            runuser -u "${requested_owner}" -- rm -rf "${candidate_omero_py_user_dir}" 2>/dev/null || true
        fi
        if [[ -d "${candidate_omero_py_dir}" ]] && [[ "$(id -u)" -eq 0 ]]; then
            log "WARN: Root cleanup of ${candidate_omero_py_dir} incomplete. Retrying as ${requested_owner}."
            runuser -u "${requested_owner}" -- rm -rf "${candidate_omero_py_dir}" 2>/dev/null || true
        fi

        if [[ -d "${candidate_omero_py_user_dir}" || -d "${candidate_omero_py_dir}" ]]; then
            log "WARN: Candidate runtime temp directory still contains stale OMERO lock state: ${candidate_dir}"
            ls -la "${candidate_dir}" >&2 || true
            return 1
        fi

        mkdir -p "${candidate_omero_py_dir}" "${candidate_omero_py_user_dir}" || return 1
        if [[ "$(id -u)" -eq 0 ]]; then
            chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" "${candidate_omero_py_dir}" "${candidate_omero_py_user_dir}" 2>/dev/null || true
            chmod 0777 "${candidate_omero_py_dir}" "${candidate_omero_py_user_dir}" 2>/dev/null || true
        fi

        return 0
    }

    local candidate_dir=""
    for candidate_dir in \
        "${expected_tmp_dir}/runtime" \
        "${expected_tmp_dir}/runtime-1" \
        "${expected_tmp_dir}/runtime-2" \
        "${expected_tmp_dir}/runtime-3"
    do
        if prepare_runtime_tmp_dir "${candidate_dir}"; then
            runtime_tmp_dir="${candidate_dir}"
            break
        fi
    done

    if [[ -z "${runtime_tmp_dir}" ]]; then
        echo "ERROR: Could not prepare a clean OMERO runtime temp directory under ${expected_tmp_dir}" >&2
        exit 1
    fi

    export TMPDIR="${runtime_tmp_dir}"
    export OMERO_TEMPDIR="${runtime_tmp_dir}"
    export OMERO_TMPDIR="${runtime_tmp_dir}"

    local omero_py_dir="${runtime_tmp_dir}/omero"
    local omero_py_user_dir="${runtime_tmp_dir}/omero_${requested_owner}"
    local legacy_omero_py_user_dir="${expected_tmp_dir}/omero_${requested_owner}"

    # CRITICAL: Always try to remove stale OMERO temp subdirs to prevent Python
    # TempFileManager from hitting PermissionError on .lock files left by previous
    # container runs (PID-based subdirs like omero_omero-server/1530/.lock).
    #
    # Strategy: try as root first, then fall back to the target user.
    # Root cleanup can fail silently on NFS with root_squash (root is mapped to
    # nobody and cannot delete files owned by omero-server).  Running as the
    # target user handles that case.
    rm -rf "${omero_py_dir}" "${omero_py_user_dir}" "${legacy_omero_py_user_dir}" "${expected_tmp_dir}/omero_${requested_owner}"_* 2>/dev/null || true

    # If the root cleanup failed (e.g. NFS root_squash), retry as the target user.
    if [[ -d "${omero_py_user_dir}" ]] && [[ "$(id -u)" -eq 0 ]]; then
        log "WARN: Root cleanup of ${omero_py_user_dir} incomplete (NFS root_squash?). Retrying as ${requested_owner}."
        runuser -u "${requested_owner}" -- rm -rf "${omero_py_user_dir}" 2>/dev/null || true
    fi
    if [[ -d "${omero_py_dir}" ]] && [[ "$(id -u)" -eq 0 ]]; then
        log "WARN: Root cleanup of ${omero_py_dir} incomplete. Retrying as ${requested_owner}."
        runuser -u "${requested_owner}" -- rm -rf "${omero_py_dir}" 2>/dev/null || true
    fi
    if [[ -d "${legacy_omero_py_user_dir}" ]] && [[ "$(id -u)" -eq 0 ]]; then
        log "WARN: Root cleanup of legacy temp dir ${legacy_omero_py_user_dir} incomplete. Retrying as ${requested_owner}."
        runuser -u "${requested_owner}" -- rm -rf "${legacy_omero_py_user_dir}" 2>/dev/null || true
    fi

    # Final check: if stale dirs still exist, log a clear error so it's diagnosable.
    if [[ -d "${omero_py_user_dir}" ]]; then
        log "WARN: Could not fully remove stale temp dir: ${omero_py_user_dir}"
        ls -la "${omero_py_user_dir}" >&2 || true
        # As a last resort, try to fix ownership of stale .lock files in-place
        # so TempFileManager can at least open them.
        if [[ "$(id -u)" -eq 0 ]]; then
            find "${omero_py_user_dir}" -name ".lock" -exec chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" {} \; 2>/dev/null || true
            find "${omero_py_user_dir}" -type d -exec chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" {} \; 2>/dev/null || true
            find "${omero_py_user_dir}" -type d -exec chmod 0777 {} \; 2>/dev/null || true
        fi
    fi
    if [[ -d "${legacy_omero_py_user_dir}" ]]; then
        log "WARN: Could not fully remove stale legacy temp dir: ${legacy_omero_py_user_dir}"
        ls -la "${legacy_omero_py_user_dir}" >&2 || true
        if [[ "$(id -u)" -eq 0 ]]; then
            find "${legacy_omero_py_user_dir}" -name ".lock" -exec chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" {} \; 2>/dev/null || true
            find "${legacy_omero_py_user_dir}" -type d -exec chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" {} \; 2>/dev/null || true
            find "${legacy_omero_py_user_dir}" -type d -exec chmod 0777 {} \; 2>/dev/null || true
        fi
    fi

    # Pre-emptively create the specific omero temp dirs to avoid Python locking errors.
    mkdir -p "${omero_py_dir}" "${omero_py_user_dir}"
    if [[ "$(id -u)" -eq 0 ]]; then
        chown "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" "${omero_py_dir}" "${omero_py_user_dir}"
        chmod 0777 "${omero_py_dir}" "${omero_py_user_dir}"
    fi

    # Ensure legacy dir is clean / symlinked so the fallback logic in Python never triggers
    # PermissionError on /opt/omero/server/omero/tmp
    if [[ -d "${legacy_tmp_dir}" && ! -L "${legacy_tmp_dir}" ]]; then
        rm -rf "${legacy_tmp_dir}" || true
    fi
    if [[ ! -e "${legacy_tmp_dir}" ]]; then
        mkdir -p "$(dirname "${legacy_tmp_dir}")"
        ln -sf "${runtime_tmp_dir}" "${legacy_tmp_dir}"
    fi
    if [[ "$(id -u)" -eq 0 ]]; then
        chown -h "$(id -u "${requested_owner}")":"$(id -g "${requested_owner}")" "${legacy_tmp_dir}" 2>/dev/null || true
    fi

    log "OMERO temp directory ready: ${TMPDIR}"
}

validate_ldap_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local required_non_empty=(
        "CONFIG_omero_ldap_urls"
        "CONFIG_omero_ldap_username"
        "CONFIG_omero_ldap_password"
    )

    local var_name
    for var_name in "${required_non_empty[@]}"; do
        if [[ -z "${!var_name:-}" ]]; then
            echo "ERROR: LDAP is enabled but ${var_name} is not set in env/omero_secrets.env" >&2
            exit 1
        fi
    done

    if [[ -z "${CONFIG_omero_ldap_base+x}" ]]; then
        echo "ERROR: LDAP is enabled but CONFIG_omero_ldap_base is not declared in env/omero_secrets.env (empty is allowed, missing is not)." >&2
        exit 1
    fi

    log "LDAP enabled; required secret-backed LDAP settings are present"
}

validate_ldap_new_user_group_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    if [[ -z "${ldap_group_setting}" ]]; then
        log "LDAP enabled without CONFIG_omero_ldap_new__user__group; OMERO will use its built-in default new-user group behavior"
        return
    fi

    if [[ "${ldap_group_setting}" == :* ]]; then
        log "LDAP new-user group uses dynamic mapping expression (${ldap_group_setting}); runtime group auto-bootstrap is skipped"
        return
    fi

    if ! [[ "${ldap_group_setting}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
        echo "ERROR: CONFIG_omero_ldap_new__user__group contains invalid OMERO group name '${ldap_group_setting}'. Allowed pattern: [A-Za-z0-9_.-]+" >&2
        exit 1
    fi
}

validate_job_service_bootstrap_configuration() {
    local required_positive_integer_vars=(
        "OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS"
        "OMERO_JOB_SERVICE_READINESS_POLL_SECONDS"
        "OMERO_JOB_SERVICE_USER_ENSURE_RETRIES"
        "OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS"
        "OMERO_JOB_SERVICE_SYNC_MAX_RETRIES"
    )

    local var_name
    for var_name in "${required_positive_integer_vars[@]}"; do
        if [[ -n "${!var_name-}" ]]; then
            require_positive_integer_env_var "${var_name}"
        fi
    done

    # Jitter may be zero (disable jitter), so validate as non-negative integer
    if [[ -n "${OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS-}" ]]; then
        local jitter_val="${OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS}"
        if ! [[ "${jitter_val}" =~ ^[0-9]+$ ]]; then
            echo "ERROR: OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS must be a non-negative integer, got: '${jitter_val}'" >&2
            exit 1
        fi
    fi
}

validate_binary_repository_cleanse_configuration() {
    local enabled="${OMERO_BINARY_REPO_CLEANSE_ON_START:-1}"

    if [[ "${enabled}" != "0" && "${enabled}" != "1" ]]; then
        echo "ERROR: OMERO_BINARY_REPO_CLEANSE_ON_START must be 0 or 1, got: '${enabled}'" >&2
        exit 1
    fi

    local required_positive_integer_vars=(
        "OMERO_BINARY_REPO_CLEANSE_STARTUP_WAIT_SECONDS"
        "OMERO_BINARY_REPO_CLEANSE_READINESS_POLL_SECONDS"
    )

    local var_name=""
    for var_name in "${required_positive_integer_vars[@]}"; do
        if [[ -n "${!var_name-}" ]]; then
            require_positive_integer_env_var "${var_name}"
        fi
    done

    if [[ -n "${OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS-}" ]]; then
        local keepalive_seconds="${OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS}"
        if ! [[ "${keepalive_seconds}" =~ ^[0-9]+$ ]]; then
            echo "ERROR: OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS must be a non-negative integer, got: '${keepalive_seconds}'" >&2
            exit 1
        fi
    fi

    local data_dir="${OMERO_BINARY_REPO_CLEANSE_DATA_DIR:-${OMERO_DIR}}"
    if [[ -n "${data_dir}" && "${data_dir}" != /* ]]; then
        echo "ERROR: OMERO_BINARY_REPO_CLEANSE_DATA_DIR must be an absolute path, got: '${data_dir}'" >&2
        exit 1
    fi
}

validate_repository_lock_cleanup_configuration() {
    local enabled="${OMERO_REPOSITORY_LOCK_CLEANUP_ON_START:-1}"

    if [[ "${enabled}" != "0" && "${enabled}" != "1" ]]; then
        echo "ERROR: OMERO_REPOSITORY_LOCK_CLEANUP_ON_START must be 0 or 1, got: '${enabled}'" >&2
        exit 1
    fi
}

validate_repo_root_sync_configuration() {
    local interval="${OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS:-3600}"
    local jitter="${OMERO_REPO_ROOT_SYNC_JITTER_SECONDS:-20}"

    if ! [[ "${interval}" =~ ^[0-9]+$ ]] || [ "${interval}" -lt 1 ]; then
        echo "ERROR: OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS must be a positive integer, got: '${interval}'" >&2
        exit 1
    fi

    if ! [[ "${jitter}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: OMERO_REPO_ROOT_SYNC_JITTER_SECONDS must be a non-negative integer, got: '${jitter}'" >&2
        exit 1
    fi

    if [[ -n "${OMERO_REPO_ROOT_BOOTSTRAP_RETRIES-}" ]]; then
        require_positive_integer_env_var "OMERO_REPO_ROOT_BOOTSTRAP_RETRIES"
    fi

    if [[ -n "${OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS-}" ]]; then
        require_positive_integer_env_var "OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS"
    fi
}

cleanup_stale_repository_lock_files() {
    local enabled="${OMERO_REPOSITORY_LOCK_CLEANUP_ON_START:-1}"
    local repository_lock_root="${OMERO_DIR%/}/.omero/repository"
    local -a repository_lock_files=()
    local lock_file=""
    local removed_count=0

    if [[ "${enabled}" != "1" ]]; then
        log "Skipping repository lock cleanup (OMERO_REPOSITORY_LOCK_CLEANUP_ON_START != 1)."
        return
    fi

    if [[ ! -d "${repository_lock_root}" ]]; then
        return
    fi

    if pgrep -f '(/opt/omero/server/.*/omero admin start --foreground|icegridnode|Blitz-0|OMERO\.IceStorm)' >/dev/null 2>&1; then
        log "WARN: Skipping repository lock cleanup because OMERO server processes already appear to be running"
        return
    fi

    mapfile -t repository_lock_files < <(find "${repository_lock_root}" -type f -name '.lock' -print 2>/dev/null | sort)
    if [[ "${#repository_lock_files[@]}" -eq 0 ]]; then
        return
    fi

    for lock_file in "${repository_lock_files[@]}"; do
        rm -f "${lock_file}" || {
            echo "ERROR: Failed to remove stale repository lock file: ${lock_file}" >&2
            exit 1
        }
        log "Removed stale repository lock file: ${lock_file}"
        removed_count=$((removed_count + 1))
    done

    log "Removed ${removed_count} stale repository lock file(s) from ${repository_lock_root}"
}

apply_ldap_runtime_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_user_filter="${CONFIG_omero_ldap_user__filter:-}"
    local ldap_new_user_group="${CONFIG_omero_ldap_new__user__group:-}"

    run_omero config set omero.ldap.config true
    run_omero config set omero.ldap.urls "${CONFIG_omero_ldap_urls}"
    run_omero config set omero.ldap.username "${CONFIG_omero_ldap_username}"
    run_omero config set omero.ldap.password "${CONFIG_omero_ldap_password}"
    run_omero config set omero.ldap.base "${CONFIG_omero_ldap_base}"
    
    if [[ -n "${CONFIG_omero_ldap_user__filter+x}" ]]; then
        run_omero config set omero.ldap.user_filter "${ldap_user_filter}"
    else
        log "LDAP user filter not declared; leaving omero.ldap.user_filter unchanged"
    fi

    if [[ -n "${ldap_new_user_group}" ]]; then
        run_omero config set omero.ldap.new_user_group "${ldap_new_user_group}"
        local configured_group=""
        configured_group="$(run_omero config get omero.ldap.new_user_group 2>/dev/null || true)"
        if [[ "${configured_group}" != "${ldap_new_user_group}" ]]; then
            echo "ERROR: Failed to persist LDAP new-user group. Expected '${ldap_new_user_group}', got '${configured_group}'." >&2
            exit 1
        fi
    fi

    log "Applied LDAP runtime configuration from environment"
}

check_writable_dir() {
    local path="$1"
    local label="$2"

    if [[ ! -d "${path}" ]]; then
        echo "ERROR: ${label} directory missing: ${path}" >&2
        exit 1
    fi

    if touch "${path}/.permission_test" 2>/dev/null; then
        rm -f "${path}/.permission_test"
        log "${label} writable: ${path}"
        return
    fi

    if chown -R "$(id -u):$(id -g)" "${path}" 2>/dev/null; then
        chmod -R u+rwX "${path}" 2>/dev/null || true
    fi

    if ! touch "${path}/.permission_test" 2>/dev/null; then
        echo "ERROR: ${label} is not writable: ${path}" >&2
        exit 1
    fi

    rm -f "${path}/.permission_test"
    log "${label} writable after ownership fix: ${path}"
}

reset_runtime_if_requested() {
    if [[ "${RESET_OMERO_RUNTIME:-0}" != "1" ]]; then
        return
    fi

    local grid_dir="${SERVER_HOME}/var/master"
    if [[ -d "${grid_dir}" ]]; then
        rm -rf "${grid_dir}"
        log "Removed IceGrid runtime directory: ${grid_dir}"
    fi
}

configure_script_python() {
    local venv_py
    venv_py="$(resolve_server_venv_python)"
    run_omero config set omero.scripts.python "${venv_py}"
    log "Configured omero.scripts.python=${venv_py}"
}

ensure_certificate_sans() {
    local cert_pem="${CERTS_DIR}/server.pem"
    local san_value="DNS:localhost,DNS:omeroserver"

    mkdir -p "${CERTS_DIR}"
    if [[ "$(id -u)" -eq 0 ]]; then
        chown "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${CERTS_DIR}"
    fi
    chmod 0750 "${CERTS_DIR}"

    if [[ ! -f "${cert_pem}" ]] || ! openssl x509 -in "${cert_pem}" -noout -text | grep -q "DNS:omeroserver"; then
        run_omero config set omero.certificates.commonname localhost
        run_omero config set omero.certificates.subjectAltName "${san_value}"
        rm -f "${CERTS_DIR}/server."* || true
        run_omero certificates
        log "Regenerated server certificate with SANs: ${san_value}"
    else
        log "Existing certificate already includes DNS:omeroserver"
    fi
}

schedule_job_service_bootstrap() {
    local root_pass="${ROOTPASS:-}"
    local job_user="${OMERO_JOB_SERVICE_USERNAME:-job-service}"
    local job_pass="${OMERO_JOB_SERVICE_PASS:-}"
    local join_all="${OMERO_JOB_SERVICE_JOIN_ALL_GROUPS:-0}"
    local interval="${OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS:-3600}"
    local max_retries="${OMERO_JOB_SERVICE_SYNC_MAX_RETRIES:-3}"
    local jitter_max="${OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS:-20}"
    local startup_wait="${OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS:-300}"
    local poll_interval="${OMERO_JOB_SERVICE_READINESS_POLL_SECONDS:-10}"
    local host="${OMERO_JOB_SERVICE_HOST:-localhost}"
    local port="${OMERO_JOB_SERVICE_PORT:-4064}"
    local user_ensure_retries="${OMERO_JOB_SERVICE_USER_ENSURE_RETRIES:-3}"
    local log_file="${SERVER_LOG_DIR}/job-service-bootstrap.log"
    local pidfile="${SERVER_VAR_DIR}/job-service-sync.pid"

    if [[ -z "${root_pass}" || -z "${job_pass}" ]]; then
        log "Skipping job-service bootstrap (ROOTPASS or OMERO_JOB_SERVICE_PASS missing)."
        return
    fi

    if [[ "${join_all}" != "1" ]]; then
        log "Skipping job-service group sync (OMERO_JOB_SERVICE_JOIN_ALL_GROUPS != 1)."
        return
    fi

    (
        set -u -o pipefail
        umask 022
        mkdir -p "${SERVER_LOG_DIR}" "${SERVER_VAR_DIR}"

        # Prevent duplicate loops robustly (pidfile alone can go stale)
        local lockdir="${pidfile}.lock"
        if ! acquire_lockdir "${lockdir}" "${pidfile}" "job-service sync"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" "${pidfile}"' EXIT

        # Log to file AND to container stdout (so it's visible via docker logs)
        exec > >(tee -a "${log_file}") 2>&1

        echo "[$(date -u)] job-service sync loop starting (host=${host}, port=${port}, interval=${interval}s, retries=${max_retries}, startup_wait=${startup_wait}s, poll=${poll_interval}s)"

        wait_for_server() {
            local wait_seconds="$1"
            local deadline=$(( $(date +%s) + wait_seconds ))

            while [[ "$(date +%s)" -lt "${deadline}" ]]; do
                if run_omero -C -s "${host}" -p "${port}" login -u root -w "${root_pass}" >/dev/null 2>&1 \
                    && run_omero user list -s "${host}" -p "${port}" -u root -w "${root_pass}" >/dev/null 2>&1; then
                    return 0
                fi
                sleep "${poll_interval}"
            done
            return 1
        }

        ensure_user_exists() {
            local _attempt
            for _attempt in $(seq 1 "${user_ensure_retries}"); do
                # Note: 'omero user info' does not accept global arguments (-s -p -u -w) after 'info'.
                # They MUST be placed BEFORE the subcommand, unlike 'omero user add'.
                if run_omero -s "${host}" -p "${port}" -u root -w "${root_pass}" user info --user-name "${job_user}" >/dev/null 2>&1; then
                    return 0
                fi

                local out="" rc=0
                out="$(run_omero user add "${job_user}" Job Service --group-name user -P "${job_pass}" -s "${host}" -p "${port}" -u root -w "${root_pass}" 2>&1)"
                rc=$?
                
                if [[ "${rc}" -eq 0 ]]; then
                    return 0
                fi
                
                # If OMERO tells us the user exists but exited with an error code, it means it was already created. Treat as success.
                if printf "%s" "${out}" | grep -qi "User exists:"; then
                    return 0
                fi

                echo "[$(date -u)] WARN: Failed to add user ${job_user} (rc=${rc}): ${out}"

                sleep $((2 * _attempt))
            done

            return 1
        }

        list_groups() {
            local out=""
            out="$(run_omero group list -s "${host}" -p "${port}" -u root -w "${root_pass}" 2>/dev/null || true)"

            # Parse both "pipe table" and "whitespace table" formats
            if printf "%s" "${out}" | grep -q '|'; then
                printf "%s\n" "${out}" \
                  | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $1); gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($1 ~ /^[0-9]+$/ && $2 ~ /^[A-Za-z0-9_.-]+$/) print $2}' \
                  | sort -u
            else
                printf "%s\n" "${out}" \
                  | awk '($1 ~ /^[0-9]+$/ && $2 ~ /^[A-Za-z0-9_.-]+$/){print $2}' \
                  | sort -u
            fi
        }

        sync_once() {
            local ready_wait="$1"
            
            # Print debug info
            echo "[$(date -u)] DEBUG: Checking OMERO readiness..."
            if ! wait_for_server "${ready_wait}"; then
                echo "[$(date -u)] WARN: OMERO not ready after ${ready_wait}s"
                return 1
            fi
            echo "[$(date -u)] DEBUG: OMERO is ready. Ensuring user exists..."

            if ! ensure_user_exists; then
                echo "[$(date -u)] ERROR: Failed to ensure ${job_user} exists"
                return 1
            fi
            echo "[$(date -u)] DEBUG: User ${job_user} exists. Listing groups..."

            local groups=""
            groups="$(list_groups | grep -v -E '^(root|system|user)$' || true)"
            if [[ -z "${groups}" ]]; then
                echo "[$(date -u)] ERROR: No groups found (or parsing failed)"
                return 1
            fi

            local failed=0
            while IFS= read -r g; do
                [[ -z "${g}" ]] && continue
                local out="" rc=0
                out="$(run_omero user joingroup "${g}" --name="${job_user}" -s "${host}" -p "${port}" -u root -w "${root_pass}" 2>&1)"
                rc=$?

                if [[ "${rc}" -eq 0 ]]; then
                    echo "[$(date -u)] OK: ensured ${job_user} in ${g}"
                    continue
                fi

                # Accept common idempotency errors
                if printf "%s" "${out}" | grep -qiE 'already.*(member|in group)|duplicate'; then
                    echo "[$(date -u)] OK: ${job_user} already in ${g}"
                    continue
                fi

                echo "[$(date -u)] ERROR: joingroup failed for ${g} (rc=${rc}): ${out}"
                failed=1
            done <<< "${groups}"

            return "${failed}"
        }

        first_cycle=1
        while true; do
            start="$(date +%s)"
            ok=0

            # First cycle: use full startup_wait so the server has time to initialize.
            # Subsequent cycles: use a shorter window since the server should already be running.
            if [[ "${first_cycle}" -eq 1 ]]; then
                ready_wait="${startup_wait}"
            else
                ready_wait=$((poll_interval * 12))
            fi

            for attempt in $(seq 1 "${max_retries}"); do
                if sync_once "${ready_wait}"; then
                    ok=1
                    break
                fi
                echo "[$(date -u)] WARN: sync attempt ${attempt}/${max_retries} failed; retrying in 60s"
                if [[ "${attempt}" -lt "${max_retries}" ]]; then
                    sleep 60
                fi
                # After first attempt in first cycle, use shorter waits
                ready_wait=$((poll_interval * 6))
            done

            [[ "${ok}" -eq 1 ]] || echo "[$(date -u)] ERROR: Job-service group sync failed after ${max_retries} attempts; will wait until next interval"
            first_cycle=0

            epoch_end="$(date +%s)"
            elapsed=$((epoch_end - start))
            sleep_for="${interval}"
            if [[ "${elapsed}" -lt "${sleep_for}" ]]; then
                sleep_for=$((sleep_for - elapsed))
            else
                sleep_for=0
            fi

            jitter=$((RANDOM % (jitter_max + 1)))
            sleep $((sleep_for + jitter))
        done
    ) &
    log "Scheduled background job-service bootstrap + hourly group sync (interval=${interval}s)"
}

schedule_ldap_group_bootstrap() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    if [[ -z "${ldap_group_setting}" || "${ldap_group_setting}" == :* ]]; then
        return
    fi

    if [[ "${ldap_group_setting}" == "default" ]]; then
        log "LDAP new-user group is set to built-in default; explicit group bootstrap is skipped"
        return
    fi

    local root_pass="${ROOTPASS:-}"
    if [[ -z "${root_pass}" ]]; then
        echo "ERROR: LDAP group bootstrap requires ROOTPASS when CONFIG_omero_ldap_new__user__group is a static non-default group name." >&2
        exit 1
    fi

    (
        set -eo pipefail
        local lockdir="${SERVER_VAR_DIR}/ldap-group-bootstrap.lock"
        if ! acquire_lockdir "${lockdir}" "" "ldap-group-bootstrap"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" ""' EXIT

        local add_output=""
        local add_exit_code=1
        local login_ok=0
        local retry_limit="${OMERO_LDAP_GROUP_BOOTSTRAP_RETRIES:-180}"
        local retry_delay_seconds="${OMERO_LDAP_GROUP_BOOTSTRAP_RETRY_DELAY_SECONDS:-2}"
        local attempt=1

        for attempt in $(seq 1 "${retry_limit}"); do
            if run_omero -C -s localhost -p 4064 login -u root -w "${root_pass}" >/dev/null 2>&1; then
                login_ok=1
                break
            fi
            sleep "${retry_delay_seconds}"
        done

        if [[ "${login_ok}" -ne 1 ]]; then
            echo "ERROR: Timed out waiting for OMERO login before ensuring LDAP new-user group '${ldap_group_setting}'." >&2
            exit 1
        fi

        for attempt in $(seq 1 "${retry_limit}"); do
            set +e
            add_output="$(run_omero group add "${ldap_group_setting}" --type=private -s localhost -p 4064 -u root -w "${root_pass}" 2>&1)"
            add_exit_code=$?
            set -e

            if [[ "${add_exit_code}" -eq 0 ]] || printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|exists"; then
                break
            fi

            sleep "${retry_delay_seconds}"
        done

        if [[ "${add_exit_code}" -eq 0 ]]; then
            log "Ensured LDAP new-user target group exists: ${ldap_group_setting}"
            exit 0
        fi

        if printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|exists"; then
            log "LDAP new-user target group already exists: ${ldap_group_setting}"
            exit 0
        fi

        echo "ERROR: Failed ensuring LDAP new-user target group '${ldap_group_setting}'." >&2
        echo "ERROR: omero output: ${add_output}" >&2
        exit 1
    ) >>"${SERVER_LOG_DIR}/ldap-group-bootstrap.log" 2>&1 &

    log "Scheduled background LDAP group bootstrap for static group '${ldap_group_setting}'"
}

list_repo_root_bootstrap_groups() {
    local root_pass="$1"
    local out=""

    out="$(run_omero group list -s localhost -p 4064 -u root -w "${root_pass}" 2>/dev/null || true)"
    if [[ -z "${out}" ]]; then
        return 0
    fi

    if printf "%s" "${out}" | grep -q '|'; then
        printf "%s\n" "${out}" \
            | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $1); gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($1 ~ /^[0-9]+$/ && $2 ~ /^[A-Za-z0-9_.-]+$/) print $2}' \
            | sort -u
        return 0
    fi

    printf "%s\n" "${out}" \
        | awk '($1 ~ /^[0-9]+$/ && $2 ~ /^[A-Za-z0-9_.-]+$/){print $2}' \
        | sort -u
}

collect_repo_root_bootstrap_paths() {
    local repo_path="${CONFIG_omero_fs_repo_path:-}"
    if [[ -z "${repo_path}" ]]; then
        return 0
    fi

    local -A seen=()
    local -A seen_groups=()
    local install_groups="${OMERO_INSTALL_GROUP_LIST:-}"
    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    local -a candidate_groups=()
    local entry=""
    local group_name=""
    local current_year=""
    local current_month=""
    local current_day=""
    local current_time=""
    local template_parts=()
    local template_part=""
    local rendered_part=""

    current_year="$(date +%Y)"
    current_month="$(date +%m)"
    current_day="$(date +%d)"
    current_time="$(date +%H-%M-%S)"

    _add_candidate_group() {
        local candidate="$1"
        candidate="$(trim_whitespace "${candidate}")"
        [[ -n "${candidate}" ]] || return 0
        [[ -n "${seen_groups[${candidate}]+x}" ]] && return 0
        seen_groups["${candidate}"]=1
        candidate_groups+=("${candidate}")
    }

    _emit_repo_paths() {
        local current_group="$1"
        local cumulative=()
        local joined=""

        # Normalize only the shared prefix segments that exist before %user%.
        # This is bounded by the template shape, not by repository size.
        IFS='/' read -r -a template_parts <<< "${repo_path}"
        for template_part in "${template_parts[@]}"; do
            [[ -n "${template_part}" ]] || continue
            if [[ "${template_part}" == *%user%* ]]; then
                break
            fi

            rendered_part="${template_part}"
            rendered_part="${rendered_part//%group%/${current_group}}"
            rendered_part="${rendered_part//%year%/${current_year}}"
            rendered_part="${rendered_part//%month%/${current_month}}"
            rendered_part="${rendered_part//%day%/${current_day}}"
            rendered_part="${rendered_part//%time%/${current_time}}"

            if [[ "${rendered_part}" == *%* ]]; then
                return 0
            fi

            [[ -n "${rendered_part}" ]] || continue
            cumulative+=("${rendered_part}")
            joined="$(IFS=/; printf '%s' "${cumulative[*]}")"
            if [[ -n "${joined}" ]] && [[ -z "${seen[${joined}]+x}" ]]; then
                seen["${joined}"]=1
                printf '%s\n' "${joined}"
            fi
        done
    }

    if [[ "$#" -gt 0 ]]; then
        for group_name in "$@"; do
            _add_candidate_group "${group_name}"
        done
    fi

    IFS=',' read -r -a _repo_root_group_entries <<< "${install_groups}"
    for entry in "${_repo_root_group_entries[@]}"; do
        entry="$(trim_whitespace "${entry}")"
        [[ -n "${entry}" ]] || continue
        [[ "${entry}" == \#* ]] && continue
        group_name="${entry%%:*}"
        _add_candidate_group "${group_name}"
    done

    if [[ "${CONFIG_omero_ldap_config:-false}" == "true" ]] \
        && [[ -n "${ldap_group_setting}" ]] \
        && [[ "${ldap_group_setting}" != "default" ]] \
        && [[ "${ldap_group_setting}" != :* ]]; then
        _add_candidate_group "${ldap_group_setting}"
    fi

    for group_name in "${candidate_groups[@]}"; do
        _emit_repo_paths "${group_name}"
    done
}

resolve_cli_home() {
    local cli_user="$1"
    local cli_home=""

    cli_home="$(getent passwd "${cli_user}" | cut -d: -f6 2>/dev/null || true)"
    if [[ -z "${cli_home}" ]] || [[ ! -d "${cli_home}" ]]; then
        cli_home="/tmp"
    fi
    printf "%s\n" "${cli_home}"
}

write_repo_root_sync_status() {
    local status="$1"
    local last_success_epoch="${2:-0}"
    local inspected_prefix_count="${3:-0}"
    local normalized_prefix_count="${4:-0}"
    local failed_prefix_count="${5:-0}"
    local tmp_status_file="${REPO_ROOT_SYNC_STATUS_FILE}.tmp.$$"

    mkdir -p "${SERVER_VAR_DIR}"
    cat > "${tmp_status_file}" <<EOF
status=${status}
last_success_epoch=${last_success_epoch}
inspected_prefix_count=${inspected_prefix_count}
normalized_prefix_count=${normalized_prefix_count}
failed_prefix_count=${failed_prefix_count}
EOF
    mv "${tmp_status_file}" "${REPO_ROOT_SYNC_STATUS_FILE}"
}

run_repo_root_bootstrap_once() {
    local root_pass="$1"
    local retry_limit="${OMERO_REPO_ROOT_BOOTSTRAP_RETRIES:-180}"
    local retry_delay_seconds="${OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS:-2}"
    local attempt=1
    local login_ok=0
    local path_list=""
    local repo_dir_path=""
    local -a repo_root_groups=()
    local lookup_output=""
    local root_dir_id=""
    local root_dir_owner=""
    local venv_py=""
    local lookup_py=""
    local cli_home=""
    local chown_output=""
    local chown_exit_code=1
    local inspected_prefix_count=0
    local normalized_prefix_count=0
    local failed_prefix_count=0
    local last_success_epoch=0

    for attempt in $(seq 1 "${retry_limit}"); do
        if run_omero -C -s localhost -p 4064 login -u root -w "${root_pass}" >/dev/null 2>&1; then
            login_ok=1
            break
        fi
        sleep "${retry_delay_seconds}"
    done

    if [[ "${login_ok}" -ne 1 ]]; then
        echo "[$(date -u)] ERROR: Timed out waiting for OMERO login before normalizing managed-repository prefixes"
        write_repo_root_sync_status "error" "0" "0" "0" "1"
        return 1
    fi

    mapfile -t repo_root_groups < <(list_repo_root_bootstrap_groups "${root_pass}")
    if [[ "${#repo_root_groups[@]}" -gt 0 ]]; then
        path_list="$(collect_repo_root_bootstrap_paths "${repo_root_groups[@]}")"
    else
        echo "[$(date -u)] WARN: OMERO group discovery returned no rows; falling back to environment-derived groups"
    fi

    if [[ -z "${path_list}" ]]; then
        path_list="$(collect_repo_root_bootstrap_paths)"
    fi

    if [[ -z "${path_list}" ]]; then
        echo "[$(date -u)] INFO: no managed-repository shared prefixes require normalization"
        last_success_epoch="$(date +%s)"
        write_repo_root_sync_status "ok" "${last_success_epoch}" "0" "0" "0"
        return 0
    fi

    venv_py="$(resolve_server_venv_python)"
    cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")"
    lookup_py="$(mktemp "${TMPDIR:-/tmp}/repo-root-lookup.XXXXXX.py")"
    cat >"${lookup_py}" <<'PY'
import sys
from omero.gateway import BlitzGateway

if len(sys.argv) != 3:
    print("usage: repo_root_lookup.py <root_pass> <repo_dir_path>", file=sys.stderr)
    sys.exit(2)

root_pass = sys.argv[1]
repo_dir_path = sys.argv[2].strip("/")
if not repo_dir_path:
    print("ERROR: empty repository path", file=sys.stderr)
    sys.exit(2)

path_parts = repo_dir_path.split("/")
dir_name = path_parts[-1]
parent_path = "/"
if len(path_parts) > 1:
    parent_path = "/" + "/".join(path_parts[:-1]) + "/"

conn = BlitzGateway("root", root_pass, host="localhost", port=4064)
try:
    if not conn.connect():
        print("ERROR: failed to connect as root", file=sys.stderr)
        sys.exit(1)
    conn.SERVICE_OPTS.setOmeroGroup("-1")
    candidates = list(conn.getObjects("OriginalFile", attributes={"name": dir_name}))
    exact = None
    for obj in candidates:
        if obj.getPath() == parent_path:
            exact = obj
            break
    if exact is None:
        print("MISSING")
        sys.exit(0)
    print(f"FOUND|{exact.getId()}|{exact.getOwnerOmeName()}")
finally:
    try:
        conn.close()
    except Exception:
        pass
PY
    chown "${OMERO_CLI_USER}" "${lookup_py}"
    chmod 0600 "${lookup_py}"

    while IFS= read -r repo_dir_path; do
        [[ -n "${repo_dir_path}" ]] || continue
        inspected_prefix_count=$((inspected_prefix_count + 1))
        echo "[$(date -u)] INFO: ensuring managed-repository shared prefix ${repo_dir_path}"
        run_omero fs mkdir --parents "${repo_dir_path}" >/dev/null 2>&1 || true

        lookup_output="$(runuser -u "${OMERO_CLI_USER}" -- env HOME="${cli_home}" TMPDIR="${TMPDIR:-/tmp}" OMERO_TMPDIR="${TMPDIR:-/tmp}" OMERO_TEMPDIR="${TMPDIR:-/tmp}" "${venv_py}" "${lookup_py}" "${root_pass}" "${repo_dir_path}" 2>&1)"
        if [[ "${lookup_output}" == MISSING* ]]; then
            echo "[$(date -u)] ERROR: repository root lookup did not find shared prefix for ${repo_dir_path} after fs mkdir"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi

        if [[ "${lookup_output}" != FOUND\|* ]]; then
            echo "[$(date -u)] ERROR: repository root lookup failed for ${repo_dir_path}: ${lookup_output}"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi

        IFS='|' read -r _found_marker root_dir_id root_dir_owner <<< "${lookup_output}"
        echo "[$(date -u)] INFO: repository prefix ${repo_dir_path} -> OriginalFile:${root_dir_id} owner=${root_dir_owner}"

        if [[ "${root_dir_owner}" == "root" ]]; then
            echo "[$(date -u)] INFO: repository prefix ${repo_dir_path} already normalized"
            continue
        fi

        # Non-destructive repair: normalize only OMERO ownership metadata for
        # shared prefix directories. No files or repository payload are deleted.
        chown_exit_code=1
        for attempt in $(seq 1 "${retry_limit}"); do
            set +e
            chown_output="$(run_omero chown root "OriginalFile:${root_dir_id}" --force 2>&1)"
            chown_exit_code=$?
            set -e
            [[ "${chown_exit_code}" -eq 0 ]] && break
            sleep "${retry_delay_seconds}"
        done

        if [[ "${chown_exit_code}" -ne 0 ]]; then
            echo "[$(date -u)] ERROR: failed to normalize repository prefix ${repo_dir_path} (OriginalFile:${root_dir_id}): ${chown_output}"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi

        normalized_prefix_count=$((normalized_prefix_count + 1))
        lookup_output="$(runuser -u "${OMERO_CLI_USER}" -- env HOME="${cli_home}" TMPDIR="${TMPDIR:-/tmp}" OMERO_TMPDIR="${TMPDIR:-/tmp}" OMERO_TEMPDIR="${TMPDIR:-/tmp}" "${venv_py}" "${lookup_py}" "${root_pass}" "${repo_dir_path}" 2>&1)"
        echo "[$(date -u)] INFO: normalized repository prefix ${repo_dir_path}: ${lookup_output}"
    done <<< "${path_list}"

    rm -f "${lookup_py}"

    if [[ "${failed_prefix_count}" -ne 0 ]]; then
        write_repo_root_sync_status "error" "0" "${inspected_prefix_count}" "${normalized_prefix_count}" "${failed_prefix_count}"
        return 1
    fi

    last_success_epoch="$(date +%s)"
    write_repo_root_sync_status "ok" "${last_success_epoch}" "${inspected_prefix_count}" "${normalized_prefix_count}" "0"
    return 0
}

schedule_repo_root_sync() {
    local root_pass="${ROOTPASS:-}"
    local repo_path="${CONFIG_omero_fs_repo_path:-}"
    local interval="${OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS:-3600}"
    local jitter_max="${OMERO_REPO_ROOT_SYNC_JITTER_SECONDS:-20}"

    if [[ -z "${root_pass}" ]]; then
        log "Skipping managed-repository root sync (ROOTPASS missing)."
        return
    fi

    if [[ "${repo_path}" != *%group%* ]]; then
        log "Managed-repository root sync skipped because CONFIG_omero_fs_repo_path has no %group% token."
        return
    fi

    (
        set -u -o pipefail
        mkdir -p "${SERVER_LOG_DIR}" "${SERVER_VAR_DIR}"

        local lockdir="${SERVER_VAR_DIR}/repo-root-bootstrap.lock"
        if ! acquire_lockdir "${lockdir}" "" "repo-root-sync"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" ""' EXIT

        while true; do
            if ! run_repo_root_bootstrap_once "${root_pass}"; then
                echo "[$(date -u)] WARN: managed-repository shared-prefix sync cycle finished with errors"
            fi
            sleep $((interval + (RANDOM % (jitter_max + 1))))
        done
    ) >>"${SERVER_LOG_DIR}/repo-root-bootstrap.log" 2>&1 &

    log "Scheduled background managed-repository shared-prefix sync (interval=${interval}s)"
}

schedule_binary_repository_cleanse() {
    local enabled="${OMERO_BINARY_REPO_CLEANSE_ON_START:-1}"
    local root_pass="${ROOTPASS:-}"
    local data_dir="${OMERO_BINARY_REPO_CLEANSE_DATA_DIR:-${OMERO_DIR}}"
    local startup_wait="${OMERO_BINARY_REPO_CLEANSE_STARTUP_WAIT_SECONDS:-300}"
    local poll_interval="${OMERO_BINARY_REPO_CLEANSE_READINESS_POLL_SECONDS:-10}"
    local keepalive_seconds="${OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS:-30}"
    local log_file="${SERVER_LOG_DIR}/binary-repository-cleanse.log"
    local server_root="${SERVER_HOME%/*}"

    if [[ "${enabled}" != "1" ]]; then
        log "Skipping binary repository cleanse (OMERO_BINARY_REPO_CLEANSE_ON_START != 1)."
        return
    fi

    if [[ -z "${root_pass}" ]]; then
        log "Skipping binary repository cleanse (ROOTPASS missing)."
        return
    fi

    (
        set -u -o pipefail
        umask 022
        mkdir -p "${SERVER_LOG_DIR}" "${SERVER_VAR_DIR}"

        local lockdir="${SERVER_VAR_DIR}/binary-repository-cleanse.lock"
        if ! acquire_lockdir "${lockdir}" "" "binary repository cleanse"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" ""' EXIT

        exec > >(tee -a "${log_file}") 2>&1

        echo "[$(date -u)] binary repository cleanse starting (data_dir=${data_dir}, keepalive=${keepalive_seconds}s)"

        if [[ ! -d "${data_dir}" ]]; then
            echo "[$(date -u)] WARN: binary repository cleanse skipped because data directory is missing: ${data_dir}"
            exit 0
        fi

        local deadline=$(( $(date +%s) + startup_wait ))
        local login_ok=0
        while [[ "$(date +%s)" -lt "${deadline}" ]]; do
            if run_omero -C -s localhost -p 4064 login -u root -w "${root_pass}" >/dev/null 2>&1; then
                login_ok=1
                break
            fi
            sleep "${poll_interval}"
        done

        if [[ "${login_ok}" -ne 1 ]]; then
            echo "[$(date -u)] ERROR: Timed out waiting for OMERO login before running binary repository cleanse"
            exit 1
        fi

        if [[ -d "${server_root}" ]]; then
            cd "${server_root}"
        fi

        local start_epoch="$(date +%s)"
        local rc=0

        run_omero_with_keepalive \
            "${keepalive_seconds}" \
            admin cleanse -q -C -s localhost -p 4064 -u root -w "${root_pass}" "${data_dir}" || rc=$?

        local elapsed=$(( $(date +%s) - start_epoch ))
        if [[ "${rc}" -eq 0 ]]; then
            echo "[$(date -u)] binary repository cleanse finished successfully in ${elapsed}s"
            exit 0
        fi

        echo "[$(date -u)] ERROR: binary repository cleanse failed with rc=${rc} after ${elapsed}s"
        exit "${rc}"
    ) &

    log "Scheduled background binary repository cleanse for ${data_dir}"
}
install_figure_script() {
    local figure_version="${OMERO_FIGURE_VERSION:-}"
    if [[ -z "${figure_version}" ]]; then
        echo "ERROR: OMERO_FIGURE_VERSION must be set in env/omeroserver.env and must not be empty." >&2
        exit 1
    fi

    local script_dir="${SERVER_HOME}/lib/scripts/omero/figure_scripts"
    local script_path="${script_dir}/Figure_To_Pdf.py"
    local tmp_dir="/tmp/omero-figure-${figure_version}"

    mkdir -p "${script_dir}"

    if [[ -f "${script_path}" ]]; then
        local current_version="unknown"
        current_version="$(grep -Eo "__version__\s*=\s*'[^']+'" "${script_path}" 2>/dev/null | head -n 1 | sed -E "s/.*'([^']+)'.*/\1/" || true)"
        if [[ "${current_version}" == "${figure_version}" ]]; then
            log "OMERO.Figure script already present (version ${current_version})"
            return
        fi
        log "OMERO.Figure script version mismatch (${current_version} != ${figure_version}); attempting upgrade"
    fi

    rm -rf "${tmp_dir}"
    mkdir -p "${tmp_dir}"

    # Download the requested version into a staging file.
    # CRITICAL: Do NOT delete the existing script until the new one is confirmed.
    local staged_script="${tmp_dir}/Figure_To_Pdf.py"

    log "Downloading OMERO.Figure Figure_To_Pdf.py (version ${figure_version})"
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch "v${figure_version}" https://github.com/ome/omero-figure.git "${tmp_dir}/repo" >/dev/null 2>&1 \
            || git clone --depth 1 --branch "${figure_version}" https://github.com/ome/omero-figure.git "${tmp_dir}/repo" >/dev/null 2>&1 \
            || true
    fi

    if [[ -f "${tmp_dir}/repo/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" ]]; then
        cp "${tmp_dir}/repo/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" "${staged_script}"
    else
        local url="https://github.com/ome/omero-figure/archive/refs/tags/v${figure_version}.tar.gz"
        if curl -fsSL "${url}" -o "${tmp_dir}/figure.tar.gz" 2>/dev/null; then
            tar -xzf "${tmp_dir}/figure.tar.gz" -C "${tmp_dir}" 2>/dev/null || true
        fi
        local extracted
        extracted="$(find "${tmp_dir}" -maxdepth 1 -type d -name "omero-figure-*${figure_version}*" | head -n 1 || true)"
        if [[ -n "${extracted}" && -f "${extracted}/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" ]]; then
            cp "${extracted}/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" "${staged_script}"
        fi
    fi

    # Only replace the existing script if the download succeeded.
    if [[ -f "${staged_script}" ]]; then
        cp -f "${staged_script}" "${script_path}"
        log "Installed OMERO.Figure script at ${script_path} (version ${figure_version})"
    elif [[ -f "${script_path}" ]]; then
        log "WARN: Could not download OMERO.Figure ${figure_version}; keeping existing script at ${script_path}"
    else
        log "ERROR: No Figure_To_Pdf.py available and download of version ${figure_version} failed"
    fi

    rm -rf "${tmp_dir}"

    if [[ "$(id -u)" -eq 0 ]]; then
        chown -R "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${SERVER_HOME}/lib/scripts" 2>/dev/null || true
    fi
    chmod -R a+rX "${SERVER_HOME}/lib/scripts" 2>/dev/null || true
}

schedule_script_registration() {
    if [[ "${REGISTER_OFFICIAL_SCRIPTS:-0}" != "1" ]]; then
        return
    fi

    local root_pass="${ROOTPASS:-}"
    if [[ -z "${root_pass}" ]]; then
        echo "ERROR: REGISTER_OFFICIAL_SCRIPTS=1 requires ROOTPASS" >&2
        exit 1
    fi

    (
        set -eo pipefail
        local lockdir="${SERVER_VAR_DIR}/register-official-scripts.lock"
        if ! acquire_lockdir "${lockdir}" "" "register-official-scripts"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" ""' EXIT

        local scripts_dir="${SERVER_HOME}/lib/scripts/omero"

        until run_omero -C -s localhost -p 4064 login -u root -w "${root_pass}" >/dev/null 2>&1; do
            sleep 2
        done

        # Create an idempotent Python script to register official scripts and clean duplicates
        local script_sync_py="${SERVER_VAR_DIR}/sync_official_scripts.py"
        cat << 'EOF' > "${script_sync_py}"
import os
import sys
from omero.gateway import BlitzGateway

def sync_scripts(conn, script_dir):
    try:
        svc = conn.getScriptService()
        existing_scripts = svc.getScripts()
    except Exception as e:
        print(f"Failed to get existing scripts: {e}")
        return

    # Build a map of filename -> list of (OriginalFile, full_db_path) tuples.
    # OriginalFile.name is the filename, OriginalFile.path is the directory.
    script_map = {}
    for s in existing_scripts:
        fname = s.name.val if hasattr(s.name, 'val') else str(s.name)
        dirpath = s.path.val if hasattr(s.path, 'val') else str(s.path)
        full_db_path = (dirpath.rstrip("/") + "/" + fname).lstrip("/")
        if fname not in script_map:
            script_map[fname] = []
        script_map[fname].append((s, full_db_path))

    scripts_root = os.path.dirname(script_dir)

    # Walk the physical script directory
    for root, dirs, files in os.walk(script_dir):
        for file in files:
            # Package markers are not runnable OMERO scripts and can create
            # broken script-service entries if uploaded.
            if not file.endswith('.py') or file == '__init__.py':
                continue

            filepath = os.path.join(root, file)
            desired_path = os.path.relpath(filepath, scripts_root).replace('\\', '/')

            existing = script_map.get(file, [])

            if len(existing) == 1:
                _, db_path = existing[0]
                if db_path == desired_path:
                    print(f"[{file}] OK (path={desired_path})")
                    continue

                # Path mismatch (e.g. legacy absolute path). Delete and re-upload.
                print(f"[{file}] path mismatch (db={db_path}, expected={desired_path}); will replace")
                # Fall through to duplicate cleanup which handles deletion + re-upload

            if len(existing) >= 1 and not (len(existing) == 1 and existing[0][1] == desired_path):
                # Delete all copies so we can re-upload with the correct path
                print(f"[{file}] removing {len(existing)} stale/duplicate DB entries")
                for s_obj, db_path in existing:
                    try:
                        sid = s_obj.id.val
                        print(f"  Deleting script ID {sid} (path={db_path})")
                        conn.deleteObjects("OriginalFile", [sid], deleteChildren=True, wait=True)
                    except Exception as e:
                        print(f"  Failed to delete script ID {sid}: {e}")

                # Upload the correct version
                print(f"[{file}] uploading as official script: {desired_path}")
                cmd = (
                    f"omero script upload --official --sudo root "
                    f"'{filepath}' "
                    f"-s localhost -p 4064 -u root -w '{sys.argv[1]}'"
                )
                rc = os.system(cmd)
                if rc != 0:
                    print(f"  WARN: upload returned exit code {rc}")
            elif len(existing) == 0:
                print(f"[{file}] not registered; uploading as official script: {desired_path}")
                cmd = (
                    f"omero script upload --official --sudo root "
                    f"'{filepath}' "
                    f"-s localhost -p 4064 -u root -w '{sys.argv[1]}'"
                )
                rc = os.system(cmd)
                if rc != 0:
                    print(f"  WARN: upload returned exit code {rc}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)

    root_pass = sys.argv[1]
    script_dir = sys.argv[2]

    conn = BlitzGateway('root', root_pass, host='localhost', port=4064)
    try:
        if conn.connect():
            sync_scripts(conn, script_dir)
        else:
            print("Failed to connect to OMERO")
            sys.exit(1)
    finally:
        conn.close()
EOF

        local venv_py
        venv_py="$(resolve_server_venv_python)"
        local cli_home
        cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")"

        # Run the idempotent sync script (output goes to the log file via the subshell redirect)
        runuser -u "${OMERO_CLI_USER}" -- env HOME="${cli_home}" TMPDIR="${TMPDIR:-/tmp}" "${venv_py}" "${script_sync_py}" "${root_pass}" "${scripts_dir}" 2>&1 || true

        rm -f "${script_sync_py}"
    ) >>"${SERVER_LOG_DIR}/register-official-scripts.log" 2>&1 &

    log "Scheduled background idempotent official script registration"
}

acquire_lockdir() {
    local lockdir="$1"
    local pidfile="${2:-}"
    local label="${3:-lock}"
    local existing_pid=""
    local existing_start_ticks=""
    local existing_boot_id=""
    local owner_uid=""
    local owner_gid=""
    local current_boot_id=""
    local lock_timestamp_path=""

    if id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        owner_uid="$(id -u "${OMERO_CLI_USER}")"
        owner_gid="$(id -g "${OMERO_CLI_USER}")"
    fi

    current_boot_id="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"

    _read_proc_start_ticks() {
        local target_pid="$1"
        [[ -r "/proc/${target_pid}/stat" ]] || return 1
        awk '{print $22}' "/proc/${target_pid}/stat" 2>/dev/null
    }

    _normalize_lock_path() {
        local target_path="$1"
        [[ -e "${target_path}" ]] || return 0
        if [[ -d "${target_path}" ]]; then
            chmod 0755 "${target_path}" 2>/dev/null || true
        else
            chmod 0644 "${target_path}" 2>/dev/null || true
        fi
        if [[ -n "${owner_uid}" && -n "${owner_gid}" ]]; then
            chown "${owner_uid}:${owner_gid}" "${target_path}" 2>/dev/null || true
        fi
    }

    _write_lock_metadata() {
        local target_lockdir="$1"
        local target_pid="$2"
        local target_start_ticks=""

        echo "${target_pid}" > "${target_lockdir}/pid" 2>/dev/null || true
        _normalize_lock_path "${target_lockdir}/pid"

        target_start_ticks="$(_read_proc_start_ticks "${target_pid}" || true)"
        if [[ -n "${target_start_ticks}" ]]; then
            echo "${target_start_ticks}" > "${target_lockdir}/proc_start_ticks" 2>/dev/null || true
            _normalize_lock_path "${target_lockdir}/proc_start_ticks"
        fi

        if [[ -n "${current_boot_id}" ]]; then
            echo "${current_boot_id}" > "${target_lockdir}/boot_id" 2>/dev/null || true
            _normalize_lock_path "${target_lockdir}/boot_id"
        fi

        if [[ -n "${pidfile}" ]]; then
            echo "${target_pid}" > "${pidfile}" 2>/dev/null || true
        fi
    }

    if mkdir "${lockdir}" 2>/dev/null; then
        _normalize_lock_path "${lockdir}"
        _write_lock_metadata "${lockdir}" "${BASHPID}"
        return 0
    fi

    existing_pid="$(cat "${lockdir}/pid" 2>/dev/null || true)"
    existing_start_ticks="$(cat "${lockdir}/proc_start_ticks" 2>/dev/null || true)"
    existing_boot_id="$(cat "${lockdir}/boot_id" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
        local live_start_ticks=""
        local live_proc_epoch=""
        local lock_epoch=""
        local lock_state="stale"

        live_start_ticks="$(_read_proc_start_ticks "${existing_pid}" || true)"
        if [[ -n "${live_start_ticks}" ]]; then
            if [[ -n "${existing_start_ticks}" ]]; then
                if [[ -n "${existing_boot_id}" && -n "${current_boot_id}" && "${existing_boot_id}" != "${current_boot_id}" ]]; then
                    lock_state="stale"
                elif [[ "${existing_start_ticks}" == "${live_start_ticks}" ]]; then
                    lock_state="active"
                fi
            else
                # Legacy lockdirs from earlier revisions only stored a PID. Those can
                # collide after container recreation because low PIDs are reused. Treat
                # the lock as stale when its timestamp predates the current process.
                lock_timestamp_path="${lockdir}/pid"
                [[ -e "${lock_timestamp_path}" ]] || lock_timestamp_path="${lockdir}"
                live_proc_epoch="$(stat -c %Y "/proc/${existing_pid}" 2>/dev/null || true)"
                lock_epoch="$(stat -c %Y "${lock_timestamp_path}" 2>/dev/null || true)"
                if [[ -n "${live_proc_epoch}" && -n "${lock_epoch}" && "${lock_epoch}" -ge "${live_proc_epoch}" ]]; then
                    lock_state="active"
                fi
            fi
        fi

        if [[ "${lock_state}" == "active" ]]; then
            log "${label} already running (pid=${existing_pid}); skipping"
            return 1
        fi

        log "Removing stale ${label} lock (${lockdir}) left by pid=${existing_pid}"
    fi

    rm -rf "${lockdir}" 2>/dev/null || true
    if ! mkdir "${lockdir}" 2>/dev/null; then
        log "ERROR: could not acquire ${label} lock (${lockdir})"
        return 1
    fi

    _normalize_lock_path "${lockdir}"
    _write_lock_metadata "${lockdir}" "${BASHPID}"
    return 0
}

release_lockdir() {
    local lockdir="$1"
    local pidfile="${2:-}"
    rm -rf "${lockdir}" 2>/dev/null || true
    if [[ -n "${pidfile}" ]]; then
        rm -f "${pidfile}" 2>/dev/null || true
    fi
}


main() {
    log "Starting consolidated startup flow"

    mkdir -p "${CERTS_DIR}" "${SERVER_LOG_DIR}"

    # Prevent accidental double-execution (entrypoint ordering bugs, etc.)
    mkdir -p "${SERVER_VAR_DIR}"
    local main_lockdir="${SERVER_VAR_DIR}/server-bootstrap.lock"
    if ! acquire_lockdir "${main_lockdir}" "" "server-bootstrap"; then
        exit 0
    fi
    trap 'release_lockdir "${main_lockdir}" ""' EXIT

    check_writable_dir "${OMERO_DIR}" "OMERO data"
    check_writable_dir "${CERTS_DIR}" "OMERO certificates"
    check_writable_dir "${SERVER_VAR_DIR}" "OMERO var"
    check_writable_dir "${SERVER_LOG_DIR}" "OMERO logs"
    ensure_tmpdir_permissions "${OMERO_CLI_USER}"

    validate_ldap_configuration
    validate_ldap_new_user_group_configuration
    validate_job_service_bootstrap_configuration
    validate_binary_repository_cleanse_configuration
    validate_repository_lock_cleanup_configuration
    validate_repo_root_sync_configuration
    apply_ldap_runtime_configuration
    reset_runtime_if_requested
    configure_script_python
    ensure_certificate_sans
    cleanup_stale_repository_lock_files
    install_figure_script
    schedule_script_registration
    schedule_job_service_bootstrap
    schedule_ldap_group_bootstrap
    schedule_repo_root_sync
    schedule_binary_repository_cleanse

    log "Startup flow finished"
}

main "$@"
