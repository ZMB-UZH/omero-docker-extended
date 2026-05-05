#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Write a log message. Inputs: shell arguments and environment. Output: command status and side effects.
log() {
    echo "[server-bootstrap] $*"
}

# Return whether non negative integer. Inputs: shell arguments and environment. Output: success or failure status.
is_non_negative_integer() {
    case "$1" in
        ""|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# Return whether positive integer. Inputs: shell arguments and environment. Output: success or failure status.
is_positive_integer() {
    is_non_negative_integer "$1" && [ "$1" -gt 0 ]
}

# Return whether tcp port. Inputs: shell arguments and environment. Output: success or failure status.
is_tcp_port() {
    is_positive_integer "$1" && [ "$1" -le 65535 ]
}

# Return whether environment variable name. Inputs: shell arguments and environment. Output: success or failure status.
is_env_var_name() {
    case "$1" in
        ""|[0-9]*|*[!A-Za-z0-9_]*) return 1 ;;
        *) return 0 ;;
    esac
}

# Return whether OMERO group name. Inputs: shell arguments and environment. Output: success or failure status.
is_omero_group_name() {
    case "$1" in
        ""|*[!A-Za-z0-9_.-]*) return 1 ;;
        *) return 0 ;;
    esac
}

# Return whether truthy bool. Inputs: shell arguments and environment. Output: success or failure status.
is_truthy_bool() {
    case "$1" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

# Return whether falsey bool. Inputs: shell arguments and environment. Output: success or failure status.
is_falsey_bool() {
    case "$1" in
        0|false|no|off) return 0 ;;
        *) return 1 ;;
    esac
}

# Require positive integer environment variable. Inputs: shell arguments and environment. Output: command status and side effects.
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

    if ! is_positive_integer "${value}"; then
        echo "ERROR: Required environment variable '${var_name}' must be a positive integer, got '${value}'." >&2
        exit 1
    fi
}

# Require tcp port environment variable. Inputs: shell arguments and environment. Output: command status and side effects.
require_tcp_port_env_var() {
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

    if ! is_tcp_port "${value}"; then
        echo "ERROR: Required environment variable '${var_name}' must be a TCP port between 1 and 65535, got '${value}'." >&2
        exit 1
    fi
}

# Require nonempty environment variable. Inputs: shell arguments and environment. Output: command status and side effects.
require_nonempty_env_var() {
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
}

# Require set environment variable. Inputs: shell arguments and environment. Output: command status and side effects.
require_set_env_var() {
    local var_name="$1"

    if [[ -z "${!var_name+x}" ]]; then
        echo "ERROR: Required environment variable '${var_name}' is not set." >&2
        exit 1
    fi
}

OMERO_DIR="${OMERO_DIR:-/OMERO}"
CERTS_DIR="${CERTS_DIR:-${OMERO_DIR}/certs}"
SERVER_HOME="${SERVER_HOME:-/opt/omero/server/OMERO.server}"
SERVER_VAR_DIR="${SERVER_VAR_DIR:-${SERVER_HOME}/var}"
SERVER_LOG_DIR="${SERVER_LOG_DIR:-${SERVER_VAR_DIR}/log}"
REPO_ROOT_SYNC_STATUS_FILE="${SERVER_VAR_DIR}/repo-root-sync.status"
REPO_ROOT_SYNC_HELPER="${SCRIPT_DIR}/repo_root_sync_helper.py"
DROPBOX_USER_DIR_SYNC_STATUS_FILE="${SERVER_VAR_DIR}/dropbox-user-dir-sync.status"
DROPBOX_USER_DIR_SYNC_HELPER="${SCRIPT_DIR}/dropbox_user_dir_sync.py"
DROPBOX_ICE_BOOTSTRAP_STATUS_FILE="${SERVER_VAR_DIR}/dropbox-ice-bootstrap.status"
JOB_SERVICE_GROUP_SYNC_HELPER="${SCRIPT_DIR}/job_service_group_sync.py"
# Resolve OMERO bin. Inputs: shell arguments and environment. Output: stdout text and command status.
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

    if command -v omero >/dev/null 2>&1; then
        command -v omero
        return 0
    fi

    echo "ERROR: Could not auto-detect an executable OMERO CLI binary. Set OMERO_BIN explicitly." >&2
    exit 1
}

OMERO_BIN="$(resolve_omero_bin)"
require_nonempty_env_var "OMERO_CLI_USER"
require_nonempty_env_var "OMERO_CLI_HOST"
require_tcp_port_env_var "OMERO_CLI_PORT"

# Resolve OMERO cli tmpdir. Inputs: shell arguments and environment. Output: stdout text and command status.
resolve_omero_cli_tmpdir() {
    local candidate="${OMERO_TMPDIR:-${TMPDIR:-${OMERO_TEMPDIR:-}}}"

    if [[ -z "${candidate}" ]]; then
        echo "ERROR: OMERO CLI temp directory is not set. Configure OMERO_TMP_PATH so Compose exports OMERO_TMPDIR/TMPDIR." >&2
        return 1
    fi

    printf "%s\n" "${candidate}"
}

# Resolve server venv python. Inputs: shell arguments and environment. Output: stdout text and command status.
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

# Trim whitespace. Inputs: shell arguments and environment. Output: command status and side effects.
trim_whitespace() {
    printf "%s" "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# Normalize directory path. Inputs: shell arguments and environment. Output: command status and side effects.
normalize_dir_path() {
    local path=""
    path="$(trim_whitespace "$1")"
    if [[ -z "${path}" ]]; then
        return 1
    fi
    while [[ "${path}" = */ && "${path}" != "/" ]]; do
        path="${path%/}"
    done
    printf "%s\n" "${path}"
}

# Perform expected managed repository root. Inputs: shell arguments and environment. Output: command status and side effects.
expected_managed_repository_root() {
    local configured_managed_dir=""
    local normalized_omero_dir=""
    local normalized_managed_dir=""

    configured_managed_dir="$(trim_whitespace "${CONFIG_omero_managed_dir:-}")"
    if [[ -z "${configured_managed_dir}" ]]; then
        echo "ERROR: CONFIG_omero_managed_dir must be set and must not be empty." >&2
        return 1
    fi

    normalized_omero_dir="$(normalize_dir_path "${OMERO_DIR}")" || {
        echo "ERROR: OMERO_DIR must be a non-empty absolute path, got: '${OMERO_DIR}'" >&2
        return 1
    }
    normalized_managed_dir="$(normalize_dir_path "${configured_managed_dir}")" || {
        echo "ERROR: CONFIG_omero_managed_dir must be a non-empty absolute path, got: '${configured_managed_dir}'" >&2
        return 1
    }

    if [[ "${normalized_managed_dir}" != /* ]]; then
        echo "ERROR: CONFIG_omero_managed_dir must be an absolute path under ${normalized_omero_dir}, got: '${configured_managed_dir}'" >&2
        return 1
    fi

    if [[ "${normalized_managed_dir}" != "${normalized_omero_dir}" ]] \
        && [[ "${normalized_managed_dir}" != "${normalized_omero_dir}/"* ]]; then
        echo "ERROR: CONFIG_omero_managed_dir must stay within ${normalized_omero_dir}, got: '${configured_managed_dir}'" >&2
        return 1
    fi

    if [[ "${normalized_managed_dir}" = "${normalized_omero_dir}" ]]; then
        echo "ERROR: CONFIG_omero_managed_dir must not point to OMERO_DIR directly: '${configured_managed_dir}'" >&2
        return 1
    fi

    printf "%s\n" "${normalized_managed_dir}"
}

# Find unexpected server managed repository directories. Inputs: shell arguments and environment. Output: command status and side effects.
find_unexpected_server_managed_repository_dirs() {
    local expected_root=""
    local server_root=""
    local expected_basename=""
    local candidate=""
    local -A seen=()

    expected_root="$(expected_managed_repository_root)" || return 1
    server_root="${SERVER_HOME%/*}"
    expected_basename="$(basename "${expected_root}")"

    [[ -d "${server_root}" ]] || return 0

    while IFS= read -r candidate; do
        [[ -n "${candidate}" ]] || continue
        candidate="$(normalize_dir_path "${candidate}")" || continue
        [[ "${candidate}" = "${expected_root}" ]] && continue
        [[ -n "${seen[${candidate}]+x}" ]] && continue
        seen["${candidate}"]=1
        printf "%s\n" "${candidate}"
    done < <(find "${server_root}" -type d \( -name "${expected_basename}" -o -name 'ManagedRepository' \) -print 2>/dev/null | sort -u)
}

# Ensure service user directory. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_service_user_directory() {
    local path="${1:?BUG: ensure_service_user_directory requires a path}"
    local label="${2:?BUG: ensure_service_user_directory requires a label}"
    local owner_uid=""
    local owner_gid=""

    # Test path access as the long-running OMERO service user. Inputs: shell arguments and environment. Output: command status.
    service_user_has_access() {
        local test_flag="${1:?BUG: service_user_has_access requires a test flag}"
        if [[ "$(id -u)" -eq 0 ]]; then
            runuser -u "${OMERO_CLI_USER}" -- test "${test_flag}" "${path}"
            return $?
        fi
        test "${test_flag}" "${path}"
    }

    if [[ "${path}" != /* ]]; then
        echo "ERROR: ${label} must be an absolute path, got: ${path}" >&2
        exit 1
    fi

    if [[ -e "${path}" && ! -d "${path}" ]]; then
        echo "ERROR: ${label} exists but is not a directory: ${path}" >&2
        exit 1
    fi

    mkdir -p "${path}" || {
        echo "ERROR: Failed to create ${label}: ${path}" >&2
        exit 1
    }

    if [[ "$(id -u)" -eq 0 ]]; then
        owner_uid="$(id -u "${OMERO_CLI_USER}")"
        owner_gid="$(id -g "${OMERO_CLI_USER}")"
        if ! service_user_has_access -r \
            || ! service_user_has_access -w \
            || ! service_user_has_access -x; then
            chown "${owner_uid}:${owner_gid}" "${path}" || {
                echo "ERROR: Failed to assign ${label} to ${OMERO_CLI_USER}: ${path}" >&2
                exit 1
            }
            chmod u+rwx "${path}" 2>/dev/null || true
        fi
    fi

    if ! service_user_has_access -r \
        || ! service_user_has_access -w \
        || ! service_user_has_access -x; then
        echo "ERROR: ${label} is not readable, writable, and traversable by ${OMERO_CLI_USER}: ${path}" >&2
        ls -ld "${path}" >&2 || true
        exit 1
    fi

    log "${label} service-user writable: ${path}"
}

# Validate managed repository configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_managed_repository_configuration() {
    local expected_root=""
    local -a unexpected_roots=()

    expected_root="$(expected_managed_repository_root)" || exit 1

    mapfile -t unexpected_roots < <(find_unexpected_server_managed_repository_dirs)
    if [[ "${#unexpected_roots[@]}" -gt 0 ]]; then
        {
            echo "ERROR: Refusing startup because unexpected image-local managed repository directories exist:"
            printf ' - %s\n' "${unexpected_roots[@]}"
            echo "ERROR: Only the bind-mounted managed repository under ${expected_root} is allowed."
        } >&2
        exit 1
    fi
}

# Ensure server data runtime directories. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_server_data_runtime_directories() {
    local data_root=""

    data_root="$(normalize_dir_path "${OMERO_DIR}")" || {
        echo "ERROR: OMERO_DIR must be a non-empty absolute path, got: '${OMERO_DIR}'" >&2
        exit 1
    }
    if [[ "${data_root}" != /* ]]; then
        echo "ERROR: OMERO_DIR must be an absolute path, got: '${OMERO_DIR}'" >&2
        exit 1
    fi

    ensure_service_user_directory "${data_root}" "OMERO data"
    ensure_service_user_directory "${data_root}/FullText" "OMERO full text index"
    ensure_service_user_directory "$(expected_managed_repository_root)" "OMERO managed repository"
}

# Verify managed repository runtime safety. Inputs: shell arguments and environment. Output: command status and side effects.
verify_managed_repository_runtime_safety() {
    local expected_root=""
    local actual_root=""
    local -a unexpected_roots=()

    expected_root="$(expected_managed_repository_root)" || return 1
    actual_root="$(trim_whitespace "$(run_omero config get omero.managed.dir 2>/dev/null || true)")"
    actual_root="$(normalize_dir_path "${actual_root}")" || actual_root=""

    if [[ -z "${actual_root}" ]]; then
        echo "ERROR: Failed to read persisted omero.managed.dir during runtime validation." >&2
        return 1
    fi

    if [[ "${actual_root}" != "${expected_root}" ]]; then
        echo "ERROR: Persisted omero.managed.dir drifted from expected managed repository root. Expected '${expected_root}', got '${actual_root}'." >&2
        return 1
    fi

    if [[ ! -d "${expected_root}" ]]; then
        echo "ERROR: Expected managed repository root does not exist at runtime: ${expected_root}" >&2
        return 1
    fi

    mapfile -t unexpected_roots < <(find_unexpected_server_managed_repository_dirs)
    if [[ "${#unexpected_roots[@]}" -gt 0 ]]; then
        {
            echo "ERROR: Unexpected image-local managed repository directories detected during runtime validation:"
            printf ' - %s\n' "${unexpected_roots[@]}"
        } >&2
        return 1
    fi

    return 0
}

# Execute a command as the OMERO CLI user. Inputs: shell arguments and environment. Output: command status and side effects.
run_as_omero_cli_user() {
    if ! id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        echo "FATAL: user '${OMERO_CLI_USER}' not found; cannot run OMERO CLI safely." >&2
        exit 1
    fi

    local cli_home=""
    cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")" || exit 1

    local cli_tmpdir=""
    cli_tmpdir="$(resolve_omero_cli_tmpdir)" || exit 1

    local had_home=0
    local had_tmpdir=0
    local had_omero_tmpdir=0
    local had_omero_tempdir=0
    local had_omero_userdir=0
    local had_omero_sessiondir=0
    local had_user=0
    local had_logname=0
    local had_lname=0
    local had_username=0
    local old_home=""
    local old_tmpdir=""
    local old_omero_tmpdir=""
    local old_omero_tempdir=""
    local old_omero_userdir=""
    local old_omero_sessiondir=""
    local old_user=""
    local old_logname=""
    local old_lname=""
    local old_username=""
    local rc=0

    if [[ -n "${HOME+x}" ]]; then had_home=1; old_home="${HOME}"; fi
    if [[ -n "${TMPDIR+x}" ]]; then had_tmpdir=1; old_tmpdir="${TMPDIR}"; fi
    if [[ -n "${OMERO_TMPDIR+x}" ]]; then had_omero_tmpdir=1; old_omero_tmpdir="${OMERO_TMPDIR}"; fi
    if [[ -n "${OMERO_TEMPDIR+x}" ]]; then had_omero_tempdir=1; old_omero_tempdir="${OMERO_TEMPDIR}"; fi
    if [[ -n "${OMERO_USERDIR+x}" ]]; then had_omero_userdir=1; old_omero_userdir="${OMERO_USERDIR}"; fi
    if [[ -n "${OMERO_SESSIONDIR+x}" ]]; then had_omero_sessiondir=1; old_omero_sessiondir="${OMERO_SESSIONDIR}"; fi
    if [[ -n "${USER+x}" ]]; then had_user=1; old_user="${USER}"; fi
    if [[ -n "${LOGNAME+x}" ]]; then had_logname=1; old_logname="${LOGNAME}"; fi
    if [[ -n "${LNAME+x}" ]]; then had_lname=1; old_lname="${LNAME}"; fi
    if [[ -n "${USERNAME+x}" ]]; then had_username=1; old_username="${USERNAME}"; fi

    export HOME="${cli_home}"
    export TMPDIR="${cli_tmpdir}"
    export OMERO_TMPDIR="${cli_tmpdir}"
    export OMERO_TEMPDIR="${cli_tmpdir}"
    export OMERO_USERDIR="${cli_tmpdir}/userdir"
    export OMERO_SESSIONDIR="${OMERO_USERDIR}/sessions"
    export USER="${OMERO_CLI_USER}"
    export LOGNAME="${OMERO_CLI_USER}"
    export LNAME="${OMERO_CLI_USER}"
    export USERNAME="${OMERO_CLI_USER}"

    # Preserve sensitive values through the process environment instead of
    # argv. The command line remains inspectable during long startup waits.
    if [[ -n "${OMERO_PASSWORD+x}" ]]; then export OMERO_PASSWORD; fi
    if [[ -n "${ROOTPASS+x}" ]]; then export ROOTPASS; fi
    if [[ -n "${OMERO_JOB_SERVICE_PASS+x}" ]]; then export OMERO_JOB_SERVICE_PASS; fi
    if [[ -n "${OMERO_BIN+x}" ]]; then export OMERO_BIN; fi
    if [[ -n "${ICE_CONFIG+x}" ]]; then export ICE_CONFIG; fi

    if [[ "$(id -u)" -eq 0 ]]; then
        runuser -p -m -u "${OMERO_CLI_USER}" -- "$@" || rc=$?
    else
        "$@" || rc=$?
    fi

    if [[ "${had_home}" -eq 1 ]]; then export HOME="${old_home}"; else unset HOME || true; fi
    if [[ "${had_tmpdir}" -eq 1 ]]; then export TMPDIR="${old_tmpdir}"; else unset TMPDIR || true; fi
    if [[ "${had_omero_tmpdir}" -eq 1 ]]; then export OMERO_TMPDIR="${old_omero_tmpdir}"; else unset OMERO_TMPDIR || true; fi
    if [[ "${had_omero_tempdir}" -eq 1 ]]; then export OMERO_TEMPDIR="${old_omero_tempdir}"; else unset OMERO_TEMPDIR || true; fi
    if [[ "${had_omero_userdir}" -eq 1 ]]; then export OMERO_USERDIR="${old_omero_userdir}"; else unset OMERO_USERDIR || true; fi
    if [[ "${had_omero_sessiondir}" -eq 1 ]]; then export OMERO_SESSIONDIR="${old_omero_sessiondir}"; else unset OMERO_SESSIONDIR || true; fi
    if [[ "${had_user}" -eq 1 ]]; then export USER="${old_user}"; else unset USER || true; fi
    if [[ "${had_logname}" -eq 1 ]]; then export LOGNAME="${old_logname}"; else unset LOGNAME || true; fi
    if [[ "${had_lname}" -eq 1 ]]; then export LNAME="${old_lname}"; else unset LNAME || true; fi
    if [[ "${had_username}" -eq 1 ]]; then export USERNAME="${old_username}"; else unset USERNAME || true; fi

    return "${rc}"
}

# Execute OMERO. Inputs: shell arguments and environment. Output: command status and side effects.
run_omero() {
    run_as_omero_cli_user "${OMERO_BIN}" "$@"
}

# Write cli keepalive config. Inputs: shell arguments and environment. Output: command status and side effects.
write_cli_keepalive_config() {
    local keepalive_seconds="${1:?BUG: write_cli_keepalive_config requires keepalive seconds}"
    local base_config="${ICE_CONFIG:-}"
    local target_dir=""
    local config_path=""
    local owner_uid=""
    local owner_gid=""

    if ! is_non_negative_integer "${keepalive_seconds}"; then
        echo "ERROR: Invalid OMERO CLI keepalive value: ${keepalive_seconds}" >&2
        return 1
    fi

    if (( keepalive_seconds <= 0 )); then
        return 1
    fi

    target_dir="$(resolve_omero_cli_tmpdir)" || return 1
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

# Execute OMERO with keepalive. Inputs: shell arguments and environment. Output: command status and side effects.
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

    if is_positive_integer "${keepalive_seconds}"; then
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

# Ensure tmpdir permissions. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_tmpdir_permissions() {
    local requested_owner="$1"
    local tmp_root="${OMERO_TMP_PATH:-}"
    local expected_tmp_dir=""
    local legacy_tmp_dir=""
    local runtime_tmp_dir=""
    legacy_tmp_dir="$(dirname "${SERVER_HOME}")/omero/tmp"
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

    # Prepare runtime temporary directory. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Validate ldap configuration. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Validate ldap new user group configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_ldap_new_user_group_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    if [[ -z "${ldap_group_setting}" ]]; then
        log "LDAP enabled without CONFIG_omero_ldap_new__user__group; OMERO will use its built-in default new-user group behavior"
        return
    fi

    if [[ "${ldap_group_setting}" = :* ]]; then
        log "LDAP new-user group uses dynamic mapping expression (${ldap_group_setting}); runtime group auto-bootstrap is skipped"
        return
    fi

    if ! is_omero_group_name "${ldap_group_setting}"; then
        echo "ERROR: CONFIG_omero_ldap_new__user__group contains invalid OMERO group name '${ldap_group_setting}'. Allowed pattern: [A-Za-z0-9_.-]+" >&2
        exit 1
    fi
}

# Validate job service bootstrap configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_job_service_bootstrap_configuration() {
    require_nonempty_env_var "OMERO_JOB_SERVICE_USERNAME"
    require_nonempty_env_var "OMERO_JOB_SERVICE_JOIN_ALL_GROUPS"
    require_nonempty_env_var "OMERO_JOB_SERVICE_HOST"
    require_tcp_port_env_var "OMERO_JOB_SERVICE_PORT"

    local required_positive_integer_vars=(
        "OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS"
        "OMERO_JOB_SERVICE_READINESS_POLL_SECONDS"
        "OMERO_JOB_SERVICE_USER_ENSURE_RETRIES"
        "OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS"
        "OMERO_JOB_SERVICE_SYNC_MAX_RETRIES"
    )

    local var_name
    for var_name in "${required_positive_integer_vars[@]}"; do
        require_positive_integer_env_var "${var_name}"
    done

    local jitter_val="${OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS-}"
    if [[ -z "${jitter_val}" ]] || ! is_non_negative_integer "${jitter_val}"; then
        echo "ERROR: OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS must be a non-negative integer, got: '${jitter_val}'" >&2
        exit 1
    fi

    if [[ "${OMERO_JOB_SERVICE_JOIN_ALL_GROUPS}" != "0" && "${OMERO_JOB_SERVICE_JOIN_ALL_GROUPS}" != "1" ]]; then
        echo "ERROR: OMERO_JOB_SERVICE_JOIN_ALL_GROUPS must be 0 or 1, got: '${OMERO_JOB_SERVICE_JOIN_ALL_GROUPS}'" >&2
        exit 1
    fi

    if [[ -z "${OMERO_JOB_SERVICE_SECURE-}" ]]; then
        echo "ERROR: OMERO_JOB_SERVICE_SECURE must be set." >&2
        exit 1
    fi

    if ! is_truthy_bool "${OMERO_JOB_SERVICE_SECURE}" \
        && ! is_falsey_bool "${OMERO_JOB_SERVICE_SECURE}"; then
        echo "ERROR: OMERO_JOB_SERVICE_SECURE must be a boolean value, got: '${OMERO_JOB_SERVICE_SECURE}'" >&2
        exit 1
    fi
}

# Validate binary repository cleanse configuration. Inputs: shell arguments and environment. Output: command status and side effects.
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
        if ! is_non_negative_integer "${keepalive_seconds}"; then
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

# Validate repository lock cleanup configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_repository_lock_cleanup_configuration() {
    local enabled="${OMERO_REPOSITORY_LOCK_CLEANUP_ON_START:-1}"

    if [[ "${enabled}" != "0" && "${enabled}" != "1" ]]; then
        echo "ERROR: OMERO_REPOSITORY_LOCK_CLEANUP_ON_START must be 0 or 1, got: '${enabled}'" >&2
        exit 1
    fi
}

# Validate rendering cache cleanup configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_rendering_cache_cleanup_configuration() {
    local enabled="${OMERO_RENDERING_CACHE_CLEANUP_ON_START:-0}"

    if [[ "${enabled}" != "0" && "${enabled}" != "1" ]]; then
        echo "ERROR: OMERO_RENDERING_CACHE_CLEANUP_ON_START must be 0 or 1, got: '${enabled}'" >&2
        exit 1
    fi
}

# Cleanup rendering caches. Inputs: shell arguments and environment. Output: command status and side effects.
cleanup_rendering_caches() {
    local enabled="${OMERO_RENDERING_CACHE_CLEANUP_ON_START:-0}"

    if [[ "${enabled}" != "1" ]]; then
        log "Skipping rendering cache cleanup (OMERO_RENDERING_CACHE_CLEANUP_ON_START != 1)."
        return
    fi

    local omero_dir="${OMERO_DIR%/}"
    local pyramids_dir="${omero_dir}/Pixels"
    local bioformats_cache_dir="${omero_dir}/BioFormatsCache"
    local thumbnails_dir="${omero_dir}/Thumbnails"
    local total_removed=0

    # Pyramid cleanup is safe ONLY when OMERO_ZARR_PIXEL_BUFFER_ENABLED=false
    # (the default).  With ZarrPixelsService disabled, the standard OMERO
    # PixelsService handles pyramid regeneration automatically on first access.
    if [[ -d "${pyramids_dir}" ]]; then
        local pyramid_count=0
        while IFS= read -r -d '' pyramid_path; do
            rm -rf "${pyramid_path}" && pyramid_count=$((pyramid_count + 1))
        done < <(find "${pyramids_dir}" -maxdepth 2 -name '*_pyramid' -print0 2>/dev/null)
        if [[ "${pyramid_count}" -gt 0 ]]; then
            log "Removed ${pyramid_count} pyramid file(s) from ${pyramids_dir}"
            total_removed=$((total_removed + pyramid_count))
        fi
    fi

    # --- Bio-Formats memo cache ---
    if [[ -d "${bioformats_cache_dir}" ]]; then
        local bf_count=0
        bf_count=$(find "${bioformats_cache_dir}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
        if [[ "${bf_count}" -gt 0 ]]; then
            rm -rf "${bioformats_cache_dir:?}"/*
            log "Cleared Bio-Formats memo cache (${bf_count} entries) from ${bioformats_cache_dir}"
            total_removed=$((total_removed + bf_count))
        fi
    fi

    # --- Thumbnail cache ---
    if [[ -d "${thumbnails_dir}" ]]; then
        local thumb_count=0
        thumb_count=$(find "${thumbnails_dir}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
        if [[ "${thumb_count}" -gt 0 ]]; then
            rm -rf "${thumbnails_dir:?}"/*
            log "Cleared thumbnail cache (${thumb_count} entries) from ${thumbnails_dir}"
            total_removed=$((total_removed + thumb_count))
        fi
    fi

    if [[ "${total_removed}" -gt 0 ]]; then
        log "Rendering cache cleanup finished: removed ${total_removed} total item(s)"
        log "IMPORTANT: Set OMERO_RENDERING_CACHE_CLEANUP_ON_START=0 in env/omeroserver.env to avoid repeating the cleanup on subsequent starts."
    else
        log "Rendering cache cleanup: nothing to remove"
    fi
}

# Validate Zarr pixel buffer configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_zarr_pixel_buffer_configuration() {
    local enabled="${OMERO_ZARR_PIXEL_BUFFER_ENABLED:-false}"

    if [[ "${enabled}" != "true" && "${enabled}" != "false" && "${enabled}" != "0" && "${enabled}" != "1" ]]; then
        echo "ERROR: OMERO_ZARR_PIXEL_BUFFER_ENABLED must be true or false, got: '${enabled}'" >&2
        exit 1
    fi
}

# Toggle Zarr pixel buffer plugin. Inputs: shell arguments and environment. Output: command status and side effects.
toggle_zarr_pixel_buffer_plugin() {
    local enabled="${OMERO_ZARR_PIXEL_BUFFER_ENABLED:-false}"
    local server_lib="${SERVER_HOME}/lib/server"
    local disabled_dir="${SERVER_HOME}/lib/server-disabled"

    if [[ "${enabled}" = "true" || "${enabled}" = "1" ]]; then
        # Restore plugin JARs from disabled directory if they were previously moved
        if [[ -d "${disabled_dir}" ]]; then
            local restored=0
            for jar in "${disabled_dir}"/omero-zarr-pixel-buffer-*.jar "${disabled_dir}"/caffeine-*.jar \
                        "${disabled_dir}"/aws-java-sdk-*.jar "${disabled_dir}"/s3fs-*.jar "${disabled_dir}"/tika-core-*.jar; do
                if [[ -f "${jar}" ]]; then
                    mv "${jar}" "${server_lib}/" && restored=$((restored + 1))
                fi
            done
            if [[ "${restored}" -gt 0 ]]; then
                log "Restored ${restored} omero-zarr-pixel-buffer JAR(s) to classpath (OMERO_ZARR_PIXEL_BUFFER_ENABLED=true)"
            fi
        fi
    else
        # Move plugin JARs out of classpath so standard PixelsService handles everything
        local moved=0
        for jar in "${server_lib}"/omero-zarr-pixel-buffer-*.jar; do
            if [[ -f "${jar}" ]]; then
                mkdir -p "${disabled_dir}"
                mv "${jar}" "${disabled_dir}/" && moved=$((moved + 1))
                # Move runtime dependencies too
                for dep in "${server_lib}"/caffeine-*.jar "${server_lib}"/aws-java-sdk-*.jar \
                           "${server_lib}"/s3fs-*.jar "${server_lib}"/tika-core-*.jar; do
                    if [[ -f "${dep}" ]]; then
                        mv "${dep}" "${disabled_dir}/" && moved=$((moved + 1))
                    fi
                done
            fi
        done
        if [[ "${moved}" -gt 0 ]]; then
            log "Moved ${moved} omero-zarr-pixel-buffer JAR(s) out of classpath (OMERO_ZARR_PIXEL_BUFFER_ENABLED=false)"
        fi
    fi
}

# Validate repo root sync configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_repo_root_sync_configuration() {
    local interval="${OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS:-3600}"
    local jitter="${OMERO_REPO_ROOT_SYNC_JITTER_SECONDS:-20}"
    local stable_prefix_depth=""

    if ! is_positive_integer "${interval}"; then
        echo "ERROR: OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS must be a positive integer, got: '${interval}'" >&2
        exit 1
    fi

    if ! is_non_negative_integer "${jitter}"; then
        echo "ERROR: OMERO_REPO_ROOT_SYNC_JITTER_SECONDS must be a non-negative integer, got: '${jitter}'" >&2
        exit 1
    fi

    if [[ -n "${OMERO_REPO_ROOT_BOOTSTRAP_RETRIES-}" ]]; then
        require_positive_integer_env_var "OMERO_REPO_ROOT_BOOTSTRAP_RETRIES"
    fi

    if [[ -n "${OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS-}" ]]; then
        require_positive_integer_env_var "OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS"
    fi

    stable_prefix_depth="$(repo_root_sync_stable_prefix_depth "$(resolve_server_venv_python)")" || {
        echo "ERROR: Failed to analyze CONFIG_omero_fs_repo_path for shared-prefix sync." >&2
        exit 1
    }
    if ! is_non_negative_integer "${stable_prefix_depth}"; then
        echo "ERROR: Invalid shared-prefix depth reported for CONFIG_omero_fs_repo_path: '${stable_prefix_depth}'" >&2
        exit 1
    fi
}

# Validate dropbox user directory sync configuration. Inputs: shell arguments and environment. Output: command status and side effects.
validate_dropbox_user_dir_sync_configuration() {
    require_nonempty_env_var "OMERO_DROPBOX_ENABLED"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_ENABLED"

    local dropbox_enabled="${OMERO_DROPBOX_ENABLED}"
    local enabled="${OMERO_DROPBOX_USER_DIR_SYNC_ENABLED}"
    local ice_startup_wait=""
    local ice_poll_interval=""
    local interval=""
    local jitter=""
    local startup_wait=""
    local poll_interval=""
    local retries=""
    local port=""
    local secure=""
    local password_env=""
    local create_root=""
    local mode=""
    local allow_world_writable=""
    local venv_py=""

    case "${dropbox_enabled}" in
        1|0|true|false|yes|no|on|off) ;;
        *)
            echo "ERROR: OMERO_DROPBOX_ENABLED must be a boolean value, got: '${dropbox_enabled}'" >&2
            exit 1
            ;;
    esac

    if is_truthy_bool "${dropbox_enabled}"; then
        require_nonempty_env_var "OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS"
        require_nonempty_env_var "OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS"

        ice_startup_wait="${OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS}"
        ice_poll_interval="${OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS}"

        if ! is_positive_integer "${ice_startup_wait}"; then
            echo "ERROR: OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS must be a positive integer, got: '${ice_startup_wait}'" >&2
            exit 1
        fi

        if ! is_positive_integer "${ice_poll_interval}"; then
            echo "ERROR: OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS must be a positive integer, got: '${ice_poll_interval}'" >&2
            exit 1
        fi

        if [[ -n "${OMERO_DROPBOX_ICE_BOOTSTRAP_MAX_RETRY_SECONDS-}" ]]; then
            require_positive_integer_env_var "OMERO_DROPBOX_ICE_BOOTSTRAP_MAX_RETRY_SECONDS"
        fi
    fi

    if [[ "${enabled}" != "1" && "${enabled}" != "0" ]]; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_ENABLED must be 0 or 1, got: '${enabled}'" >&2
        exit 1
    fi

    if is_falsey_bool "${dropbox_enabled}" && [[ "${enabled}" = "1" ]]; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_ENABLED=1 requires OMERO_DROPBOX_ENABLED=1." >&2
        exit 1
    fi

    if [[ "${enabled}" != "1" ]]; then
        return
    fi

    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_INTERVAL_SECONDS"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_JITTER_SECONDS"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_HOST"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PORT"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_SECURE"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_USERNAME"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PASSWORD_ENV"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_CREATE_ROOT"
    require_set_env_var "OMERO_DROPBOX_USER_DIR_OWNER"
    require_set_env_var "OMERO_DROPBOX_USER_DIR_GROUP"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_MODE"
    require_nonempty_env_var "OMERO_DROPBOX_USER_DIR_ALLOW_WORLD_WRITABLE"

    interval="${OMERO_DROPBOX_USER_DIR_SYNC_INTERVAL_SECONDS}"
    jitter="${OMERO_DROPBOX_USER_DIR_SYNC_JITTER_SECONDS}"
    startup_wait="${OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS}"
    poll_interval="${OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS}"
    retries="${OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES}"
    port="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PORT}"
    secure="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_SECURE}"
    password_env="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PASSWORD_ENV}"
    create_root="${OMERO_DROPBOX_USER_DIR_CREATE_ROOT}"
    mode="${OMERO_DROPBOX_USER_DIR_MODE}"
    allow_world_writable="${OMERO_DROPBOX_USER_DIR_ALLOW_WORLD_WRITABLE}"

    if [[ ! -r "${DROPBOX_USER_DIR_SYNC_HELPER}" ]]; then
        echo "ERROR: Missing DropBox user directory sync helper: ${DROPBOX_USER_DIR_SYNC_HELPER}" >&2
        exit 1
    fi

    if ! is_positive_integer "${interval}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_INTERVAL_SECONDS must be a positive integer, got: '${interval}'" >&2
        exit 1
    fi

    if ! is_non_negative_integer "${jitter}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_JITTER_SECONDS must be a non-negative integer, got: '${jitter}'" >&2
        exit 1
    fi

    if ! is_positive_integer "${startup_wait}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS must be a positive integer, got: '${startup_wait}'" >&2
        exit 1
    fi

    if ! is_positive_integer "${poll_interval}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS must be a positive integer, got: '${poll_interval}'" >&2
        exit 1
    fi

    if ! is_positive_integer "${retries}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES must be a positive integer, got: '${retries}'" >&2
        exit 1
    fi

    if ! is_positive_integer "${port}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PORT must be a positive integer, got: '${port}'" >&2
        exit 1
    fi

    case "${secure}" in
        1|0|true|false|yes|no|on|off) ;;
        *)
            echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_OMERO_SECURE must be a boolean value, got: '${secure}'" >&2
            exit 1
            ;;
    esac

    case "${create_root}" in
        1|0|true|false|yes|no|on|off) ;;
        *)
            echo "ERROR: OMERO_DROPBOX_USER_DIR_CREATE_ROOT must be a boolean value, got: '${create_root}'" >&2
            exit 1
            ;;
    esac

    if ! is_env_var_name "${password_env}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PASSWORD_ENV must be an environment variable name, got: '${password_env}'" >&2
        exit 1
    fi

    venv_py="$(resolve_server_venv_python)"
    "${venv_py}" "${DROPBOX_USER_DIR_SYNC_HELPER}" validate \
        --mode "${mode}" \
        --allow-world-writable "${allow_world_writable}" || exit 1
}

# Cleanup stale repository lock files. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Apply ldap runtime configuration. Inputs: shell arguments and environment. Output: command status and side effects.
apply_ldap_runtime_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_user_filter="${CONFIG_omero_ldap_user__filter:-}"
    local ldap_new_user_group="${CONFIG_omero_ldap_new__user__group:-}"
    local ldap_urls="${CONFIG_omero_ldap_urls:-}"
    local ldap_username="${CONFIG_omero_ldap_username:-}"
    local -n ldap_bind_value=CONFIG_omero_ldap_password
    local ldap_base="${CONFIG_omero_ldap_base-}"

    run_omero config set omero.ldap.config true
    run_omero config set omero.ldap.urls "${ldap_urls}"
    run_omero config set omero.ldap.username "${ldap_username}"
    run_omero config set omero.ldap.password "${ldap_bind_value}"
    run_omero config set omero.ldap.base "${ldap_base}"
    
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

# Check writable directory. Inputs: shell arguments and environment. Output: command status and side effects.
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

    if ! touch "${path}/.permission_test" 2>/dev/null; then
        echo "ERROR: ${label} is not writable: ${path}" >&2
        exit 1
    fi

    rm -f "${path}/.permission_test"
    log "${label} writable after ownership fix: ${path}"
}

# Reset runtime if requested. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Configure script python. Inputs: shell arguments and environment. Output: command status and side effects.
configure_script_python() {
    local venv_py
    venv_py="$(resolve_server_venv_python)"
    run_omero config set omero.scripts.python "${venv_py}"
    log "Configured omero.scripts.python=${venv_py}"
}

# Configure import runtime paths. Inputs: shell arguments and environment. Output: command status and side effects.
configure_import_runtime_paths() {
    local shared_tmp_path="${OMERO_TMP_PATH:-}"
    local runtime_state_path="${SERVER_VAR_DIR%/}/managed-zarr-runtime.env"
    local runtime_state_tmp="${runtime_state_path}.tmp"

    if [[ -z "${shared_tmp_path}" ]]; then
        echo "ERROR: OMERO_TMP_PATH is required for import runtime configuration." >&2
        exit 1
    fi

    printf '%s\n' \
        "omero.web.import.shared_tmp_path=${shared_tmp_path}" \
        > "${runtime_state_tmp}"
    mv -f "${runtime_state_tmp}" "${runtime_state_path}"
    chown "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${runtime_state_path}" 2>/dev/null || true
    chmod 0644 "${runtime_state_path}" 2>/dev/null || true

    log "Wrote import runtime path state to ${runtime_state_path}"
}

# Ensure certificate sans. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Schedule job service bootstrap. Inputs: shell arguments and environment. Output: command status and side effects.
schedule_job_service_bootstrap() {
    local root_pass="${ROOTPASS:-}"
    local job_user="${OMERO_JOB_SERVICE_USERNAME}"
    local job_pass="${OMERO_JOB_SERVICE_PASS:-}"
    local join_all="${OMERO_JOB_SERVICE_JOIN_ALL_GROUPS}"
    local interval="${OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS}"
    local max_retries="${OMERO_JOB_SERVICE_SYNC_MAX_RETRIES}"
    local jitter_max="${OMERO_JOB_SERVICE_SYNC_JITTER_SECONDS}"
    local startup_wait="${OMERO_JOB_SERVICE_STARTUP_WAIT_SECONDS}"
    local poll_interval="${OMERO_JOB_SERVICE_READINESS_POLL_SECONDS}"
    local host="${OMERO_JOB_SERVICE_HOST}"
    local port="${OMERO_JOB_SERVICE_PORT}"
    local secure="${OMERO_JOB_SERVICE_SECURE}"
    local user_ensure_retries="${OMERO_JOB_SERVICE_USER_ENSURE_RETRIES}"
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

        # Wait for server. Inputs: shell arguments and environment. Output: command status and side effects.
        wait_for_server() {
            local wait_seconds="$1"
            local deadline=$(( $(date +%s) + wait_seconds ))

            while [[ "$(date +%s)" -lt "${deadline}" ]]; do
                if OMERO_PASSWORD="${root_pass}" run_omero -C -s "${host}" -p "${port}" login -u root >/dev/null 2>&1 \
                    && OMERO_PASSWORD="${root_pass}" run_omero user list -s "${host}" -p "${port}" -u root >/dev/null 2>&1; then
                    return 0
                fi
                sleep "${poll_interval}"
            done
            return 1
        }

        # Execute job service group sync helper. Inputs: shell arguments and environment. Output: command status and side effects.
        run_job_service_group_sync_helper() {
            local venv_py=""
            local cli_home=""
            local cli_tmpdir=""
            local -a helper_cmd=()

            if [[ ! -r "${JOB_SERVICE_GROUP_SYNC_HELPER}" ]]; then
                echo "[$(date -u)] ERROR: Missing job-service group sync helper: ${JOB_SERVICE_GROUP_SYNC_HELPER}"
                return 1
            fi

            venv_py="$(resolve_server_venv_python)"
            cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")" || return 1
            cli_tmpdir="$(resolve_omero_cli_tmpdir)" || return 1

            helper_cmd=(
                "${venv_py}"
                "${JOB_SERVICE_GROUP_SYNC_HELPER}"
                --host "${host}"
                --port "${port}"
                --secure "${secure}"
                --root-user "root"
                --job-user "${job_user}"
                --user-retries "${user_ensure_retries}"
            )

            if [[ "$(id -u)" -eq 0 ]]; then
                HOME="${cli_home}" \
                    TMPDIR="${cli_tmpdir}" \
                    OMERO_TMPDIR="${cli_tmpdir}" \
                    OMERO_TEMPDIR="${cli_tmpdir}" \
                    OMERO_USERDIR="${cli_tmpdir}/userdir" \
                    OMERO_SESSIONDIR="${cli_tmpdir}/userdir/sessions" \
                    USER="${OMERO_CLI_USER}" \
                    LOGNAME="${OMERO_CLI_USER}" \
                    LNAME="${OMERO_CLI_USER}" \
                    USERNAME="${OMERO_CLI_USER}" \
                    ROOTPASS="${root_pass}" \
                    OMERO_JOB_SERVICE_PASS="${job_pass}" \
                    runuser -p -m -u "${OMERO_CLI_USER}" -- "${helper_cmd[@]}"
            else
                HOME="${cli_home}" \
                    TMPDIR="${cli_tmpdir}" \
                    OMERO_TMPDIR="${cli_tmpdir}" \
                    OMERO_TEMPDIR="${cli_tmpdir}" \
                    ROOTPASS="${root_pass}" \
                    OMERO_JOB_SERVICE_PASS="${job_pass}" \
                    "${helper_cmd[@]}"
            fi
        }

        # Sync once. Inputs: shell arguments and environment. Output: command status and side effects.
        sync_once() {
            local ready_wait="$1"
            
            # Print debug info
            echo "[$(date -u)] DEBUG: Checking OMERO readiness..."
            if ! wait_for_server "${ready_wait}"; then
                echo "[$(date -u)] WARN: OMERO not ready after ${ready_wait}s"
                return 1
            fi
            echo "[$(date -u)] DEBUG: OMERO is ready. Running job-service group sync helper..."

            run_job_service_group_sync_helper
        }

        while true; do
            start="$(date +%s)"
            ok=0

            for attempt in $(seq 1 "${max_retries}"); do
                if sync_once "${startup_wait}"; then
                    ok=1
                    break
                fi
                if [[ "${attempt}" -lt "${max_retries}" ]]; then
                    echo "[$(date -u)] WARN: sync attempt ${attempt}/${max_retries} did not complete; retrying in ${poll_interval}s with readiness window ${startup_wait}s"
                    sleep "${poll_interval}"
                fi
            done

            [[ "${ok}" -eq 1 ]] || echo "[$(date -u)] ERROR: Job-service group sync failed after ${max_retries} attempts; will wait until next interval"

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

# Schedule ldap group bootstrap. Inputs: shell arguments and environment. Output: command status and side effects.
schedule_ldap_group_bootstrap() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    if [[ -z "${ldap_group_setting}" || "${ldap_group_setting}" = :* ]]; then
        return
    fi

    if [[ "${ldap_group_setting}" = "default" ]]; then
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
            if OMERO_PASSWORD="${root_pass}" run_omero -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" login -u root >/dev/null 2>&1; then
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
            add_output="$(OMERO_PASSWORD="${root_pass}" run_omero group add "${ldap_group_setting}" --type=private -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" -u root 2>&1)"
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

# Perform repo root sync stable prefix depth. Inputs: shell arguments and environment. Output: command status and side effects.
repo_root_sync_stable_prefix_depth() {
    local python_bin="${1:?BUG: repo_root_sync_stable_prefix_depth requires a python path}"

    if [[ ! -r "${REPO_ROOT_SYNC_HELPER}" ]]; then
        echo "ERROR: Missing repo-root sync helper: ${REPO_ROOT_SYNC_HELPER}" >&2
        return 1
    fi

    "${python_bin}" "${REPO_ROOT_SYNC_HELPER}" stable-depth \
        --repo-template "${CONFIG_omero_fs_repo_path:-}"
}

# Execute repo root sync helper. Inputs: shell arguments and environment. Output: command status and side effects.
run_repo_root_sync_helper() {
    local python_bin="${1:?BUG: run_repo_root_sync_helper requires a python path}"
    local cli_home="${2:?BUG: run_repo_root_sync_helper requires a CLI home}"
    local cli_tmpdir=""
    shift 2

    if [[ ! -r "${REPO_ROOT_SYNC_HELPER}" ]]; then
        echo "ERROR: Missing repo-root sync helper: ${REPO_ROOT_SYNC_HELPER}" >&2
        return 1
    fi

    cli_tmpdir="$(resolve_omero_cli_tmpdir)" || return 1

    run_as_omero_cli_user "${python_bin}" "${REPO_ROOT_SYNC_HELPER}" "$@"
}

# Build repo root sync plan. Inputs: shell arguments and environment. Output: command status and side effects.
build_repo_root_sync_plan() {
    local python_bin="${1:?BUG: build_repo_root_sync_plan requires a python path}"
    local cli_home="${2:?BUG: build_repo_root_sync_plan requires a CLI home}"

    run_repo_root_sync_helper "${python_bin}" "${cli_home}" plan \
        --managed-root "$(expected_managed_repository_root)" \
        --repo-template "${CONFIG_omero_fs_repo_path:-}" \
        --install-groups "${OMERO_INSTALL_GROUP_LIST:-}" \
        --ldap-config "${CONFIG_omero_ldap_config:-false}" \
        --ldap-group "${CONFIG_omero_ldap_new__user__group:-}"
}

# Perform lookup repo root prefix. Inputs: shell arguments and environment. Output: command status and side effects.
lookup_repo_root_prefix() {
    local python_bin="${1:?BUG: lookup_repo_root_prefix requires a python path}"
    local cli_home="${2:?BUG: lookup_repo_root_prefix requires a CLI home}"
    local root_pass="${3:?BUG: lookup_repo_root_prefix requires ROOTPASS}"
    local repo_dir_path="${4:?BUG: lookup_repo_root_prefix requires a repo path}"
    local managed_repo_root="${5:?BUG: lookup_repo_root_prefix requires a managed root}"

    ROOTPASS="${root_pass}" run_repo_root_sync_helper "${python_bin}" "${cli_home}" lookup \
        --root-password-env ROOTPASS \
        --host "${OMERO_CLI_HOST}" \
        --port "${OMERO_CLI_PORT}" \
        --repo-dir-path "${repo_dir_path}" \
        --expected-managed-dir "${managed_repo_root}"
}

# Resolve cli home. Inputs: shell arguments and environment. Output: stdout text and command status.
resolve_cli_home() {
    local cli_user="$1"
    local cli_home=""

    cli_home="$(getent passwd "${cli_user}" | cut -d: -f6 2>/dev/null || true)"
    if [[ -z "${cli_home}" ]] || [[ ! -d "${cli_home}" ]]; then
        echo "ERROR: Could not resolve an existing HOME directory for OMERO CLI user '${cli_user}'." >&2
        return 1
    fi
    printf "%s\n" "${cli_home}"
}

# Write repo root sync status. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Execute repo root bootstrap once. Inputs: shell arguments and environment. Output: command status and side effects.
run_repo_root_bootstrap_once() {
    local root_pass="$1"
    local retry_limit="${OMERO_REPO_ROOT_BOOTSTRAP_RETRIES:-180}"
    local retry_delay_seconds="${OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS:-2}"
    local lookup_retry_limit=5
    local attempt=1
    local login_ok=0
    local path_list=""
    local repo_dir_path=""
    local lookup_output=""
    local lookup_attempt=1
    local lookup_exit_code=1
    local plan_exit_code=1
    local root_dir_id=""
    local root_dir_owner=""
    local venv_py=""
    local cli_home=""
    local managed_repo_root=""
    local chown_output=""
    local chown_exit_code=1
    local inspected_prefix_count=0
    local normalized_prefix_count=0
    local failed_prefix_count=0
    local last_success_epoch=0

    for attempt in $(seq 1 "${retry_limit}"); do
        if OMERO_PASSWORD="${root_pass}" run_omero -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" login -u root >/dev/null 2>&1; then
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

    if ! verify_managed_repository_runtime_safety; then
        echo "[$(date -u)] ERROR: managed-repository runtime validation failed; aborting shared-prefix sync"
        write_repo_root_sync_status "error" "0" "0" "0" "1"
        return 1
    fi

    venv_py="$(resolve_server_venv_python)"
    cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")" || return 1
    managed_repo_root="$(expected_managed_repository_root)"
    set +e
    path_list="$(build_repo_root_sync_plan "${venv_py}" "${cli_home}" 2>&1)"
    plan_exit_code=$?
    set -e

    if [[ "${plan_exit_code}" -ne 0 ]]; then
        echo "[$(date -u)] ERROR: failed to build managed-repository shared-prefix plan: ${path_list}"
        write_repo_root_sync_status "error" "0" "0" "0" "1"
        return 1
    fi

    if [[ -z "${path_list}" ]]; then
        echo "[$(date -u)] INFO: no deterministic managed-repository shared prefixes require normalization"
        last_success_epoch="$(date +%s)"
        write_repo_root_sync_status "ok" "${last_success_epoch}" "0" "0" "0"
        return 0
    fi

    while IFS= read -r repo_dir_path; do
        [[ -n "${repo_dir_path}" ]] || continue
        inspected_prefix_count=$((inspected_prefix_count + 1))
        echo "[$(date -u)] INFO: ensuring managed-repository shared prefix ${repo_dir_path}"
        lookup_output=""
        lookup_exit_code=1

        # Retry the exact same OMERO mkdir+lookup flow a few times because the
        # new shared-prefix row is not always queryable immediately.
        for lookup_attempt in $(seq 1 "${lookup_retry_limit}"); do
            run_omero fs mkdir --parents "${repo_dir_path}" >/dev/null 2>&1 || true
            set +e
            lookup_output="$(lookup_repo_root_prefix "${venv_py}" "${cli_home}" "${root_pass}" "${repo_dir_path}" "${managed_repo_root}" 2>&1)"
            lookup_exit_code=$?
            set -e

            if [[ "${lookup_exit_code}" -eq 0 ]] && [[ "${lookup_output}" = FOUND\|* ]]; then
                break
            fi

            if [[ "${lookup_attempt}" -lt "${lookup_retry_limit}" ]]; then
                sleep "${retry_delay_seconds}"
            fi
        done

        if [[ "${lookup_exit_code}" -ne 0 ]]; then
            echo "[$(date -u)] ERROR: repository root lookup failed for ${repo_dir_path}: ${lookup_output}"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi

        if [[ "${lookup_output}" = MISSING* ]]; then
            echo "[$(date -u)] ERROR: repository root lookup did not find shared prefix for ${repo_dir_path} after fs mkdir retries"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi

        if [[ "${lookup_output}" != FOUND\|* ]]; then
            echo "[$(date -u)] ERROR: repository root lookup failed for ${repo_dir_path}: ${lookup_output}"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi

        IFS='|' read -r _found_marker root_dir_id root_dir_owner root_dir_repo <<< "${lookup_output}"

        echo "[$(date -u)] INFO: repository prefix ${repo_dir_path} -> OriginalFile:${root_dir_id} owner=${root_dir_owner} repo=${root_dir_repo}"

        if [[ "${root_dir_owner}" = "root" ]]; then
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
        set +e
        lookup_output="$(lookup_repo_root_prefix "${venv_py}" "${cli_home}" "${root_pass}" "${repo_dir_path}" "${managed_repo_root}" 2>&1)"
        lookup_exit_code=$?
        set -e
        if [[ "${lookup_exit_code}" -ne 0 ]]; then
            echo "[$(date -u)] ERROR: post-normalization repository lookup failed for ${repo_dir_path}: ${lookup_output}"
            failed_prefix_count=$((failed_prefix_count + 1))
            continue
        fi
        echo "[$(date -u)] INFO: normalized repository prefix ${repo_dir_path}: ${lookup_output}"
    done <<< "${path_list}"

    if [[ "${failed_prefix_count}" -ne 0 ]]; then
        write_repo_root_sync_status "error" "0" "${inspected_prefix_count}" "${normalized_prefix_count}" "${failed_prefix_count}"
        return 1
    fi

    last_success_epoch="$(date +%s)"
    write_repo_root_sync_status "ok" "${last_success_epoch}" "${inspected_prefix_count}" "${normalized_prefix_count}" "0"
    return 0
}

# Schedule repo root sync. Inputs: shell arguments and environment. Output: command status and side effects.
schedule_repo_root_sync() {
    local root_pass="${ROOTPASS:-}"
    local repo_path="${CONFIG_omero_fs_repo_path:-}"
    local venv_py=""
    local stable_prefix_depth=""
    local interval="${OMERO_REPO_ROOT_SYNC_INTERVAL_SECONDS:-3600}"
    local jitter_max="${OMERO_REPO_ROOT_SYNC_JITTER_SECONDS:-20}"

    if [[ -z "${root_pass}" ]]; then
        log "Skipping managed-repository root sync (ROOTPASS missing)."
        return
    fi

    if [[ -z "${repo_path}" ]]; then
        log "Managed-repository root sync skipped because CONFIG_omero_fs_repo_path is empty."
        return
    fi

    venv_py="$(resolve_server_venv_python)"
    stable_prefix_depth="$(repo_root_sync_stable_prefix_depth "${venv_py}")" || {
        echo "ERROR: Failed to analyze CONFIG_omero_fs_repo_path for shared-prefix sync." >&2
        exit 1
    }

    if [[ "${stable_prefix_depth}" -lt 1 ]]; then
        log "Managed-repository root sync skipped because CONFIG_omero_fs_repo_path has no stable shared prefix before %user% or volatile tokens."
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

# Write dropbox ice bootstrap status. Inputs: shell arguments and environment. Output: command status and side effects.
write_dropbox_ice_bootstrap_status() {
    local status="$1"
    local action="$2"
    local message="$3"
    local last_success_epoch="$4"
    local tmp_status_file="${DROPBOX_ICE_BOOTSTRAP_STATUS_FILE}.tmp.$$"

    mkdir -p "$(dirname "${DROPBOX_ICE_BOOTSTRAP_STATUS_FILE}")"
    cat > "${tmp_status_file}" <<EOF
status=${status}
action=${action}
message=${message}
last_success_epoch=${last_success_epoch}
updated_epoch=$(date +%s)
EOF
    mv "${tmp_status_file}" "${DROPBOX_ICE_BOOTSTRAP_STATUS_FILE}"
}

# Wait for dropbox ice admin. Inputs: shell arguments and environment. Output: command status and side effects.
wait_for_dropbox_ice_admin() {
    local wait_seconds="$1"
    local poll_interval="$2"
    local deadline=$(( $(date +%s) + wait_seconds ))

    while [[ "$(date +%s)" -lt "${deadline}" ]]; do
        if dropbox_ice_admin_ready; then
            return 0
        fi
        sleep "${poll_interval}"
    done

    return 1
}

# Perform dropbox ice admin ready. Inputs: shell arguments and environment. Output: command status and side effects.
dropbox_ice_admin_ready() {
    local internal_cfg="${SERVER_HOME}/etc/internal.cfg"

    [[ -r "${internal_cfg}" ]] \
        && pgrep -f 'icegridnode .*internal\.cfg' >/dev/null 2>&1 \
        && run_dropbox_ice_command server list >/dev/null 2>&1
}

# Wait for dropbox user directory sync API. Inputs: shell arguments and environment. Output: command status and side effects.
wait_for_dropbox_user_dir_sync_api() {
    local wait_seconds="$1"
    local poll_interval="$2"
    local host="$3"
    local port="$4"
    local username="$5"
    local bind_env_name="$6"
    local deadline=$(( $(date +%s) + wait_seconds ))
    local cli_home=""
    local cli_tmpdir=""

    if ! is_env_var_name "${bind_env_name}"; then
        return 1
    fi

    local -n dropbox_bind_value="${bind_env_name}"
    if [[ -z "${dropbox_bind_value-}" ]]; then
        return 1
    fi

    cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")" || return 1
    cli_tmpdir="$(resolve_omero_cli_tmpdir)" || return 1
    while [[ "$(date +%s)" -lt "${deadline}" ]]; do
        if dropbox_ice_admin_ready \
            && OMERO_PASSWORD="${dropbox_bind_value}" run_omero login -q -C -t 60 \
                -s "${host}" -p "${port}" -u "${username}" >/dev/null 2>&1; then
            return 0
        fi
        sleep "${poll_interval}"
    done

    return 1
}

# Perform environment variable value is empty. Inputs: shell arguments and environment. Output: command status and side effects.
env_var_value_is_empty() {
    local env_name="$1"

    if ! is_env_var_name "${env_name}"; then
        return 0
    fi

    local -n env_value_ref="${env_name}"
    [[ -z "${env_value_ref-}" ]]
}

# Execute dropbox ice command. Inputs: shell arguments and environment. Output: command status and side effects.
run_dropbox_ice_command() {
    local out=""
    local rc=0

    out="$(run_omero admin ice "$@" 2>&1)" || rc=$?
    if [[ -n "${out}" ]]; then
        printf "%s\n" "${out}"
    fi

    return "${rc}"
}

# Start dropbox ice server. Inputs: shell arguments and environment. Output: command status and side effects.
start_dropbox_ice_server() {
    local server_name="$1"
    local out=""
    local rc=0

    out="$(run_omero admin ice server start "${server_name}" 2>&1)" || rc=$?
    if [[ "${rc}" -eq 0 ]]; then
        if [[ -n "${out}" ]]; then
            printf "%s\n" "${out}"
        fi
        return 0
    fi

    if printf "%s" "${out}" | grep -Eiq 'already|is active|ServerActiveException'; then
        echo "[$(date -u)] ${server_name} already active"
        return 0
    fi

    if [[ -n "${out}" ]]; then
        printf "%s\n" "${out}"
    fi
    return "${rc}"
}

# Execute dropbox ice bootstrap once. Inputs: shell arguments and environment. Output: command status and side effects.
run_dropbox_ice_bootstrap_once() {
    local startup_wait="${OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS}"
    local poll_interval="${OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS}"
    local last_success_epoch=""
    local api_host="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_HOST}"
    local api_port="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PORT}"
    local api_username="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_USERNAME}"
    local api_password_env="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PASSWORD_ENV}"

    write_dropbox_ice_bootstrap_status "running" "enable-start" "waiting-for-omero-admin" "0"

    if ! wait_for_dropbox_ice_admin "${startup_wait}" "${poll_interval}"; then
        write_dropbox_ice_bootstrap_status "retrying" "enable" "omero-admin-not-ready" "0"
        echo "[$(date -u)] WARN: OMERO IceGrid did not become ready after ${startup_wait}s"
        return 1
    fi

    if [[ "${OMERO_DROPBOX_USER_DIR_SYNC_ENABLED}" = "1" ]]; then
        write_dropbox_ice_bootstrap_status "running" "enable-start" "waiting-for-omero-api" "0"
        if env_var_value_is_empty "${api_password_env}"; then
            write_dropbox_ice_bootstrap_status "error" "enable" "omero-api-password-missing" "0"
            echo "[$(date -u)] ERROR: OMERO API readiness check cannot run because DropBox password env is missing"
            return 2
        fi
        if ! wait_for_dropbox_user_dir_sync_api \
            "${startup_wait}" \
            "${poll_interval}" \
            "${api_host}" \
            "${api_port}" \
            "${api_username}" \
            "${api_password_env}"; then
            write_dropbox_ice_bootstrap_status "retrying" "enable" "omero-api-not-ready" "0"
            echo "[$(date -u)] WARN: OMERO API did not become ready before DropBox Ice server start after ${startup_wait}s"
            return 1
        fi
    fi

    if ! run_dropbox_ice_command server enable MonitorServer; then
        write_dropbox_ice_bootstrap_status "retrying" "enable" "monitor-enable-failed" "0"
        return 1
    fi
    if ! run_dropbox_ice_command server enable DropBox; then
        write_dropbox_ice_bootstrap_status "retrying" "enable" "dropbox-enable-failed" "0"
        return 1
    fi
    if ! start_dropbox_ice_server MonitorServer; then
        write_dropbox_ice_bootstrap_status "retrying" "start" "monitor-start-failed" "0"
        return 1
    fi
    if ! start_dropbox_ice_server DropBox; then
        write_dropbox_ice_bootstrap_status "retrying" "start" "dropbox-start-failed" "0"
        return 1
    fi

    last_success_epoch="$(date +%s)"
    write_dropbox_ice_bootstrap_status "ok" "enable-start" "ready" "${last_success_epoch}"
    echo "[$(date -u)] DropBox Ice servers are enabled and started"
}

# Schedule dropbox ice bootstrap. Inputs: shell arguments and environment. Output: command status and side effects.
schedule_dropbox_ice_bootstrap() {
    local enabled="${OMERO_DROPBOX_ENABLED}"
    local startup_wait="${OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS}"
    local poll_interval="${OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS}"
    local max_retry_seconds="${OMERO_DROPBOX_ICE_BOOTSTRAP_MAX_RETRY_SECONDS:-3600}"

    if is_falsey_bool "${enabled}"; then
        log "Skipping DropBox Ice bootstrap (OMERO_DROPBOX_ENABLED=${enabled})."
        return
    fi

    (
        set -u -o pipefail
        mkdir -p "${SERVER_LOG_DIR}" "${SERVER_VAR_DIR}"

        local lockdir="${SERVER_VAR_DIR}/dropbox-ice-bootstrap.lock"
        if ! acquire_lockdir "${lockdir}" "" "dropbox-ice-bootstrap"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" ""' EXIT

        echo "[$(date -u)] DropBox Ice bootstrap waiting for OMERO admin readiness (startup_wait=${startup_wait}s, poll=${poll_interval}s, max_retry=${max_retry_seconds}s)"
        local attempt=1
        local loop_started_epoch=""
        loop_started_epoch="$(date +%s)"
        while true; do
            local rc=0
            run_dropbox_ice_bootstrap_once || rc=$?
            if [[ "${rc}" -eq 0 ]]; then
                exit 0
            fi
            if [[ "${rc}" -eq 2 ]]; then
                echo "[$(date -u)] ERROR: DropBox Ice bootstrap stopped on non-retryable configuration error"
                exit 1
            fi
            local elapsed=0
            local last_message="retry-budget-exhausted"
            elapsed=$(( $(date +%s) - loop_started_epoch ))
            if [[ "${elapsed}" -ge "${max_retry_seconds}" ]]; then
                if [[ -r "${DROPBOX_ICE_BOOTSTRAP_STATUS_FILE}" ]]; then
                    last_message="$(sed -n 's/^message=//p' "${DROPBOX_ICE_BOOTSTRAP_STATUS_FILE}" | tail -n 1)"
                fi
                if [[ -z "${last_message}" ]]; then
                    last_message="retry-budget-exhausted"
                fi
                write_dropbox_ice_bootstrap_status "error" "enable-start" "${last_message}-retry-budget-exhausted" "0"
                echo "[$(date -u)] ERROR: DropBox Ice bootstrap retry budget exhausted after ${elapsed}s"
                exit 1
            fi
            echo "[$(date -u)] WARN: DropBox Ice bootstrap attempt ${attempt} did not complete; retrying in ${poll_interval}s"
            attempt=$((attempt + 1))
            sleep "${poll_interval}"
        done
    ) >>"${SERVER_LOG_DIR}/dropbox-ice-bootstrap.log" 2>&1 &

    log "Scheduled background DropBox Ice bootstrap"
}

# Write dropbox user directory sync status. Inputs: shell arguments and environment. Output: command status and side effects.
write_dropbox_user_dir_sync_status() {
    local status="$1"
    local message="$2"
    local last_success_epoch="$3"
    local failed_count="$4"
    local tmp_status_file="${DROPBOX_USER_DIR_SYNC_STATUS_FILE}.tmp.$$"

    mkdir -p "$(dirname "${DROPBOX_USER_DIR_SYNC_STATUS_FILE}")"
    cat > "${tmp_status_file}" <<EOF
status=${status}
last_success_epoch=${last_success_epoch}
dropbox_root=
eligible_user_count=0
created_count=0
existing_count=0
skipped_count=0
failed_count=${failed_count}
message=${message}
updated_epoch=$(date +%s)
EOF
    mv "${tmp_status_file}" "${DROPBOX_USER_DIR_SYNC_STATUS_FILE}"
}

# Execute dropbox user directory sync once. Inputs: shell arguments and environment. Output: command status and side effects.
run_dropbox_user_dir_sync_once() {
    local wait_seconds="${1:-0}"
    local venv_py=""
    local status_file="${DROPBOX_USER_DIR_SYNC_STATUS_FILE}"
    local host="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_HOST}"
    local port="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PORT}"
    local secure="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_SECURE}"
    local username="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_USERNAME}"
    local password_env="${OMERO_DROPBOX_USER_DIR_SYNC_OMERO_PASSWORD_ENV}"
    local create_root="${OMERO_DROPBOX_USER_DIR_CREATE_ROOT}"
    local owner="${OMERO_DROPBOX_USER_DIR_OWNER}"
    local group="${OMERO_DROPBOX_USER_DIR_GROUP}"
    local mode="${OMERO_DROPBOX_USER_DIR_MODE}"
    local allow_world_writable="${OMERO_DROPBOX_USER_DIR_ALLOW_WORLD_WRITABLE}"
    local retries="${OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES}"
    local retry_delay="${OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS}"
    local cli_tmpdir=""

    write_dropbox_user_dir_sync_status "running" "waiting-for-omero-admin" "0" "0"

    if env_var_value_is_empty "${password_env}"; then
        local missing_password_message="missing-password-env"
        if [[ "${password_env}" = "ROOTPASS" ]]; then
            missing_password_message="missing-rootpass"
        fi
        write_dropbox_user_dir_sync_status "error" "${missing_password_message}" "0" "1"
        echo "[$(date -u)] ERROR: ${password_env} is required for DropBox user directory sync"
        return 1
    fi

    if is_positive_integer "${wait_seconds}"; then
        if ! wait_for_dropbox_user_dir_sync_api \
            "${wait_seconds}" \
            "${retry_delay}" \
            "${host}" \
            "${port}" \
            "${username}" \
            "${password_env}"; then
            write_dropbox_user_dir_sync_status "retrying" "omero-admin-not-ready" "0" "1"
            echo "[$(date -u)] WARN: OMERO API did not become ready before DropBox user directory sync after ${wait_seconds}s"
            return 1
        fi
    fi

    if ! venv_py="$(resolve_server_venv_python)"; then
        write_dropbox_user_dir_sync_status "error" "server-venv-python-not-found" "0" "1"
        return 1
    fi

    local cli_home=""
    cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")" || return 1
    cli_tmpdir="$(resolve_omero_cli_tmpdir)" || return 1
    local -n dropbox_sync_bind_value="${password_env}"
    if ! env "${password_env}=${dropbox_sync_bind_value}" HOME="${cli_home}" \
        TMPDIR="${cli_tmpdir}" OMERO_TMPDIR="${cli_tmpdir}" OMERO_TEMPDIR="${cli_tmpdir}" \
        "${venv_py}" "${DROPBOX_USER_DIR_SYNC_HELPER}" sync \
        --host "${host}" \
        --port "${port}" \
        --secure "${secure}" \
        --username "${username}" \
        --password-env "${password_env}" \
        --create-root "${create_root}" \
        --owner "${owner}" \
        --group "${group}" \
        --mode "${mode}" \
        --allow-world-writable "${allow_world_writable}" \
        --status-file "${status_file}" \
        --connect-retries "${retries}" \
        --connect-retry-delay-seconds "${retry_delay}"; then
        if [[ ! -r "${status_file}" ]] || grep -q '^status=running$' "${status_file}"; then
            write_dropbox_user_dir_sync_status "error" "helper-command-failed" "0" "1"
        fi
        return 1
    fi
}

# Schedule dropbox user directory sync. Inputs: shell arguments and environment. Output: command status and side effects.
schedule_dropbox_user_dir_sync() {
    local enabled="${OMERO_DROPBOX_USER_DIR_SYNC_ENABLED}"
    local interval="${OMERO_DROPBOX_USER_DIR_SYNC_INTERVAL_SECONDS}"
    local jitter_max="${OMERO_DROPBOX_USER_DIR_SYNC_JITTER_SECONDS}"
    local startup_wait="${OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS}"

    if [[ "${enabled}" != "1" ]]; then
        log "Skipping DropBox user directory sync (OMERO_DROPBOX_USER_DIR_SYNC_ENABLED != 1)."
        return
    fi

    (
        set -u -o pipefail
        mkdir -p "${SERVER_LOG_DIR}" "${SERVER_VAR_DIR}"

        local lockdir="${SERVER_VAR_DIR}/dropbox-user-dir-sync.lock"
        if ! acquire_lockdir "${lockdir}" "" "dropbox-user-dir-sync"; then
            exit 0
        fi
        trap 'release_lockdir "${lockdir}" ""' EXIT

        local first_cycle="1"
        while true; do
            local cycle_wait="0"
            if [[ "${first_cycle}" = "1" ]]; then
                cycle_wait="${startup_wait}"
                first_cycle="0"
            fi
            if ! run_dropbox_user_dir_sync_once "${cycle_wait}"; then
                echo "[$(date -u)] WARN: DropBox user directory sync cycle finished with errors"
            fi
            sleep $((interval + (RANDOM % (jitter_max + 1))))
        done
    ) >>"${SERVER_LOG_DIR}/dropbox-user-dir-sync.log" 2>&1 &

    log "Scheduled background DropBox user directory sync (interval=${interval}s)"
}

# Schedule binary repository cleanse. Inputs: shell arguments and environment. Output: command status and side effects.
schedule_binary_repository_cleanse() {
    local enabled="${OMERO_BINARY_REPO_CLEANSE_ON_START:-1}"
    local root_pass="${ROOTPASS:-}"
    local data_dir="${OMERO_BINARY_REPO_CLEANSE_DATA_DIR:-${OMERO_DIR}}"
    local startup_wait="${OMERO_BINARY_REPO_CLEANSE_STARTUP_WAIT_SECONDS:-900}"
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
            if OMERO_PASSWORD="${root_pass}" run_omero -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" login -u root >/dev/null 2>&1; then
                login_ok=1
                break
            fi
            sleep "${poll_interval}"
        done

        if [[ "${login_ok}" -ne 1 ]]; then
            echo "[$(date -u)] ERROR: Timed out waiting for OMERO login before running binary repository cleanse"
            exit 1
        fi

        if ! verify_managed_repository_runtime_safety; then
            echo "[$(date -u)] ERROR: managed-repository runtime validation failed; refusing binary repository cleanse"
            exit 1
        fi

        local start_epoch=""
        local rc=0
        start_epoch="$(date +%s)"

        OMERO_PASSWORD="${root_pass}" run_omero_with_keepalive \
            "${keepalive_seconds}" \
            admin cleanse -q -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" -u root "${data_dir}" || rc=$?

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
# Install figure script. Inputs: shell arguments and environment. Output: command status and side effects.
install_figure_script() {
    local figure_version="${OMERO_FIGURE_VERSION:-}"
    if [[ -z "${figure_version}" ]]; then
        echo "ERROR: OMERO_FIGURE_VERSION must be set in env/omeroserver.env and must not be empty." >&2
        exit 1
    fi

    local script_dir="${SERVER_HOME}/lib/scripts/omero/figure_scripts"
    local script_path="${script_dir}/Figure_To_Pdf.py"
    local tmp_root=""
    local tmp_dir=""

    mkdir -p "${script_dir}"

    if [[ -f "${script_path}" ]]; then
        local current_version="unknown"
        current_version="$(grep -E '^\s*(VERSION|__version__)\s*=' "${script_path}" 2>/dev/null | head -n 1 | sed -E "s/.*[\"']([^\"']+)[\"'].*/\1/" || true)"
        if [[ "${current_version}" = "${figure_version}" ]]; then
            log "OMERO.Figure script already present (version ${current_version})"
            return
        fi
        log "OMERO.Figure script version mismatch (${current_version} != ${figure_version}); attempting upgrade"
    fi

    tmp_root="$(resolve_omero_cli_tmpdir)" || exit 1
    tmp_dir="$(mktemp -d "${tmp_root%/}/omero-figure-${figure_version}.XXXXXX")" || {
        echo "ERROR: Could not create OMERO.Figure staging directory under ${tmp_root}" >&2
        exit 1
    }

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

# Schedule script registration. Inputs: shell arguments and environment. Output: command status and side effects.
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

        until OMERO_PASSWORD="${root_pass}" run_omero -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" login -u root >/dev/null 2>&1; do
            sleep 2
        done

        # Create an idempotent Python script to register official scripts and clean duplicates
        local script_sync_py="${SERVER_VAR_DIR}/sync_official_scripts.py"
        cat << 'EOF' > "${script_sync_py}"
import os
import subprocess
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
                env = {**os.environ, "OMERO_PASSWORD": root_pass}
                cmd = [
                    os.environ.get("OMERO_BIN", "omero"),
                    "script",
                    "upload",
                    "--official",
                    "--sudo",
                    "root",
                    filepath,
                    "-s",
                    os.environ["OMERO_CLI_HOST"],
                    "-p",
                    os.environ["OMERO_CLI_PORT"],
                    "-u",
                    "root",
                ]
                rc = subprocess.run(cmd, env=env, check=False).returncode
                if rc != 0:
                    print(f"  WARN: upload returned exit code {rc}")
            elif len(existing) == 0:
                print(f"[{file}] not registered; uploading as official script: {desired_path}")
                env = {**os.environ, "OMERO_PASSWORD": root_pass}
                cmd = [
                    os.environ.get("OMERO_BIN", "omero"),
                    "script",
                    "upload",
                    "--official",
                    "--sudo",
                    "root",
                    filepath,
                    "-s",
                    os.environ["OMERO_CLI_HOST"],
                    "-p",
                    os.environ["OMERO_CLI_PORT"],
                    "-u",
                    "root",
                ]
                rc = subprocess.run(cmd, env=env, check=False).returncode
                if rc != 0:
                    print(f"  WARN: upload returned exit code {rc}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    root_pass = os.environ["ROOTPASS"]
    script_dir = sys.argv[1]
    omero_host = os.environ["OMERO_CLI_HOST"]
    omero_port = int(os.environ["OMERO_CLI_PORT"])

    conn = BlitzGateway('root', root_pass, host=omero_host, port=omero_port)
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
        cli_home="$(resolve_cli_home "${OMERO_CLI_USER}")" || exit 1
        local cli_tmpdir
        cli_tmpdir="$(resolve_omero_cli_tmpdir)" || exit 1

        # Run the idempotent sync script (output goes to the log file via the subshell redirect)
        ROOTPASS="${root_pass}" OMERO_BIN="${OMERO_BIN}" \
            run_as_omero_cli_user "${venv_py}" "${script_sync_py}" "${scripts_dir}" 2>&1 || true

        rm -f "${script_sync_py}"
    ) >>"${SERVER_LOG_DIR}/register-official-scripts.log" 2>&1 &

    log "Scheduled background idempotent official script registration"
}

# Acquire lockdir. Inputs: shell arguments and environment. Output: command status and side effects.
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

    # Read proc start ticks. Inputs: shell arguments and environment. Output: command status and side effects.
    _read_proc_start_ticks() {
        local target_pid="$1"
        [[ -r "/proc/${target_pid}/stat" ]] || return 1
        awk '{print $22}' "/proc/${target_pid}/stat" 2>/dev/null
    }

    # Normalize lock path. Inputs: shell arguments and environment. Output: command status and side effects.
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

    # Write lock metadata. Inputs: shell arguments and environment. Output: command status and side effects.
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
                elif [[ "${existing_start_ticks}" = "${live_start_ticks}" ]]; then
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

        if [[ "${lock_state}" = "active" ]]; then
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

# Release lockdir. Inputs: shell arguments and environment. Output: command status and side effects.
release_lockdir() {
    local lockdir="$1"
    local pidfile="${2:-}"
    rm -rf "${lockdir}" 2>/dev/null || true
    if [[ -n "${pidfile}" ]]; then
        rm -f "${pidfile}" 2>/dev/null || true
    fi
}


# Execute the command entrypoint. Inputs: shell arguments and environment. Output: command status and side effects.
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

    check_writable_dir "${CERTS_DIR}" "OMERO certificates"
    check_writable_dir "${SERVER_VAR_DIR}" "OMERO var"
    check_writable_dir "${SERVER_LOG_DIR}" "OMERO logs"
    ensure_tmpdir_permissions "${OMERO_CLI_USER}"

    # Reset OMERO config to a clean slate before applying any settings.
    # The upstream base image originally did this inside its .omero config
    # file, but that runs AFTER our bootstrap — wiping certificate SANs,
    # omero.scripts.python, and other properties we just set.  Moving the
    # reset here ensures a clean slate while preserving the correct order.
    run_omero config drop default
    log "Reset OMERO config to defaults (clean slate)"

    validate_managed_repository_configuration
    ensure_server_data_runtime_directories
    validate_ldap_configuration
    validate_ldap_new_user_group_configuration
    validate_job_service_bootstrap_configuration
    validate_binary_repository_cleanse_configuration
    validate_repository_lock_cleanup_configuration
    validate_rendering_cache_cleanup_configuration
    validate_zarr_pixel_buffer_configuration
    validate_repo_root_sync_configuration
    validate_dropbox_user_dir_sync_configuration
    apply_ldap_runtime_configuration
    reset_runtime_if_requested
    configure_script_python
    configure_import_runtime_paths
    ensure_certificate_sans
    cleanup_stale_repository_lock_files
    cleanup_rendering_caches
    toggle_zarr_pixel_buffer_plugin
    install_figure_script
    schedule_script_registration
    schedule_job_service_bootstrap
    schedule_ldap_group_bootstrap
    schedule_repo_root_sync
    schedule_dropbox_ice_bootstrap
    schedule_dropbox_user_dir_sync
    schedule_binary_repository_cleanse

    log "Startup flow finished"
}

main "$@"
