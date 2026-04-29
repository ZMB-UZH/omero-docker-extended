#!/usr/bin/env bash

# Configuration
# -------------
SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SCRIPT_ENV_FILE=""
USE_CACHE_BUILD="${USE_CACHE_BUILD:-1}"             # set to 1 to enable buildx inline cache
USE_BUILDX_COMPRESSED_BUILD="${USE_BUILDX_COMPRESSED_BUILD:-0}" # set to 0 to use plain docker compose build
DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE:-0}" # set to 1 to rebuild final images into single-layer outputs
APPLY_SECURITY_HARDENING="${APPLY_SECURITY_HARDENING:-}" # set to 0/1 to override the prompt; empty defaults the prompt to yes
ENABLE_VULNERABILITY_SCAN="${ENABLE_VULNERABILITY_SCAN:-0}" # set to 1 to run Docker Scout vulnerability scanning
KEEP_IMAGES="${KEEP_IMAGES:-0}"                     # set to 1 to keep existing images
START_CONTAINERS="${START_CONTAINERS:-1}"            # set to 0 to skip `docker compose up -d`
BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH="${BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH:-installation/docker_buildx_compressed_push.sh}"
INSTALLATION_AUTOMATION_MODE="${INSTALLATION_AUTOMATION_MODE:-0}" # set to 1 to run fully non-interactive (no /dev/tty prompts)
COMPOSE_UP_RETRIES="${COMPOSE_UP_RETRIES:-2}"
COMPOSE_UP_RETRY_DELAY_SECONDS="${COMPOSE_UP_RETRY_DELAY_SECONDS:-30}"
COMPOSE_UP_WAIT_TIMEOUT_SECONDS="${COMPOSE_UP_WAIT_TIMEOUT_SECONDS:-3600}"
OMERO_WEB_HOST_PORT="${OMERO_WEB_HOST_PORT:-}"
CONFIG_omero_web_application__server_port="${CONFIG_omero_web_application__server_port:-}"
OMERO_SERVER_HOST_PORT="${OMERO_SERVER_HOST_PORT:-}"
OMERO_CLI_HOST="${OMERO_CLI_HOST:-}"
OMERO_CLI_PORT="${OMERO_CLI_PORT:-}"
OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS="${OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS:-}"
OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS="${OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS:-}"
OMERO_SERVER_HEALTHCHECK_RETRIES="${OMERO_SERVER_HEALTHCHECK_RETRIES:-}"
OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS="${OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS:-}"
OMERO_JOB_SERVICE_HOST="${OMERO_JOB_SERVICE_HOST:-}"
OMERO_JOB_SERVICE_PORT="${OMERO_JOB_SERVICE_PORT:-}"
OMERO_SERVER_UID="${OMERO_SERVER_UID:-}"
OMERO_SERVER_GID="${OMERO_SERVER_GID:-}"
OMERO_WEB_UID="${OMERO_WEB_UID:-}"
OMERO_WEB_GID="${OMERO_WEB_GID:-}"
PROMETHEUS_UID="${PROMETHEUS_UID:-}"
PROMETHEUS_GID="${PROMETHEUS_GID:-}"
GRAFANA_UID="${GRAFANA_UID:-}"
GRAFANA_GID="${GRAFANA_GID:-}"
LOKI_UID="${LOKI_UID:-}"
LOKI_GID="${LOKI_GID:-}"
ALLOY_UID="${ALLOY_UID:-}"
ALLOY_GID="${ALLOY_GID:-}"
DATABASE_UID="${DATABASE_UID:-}"
DATABASE_GID="${DATABASE_GID:-}"
DATABASE_PLUGIN_UID="${DATABASE_PLUGIN_UID:-}"
DATABASE_PLUGIN_GID="${DATABASE_PLUGIN_GID:-}"
PATH_USAGE_EXPORTER_UID="${PATH_USAGE_EXPORTER_UID:-}"
PATH_USAGE_EXPORTER_GID="${PATH_USAGE_EXPORTER_GID:-}"
CROWDSEC_UID="${CROWDSEC_UID:-}"
CROWDSEC_GID="${CROWDSEC_GID:-}"
OMERO_SERVER_ENV_FILE="${REPO_ROOT_DIR}/env/omeroserver.env"
OMERO_WEB_ENV_FILE="${REPO_ROOT_DIR}/env/omeroweb.env"
OMERO_CELERY_ENV_FILE="${REPO_ROOT_DIR}/env/omero-celery.env"
GRAFANA_ENV_FILE="${REPO_ROOT_DIR}/env/grafana.env"

# Allow override, but default to the repo's current image names (adjust via env vars if you rename them in compose)
OMERO_SERVER_IMAGE="${OMERO_SERVER_IMAGE:-omeroserver:custom}"
OMERO_WEB_IMAGE="${OMERO_WEB_IMAGE:-omeroweb:custom}"
PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-}"
GRAFANA_IMAGE="${GRAFANA_IMAGE:-}"
LOKI_IMAGE="${LOKI_IMAGE:-}"
ALLOY_IMAGE="${ALLOY_IMAGE:-}"
DATABASE_IMAGE="${DATABASE_IMAGE:-}"
DATABASE_PLUGIN_IMAGE="${DATABASE_PLUGIN_IMAGE:-}"
PATH_USAGE_EXPORTER_IMAGE="${PATH_USAGE_EXPORTER_IMAGE:-path-usage-exporter:custom}"
CROWDSEC_IMAGE="${CROWDSEC_IMAGE:-crowdsec:custom}"
CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS="${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS:-600}"
CROWDSEC_INSTALL_AUTO_RESTART_STALE_GRACE_SECONDS="${CROWDSEC_INSTALL_AUTO_RESTART_STALE_GRACE_SECONDS:-900}"
CROWDSEC_INSTALL_AUTO_RESTART_HELPER="${SCRIPT_DIR}/crowdsec_install_auto_restart.sh"
CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=0
CROWDSEC_INSTALL_BOOTSTRAP_ENROLL=0
CROWDSEC_INSTALL_BOOTSTRAP_STATUS=""

set -euo pipefail

ENV_ASSIGNMENT_HELPER_PATH="${SCRIPT_DIR}/env_assignment_utils.sh"
if [ ! -r "${ENV_ASSIGNMENT_HELPER_PATH}" ]; then
    echo "ERROR: Missing env assignment helper: ${ENV_ASSIGNMENT_HELPER_PATH}" >&2
    exit 1
fi
# shellcheck disable=SC1090
. "${ENV_ASSIGNMENT_HELPER_PATH}"

TRANSCRIPT_HELPER_PATH="${SCRIPT_DIR}/install_transcript_utils.sh"
if [ -r "${TRANSCRIPT_HELPER_PATH}" ]; then
    # shellcheck disable=SC1090
    . "${TRANSCRIPT_HELPER_PATH}"
fi

if declare -F install_transcript_enable >/dev/null 2>&1; then
    install_transcript_enable "${REPO_ROOT_DIR}/installation_paths.env" "$0" "$@"
fi

if ! declare -F install_transcript_record_line >/dev/null 2>&1; then
    install_transcript_record_line() {
        :
    }
fi

if ! declare -F install_transcript_record_text >/dev/null 2>&1; then
    install_transcript_record_text() {
        :
    }
fi

is_non_negative_integer() {
    case "${1:-}" in
        ""|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}


is_positive_integer() {
    local value="${1:-}"

    is_non_negative_integer "${value}" || return 1
    case "${value}" in
        *[1-9]*) return 0 ;;
        *) return 1 ;;
    esac
}


is_shell_variable_name() {
    case "${1:-}" in
        ""|[0-9]*|*[!A-Za-z0-9_]*) return 1 ;;
        *) return 0 ;;
    esac
}


is_omero_group_name() {
    case "${1:-}" in
        ""|*[!A-Za-z0-9_.-]*) return 1 ;;
        *) return 0 ;;
    esac
}


is_crowdsec_enabled() {
    local key="${CROWDSEC_ENROLL_KEY:-}"
    local legacy_placeholder_prefix="CHANGE"

    if [[ -z "${key}" \
        || "${key}" == "${legacy_placeholder_prefix}VALUE2" \
        || "${key}" == "${legacy_placeholder_prefix}VALUE3" ]]; then
        return 1
    fi

    return 0
}


crowdsec_install_auto_restart_marker_path() {
    printf '%s' "${CROWDSEC_DB_PATH%/}/.install-auto-restart.pending"
}


crowdsec_install_enrollment_done_marker_path() {
    printf '%s' "${CROWDSEC_DB_PATH%/}/.console-enrollment-install.done"
}


crowdsec_has_install_enrollment_done_marker() {
    [ -f "$(crowdsec_install_enrollment_done_marker_path)" ]
}


clear_crowdsec_install_enrollment_done_marker() {
    local marker_path=""

    marker_path="$(crowdsec_install_enrollment_done_marker_path)"
    if [ ! -f "${marker_path}" ]; then
        return 0
    fi

    if ! rm -f "${marker_path}"; then
        echo "ERROR: Failed to remove CrowdSec install enrollment marker: ${marker_path}" >&2
        return 1
    fi

    echo "Removed existing CrowdSec install enrollment marker so this installation run requests dashboard approval again."
    return 0
}


crowdsec_directory_has_runtime_state() {
    local directory_path="${1:?BUG: crowdsec_directory_has_runtime_state requires a path}"

    if [ ! -d "${directory_path}" ]; then
        return 1
    fi

    if find "${directory_path}" \
        -mindepth 1 \
        -maxdepth 1 \
        ! -name '.console-enrollment-install.done' \
        ! -name '.install-auto-restart.pending' \
        -print -quit | grep -q .; then
        return 0
    fi

    return 1
}


crowdsec_has_preexisting_runtime_state() {
    if crowdsec_directory_has_runtime_state "${CROWDSEC_CONFIG_PATH}"; then
        return 0
    fi

    if crowdsec_directory_has_runtime_state "${CROWDSEC_DB_PATH}"; then
        return 0
    fi

    return 1
}


prepare_crowdsec_install_bootstrap_enrollment() {
    CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=0
    CROWDSEC_INSTALL_BOOTSTRAP_ENROLL=0
    CROWDSEC_INSTALL_BOOTSTRAP_STATUS="disabled"

    if ! is_crowdsec_enabled; then
        return 0
    fi

    if crowdsec_has_install_enrollment_done_marker; then
        if ! clear_crowdsec_install_enrollment_done_marker; then
            return 1
        fi
    fi

    if crowdsec_has_preexisting_runtime_state; then
        CROWDSEC_INSTALL_BOOTSTRAP_STATUS="reinstall_existing_runtime_state"
        echo "CrowdSec runtime state already exists under ${CROWDSEC_CONFIG_PATH} and/or ${CROWDSEC_DB_PATH}."
        echo "This installation run will still create a fresh CrowdSec dashboard enrollment request and schedule the install-only auto-restart."
    else
        CROWDSEC_INSTALL_BOOTSTRAP_STATUS="install_startup"
    fi

    CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED=1
    CROWDSEC_INSTALL_BOOTSTRAP_ENROLL=1
    return 0
}

print_crowdsec_install_bootstrap_status() {
    case "${CROWDSEC_INSTALL_BOOTSTRAP_STATUS:-disabled}" in
        disabled)
            return 0
            ;;
        install_startup)
            echo "CrowdSec install enrollment mode: fresh install startup."
            return 0
            ;;
        reinstall_existing_runtime_state)
            echo "CrowdSec install enrollment mode: existing runtime state with renewed dashboard enrollment."
            return 0
            ;;
        *)
            echo "CrowdSec install enrollment mode: ${CROWDSEC_INSTALL_BOOTSTRAP_STATUS}"
            return 0
            ;;
    esac
}


load_installation_paths_env() {
    local env_file_path="${1:?BUG: load_installation_paths_env requires a path}"
    local env_line
    local env_key
    local env_value
    local resolved_value

    if [ ! -r "${env_file_path}" ]; then
        echo "ERROR: Installation paths file is missing or unreadable: ${env_file_path}" >&2
        return 1
    fi

    while IFS= read -r env_line || [ -n "${env_line}" ]; do
        case "${env_line}" in
            ''|'#'*)
                continue
                ;;
            [A-Za-z_]*=*)
                env_key="${env_line%%=*}"
                env_value="${env_line#*=}"
                if ! is_shell_variable_name "${env_key}"; then
                    echo "ERROR: Invalid environment variable name in ${env_file_path}: ${env_key}" >&2
                    return 1
                fi
                if ! resolved_value="$(resolve_env_assignment_value "${env_value}")"; then
                    echo "ERROR: Refusing unsafe value for ${env_key} from ${env_file_path}" >&2
                    return 1
                fi
                printf -v "${env_key}" '%s' "${resolved_value}"
                export "${env_key?}"
                ;;
            *)
                ;;
        esac
    done < "${env_file_path}"
}

load_secrets_env() {
    local secrets_env_file="${1:?BUG: load_secrets_env requires a path}"

    if [ ! -r "${secrets_env_file}" ]; then
        echo "ERROR: Secrets env file is missing or unreadable: ${secrets_env_file}" >&2
        echo "ERROR: Create it from env/omero_secrets_example.env (copy → env/omero_secrets.env) and set real values." >&2
        return 1
    fi

    set -a
    load_installation_paths_env "${secrets_env_file}"
    set +a
}

run_runtime_env_contract_check() {
    local repo_root="${1:?BUG: run_runtime_env_contract_check requires repo root}"
    shift

    local guard_path="${repo_root%/}/tools/env_safety_guard.py"

    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 is required for initial deployment env validation." >&2
        return 1
    fi

    if [ ! -r "${guard_path}" ]; then
        echo "ERROR: Missing deployment env validator: ${guard_path}" >&2
        return 1
    fi

    python3 "${guard_path}" --repo-root "${repo_root}" runtime-env-check "$@"
}


bootstrap_env_files_from_examples() {
    local env_dir="${REPO_ROOT_DIR}/env"
    local example_file actual_file

    if [ ! -d "${env_dir}" ]; then
        return 0
    fi

    for example_file in "${env_dir}"/*_example.env; do
        [ -f "${example_file}" ] || continue

        # IMPORTANT:
        # Secrets MUST NEVER be auto-created by automation.
        # The user is the sole creator of env/omero_secrets.env.
        if [ "$(basename "${example_file}")" = "omero_secrets_example.env" ]; then
            continue
        fi

        # Derive the actual filename: foo_example.env → foo.env
        actual_file="${example_file%_example.env}.env"
        if [ ! -f "${actual_file}" ]; then
            echo "First-time setup: creating ${actual_file} from $(basename "${example_file}")"
            cp "${example_file}" "${actual_file}"
        fi
    done
}

resolve_script_env_file() {
    local default_env_file="${REPO_ROOT_DIR}/installation_paths.env"

    bootstrap_env_files_from_examples

    if [ ! -f "${default_env_file}" ]; then
        echo "ERROR: Missing required installation paths file: ${default_env_file}" >&2
        echo "ERROR: Create it manually from installation_paths_example.env and set your own paths before rerunning." >&2
        return 1
    fi

    SCRIPT_ENV_FILE="${default_env_file}"
}


# Bash requirement (warning)
# --------------------------
if [ -z "${BASH_VERSION:-}" ]; then
    echo "ERROR: This script MUST be run with bash." >&2
    exit 1
fi

if ! resolve_script_env_file; then
    exit 1
fi

if ! load_installation_paths_env "${SCRIPT_ENV_FILE}"; then
    exit 1
fi


SECRETS_ENV_FILE="${REPO_ROOT_DIR}/env/omero_secrets.env"
if ! load_secrets_env "${SECRETS_ENV_FILE}"; then
    exit 1
fi

if ! run_runtime_env_contract_check "${REPO_ROOT_DIR}" --skip-dot-env; then
    exit 1
fi

for required_runtime_env_file in \
    "${OMERO_SERVER_ENV_FILE}" \
    "${OMERO_WEB_ENV_FILE}" \
    "${OMERO_CELERY_ENV_FILE}" \
    "${GRAFANA_ENV_FILE}"
do
    set -a
    if ! load_installation_paths_env "${required_runtime_env_file}"; then
        set +a
        exit 1
    fi
    set +a
done

require_nonempty_config_var() {
    local variable_name="$1"
    local variable_source="$2"
    local variable_value="${!variable_name:-}"

    if [ -z "${variable_value}" ]; then
        echo "ERROR: Missing required configuration variable ${variable_name} in ${variable_source}" >&2
        return 1
    fi

    return 0
}

require_path_config_var() {
    local variable_name="$1"
    local variable_source="$2"
    local variable_value="${!variable_name:-}"

    if ! require_nonempty_config_var "${variable_name}" "${variable_source}"; then
        return 1
    fi

    if ! is_valid_linux_path "${variable_value}"; then
        echo "ERROR: ${variable_name} must be a valid absolute Linux path: ${variable_value}" >&2
        return 1
    fi

    return 0
}

validate_retry_config() {
    if ! is_positive_integer "${COMPOSE_UP_RETRIES}"; then
        echo "ERROR: COMPOSE_UP_RETRIES must be an integer >= 1. Got: ${COMPOSE_UP_RETRIES}" >&2
        return 1
    fi

    if ! is_non_negative_integer "${COMPOSE_UP_RETRY_DELAY_SECONDS}"; then
        echo "ERROR: COMPOSE_UP_RETRY_DELAY_SECONDS must be an integer >= 0. Got: ${COMPOSE_UP_RETRY_DELAY_SECONDS}" >&2
        return 1
    fi

    if ! is_positive_integer "${COMPOSE_UP_WAIT_TIMEOUT_SECONDS}"; then
        echo "ERROR: COMPOSE_UP_WAIT_TIMEOUT_SECONDS must be an integer >= 1. Got: ${COMPOSE_UP_WAIT_TIMEOUT_SECONDS}" >&2
        return 1
    fi

    return 0
}

validate_tcp_port_config() {
    local variable_name="${1:?BUG: validate_tcp_port_config requires variable name}"
    local variable_value="${2:-}"

    case "${variable_value}" in
        ""|*[!0-9]*)
            echo "ERROR: ${variable_name} must be an integer TCP port. Got: ${variable_value:-<empty>}" >&2
            return 1
            ;;
    esac

    if [ "${variable_value}" -lt 1 ] || [ "${variable_value}" -gt 65535 ]; then
        echo "ERROR: ${variable_name} must be between 1 and 65535. Got: ${variable_value}" >&2
        return 1
    fi

    return 0
}

validate_crowdsec_install_auto_restart_config() {
    if ! is_non_negative_integer "${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS}"; then
        echo "ERROR: CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS must be an integer >= 0. Got: ${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS}" >&2
        return 1
    fi

    if ! is_non_negative_integer "${CROWDSEC_INSTALL_AUTO_RESTART_STALE_GRACE_SECONDS}"; then
        echo "ERROR: CROWDSEC_INSTALL_AUTO_RESTART_STALE_GRACE_SECONDS must be an integer >= 0. Got: ${CROWDSEC_INSTALL_AUTO_RESTART_STALE_GRACE_SECONDS}" >&2
        return 1
    fi

    return 0
}

validate_toggle_config() {
    local variable_name="${1:?BUG: validate_toggle_config requires variable name}"
    local variable_value="${2:-}"

    if [ "${variable_value}" != "0" ] && [ "${variable_value}" != "1" ]; then
        echo "ERROR: ${variable_name} must be 0 or 1. Got: ${variable_value}" >&2
        return 1
    fi

    return 0
}

resolve_buildx_inline_cache_setting() {
    if [ -n "${DOCKER_BUILD_INLINE_CACHE:-}" ]; then
        printf '%s' "${DOCKER_BUILD_INLINE_CACHE}"
        return 0
    fi

    printf '%s' "${USE_CACHE_BUILD}"
    return 0
}

resolve_build_provenance_setting() {
    if [ -n "${DOCKER_BUILD_PROVENANCE:-}" ]; then
        if [ "${DOCKER_BUILD_PROVENANCE}" = "1" ]; then
            printf 'true'
            return 0
        fi

        printf 'false'
        return 0
    fi

    printf 'false'
    return 0
}

# ---------------------------------------------------------------------------
# run_image_build
#
# Cache is controlled by USE_CACHE_BUILD (from the "Use cache?" prompt),
# which applies to both buildx inline cache and docker build cache.
# ---------------------------------------------------------------------------
run_image_build() {
    local inline_cache_setting=""
    local buildx_helper_path="${OMERO_INSTALLATION_PATH%/}/${BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH}"
    local local_cache_enabled_setting="${DOCKER_BUILD_LOCAL_CACHE_ENABLED:-1}"
    local provenance_setting=""
    local server_env_source="${OMERO_SERVER_ENV_FILE:-env/omeroserver.env}"

    if [ -z "${OMERO_CLI_ZARR_VERSION:-}" ]; then
        echo "ERROR: Missing required configuration variable OMERO_CLI_ZARR_VERSION in ${server_env_source}" >&2
        return 1
    fi

    if [ -z "${OMERO_DROPBOX_VERSION:-}" ]; then
        echo "ERROR: Missing required configuration variable OMERO_DROPBOX_VERSION in ${server_env_source}" >&2
        return 1
    fi

    if [ -z "${OME_ZARR_PY_VERSION:-}" ]; then
        echo "ERROR: Missing required configuration variable OME_ZARR_PY_VERSION in ${server_env_source}" >&2
        return 1
    fi

    if [ -z "${BIOFORMATS2RAW_VERSION:-}" ]; then
        echo "ERROR: Missing required configuration variable BIOFORMATS2RAW_VERSION in ${server_env_source}" >&2
        return 1
    fi

    if [ -z "${BIOFORMATS_VERSION:-}" ]; then
        echo "ERROR: Missing required configuration variable BIOFORMATS_VERSION in ${server_env_source}" >&2
        return 1
    fi

    provenance_setting="$(resolve_build_provenance_setting)"

    # This function is called from `if ! run_image_build; then`, which disables
    # Bash errexit semantics inside the function body. Check critical commands
    # explicitly so build or flatten failures cannot fall through as success.

    if [ "${USE_BUILDX_COMPRESSED_BUILD}" = "0" ]; then
        echo "Building OMERO images via docker compose build workflow..."
        echo "  Compose file   : ${COMPOSE_FILE}"
        echo "  Cache enabled  : ${USE_CACHE_BUILD}"
        echo "  Provenance     : ${provenance_setting}"
        echo "  Security harden: ${APPLY_SECURITY_HARDENING}"
        echo "  Vuln scan      : ${ENABLE_VULNERABILITY_SCAN}"

        local -a compose_build_args=(build)
        if [ "${USE_CACHE_BUILD}" = "0" ]; then
            compose_build_args+=(--no-cache)
        fi
        compose_build_args+=(--provenance "${provenance_setting}")

        # Optional Docker image security hardening build args
        if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then
            compose_build_args+=(--build-arg "APPLY_SECURITY_HARDENING=1")
            compose_build_args+=(--build-arg "APPLY_DNF_UPDATES=1")
            compose_build_args+=(--build-arg "APPLY_OMERO_VENV_TOOLING_UPDATES=1")
            compose_build_args+=(--build-arg "APPLY_OMEROWEB_DNF_UPDATES=1")
            compose_build_args+=(--build-arg "APPLY_OMEROWEB_VENV_TOOLING_UPDATES=1")
        fi

        if ! compose_with_installation_env "${COMPOSE_FILE}" "${compose_build_args[@]}"; then
            echo "ERROR: docker compose build workflow failed." >&2
            return 1
        fi

        if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" = "1" ]; then
            if [ ! -x "${buildx_helper_path}" ]; then
                echo "ERROR: Flatten helper is missing or not executable: ${buildx_helper_path}" >&2
                echo "ERROR: Re-run the pull/update script and ensure installation/docker_buildx_compressed_push.sh exists." >&2
                return 1
            fi

            echo "Flattening compose-built images into single-layer outputs..."
            if ! COMPOSE_FILE="${COMPOSE_FILE}" \
                DOCKER_BUILD_PROVENANCE="${DOCKER_BUILD_PROVENANCE:-0}" \
                DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" \
                DOCKER_BUILD_FLATTEN_ONLY="1" \
                DOCKER_BUILD_PUSH_IMAGES="0" \
                "${buildx_helper_path}"; then
                echo "ERROR: Compose image flatten workflow failed." >&2
                return 1
            fi
        fi
        return 0
    fi

    if [ ! -x "${buildx_helper_path}" ]; then
        echo "ERROR: Buildx compression helper is missing or not executable: ${buildx_helper_path}" >&2
        echo "ERROR: Re-run the pull/update script and ensure installation/docker_buildx_compressed_push.sh exists." >&2
        return 1
    fi

    inline_cache_setting="$(resolve_buildx_inline_cache_setting)"

    echo "Building OMERO images via Buildx compressed (zstd) workflow..."
    echo "  Helper script : ${buildx_helper_path}"
    echo "  Cache enabled : ${inline_cache_setting}"
    echo "  Provenance    : ${provenance_setting}"
    echo "  Security harden: ${APPLY_SECURITY_HARDENING}"
    echo "  Vuln scan      : ${ENABLE_VULNERABILITY_SCAN}"

    # Derive no-cache flag: if cache is disabled (0), also disable docker layer cache
    local no_cache_setting="0"
    if [ "${inline_cache_setting}" = "0" ]; then
        no_cache_setting="1"
        # Keep Buildx status/output aligned with the installer's no-cache choice.
        local_cache_enabled_setting="0"
    fi

    if ! COMPOSE_FILE="${COMPOSE_FILE}" \
        DOCKER_BUILD_INLINE_CACHE="${inline_cache_setting}" \
        DOCKER_BUILD_NO_CACHE="${no_cache_setting}" \
        DOCKER_BUILD_LOCAL_CACHE_ENABLED="${local_cache_enabled_setting}" \
        DOCKER_BUILD_LOCAL_CACHE_MODE="${DOCKER_BUILD_LOCAL_CACHE_MODE:-min}" \
        DOCKER_BUILD_PROVENANCE="${DOCKER_BUILD_PROVENANCE:-0}" \
        DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" \
        "${buildx_helper_path}"; then
        echo "ERROR: Buildx compressed build workflow failed." >&2
        return 1
    fi
    return 0
}

resolve_buildx_local_cache_dir() {
    if [ -n "${BUILDX_DATA_PATH:-}" ]; then
        printf '%s' "${BUILDX_DATA_PATH}"
        return 0
    fi

    if [ -n "${OMERO_DATA_PATH:-}" ]; then
        printf '%s' "${OMERO_DATA_PATH%/}/buildx_cache"
        return 0
    fi

    return 1
}

cleanup_local_build_cache_if_disabled() {
    local buildx_local_cache_dir=""

    if [ "${USE_CACHE_BUILD}" != "0" ]; then
        return 0
    fi

    echo "Build cache is disabled; cleaning local build cache before rebuild..."

    if docker builder prune --help >/dev/null 2>&1; then
        if ! docker builder prune -a -f >/dev/null; then
            echo "ERROR: Failed to clean docker builder cache while USE_CACHE_BUILD=0." >&2
            return 1
        fi
        echo "Removed docker builder cache."
    else
        echo "WARNING: docker builder prune is unavailable; skipping docker builder cache cleanup."
    fi

    if [ "${USE_BUILDX_COMPRESSED_BUILD}" = "1" ]; then
        if ! buildx_local_cache_dir="$(resolve_buildx_local_cache_dir)"; then
            echo "ERROR: Buildx cache cleanup requested but no cache path could be resolved (BUILDX_DATA_PATH and OMERO_DATA_PATH are both unset)." >&2
            return 1
        fi

        if [ -d "${buildx_local_cache_dir}" ]; then
            if ! rm -rf "${buildx_local_cache_dir}"; then
                echo "ERROR: Failed to remove Buildx local cache directory: ${buildx_local_cache_dir}" >&2
                return 1
            fi
            echo "Removed Buildx local cache directory: ${buildx_local_cache_dir}"
        else
            echo "Buildx local cache directory not present, nothing to remove: ${buildx_local_cache_dir}"
        fi
    fi

    return 0
}

compose_with_installation_env() {
    local compose_file="$1"
    shift

    docker compose \
        --project-directory "${OMERO_INSTALLATION_PATH%/}" \
        -f "${compose_file}" \
        "$@"
}

compose_images_with_installation_env() {
    local compose_file="$1"

    compose_with_installation_env "${compose_file}" config --images 2>/dev/null || true
}

export_compose_interpolation_env() {
    local env_var_name=""
    local required_compose_env_vars=(
        OMERO_INSTALLATION_PATH
        OMERO_DATABASE_PATH
        OMERO_PLUGIN_DATABASE_PATH
        OMERO_DATA_PATH
        OMERO_TMP_PATH
        OMERO_DATA_DIR
        OMERO_USER_DATA_PATH
        OMERO_IMPORT_PATH
        OMERO_SERVER_VAR_PATH
        OMERO_WEB_VAR_PATH
        OMERO_SERVER_LOGS_PATH
        OMERO_WEB_LOGS_PATH
        OMERO_WEB_SUPERVISOR_LOGS_PATH
        PORTAINER_DATA_PATH
        PROMETHEUS_DATA_PATH
        GRAFANA_DATA_PATH
        LOKI_DATA_PATH
        ALLOY_DATA_PATH
        PG_MAINTENANCE_DATA_PATH
        BUILDX_DATA_PATH
        NODE_EXPORTER_TEXTFILE_PATH
        CROWDSEC_DB_PATH
        CROWDSEC_CONFIG_PATH
        OMERO_SERVER_HOST_PORT
        OMERO_CLI_PORT
        OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS
        OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS
        OMERO_SERVER_HEALTHCHECK_RETRIES
        OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS
        OMERO_DROPBOX_VERSION
        OMERO_CLI_ZARR_VERSION
        OME_ZARR_PY_VERSION
        BIOFORMATS2RAW_VERSION
        BIOFORMATS_VERSION
    )

    for env_var_name in "${required_compose_env_vars[@]}"; do
        if [ -z "${!env_var_name:-}" ]; then
            echo "ERROR: Missing required docker compose interpolation variable: ${env_var_name}" >&2
            return 1
        fi

        export "${env_var_name}=${!env_var_name}"
    done

    if is_crowdsec_enabled; then
        export COMPOSE_PROFILES="crowdsec${COMPOSE_PROFILES:+,${COMPOSE_PROFILES}}"
    fi

    return 0
}

validate_numeric_id() {
    local id_label="$1"
    local id_value="$2"

    if ! is_non_negative_integer "${id_value}"; then
        echo "ERROR: ${id_label} must be a numeric ID. Got: ${id_value}" >&2
        return 1
    fi

    return 0
}

ensure_container_writable_path() {
    local path_to_prepare="$1"
    local path_label="$2"

    if [ -e "${path_to_prepare}" ] && [ ! -d "${path_to_prepare}" ]; then
        echo "ERROR: ${path_label} exists but is not a directory: ${path_to_prepare}" >&2
        return 1
    fi

    if ! install -d -m 0775 "${path_to_prepare}"; then
        echo "ERROR: Failed to create ${path_label}: ${path_to_prepare}" >&2
        return 1
    fi

    if ! chmod 0775 "${path_to_prepare}"; then
        echo "ERROR: Failed to set permissions for ${path_label}: ${path_to_prepare}" >&2
        return 1
    fi

    return 0
}

print_compose_failure_context() {
    local compose_file="$1"

    echo "ERROR: docker compose up failed. Collecting service health details..." >&2
    compose_with_installation_env "${compose_file}" ps >&2 || true

    local failed_services=""
    local ps_lines=""

    ps_lines="$(compose_with_installation_env "${compose_file}" ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null || true)"
    failed_services="$(
        printf '%s\n' "${ps_lines}" \
            | awk '$2 ~ /^(exited|dead|restarting)$/ || $3 == "unhealthy" {print $1}' \
            | sort -u
    )"

    if [ -z "${failed_services}" ]; then
        echo "ERROR: Could not identify exited, restarting, dead, or unhealthy services. Inspect health status and logs manually." >&2
        return 0
    fi

    local service_name
    while IFS= read -r service_name; do
        if [ -z "${service_name}" ]; then
            continue
        fi
        echo "----- BEGIN STATUS: ${service_name} -----" >&2
        compose_with_installation_env "${compose_file}" ps "${service_name}" >&2 || true
        echo "----- END STATUS: ${service_name} -----" >&2
        echo "----- BEGIN LOGS: ${service_name} -----" >&2
        compose_with_installation_env "${compose_file}" logs --tail 120 "${service_name}" >&2 || true
        echo "----- END LOGS: ${service_name} -----" >&2
    done <<< "${failed_services}"
}

remove_stale_crowdsec_install_auto_restart_marker() {
    local marker_path="${1:?BUG: remove_stale_crowdsec_install_auto_restart_marker requires a path}"
    local target_epoch=""
    local now_epoch=""

    if [ ! -f "${marker_path}" ]; then
        return 0
    fi

    target_epoch="$(awk -F= '/^target_epoch=/{print $2; exit}' "${marker_path}" 2>/dev/null || true)"
    if ! is_non_negative_integer "${target_epoch}"; then
        rm -f "${marker_path}" || true
        return 0
    fi

    now_epoch="$(date -u +%s)"
    if [ "${now_epoch}" -gt $((target_epoch + CROWDSEC_INSTALL_AUTO_RESTART_STALE_GRACE_SECONDS)) ]; then
        rm -f "${marker_path}" || true
    fi

    return 0
}

resolve_crowdsec_install_auto_restart_remaining_delay() {
    local total_delay_seconds="${1:?BUG: resolve_crowdsec_install_auto_restart_remaining_delay requires total delay}"
    local container_name="${2:-crowdsec}"
    local started_at=""
    local start_epoch=""
    local now_epoch=""
    local elapsed_seconds=0
    local remaining_delay_seconds="${total_delay_seconds}"

    started_at="$(docker inspect --format '{{.State.StartedAt}}' "${container_name}" 2>/dev/null || true)"
    if [ -z "${started_at}" ]; then
        printf '%s' "${remaining_delay_seconds}"
        return 0
    fi

    start_epoch="$(date -u -d "${started_at}" +%s 2>/dev/null || true)"
    now_epoch="$(date -u +%s)"
    if ! is_non_negative_integer "${start_epoch}" || [ "${start_epoch}" -gt "${now_epoch}" ]; then
        printf '%s' "${remaining_delay_seconds}"
        return 0
    fi

    elapsed_seconds=$((now_epoch - start_epoch))
    if [ "${elapsed_seconds}" -ge "${total_delay_seconds}" ]; then
        printf '0'
        return 0
    fi

    remaining_delay_seconds=$((total_delay_seconds - elapsed_seconds))
    printf '%s' "${remaining_delay_seconds}"
    return 0
}

print_crowdsec_install_enrollment_notice() {
    local remaining_delay_seconds="${1:?BUG: print_crowdsec_install_enrollment_notice requires delay}"
    local window_minutes=0

    if [ "${remaining_delay_seconds}" -eq 0 ]; then
        window_minutes=0
    else
        window_minutes=$(((remaining_delay_seconds + 59) / 60))
    fi

    echo ""
    echo "============================================================"
    echo "CrowdSec Console Approval Required"
    echo "============================================================"
    echo "Approve the new CrowdSec engine in the CrowdSec dashboard"
    echo "within the next ${window_minutes} minute(s)."
    echo "This enrollment request is created during installation"
    echo "startup, not on ordinary CrowdSec restarts."
    echo "A one-time automatic restart of the 'crowdsec' container has"
    echo "been scheduled for this installation run only."
    if [ "${remaining_delay_seconds}" -eq 0 ]; then
        echo "The 10-minute approval window has already elapsed, so the"
        echo "automatic restart will run immediately."
    else
        echo "The restart will run about ${window_minutes} minute(s) after"
        echo "CrowdSec first started during this installation."
    fi
    echo "If approval happens after that window, restart 'crowdsec'"
    echo "manually once."
    echo "============================================================"
    echo ""
}

schedule_crowdsec_install_auto_restart() {
    local helper_path="${CROWDSEC_INSTALL_AUTO_RESTART_HELPER}"
    local marker_path=""
    local remaining_delay_seconds="${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS}"
    local scheduled_epoch=""
    local target_epoch=""

    if [ "${CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}" != "1" ]; then
        return 0
    fi

    if [ ! -x "${helper_path}" ]; then
        echo "WARNING: CrowdSec install auto-restart helper is missing or not executable: ${helper_path}" >&2
        return 0
    fi

    marker_path="$(crowdsec_install_auto_restart_marker_path)"
    remove_stale_crowdsec_install_auto_restart_marker "${marker_path}"

    if [ -f "${marker_path}" ]; then
        echo "CrowdSec install-only auto-restart is already scheduled. Leaving the existing one-shot schedule in place."
        return 0
    fi

    remaining_delay_seconds="$(resolve_crowdsec_install_auto_restart_remaining_delay "${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS}" "crowdsec")"
    scheduled_epoch="$(date -u +%s)"
    target_epoch=$((scheduled_epoch + remaining_delay_seconds))

    cat > "${marker_path}" <<EOF
scheduled_epoch=${scheduled_epoch}
target_epoch=${target_epoch}
container_name=crowdsec
EOF
    chmod 0600 "${marker_path}" || true

    nohup env \
        CROWDSEC_AUTO_RESTART_MARKER="${marker_path}" \
        CROWDSEC_AUTO_RESTART_DELAY_SECONDS="${remaining_delay_seconds}" \
        CROWDSEC_AUTO_RESTART_CONTAINER_NAME="crowdsec" \
        bash "${helper_path}" >/dev/null 2>&1 &

    echo "Scheduled one-time CrowdSec install auto-restart in ${remaining_delay_seconds}s."
    return 0
}

compose_up_with_retries() {
    local compose_file="$1"
    local attempt=1
    local crowdsec_bootstrap_enroll="${CROWDSEC_INSTALL_BOOTSTRAP_ENROLL:-0}"

    while [ "${attempt}" -le "${COMPOSE_UP_RETRIES}" ]; do
        echo "Starting containers (attempt ${attempt}/${COMPOSE_UP_RETRIES})..."

        if CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="${crowdsec_bootstrap_enroll}" compose_with_installation_env "${compose_file}" up -d --wait --wait-timeout "${COMPOSE_UP_WAIT_TIMEOUT_SECONDS}"; then
            echo "Containers started successfully."
            return 0
        fi

        if [ "${attempt}" -ge "${COMPOSE_UP_RETRIES}" ]; then
            echo "ERROR: docker compose up failed after ${COMPOSE_UP_RETRIES} attempt(s)." >&2
            print_compose_failure_context "${compose_file}"
            return 1
        fi

        echo "WARNING: docker compose up failed on attempt ${attempt}. Retrying in ${COMPOSE_UP_RETRY_DELAY_SECONDS}s..." >&2
        sleep "${COMPOSE_UP_RETRY_DELAY_SECONDS}"
        attempt=$((attempt + 1))
    done

    return 1
}


normalize_omero_install_group_list() {
    local raw_group_list="${1:-}"
    local list_without_inline_comment=""
    local group_entry=""
    local normalized_entry=""
    local normalized_list=""
    local separator=""
    local -a group_entries=()

    # Allow sysadmins to effectively disable group bootstrap with inline comments,
    # for example: OMERO_INSTALL_GROUP_LIST=# disabled for fresh install
    list_without_inline_comment="${raw_group_list%%#*}"

    IFS="," read -r -a group_entries <<< "${list_without_inline_comment}"
    for group_entry in "${group_entries[@]}"; do
        normalized_entry="$(printf '%s' "${group_entry}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [ -z "${normalized_entry}" ] && continue

        normalized_list+="${separator}${normalized_entry}"
        separator=","
    done
    printf '%s' "${normalized_list}"
}

validate_omero_install_group_list() {
    local raw_group_list="${1:-}"
    local normalized_group_list=""

    normalized_group_list="$(normalize_omero_install_group_list "${raw_group_list}")"
    if [ -z "${normalized_group_list}" ]; then
        return 0
    fi

    local group_entry=""
    local group_name=""
    local group_permission=""
    local -a group_entries=()

    IFS="," read -r -a group_entries <<< "${normalized_group_list}"
    for group_entry in "${group_entries[@]}"; do
        case "${group_entry}" in
            *:*) ;;
            *)
                echo "ERROR: Invalid OMERO_INSTALL_GROUP_LIST entry (missing ':'): ${group_entry}" >&2
                return 1
                ;;
        esac

        group_name="${group_entry%%:*}"
        group_permission="${group_entry#*:}"

        if [ -z "${group_name}" ]; then
            echo "ERROR: OMERO_INSTALL_GROUP_LIST contains an entry with empty group name: ${group_entry}" >&2
            return 1
        fi

        if ! is_omero_group_name "${group_name}"; then
            echo "ERROR: Invalid OMERO group name '${group_name}' in OMERO_INSTALL_GROUP_LIST. Allowed pattern: [A-Za-z0-9_.-]+" >&2
            return 1
        fi

        case "${group_permission}" in
            private|read-only|read-annotate|read-write)
                ;;
            *)
                echo "ERROR: Invalid OMERO group permission '${group_permission}' for group '${group_name}'. Supported values: private, read-only, read-annotate, read-write" >&2
                return 1
                ;;
        esac
    done

    return 0
}

create_omero_groups_from_list() {
    local compose_file="$1"
    local raw_group_list="${2:-}"
    local normalized_group_list=""

    normalized_group_list="$(normalize_omero_install_group_list "${raw_group_list}")"
    if [ -z "${normalized_group_list}" ]; then
        echo "OMERO_INSTALL_GROUP_LIST is empty/commented; skipping OMERO installation group bootstrap."
        return 0
    fi

    if [ ! -r "${OMERO_SERVER_ENV_FILE}" ]; then
        echo "ERROR: OMERO server env file is required for deterministic group bootstrap and was not found: ${OMERO_SERVER_ENV_FILE}" >&2
        return 1
    fi

    if ! validate_omero_install_group_list "${normalized_group_list}"; then
        return 1
    fi

    local group_entry=""
    local group_name=""
    local group_permission=""
    local add_output=""
    local add_exit_code=0
    local add_attempt=0
    local add_retry_limit="${OMERO_GROUP_BOOTSTRAP_RETRIES:-20}"
    local add_retry_delay_seconds="${OMERO_GROUP_BOOTSTRAP_RETRY_DELAY_SECONDS:-3}"
    local -a group_entries=()

    echo "Bootstrapping OMERO groups from OMERO_INSTALL_GROUP_LIST..."

    IFS="," read -r -a group_entries <<< "${normalized_group_list}"
    for group_entry in "${group_entries[@]}"; do
        [ -z "${group_entry}" ] && continue

        group_name="${group_entry%%:*}"
        group_permission="${group_entry#*:}"

        echo "Ensuring OMERO group exists: ${group_name} (${group_permission})"

        add_output=""
        add_exit_code=1
        for add_attempt in $(seq 1 "${add_retry_limit}"); do
            set +e
            # Use docker exec explicitly with non-interactive flags and without pseudo-TTY (-T)
            # The < /dev/null redirect ensures if any prompt triggers it fails instead of hanging forever
            add_output="$(compose_with_installation_env "${compose_file}" exec -T \
                -e ROOTPASS="${ROOTPASS}" \
                -e OMERO_CLI_HOST="${OMERO_CLI_HOST}" \
                -e OMERO_CLI_PORT="${OMERO_CLI_PORT}" \
                -e TARGET_GROUP_NAME="${group_name}" \
                -e TARGET_GROUP_PERMISSION="${group_permission}" \
                omeroserver bash -s 2>&1 <<'EOS_GROUP_BOOTSTRAP'
set -euo pipefail

: "${OMERO_CLI_USER:?OMERO_CLI_USER is required}"
: "${OMERO_CLI_HOST:?OMERO_CLI_HOST is required}"
: "${OMERO_CLI_PORT:?OMERO_CLI_PORT is required}"
: "${OMERO_TMP_PATH:?OMERO_TMP_PATH is required}"
: "${OMERODIR:?OMERODIR is required}"

resolve_omero_bin() {
    local candidate=""
    local server_root=""
    server_root="$(dirname "${OMERODIR}")"
    for candidate in "${server_root}"/venv*/bin/omero "${OMERODIR}"/bin/omero; do
        [ -x "${candidate}" ] || continue
        printf "%s" "${candidate}"
        return 0
    done
    return 1
}

resolve_cli_home() {
    local cli_home=""
    cli_home="$(getent passwd "${OMERO_CLI_USER}" | cut -d: -f6 2>/dev/null || true)"
    if [ -z "${cli_home}" ] || [ ! -d "${cli_home}" ]; then
        echo "OMERO CLI user home not found for ${OMERO_CLI_USER}" >&2
        return 1
    fi
    printf "%s" "${cli_home}"
}

OMERO_BIN="$(resolve_omero_bin || true)"
if [ -z "${OMERO_BIN}" ]; then
    echo "OMERO CLI executable not found from OMERODIR=${OMERODIR}"
    exit 127
fi

OMERO_TMPDIR_VALUE="${OMERO_TMP_PATH%/}/omero-server/tmp"
OMERO_CLI_HOME="$(resolve_cli_home)"
mkdir -p "${OMERO_TMPDIR_VALUE}"
chown "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${OMERO_TMPDIR_VALUE}"
chmod 0700 "${OMERO_TMPDIR_VALUE}"

run_omero_cli() {
    runuser -u "${OMERO_CLI_USER}" -- env \
        HOME="${OMERO_CLI_HOME}" \
        TMPDIR="${OMERO_TMPDIR_VALUE}" \
        OMERO_TMPDIR="${OMERO_TMPDIR_VALUE}" \
        OMERO_TEMPDIR="${OMERO_TMPDIR_VALUE}" \
        OMERO_PASSWORD="${ROOTPASS}" \
        "${OMERO_BIN}" "$@"
}

if ! run_omero_cli -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" login -u root </dev/null >/dev/null 2>&1; then
    echo "Failed to login or ICE not ready"
    exit 1
fi
run_omero_cli -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" -u root group add "${TARGET_GROUP_NAME}" --type="${TARGET_GROUP_PERMISSION}" </dev/null
EOS_GROUP_BOOTSTRAP
            )"
            add_exit_code=$?
            set -e

            if [ "${add_exit_code}" -eq 0 ] || printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|name already in use|name in use|exists"; then
                break
            fi

            if [ "${add_attempt}" -lt "${add_retry_limit}" ]; then
                echo "WARNING: Group bootstrap attempt ${add_attempt}/${add_retry_limit} failed for '${group_name}'. Retrying in ${add_retry_delay_seconds}s..." >&2
                sleep "${add_retry_delay_seconds}"
            fi
        done

        if [ "${add_exit_code}" -eq 0 ]; then
            echo "Created OMERO group '${group_name}' (${group_permission})."
            continue
        fi

        if printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|exists"; then
            echo "OMERO group '${group_name}' already exists; skipping creation."
            continue
        fi

        echo "ERROR: Failed to ensure OMERO group '${group_name}' (${group_permission})." >&2
        echo "ERROR: omero output: ${add_output}" >&2
        return 1
    done

    echo "OMERO installation group bootstrap completed."
    return 0
}

add_job_service_to_install_groups() {
    local compose_file="$1"
    local raw_group_list="${2:-}"
    local job_user="${OMERO_JOB_SERVICE_USERNAME:?OMERO_JOB_SERVICE_USERNAME is required}"
    local job_pass="${OMERO_JOB_SERVICE_PASS:-}"
    local join_all="${OMERO_JOB_SERVICE_JOIN_ALL_GROUPS:?OMERO_JOB_SERVICE_JOIN_ALL_GROUPS is required}"
    local job_secure="${OMERO_JOB_SERVICE_SECURE:?OMERO_JOB_SERVICE_SECURE is required}"
    local job_host="${OMERO_JOB_SERVICE_HOST:?OMERO_JOB_SERVICE_HOST is required}"
    local job_port="${OMERO_JOB_SERVICE_PORT:?OMERO_JOB_SERVICE_PORT is required}"
    local user_ensure_retries="${OMERO_JOB_SERVICE_USER_ENSURE_RETRIES:?OMERO_JOB_SERVICE_USER_ENSURE_RETRIES is required}"
    local helper_path="/startup/job_service_group_sync.py"

    if [ "${join_all}" != "1" ]; then
        echo "Skipping job-service group membership (OMERO_JOB_SERVICE_JOIN_ALL_GROUPS != 1)."
        return 0
    fi

    if [ -z "${job_pass}" ] || [ -z "${ROOTPASS:-}" ]; then
        echo "Skipping job-service group membership (OMERO_JOB_SERVICE_PASS or ROOTPASS not set)."
        return 0
    fi

    local normalized_group_list=""
    normalized_group_list="$(normalize_omero_install_group_list "${raw_group_list}")"
    if [ -z "${normalized_group_list}" ]; then
        echo "OMERO_INSTALL_GROUP_LIST is empty/commented; continuing with full group discovery for job-service membership sync."
    fi

    echo "Adding ${job_user} to all OMERO groups (excluding: root, system, user)..."

    local output=""
    local exit_code=1
    local retry_limit="${OMERO_GROUP_BOOTSTRAP_RETRIES:-20}"
    local retry_delay="${OMERO_GROUP_BOOTSTRAP_RETRY_DELAY_SECONDS:-3}"
    local attempt=0

    for attempt in $(seq 1 "${retry_limit}"); do
        set +e
        output="$(compose_with_installation_env "${compose_file}" exec -T \
            -e ROOTPASS="${ROOTPASS}" \
            -e OMERO_JOB_SERVICE_PASS="${job_pass}" \
            -e JOB_USER="${job_user}" \
            -e JOB_SERVICE_HOST="${job_host}" \
            -e JOB_SERVICE_PORT="${job_port}" \
            -e JOB_SERVICE_SECURE="${job_secure}" \
            -e JOB_SERVICE_USER_RETRIES="${user_ensure_retries}" \
            -e JOB_SERVICE_SYNC_HELPER="${helper_path}" \
            omeroserver bash -s 2>&1 <<'EOS_JOB_SERVICE'
set -euo pipefail

: "${OMERO_CLI_USER:?OMERO_CLI_USER is required}"
: "${OMERO_TMP_PATH:?OMERO_TMP_PATH is required}"
: "${OMERODIR:?OMERODIR is required}"
: "${JOB_USER:?JOB_USER is required}"
: "${JOB_SERVICE_HOST:?JOB_SERVICE_HOST is required}"
: "${JOB_SERVICE_PORT:?JOB_SERVICE_PORT is required}"
: "${JOB_SERVICE_SECURE:?JOB_SERVICE_SECURE is required}"
: "${JOB_SERVICE_USER_RETRIES:?JOB_SERVICE_USER_RETRIES is required}"
: "${JOB_SERVICE_SYNC_HELPER:?JOB_SERVICE_SYNC_HELPER is required}"

resolve_server_python() {
    local candidate=""
    local server_root=""
    server_root="$(dirname "${OMERODIR}")"
    for candidate in "${server_root}"/venv*/bin/python "${OMERODIR}"/bin/python; do
        [ -x "${candidate}" ] || continue
        printf "%s" "${candidate}"
        return 0
    done
    return 1
}

resolve_cli_home() {
    local cli_home=""
    cli_home="$(getent passwd "${OMERO_CLI_USER}" | cut -d: -f6 2>/dev/null || true)"
    if [ -z "${cli_home}" ] || [ ! -d "${cli_home}" ]; then
        echo "OMERO CLI user home not found for ${OMERO_CLI_USER}" >&2
        return 1
    fi
    printf "%s" "${cli_home}"
}

SERVER_PYTHON="$(resolve_server_python || true)"
if [ -z "${SERVER_PYTHON}" ]; then
    echo "OMERO server Python executable not found from OMERODIR=${OMERODIR}"
    exit 127
fi

if [ ! -r "${JOB_SERVICE_SYNC_HELPER}" ]; then
    echo "Job-service group sync helper is missing: ${JOB_SERVICE_SYNC_HELPER}"
    exit 127
fi

OMERO_TMPDIR_VALUE="${OMERO_TMP_PATH%/}/omero-server/tmp"
OMERO_CLI_HOME="$(resolve_cli_home)"
mkdir -p "${OMERO_TMPDIR_VALUE}"
chown "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${OMERO_TMPDIR_VALUE}"
chmod 0700 "${OMERO_TMPDIR_VALUE}"

exec runuser -u "${OMERO_CLI_USER}" -- env \
    HOME="${OMERO_CLI_HOME}" \
    TMPDIR="${OMERO_TMPDIR_VALUE}" \
    OMERO_TMPDIR="${OMERO_TMPDIR_VALUE}" \
    OMERO_TEMPDIR="${OMERO_TMPDIR_VALUE}" \
    ROOTPASS="${ROOTPASS}" \
    OMERO_JOB_SERVICE_PASS="${OMERO_JOB_SERVICE_PASS}" \
    "${SERVER_PYTHON}" "${JOB_SERVICE_SYNC_HELPER}" \
    --host "${JOB_SERVICE_HOST}" \
    --port "${JOB_SERVICE_PORT}" \
    --secure "${JOB_SERVICE_SECURE}" \
    --root-user root \
    --job-user "${JOB_USER}" \
    --user-retries "${JOB_SERVICE_USER_RETRIES}"
EOS_JOB_SERVICE
        )"
        exit_code=$?
        set -e

        if [ "${exit_code}" -eq 0 ]; then
            break
        fi

        if [ "${attempt}" -lt "${retry_limit}" ]; then
            echo "WARNING: job-service group membership attempt ${attempt}/${retry_limit} failed. Retrying in ${retry_delay}s..." >&2
            sleep "${retry_delay}"
        fi
    done

    if [ "${exit_code}" -ne 0 ]; then
        echo "ERROR: Could not add ${job_user} to all eligible groups during installation." >&2
        echo "ERROR: Last output: ${output}" >&2
        return 1
    fi

    echo "Job-service installation & group membership completed."
    return 0
}

repo_root_sync_stable_prefix_depth() {
    local helper_path="${REPO_ROOT_DIR}/startup/repo_root_sync_helper.py"

    if [ ! -r "${helper_path}" ]; then
        echo "ERROR: Missing repo-root sync helper: ${helper_path}" >&2
        return 1
    fi

    python3 "${helper_path}" stable-depth \
        --repo-template "${CONFIG_omero_fs_repo_path:-}"
}

wait_for_repo_root_sync_ready() {
    local started_epoch="${1:?BUG: wait_for_repo_root_sync_ready requires a start epoch}"
    local status_file="${OMERO_SERVER_VAR_PATH%/}/repo-root-sync.status"
    local retry_limit="${OMERO_REPO_ROOT_BOOTSTRAP_RETRIES:-180}"
    local retry_delay_seconds="${OMERO_REPO_ROOT_BOOTSTRAP_RETRY_DELAY_SECONDS:-2}"
    local stable_prefix_depth=""
    local poll_interval_seconds=5
    local max_wait_seconds=0
    local deadline_epoch=0
    local now_epoch=0
    local status=""
    local last_success_epoch=""
    local status_line=""

    if [ "${START_CONTAINERS}" -ne 1 ]; then
        return 0
    fi

    if [ -z "${ROOTPASS:-}" ]; then
        echo "Skipping managed-repository shared-prefix readiness wait (ROOTPASS not set)."
        return 0
    fi

    stable_prefix_depth="$(repo_root_sync_stable_prefix_depth)" || {
        echo "ERROR: Failed to analyze CONFIG_omero_fs_repo_path for shared-prefix readiness." >&2
        return 1
    }

    if ! is_non_negative_integer "${stable_prefix_depth}"; then
        echo "ERROR: Invalid shared-prefix depth reported for CONFIG_omero_fs_repo_path: ${stable_prefix_depth}" >&2
        return 1
    fi

    if [ "${stable_prefix_depth}" -lt 1 ]; then
        echo "Skipping managed-repository shared-prefix readiness wait (CONFIG_omero_fs_repo_path has no stable shared prefix before %user% or volatile tokens)."
        return 0
    fi

    if ! is_positive_integer "${retry_limit}"; then
        retry_limit=180
    fi
    if ! is_non_negative_integer "${retry_delay_seconds}"; then
        retry_delay_seconds=2
    fi

    max_wait_seconds=$((retry_limit * retry_delay_seconds + 120))
    deadline_epoch=$((started_epoch + max_wait_seconds))

    echo "Waiting for managed-repository shared-prefix normalization to complete..."

    while true; do
        if [ -r "${status_file}" ]; then
            status="$(sed -n 's/^status=//p' "${status_file}" | tail -n 1)"
            last_success_epoch="$(sed -n 's/^last_success_epoch=//p' "${status_file}" | tail -n 1)"
            if [ "${status}" = "ok" ] && is_non_negative_integer "${last_success_epoch}" && [ "${last_success_epoch}" -ge "${started_epoch}" ]; then
                echo "Managed-repository shared-prefix normalization is ready."
                return 0
            fi
        fi

        now_epoch="$(date +%s)"
        if [ "${now_epoch}" -ge "${deadline_epoch}" ]; then
            echo "ERROR: Timed out waiting for managed-repository shared-prefix normalization status at ${status_file}" >&2
            if [ -r "${status_file}" ]; then
                status_line="$(tr '\n' ' ' < "${status_file}" | sed 's/[[:space:]]\+/ /g')"
                echo "ERROR: Last repo-root sync status: ${status_line}" >&2
            fi
            return 1
        fi

        sleep "${poll_interval_seconds}"
    done
}

wait_for_dropbox_ice_bootstrap_ready() {
    local started_epoch="${1:?BUG: wait_for_dropbox_ice_bootstrap_ready requires a start epoch}"
    local enabled="${OMERO_DROPBOX_ENABLED:?OMERO_DROPBOX_ENABLED is required}"
    local server_var_path="${OMERO_SERVER_VAR_PATH:?OMERO_SERVER_VAR_PATH is required}"
    local status_file="${server_var_path%/}/dropbox-ice-bootstrap.status"
    local startup_wait_seconds="${OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS:?OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS is required}"
    local poll_interval_seconds="${OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS:?OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS is required}"
    local max_wait_seconds=0
    local deadline_epoch=0
    local now_epoch=0
    local status=""
    local last_success_epoch=""
    local status_line=""

    if [ "${START_CONTAINERS}" -ne 1 ]; then
        return 0
    fi

    case "${enabled}" in
        1|true|yes|on) ;;
        *)
            echo "Skipping DropBox Ice bootstrap readiness wait (OMERO_DROPBOX_ENABLED=${enabled})."
            return 0
            ;;
    esac

    if ! is_positive_integer "${startup_wait_seconds}"; then
        echo "ERROR: OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS must be a positive integer, got: ${startup_wait_seconds}" >&2
        return 2
    fi
    if ! is_positive_integer "${poll_interval_seconds}"; then
        echo "ERROR: OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS must be a positive integer, got: ${poll_interval_seconds}" >&2
        return 2
    fi

    max_wait_seconds=$((startup_wait_seconds + poll_interval_seconds))
    deadline_epoch=$(( $(date +%s) + max_wait_seconds ))

    echo "Waiting for DropBox Ice bootstrap to complete..."

    while true; do
        if [ -r "${status_file}" ]; then
            status="$(sed -n 's/^status=//p' "${status_file}" | tail -n 1)"
            last_success_epoch="$(sed -n 's/^last_success_epoch=//p' "${status_file}" | tail -n 1)"
            if [ "${status}" = "ok" ] && is_non_negative_integer "${last_success_epoch}" && [ "${last_success_epoch}" -ge "${started_epoch}" ]; then
                echo "DropBox Ice bootstrap is ready."
                return 0
            fi
            if [ "${status}" = "error" ]; then
                status_line="$(tr '\n' ' ' < "${status_file}" | sed 's/[[:space:]]\+/ /g')"
                echo "ERROR: DropBox Ice bootstrap reported a non-retryable error at ${status_file}: ${status_line}" >&2
                return 2
            fi
        fi

        now_epoch="$(date +%s)"
        if [ "${now_epoch}" -ge "${deadline_epoch}" ]; then
            echo "WARNING: Timed out waiting for DropBox Ice bootstrap status at ${status_file}; the container bootstrap loop keeps retrying in the background." >&2
            if [ -r "${status_file}" ]; then
                status_line="$(tr '\n' ' ' < "${status_file}" | sed 's/[[:space:]]\+/ /g')"
                echo "WARNING: Last DropBox Ice bootstrap status: ${status_line}" >&2
            fi
            return 1
        fi

        sleep "${poll_interval_seconds}"
    done
}

wait_for_dropbox_user_dir_sync_ready() {
    local started_epoch="${1:?BUG: wait_for_dropbox_user_dir_sync_ready requires a start epoch}"
    local enabled="${OMERO_DROPBOX_USER_DIR_SYNC_ENABLED:?OMERO_DROPBOX_USER_DIR_SYNC_ENABLED is required}"
    local server_var_path="${OMERO_SERVER_VAR_PATH:?OMERO_SERVER_VAR_PATH is required}"
    local status_file="${server_var_path%/}/dropbox-user-dir-sync.status"
    local retry_limit="${OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES:?OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES is required}"
    local retry_delay_seconds="${OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS:?OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS is required}"
    local startup_wait_seconds="${OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS:?OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS is required}"
    local poll_interval_seconds=5
    local max_wait_seconds=0
    local deadline_epoch=0
    local now_epoch=0
    local status=""
    local last_success_epoch=""
    local status_line=""

    if [ "${START_CONTAINERS}" -ne 1 ]; then
        return 0
    fi

    if [ "${enabled}" != "1" ]; then
        echo "Skipping DropBox user directory sync readiness wait (OMERO_DROPBOX_USER_DIR_SYNC_ENABLED=${enabled})."
        return 0
    fi

    if [ -z "${ROOTPASS:-}" ]; then
        echo "ERROR: ROOTPASS is required for DropBox user directory sync readiness." >&2
        return 2
    fi

    if ! is_positive_integer "${retry_limit}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES must be a positive integer, got: ${retry_limit}" >&2
        return 2
    fi
    if ! is_positive_integer "${retry_delay_seconds}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS must be a positive integer, got: ${retry_delay_seconds}" >&2
        return 2
    fi
    if ! is_positive_integer "${startup_wait_seconds}"; then
        echo "ERROR: OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS must be a positive integer, got: ${startup_wait_seconds}" >&2
        return 2
    fi

    max_wait_seconds=$((startup_wait_seconds + retry_limit * retry_delay_seconds + retry_delay_seconds))
    deadline_epoch=$(( $(date +%s) + max_wait_seconds ))

    echo "Waiting for DropBox user directory synchronization to complete..."

    while true; do
        if [ -r "${status_file}" ]; then
            status="$(sed -n 's/^status=//p' "${status_file}" | tail -n 1)"
            last_success_epoch="$(sed -n 's/^last_success_epoch=//p' "${status_file}" | tail -n 1)"
            if [ "${status}" = "ok" ] && is_non_negative_integer "${last_success_epoch}" && [ "${last_success_epoch}" -ge "${started_epoch}" ]; then
                echo "DropBox user directory synchronization is ready."
                return 0
            fi
            if [ "${status}" = "error" ]; then
                status_line="$(tr '\n' ' ' < "${status_file}" | sed 's/[[:space:]]\+/ /g')"
                echo "ERROR: DropBox user directory synchronization reported a non-retryable error at ${status_file}: ${status_line}" >&2
                return 2
            fi
        fi

        now_epoch="$(date +%s)"
        if [ "${now_epoch}" -ge "${deadline_epoch}" ]; then
            echo "WARNING: Timed out waiting for DropBox user directory synchronization status at ${status_file}; the container sync loop keeps retrying in the background." >&2
            if [ -r "${status_file}" ]; then
                status_line="$(tr '\n' ' ' < "${status_file}" | sed 's/[[:space:]]\+/ /g')"
                echo "WARNING: Last DropBox user directory sync status: ${status_line}" >&2
            fi
            return 1
        fi

        sleep "${poll_interval_seconds}"
    done
}

stop_old_installation_containers() {
    local old_install_path="${1%/}"
    local old_database_path="$2"
    local old_plugin_database_path="$3"
    local old_data_path="${4%/}"
    local old_omero_data_dir="$5"
    local keep_images="$6"
    local old_compose_file="${old_install_path}/docker-compose.yml"
    local old_dot_env="${old_install_path}/.env"
    local created_temp_dot_env=false

    echo ""
    echo "Installation path changed: ${old_install_path}/ -> ${OMERO_INSTALLATION_PATH}"
    echo "Stopping containers from previous installation path..."

    if [ -f "${old_compose_file}" ]; then
        if [ ! -f "${old_dot_env}" ]; then
            cat > "${old_dot_env}" <<OLD_DOTENV
# Temporary .env generated for old-path container cleanup.
OMERO_INSTALLATION_PATH=${old_install_path}/
OMERO_DATABASE_PATH=${old_database_path}
OMERO_PLUGIN_DATABASE_PATH=${old_plugin_database_path}
OMERO_DATA_PATH=${old_data_path}
OMERO_TMP_PATH=${old_install_path}/omero_temp
OMERO_DATA_DIR=${old_omero_data_dir}
OMERO_USER_DATA_PATH=${old_data_path}/omero_user_data
OMERO_IMPORT_PATH=${old_install_path}/omero_temp/omeroweb-import
OMERO_SERVER_VAR_PATH=${old_data_path}/omero_server_var
OMERO_WEB_VAR_PATH=${old_data_path}/omero_web_var
OMERO_SERVER_LOGS_PATH=${old_data_path}/omero_server_logs
OMERO_WEB_LOGS_PATH=${old_data_path}/omero_web_logs
OMERO_WEB_SUPERVISOR_LOGS_PATH=${old_data_path}/omero_web_supervisor_logs
PORTAINER_DATA_PATH=${old_data_path}/portainer_data
PROMETHEUS_DATA_PATH=${old_data_path}/prometheus_data
GRAFANA_DATA_PATH=${old_data_path}/grafana_data
LOKI_DATA_PATH=${old_data_path}/loki_data
ALLOY_DATA_PATH=${old_data_path}/alloy_data
PG_MAINTENANCE_DATA_PATH=${old_data_path}/pg_maintenance_data
NODE_EXPORTER_TEXTFILE_PATH=${old_data_path}/node_exporter_textfile
CROWDSEC_DB_PATH=${old_data_path}/crowdsec_db
CROWDSEC_CONFIG_PATH=${old_data_path}/crowdsec_config
OLD_DOTENV
            created_temp_dot_env=true
        fi

        echo "Running docker compose down from old installation path: ${old_install_path}/"
        if [ "${keep_images}" -eq 1 ]; then
            docker compose \
                --project-directory "${old_install_path}" \
                -f "${old_compose_file}" \
                down --remove-orphans 2>&1 || true
        else
            docker compose \
                --project-directory "${old_install_path}" \
                -f "${old_compose_file}" \
                down --remove-orphans --rmi all 2>&1 || true
        fi

        if [ "${created_temp_dot_env}" = true ] && [ -f "${old_dot_env}" ]; then
            rm -f "${old_dot_env}"
        fi
    else
        echo "No docker-compose.yml at old installation path; skipping compose down."
    fi

    local fixed_name
    for fixed_name in portainer redis-sysctl-init pg-maintenance; do
        if docker container inspect "${fixed_name}" >/dev/null 2>&1; then
            echo "Force-removing leftover container with fixed name: ${fixed_name}"
            docker rm -fv "${fixed_name}" 2>/dev/null || true
        fi
    done

    echo "Old installation container cleanup complete."
    echo ""
}

# Root-only safety check
# ----------------------
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

# Lockfile (prevents concurrent runs)
# -----------------------------------
LOCKFILE="/var/lock/${SCRIPT_NAME}.lock"

exec 9>"${LOCKFILE}"
if ! flock -w 15 9; then
    echo "ERROR: Could not acquire lock (${LOCKFILE}) within 15 seconds. Another update may be running." >&2
    exit 1
fi

is_valid_linux_path() {
    local path_input="$1"

    if [ -z "${path_input}" ] || [ "${path_input#/}" = "${path_input}" ]; then
        return 1
    fi

    if printf '%s' "${path_input}" | grep -q '[[:cntrl:]]'; then
        return 1
    fi

    return 0
}

validate_installation_path() {
    local install_path="$1"

    if ! is_valid_linux_path "${install_path}"; then
        return 1
    fi

    if [ -e "${install_path}" ] && [ ! -d "${install_path}" ]; then
        echo "Path exists but is not a directory: ${install_path}" >&2
        return 1
    fi

    if [ -d "${install_path}" ] && [ ! -w "${install_path}" ]; then
        echo "Directory is not writable: ${install_path}" >&2
        return 1
    fi

    return 0
}

ensure_installation_path() {
    local install_path="$1"

    if [ -e "${install_path}" ] && [ ! -d "${install_path}" ]; then
        echo "ERROR: OMERO installation path exists but is not a directory: ${install_path}" >&2
        return 1
    fi

    if [ ! -d "${install_path}" ]; then
        echo "OMERO installation path does not exist yet. Creating empty directory with mode 0755: ${install_path}"
        if ! install -d -m 0755 "${install_path}"; then
            echo "ERROR: Failed to create OMERO installation path: ${install_path}" >&2
            return 1
        fi
    fi

    if [ ! -w "${install_path}" ] || [ ! -x "${install_path}" ]; then
        echo "ERROR: OMERO installation path is not writable: ${install_path}" >&2
        return 1
    fi

    return 0
}

count_top_level_entries() {
    local target_path="$1"

    if [ ! -d "${target_path}" ]; then
        printf '0'
        return 0
    fi

    find "${target_path}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d '[:space:]'
}

warn_directory_not_empty() {
    local target_path="$1"
    local target_label="$2"
    local existing_entries="0"

    if [ -e "${target_path}" ] && [ ! -d "${target_path}" ]; then
        echo "WARNING: ${target_label} exists but is not a directory: ${target_path}" >&2
        return 0
    fi

    if [ ! -d "${target_path}" ]; then
        return 0
    fi

    existing_entries="$(count_top_level_entries "${target_path}")"
    if [ "${existing_entries}" -gt 0 ]; then
        echo "WARNING: ${target_label} is not empty (found ${existing_entries} top-level item(s)): ${target_path}" >&2
        echo "         Existing data will be reused. If you need a clean installation, remove the contents manually first." >&2
    fi

    return 0
}

collect_bootstrap_sentinel_names() {
    (
        local _install_root="${OMERO_INSTALLATION_PATH:-}"
        _install_root="${_install_root%/}"

        local _path
        for _path in \
            "${OMERO_DATABASE_PATH:-}" \
            "${OMERO_PLUGIN_DATABASE_PATH:-}" \
            "${OMERO_DATA_PATH:-}" \
            "${OMERO_USER_DATA_PATH:-}" \
            "${OMERO_IMPORT_PATH:-}" \
            "${OMERO_SERVER_VAR_PATH:-}" \
            "${OMERO_WEB_VAR_PATH:-}" \
            "${OMERO_SERVER_LOGS_PATH:-}" \
            "${OMERO_WEB_LOGS_PATH:-}" \
            "${OMERO_WEB_SUPERVISOR_LOGS_PATH:-}" \
            "${PORTAINER_DATA_PATH:-}" \
            "${PROMETHEUS_DATA_PATH:-}" \
            "${GRAFANA_DATA_PATH:-}" \
            "${LOKI_DATA_PATH:-}" \
            "${ALLOY_DATA_PATH:-}" \
            "${PG_MAINTENANCE_DATA_PATH:-}" \
            "${NODE_EXPORTER_TEXTFILE_PATH:-}" \
            "${CROWDSEC_DB_PATH:-}" \
            "${CROWDSEC_CONFIG_PATH:-}"; do

            [ -z "${_path}" ] && continue
            _path="${_path%/}"

            local _rel=""
            if [ -n "${_install_root}" ] && [ "${_path}" != "${_install_root}" ]; then
                case "${_path}" in
                    "${_install_root}/"*)
                        _rel="${_path#"${_install_root}/"}"
                        ;;
                    *)
                        _rel="$(basename "${_path}")"
                        ;;
                esac
            else
                _rel="$(basename "${_path}")"
            fi

            local _saved_IFS="${IFS}"
            IFS='/'
            # shellcheck disable=SC2086
            for _component in ${_rel}; do
                [ -n "${_component}" ] && printf '%s\n' "${_component}"
            done
            IFS="${_saved_IFS}"
        done
    ) | sort -u
}

collect_repo_data_dir_names() {
    local repo_root="${REPO_ROOT_DIR%/}"

    (
        local _path
        for _path in \
            "${OMERO_DATABASE_PATH:-}" \
            "${OMERO_PLUGIN_DATABASE_PATH:-}" \
            "${OMERO_DATA_PATH:-}" \
            "${OMERO_USER_DATA_PATH:-}" \
            "${OMERO_IMPORT_PATH:-}" \
            "${OMERO_SERVER_VAR_PATH:-}" \
            "${OMERO_WEB_VAR_PATH:-}" \
            "${OMERO_SERVER_LOGS_PATH:-}" \
            "${OMERO_WEB_LOGS_PATH:-}" \
            "${OMERO_WEB_SUPERVISOR_LOGS_PATH:-}" \
            "${PORTAINER_DATA_PATH:-}" \
            "${PROMETHEUS_DATA_PATH:-}" \
            "${GRAFANA_DATA_PATH:-}" \
            "${LOKI_DATA_PATH:-}" \
            "${ALLOY_DATA_PATH:-}" \
            "${PG_MAINTENANCE_DATA_PATH:-}" \
            "${NODE_EXPORTER_TEXTFILE_PATH:-}" \
            "${CROWDSEC_DB_PATH:-}" \
            "${CROWDSEC_CONFIG_PATH:-}"; do

            [ -z "${_path}" ] && continue
            _path="${_path%/}"
            [ "${_path}" = "${repo_root}" ] && continue

            case "${_path}" in
                "${repo_root}/"*)
                    local _rel="${_path#"${repo_root}/"}"
                    local _top="${_rel%%/*}"
                    [ -n "${_top}" ] && printf '%s\n' "${_top}"
                    ;;
            esac
        done
    ) | sort -u
}

bootstrap_installation_checkout_if_missing() {
    local install_path="$1"
    local compose_file_path="${install_path%/}/docker-compose.yml"
    local install_realpath=""
    local repo_realpath=""

    if [ -f "${compose_file_path}" ]; then
        return 0
    fi

    if ! ensure_installation_path "${install_path}"; then
        return 1
    fi

    warn_directory_not_empty "${install_path}" "OMERO installation path"

    install_realpath="$(realpath -m "${install_path}")"
    repo_realpath="$(realpath -m "${REPO_ROOT_DIR}")"

    if [ "${install_realpath}" = "${repo_realpath}" ]; then
        echo "ERROR: docker-compose.yml is missing from OMERO installation path: ${compose_file_path}" >&2
        echo "ERROR: Repository checkout appears incomplete. Re-run github_pull_project_bash to restore project files." >&2
        return 1
    fi

    case "${install_realpath}" in
        "${repo_realpath}"/*)
            local _rel_to_repo="${install_realpath#"${repo_realpath}/"}"
            local _exclude_top="${_rel_to_repo%%/*}"

            echo "docker-compose.yml not found in installation path. Bootstrapping project checkout into: ${install_path}"
            echo "NOTE: Installation path is inside repository root. Excluding '${_exclude_top}' from bootstrap copy to avoid recursion."

            local -a _find_excludes=( ! -name "${_exclude_top}" )
            local _data_dir_name
            while IFS= read -r _data_dir_name; do
                [ -n "${_data_dir_name}" ] && _find_excludes+=( ! -name "${_data_dir_name}" )
            done < <(collect_repo_data_dir_names)

            local -a _sentinel_names=()
            local _sname
            while IFS= read -r _sname; do
                [ -n "${_sname}" ] && _sentinel_names+=("${_sname}")
            done < <(collect_bootstrap_sentinel_names)

            local -a _sentinel_find_expr=()
            if [ ${#_sentinel_names[@]} -gt 0 ]; then
                _sentinel_find_expr+=( \( )
                local _first=true
                for _sname in "${_sentinel_names[@]}"; do
                    if [ "${_first}" = true ]; then
                        _first=false
                    else
                        _sentinel_find_expr+=( -o )
                    fi
                    _sentinel_find_expr+=( -name "${_sname}" )
                done
                _sentinel_find_expr+=( \) )
            fi

            local _copy_failed=false
            local _item
            while IFS= read -r _item; do
                [ -z "${_item}" ] && continue

                if [ -d "${_item}" ] && [ ${#_sentinel_find_expr[@]} -gt 0 ]; then
                    if find "${_item}" -type d "${_sentinel_find_expr[@]}" -print -quit 2>/dev/null | grep -q .; then
                        echo "NOTE: Skipping '$(basename "${_item}")' (contains data/database subdirectories from previous installation)."
                        continue
                    fi
                fi

                if ! cp -a "${_item}" "${install_path}/"; then
                    _copy_failed=true
                    break
                fi
            done < <(find "${REPO_ROOT_DIR}" -mindepth 1 -maxdepth 1 "${_find_excludes[@]}")

            if [ "${_copy_failed}" = true ]; then
                echo "ERROR: Failed to copy project checkout from ${REPO_ROOT_DIR} to ${install_path}" >&2
                return 1
            fi

            if [ ! -f "${compose_file_path}" ]; then
                echo "ERROR: Bootstrap copy completed but docker-compose.yml is still missing: ${compose_file_path}" >&2
                return 1
            fi

            return 0
            ;;
    esac

    echo "docker-compose.yml not found in installation path. Bootstrapping project checkout into: ${install_path}"

    local -a _find_excludes=()
    local _data_dir_name
    while IFS= read -r _data_dir_name; do
        [ -n "${_data_dir_name}" ] && _find_excludes+=( ! -name "${_data_dir_name}" )
    done < <(collect_repo_data_dir_names)

    local -a _sentinel_names=()
    local _sname
    while IFS= read -r _sname; do
        [ -n "${_sname}" ] && _sentinel_names+=("${_sname}")
    done < <(collect_bootstrap_sentinel_names)

    local -a _sentinel_find_expr=()
    if [ ${#_sentinel_names[@]} -gt 0 ]; then
        _sentinel_find_expr+=( \( )
        local _first=true
        for _sname in "${_sentinel_names[@]}"; do
            if [ "${_first}" = true ]; then
                _first=false
            else
                _sentinel_find_expr+=( -o )
            fi
            _sentinel_find_expr+=( -name "${_sname}" )
        done
        _sentinel_find_expr+=( \) )
    fi

    local _copy_failed=false
    local _item
    while IFS= read -r _item; do
        [ -z "${_item}" ] && continue

        if [ -d "${_item}" ] && [ ${#_sentinel_find_expr[@]} -gt 0 ]; then
            if find "${_item}" -type d "${_sentinel_find_expr[@]}" -print -quit 2>/dev/null | grep -q .; then
                echo "NOTE: Skipping '$(basename "${_item}")' (contains data/database subdirectories from previous installation)."
                continue
            fi
        fi

        if ! cp -a "${_item}" "${install_path}/"; then
            _copy_failed=true
            break
        fi
    done < <(find "${REPO_ROOT_DIR}" -mindepth 1 -maxdepth 1 "${_find_excludes[@]}")

    if [ "${_copy_failed}" = true ]; then
        echo "ERROR: Failed to copy project checkout from ${REPO_ROOT_DIR} to ${install_path}" >&2
        return 1
    fi

    if [ ! -f "${compose_file_path}" ]; then
        echo "ERROR: Bootstrap copy completed but docker-compose.yml is still missing: ${compose_file_path}" >&2
        return 1
    fi

    return 0
}

write_compose_dot_env() {
    local dot_env_path="${1:?BUG: write_compose_dot_env requires a path}"

    cat > "${dot_env_path}" <<DOTENV
# Auto-generated by installation_script.sh – do not edit manually.
# Re-run the installation script to regenerate after changing paths.
#
# Canonical comma-separated env-file list for shells/tools that honor
# COMPOSE_ENV_FILES. Agent and script runbooks still pass explicit --env-file
# arguments for first-attempt portability across Compose versions.
COMPOSE_ENV_FILES=installation_paths.env,env/omero_secrets.env,env/omeroserver.env,env/omeroweb.env,env/omero-celery.env,env/grafana.env
#
# This file contains fully-resolved paths so that docker compose
# commands (up, down, ps, logs, ...) work out of the box without
# requiring --env-file or COMPOSE_ENV_FILES support from the installation root.
#
# NOTE: Compose interpolation happens before service-level env_file loading.
# Required paths, ports, Redis settings, and build version pins are mirrored
# here so manual commands like \`docker compose down\`, \`config\`, and
# \`build\` work without copying secret values into Compose interpolation.
COMPOSE_PROJECT_NAME=${OMERO_COMPOSE_PROJECT_NAME}
OMERO_INSTALLATION_PATH=${OMERO_INSTALLATION_PATH}
OMERO_DATABASE_PATH=${OMERO_DATABASE_PATH}
OMERO_PLUGIN_DATABASE_PATH=${OMERO_PLUGIN_DATABASE_PATH}
OMERO_DATA_PATH=${OMERO_DATA_PATH}
OMERO_TMP_PATH=${OMERO_TMP_PATH}
OMERO_DATA_DIR=${OMERO_DATA_DIR}
OMERO_USER_DATA_PATH=${OMERO_USER_DATA_PATH}
OMERO_IMPORT_PATH=${OMERO_IMPORT_PATH}
OMERO_SERVER_VAR_PATH=${OMERO_SERVER_VAR_PATH}
OMERO_SERVER_LOGS_PATH=${OMERO_SERVER_LOGS_PATH}
OMERO_WEB_VAR_PATH=${OMERO_WEB_VAR_PATH}
OMERO_WEB_LOGS_PATH=${OMERO_WEB_LOGS_PATH}
OMERO_WEB_SUPERVISOR_LOGS_PATH=${OMERO_WEB_SUPERVISOR_LOGS_PATH}
OMERO_WEB_HOST_PORT=${OMERO_WEB_HOST_PORT}
CONFIG_omero_web_application__server_port=${CONFIG_omero_web_application__server_port}
OMERO_SERVER_HOST_PORT=${OMERO_SERVER_HOST_PORT}
OMERO_CLI_HOST=${OMERO_CLI_HOST}
OMERO_CLI_PORT=${OMERO_CLI_PORT}
OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS=${OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS}
OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS=${OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS}
OMERO_SERVER_HEALTHCHECK_RETRIES=${OMERO_SERVER_HEALTHCHECK_RETRIES}
OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS=${OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS}
PORTAINER_DATA_PATH=${PORTAINER_DATA_PATH}
PROMETHEUS_DATA_PATH=${PROMETHEUS_DATA_PATH}
GRAFANA_DATA_PATH=${GRAFANA_DATA_PATH}
LOKI_DATA_PATH=${LOKI_DATA_PATH}
ALLOY_DATA_PATH=${ALLOY_DATA_PATH}
PG_MAINTENANCE_DATA_PATH=${PG_MAINTENANCE_DATA_PATH}
NODE_EXPORTER_TEXTFILE_PATH=${NODE_EXPORTER_TEXTFILE_PATH}
CROWDSEC_DB_PATH=${CROWDSEC_DB_PATH}
CROWDSEC_CONFIG_PATH=${CROWDSEC_CONFIG_PATH}
OMERO_DROPBOX_VERSION=${OMERO_DROPBOX_VERSION}
OMERO_CLI_ZARR_VERSION=${OMERO_CLI_ZARR_VERSION}
OME_ZARR_PY_VERSION=${OME_ZARR_PY_VERSION}
BIOFORMATS2RAW_VERSION=${BIOFORMATS2RAW_VERSION}
BIOFORMATS_VERSION=${BIOFORMATS_VERSION}
REDIS_SAVE_POLICY=
REDIS_APPENDONLY=no
REDIS_MAXMEMORY=512mb
REDIS_MAXMEMORY_POLICY=allkeys-lru
REDIS_DATA_TMPFS_SIZE=512m
DOTENV

    if is_crowdsec_enabled; then
        echo "COMPOSE_PROFILES=crowdsec" >> "${dot_env_path}"
    fi

    chmod 0600 "${dot_env_path}"

    if [ -n "${SUDO_UID:-}" ] && [ -n "${SUDO_GID:-}" ]; then
        if ! is_non_negative_integer "${SUDO_UID}" || ! is_non_negative_integer "${SUDO_GID}"; then
            echo "ERROR: SUDO_UID/SUDO_GID must be numeric when provided. Got SUDO_UID=${SUDO_UID:-unset}, SUDO_GID=${SUDO_GID:-unset}" >&2
            return 1
        fi

        if ! chown "${SUDO_UID}:${SUDO_GID}" "${dot_env_path}"; then
            echo "ERROR: Failed to assign generated docker compose .env ownership to invoking sudo user (${SUDO_UID}:${SUDO_GID}): ${dot_env_path}" >&2
            return 1
        fi
    fi

    echo "Generated docker compose .env file: ${dot_env_path}"
}

derive_compose_project_name() {
    local install_path="${1:?BUG: derive_compose_project_name requires a path}"
    local install_name=""
    local normalized=""

    install_name="$(basename "${install_path%/}")"
    if [ -z "${install_name}" ] || [ "${install_name}" = "/" ] || [ "${install_name}" = "." ]; then
        install_name="omero"
    fi

    normalized="$(
        printf '%s' "${install_name}" \
            | tr '[:upper:]' '[:lower:]' \
            | sed -E 's/[^a-z0-9_-]+/-/g; s/^[-_]+//; s/[-_]+$//'
    )"

    if [ -z "${normalized}" ]; then
        normalized="omero"
    fi

    case "${normalized}" in
        [a-z0-9]*)
            ;;
        *)
            normalized="omero-${normalized}"
            ;;
    esac

    printf '%s' "${normalized}"
}

write_installation_paths_env() {
    local env_file_path="${1:?BUG: write_installation_paths_env requires a path}"

    mkdir -p "$(dirname "${env_file_path}")"
    cat > "${env_file_path}" <<ENVFILE
# Auto-generated by installation_script.sh – do not edit manually.
# Re-run the installation script to regenerate after changing paths.
#
# This file is the single source of truth for all installation paths.
# It is read by github_pull_project_bash to determine which directories
# to protect during updates, and by the installation script itself.
#
# Required variables:
#   OMERO_INSTALLATION_PATH
#   OMERO_DATABASE_PATH
#   OMERO_PLUGIN_DATABASE_PATH
#   OMERO_DATA_PATH
#   OMERO_TMP_PATH
#   OMERO_DATA_DIR
#   OMERO_USER_DATA_PATH
#   OMERO_IMPORT_PATH
#   OMERO_SERVER_VAR_PATH
#   OMERO_WEB_VAR_PATH
#   OMERO_SERVER_LOGS_PATH
#   OMERO_WEB_LOGS_PATH
#   OMERO_WEB_SUPERVISOR_LOGS_PATH
#   PROMETHEUS_DATA_PATH
#   GRAFANA_DATA_PATH
#   PORTAINER_DATA_PATH
#   LOKI_DATA_PATH
#   ALLOY_DATA_PATH
#   PG_MAINTENANCE_DATA_PATH
#   BUILDX_DATA_PATH
#   NODE_EXPORTER_TEXTFILE_PATH
#   CROWDSEC_DB_PATH
#   CROWDSEC_CONFIG_PATH
#
OMERO_INSTALLATION_PATH=${OMERO_INSTALLATION_PATH}
OMERO_DATABASE_PATH=${OMERO_DATABASE_PATH}
OMERO_PLUGIN_DATABASE_PATH=${OMERO_PLUGIN_DATABASE_PATH}
OMERO_DATA_PATH=${OMERO_DATA_PATH}
OMERO_TMP_PATH=${OMERO_TMP_PATH}
OMERO_DATA_DIR=${OMERO_DATA_DIR}
#
OMERO_USER_DATA_PATH=\${OMERO_DATA_PATH}/omero_user_data
OMERO_IMPORT_PATH=\${OMERO_TMP_PATH}/omeroweb-import
OMERO_SERVER_VAR_PATH=\${OMERO_DATA_PATH}/omero_server_var
OMERO_WEB_VAR_PATH=\${OMERO_DATA_PATH}/omero_web_var
OMERO_SERVER_LOGS_PATH=\${OMERO_DATA_PATH}/omero_server_logs
OMERO_WEB_LOGS_PATH=\${OMERO_DATA_PATH}/omero_web_logs
OMERO_WEB_SUPERVISOR_LOGS_PATH=\${OMERO_DATA_PATH}/omero_web_supervisor_logs
PROMETHEUS_DATA_PATH=\${OMERO_DATA_PATH}/prometheus_data
GRAFANA_DATA_PATH=\${OMERO_DATA_PATH}/grafana_data
PORTAINER_DATA_PATH=\${OMERO_DATA_PATH}/portainer_data
LOKI_DATA_PATH=\${OMERO_DATA_PATH}/loki_data
ALLOY_DATA_PATH=\${OMERO_DATA_PATH}/alloy_data
PG_MAINTENANCE_DATA_PATH=\${OMERO_DATA_PATH}/pg_maintenance_data
BUILDX_DATA_PATH=\${OMERO_DATA_PATH}/buildx_cache
NODE_EXPORTER_TEXTFILE_PATH=\${OMERO_DATA_PATH}/node_exporter_textfile
CROWDSEC_DB_PATH=\${OMERO_DATA_PATH}/crowdsec_db
CROWDSEC_CONFIG_PATH=\${OMERO_DATA_PATH}/crowdsec_config
#
ENVFILE

    echo "Generated installation paths env file: ${env_file_path}"
}
verify_installation_paths_env_content() {
    local env_file_path="${1:?BUG: verify_installation_paths_env_content requires a path}"

    if [ ! -r "${env_file_path}" ]; then
        echo "ERROR: installation paths env file is missing or unreadable after write: ${env_file_path}" >&2
        return 1
    fi

    local expected_var expected_value actual_value
    local required_vars=(
        OMERO_INSTALLATION_PATH
        OMERO_DATABASE_PATH
        OMERO_PLUGIN_DATABASE_PATH
        OMERO_DATA_PATH
        OMERO_TMP_PATH
        OMERO_DATA_DIR
        OMERO_USER_DATA_PATH
        OMERO_IMPORT_PATH
        OMERO_SERVER_VAR_PATH
        OMERO_WEB_VAR_PATH
        OMERO_SERVER_LOGS_PATH
        OMERO_WEB_LOGS_PATH
        OMERO_WEB_SUPERVISOR_LOGS_PATH
        PROMETHEUS_DATA_PATH
        GRAFANA_DATA_PATH
        PORTAINER_DATA_PATH
        LOKI_DATA_PATH
        ALLOY_DATA_PATH
        PG_MAINTENANCE_DATA_PATH
        BUILDX_DATA_PATH
        NODE_EXPORTER_TEXTFILE_PATH
        CROWDSEC_DB_PATH
        CROWDSEC_CONFIG_PATH
    )

    for expected_var in "${required_vars[@]}"; do
        expected_value="${!expected_var:-}"
        actual_value="$(CMD="\. \"${env_file_path}\" 2>/dev/null || exit 1; printf '%s' \"\${${expected_var}:-}\""; bash -c "$CMD")"

        if [ -z "${actual_value}" ]; then
            echo "ERROR: ${expected_var} was not written to ${env_file_path}." >&2
            return 1
        fi

        if [ "${actual_value}" != "${expected_value}" ]; then
            echo "ERROR: ${expected_var} value mismatch in ${env_file_path}." >&2
            echo "ERROR: Expected: ${expected_value}" >&2
            echo "ERROR: Actual:   ${actual_value}" >&2
            return 1
        fi
    done

    return 0
}

validate_path_is_preparable() {
    local path_to_check="$1"
    local path_label="$2"
    local probe_dir=""

    if ! is_valid_linux_path "${path_to_check}"; then
        echo "ERROR: ${path_label} must be a valid absolute Linux path: ${path_to_check}" >&2
        return 1
    fi

    if [ -e "${path_to_check}" ] && [ ! -d "${path_to_check}" ]; then
        echo "ERROR: ${path_label} exists but is not a directory: ${path_to_check}" >&2
        return 1
    fi

    if [ -d "${path_to_check}" ]; then
        if [ ! -w "${path_to_check}" ] || [ ! -x "${path_to_check}" ]; then
            echo "ERROR: ${path_label} is not writable: ${path_to_check}" >&2
            return 1
        fi
        return 0
    fi

    probe_dir="${path_to_check%/}"
    while [ -n "${probe_dir}" ] && [ "${probe_dir}" != "/" ] && [ ! -e "${probe_dir}" ]; do
        probe_dir="$(dirname "${probe_dir}")"
    done

    if [ -z "${probe_dir}" ]; then
        probe_dir="/"
    fi

    if [ ! -d "${probe_dir}" ]; then
        echo "ERROR: ${path_label} parent path does not resolve to a directory: ${probe_dir}" >&2
        return 1
    fi

    if [ ! -w "${probe_dir}" ] || [ ! -x "${probe_dir}" ]; then
        echo "ERROR: ${path_label} cannot be created because parent directory is not writable: ${probe_dir}" >&2
        return 1
    fi

    return 0
}

tty_echo() {
    local message="${1:-}"

    if [ -r /dev/tty ]; then
        echo "${message}" > /dev/tty
    fi
    install_transcript_record_line "${message}"
}

tty_write_text() {
    local rendered_message="${1:-}"

    if [ -r /dev/tty ]; then
        printf '%s' "${rendered_message}" > /dev/tty
    fi
    install_transcript_record_text "${rendered_message}"
}

tty_read_line() {
    local __result_var="${1:?BUG: tty_read_line requires target variable name}"
    local __tty_read_value=""

    if ! is_shell_variable_name "${__result_var}"; then
        echo "ERROR: tty_read_line target must be a valid shell variable name: ${__result_var}" >&2
        return 1
    fi

    # Keep the internal buffer name distinct from common caller locals like
    # "reply" so write-back targets never collide with this function scope.
    if ! IFS= read -r __tty_read_value < /dev/tty; then
        return 1
    fi

    install_transcript_record_line "${__tty_read_value}"
    printf -v "${__result_var}" '%s' "${__tty_read_value}"
    return 0
}

prompt_for_preparable_path() {
    local default_path="$1"
    local path_label="$2"
    local selected_path=""

    while true; do
        selected_path="$(resolve_path_with_default_prompt "${default_path}" "${path_label}")"
        if validate_path_is_preparable "${selected_path}" "${path_label}"; then
            printf '%s' "${selected_path}"
            return 0
        fi

        if [ -r /dev/tty ]; then
            tty_echo "Please choose a different ${path_label}."
        else
            return 1
        fi
    done
}

ensure_data_path() {
    local data_path="$1"
    local path_label="$2"

    if [ -e "${data_path}" ] && [ ! -d "${data_path}" ]; then
        echo "ERROR: ${path_label} exists but is not a directory: ${data_path}" >&2
        return 1
    fi

    if [ ! -d "${data_path}" ]; then
        echo "${path_label} does not exist yet. Creating empty directory with mode 0755 (no existing data is removed): ${data_path}"
        if ! install -d -m 0755 "${data_path}"; then
            echo "ERROR: Failed to create ${path_label}: ${data_path}" >&2
            return 1
        fi
    else
        local existing_entries
        existing_entries="$(find "${data_path}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d '[:space:]')"
        echo "${path_label} already exists with ${existing_entries} top-level item(s); preserving existing data: ${data_path}"
    fi

    if [ ! -w "${data_path}" ]; then
        echo "ERROR: ${path_label} is not writable: ${data_path}" >&2
        return 1
    fi

    return 0
}


log_path_snapshot() {
    local path_to_check="$1"
    local label="$2"

    if [ ! -d "${path_to_check}" ]; then
        echo "SNAPSHOT(meta-only, non-recursive): ${label}: missing path ${path_to_check}"
        return 0
    fi

    local top_level_entries="0"
    local dir_owner="unknown"
    local dir_mode="unknown"

    top_level_entries="$(find "${path_to_check}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d '[:space:]')"
    if stat -c '%U:%G %a' "${path_to_check}" >/dev/null 2>&1; then
        dir_owner="$(stat -c '%U:%G' "${path_to_check}")"
        dir_mode="$(stat -c '%a' "${path_to_check}")"
    fi

    echo "SNAPSHOT(meta-only, non-recursive): ${label}: top_level_entries=${top_level_entries} owner=${dir_owner} mode=${dir_mode} path=${path_to_check}"
}

resolve_delete_images_choice() {
    local reply=""
    local override_choice="${DELETE_IMAGES_CHOICE:-}"

    if [ -n "${override_choice}" ]; then
        reply="$(printf '%s' "${override_choice}" | tr '[:upper:]' '[:lower:]')"
        case "${reply}" in
            y|yes)
                KEEP_IMAGES=0
                echo "DELETE_IMAGES_CHOICE=${override_choice}: removing container images."
                return 0
                ;;
            n|no)
                KEEP_IMAGES=1
                echo "DELETE_IMAGES_CHOICE=${override_choice}: keeping container images."
                return 0
                ;;
            *)
                echo "ERROR: DELETE_IMAGES_CHOICE must be one of: y, yes, n, no. Got: ${override_choice}" >&2
                return 1
                ;;
        esac
    fi

    if [ "${INSTALLATION_AUTOMATION_MODE}" = "1" ]; then
        KEEP_IMAGES=1
        echo "INSTALLATION_AUTOMATION_MODE=1: defaulting to keep existing images."
        return 0
    fi

    if [ ! -r /dev/tty ]; then
        KEEP_IMAGES=1
        echo "WARNING: /dev/tty is not available; defaulting to keep existing images." >&2
        return 0
    fi

    reply="$(prompt_yes_no "Delete all container images? Y/n (Default: n)" "no")"
    if [ "${reply}" = "yes" ]; then
        KEEP_IMAGES=0
    else
        KEEP_IMAGES=1
    fi

    return 0
}

resolve_path_with_default_prompt() {
    local default_path="$1"
    local path_label="$2"
    local reply=""
    local chosen_path=""
    local prompt_message=""

    while true; do
        reply="$(prompt_yes_no "Use default ${path_label} (${default_path})? Y/n (Default: Y)" "yes")"

        if [ "${reply}" = "yes" ]; then
            printf '%s' "${default_path}"
            return 0
        fi

        while true; do
            printf -v prompt_message '%s: (Current: %s) ' "${path_label}" "${default_path}"
            tty_write_text "${prompt_message}"

            if ! tty_read_line chosen_path; then
                printf '%s' "${default_path}"
                return 0
            fi

            if [ -z "${chosen_path}" ]; then
                chosen_path="${default_path}"
            fi

            if is_valid_linux_path "${chosen_path}"; then
                printf '%s' "${chosen_path}"
                return 0
            fi

            tty_echo "Wrong ${path_label}, try again: (Current: ${default_path})"
        done
    done
}

prompt_yes_no() {
    local prompt_message="$1"
    local default_choice="$2"
    local reply=""

    if [ "${INSTALLATION_AUTOMATION_MODE}" = "1" ] || [ ! -r /dev/tty ]; then
        printf '%s' "${default_choice}"
        return 0
    fi

    while true; do
        tty_echo "${prompt_message}"
        tty_write_text '> '

        if ! tty_read_line reply; then
            printf '%s' "${default_choice}"
            return 0
        fi

        reply="$(printf '%s' "${reply}" | tr '[:upper:]' '[:lower:]')"

        if [ -z "${reply}" ]; then
            printf '%s' "${default_choice}"
            return 0
        fi

        case "${reply}" in
            y|yes)
                printf '%s' "yes"
                return 0
                ;;
            n|no)
                printf '%s' "no"
                return 0
                ;;
            *)
                tty_echo "Wrong choice. Please type Y or n."
                ;;
        esac
    done
}

resolve_cache_build_choice() {
    local reply=""
    local override_choice="${USE_CACHE_BUILD_CHOICE:-}"
    local prompt_message=""

    if [ -n "${override_choice}" ]; then
        reply="$(printf '%s' "${override_choice}" | tr '[:upper:]' '[:lower:]')"
        case "${reply}" in
            y|yes)
                USE_CACHE_BUILD=1
                echo "USE_CACHE_BUILD_CHOICE=${override_choice}: build cache enabled (docker layer cache + buildx inline cache)."
                return 0
                ;;
            n|no)
                USE_CACHE_BUILD=0
                echo "USE_CACHE_BUILD_CHOICE=${override_choice}: build cache disabled (no docker layer cache, no buildx inline cache)."
                return 0
                ;;
            *)
                echo "ERROR: USE_CACHE_BUILD_CHOICE must be one of: y, yes, n, no. Got: ${override_choice}" >&2
                return 1
                ;;
        esac
    fi

    if [ "${USE_BUILDX_COMPRESSED_BUILD}" = "1" ]; then
        prompt_message="Use build cache? (controls both docker layer cache and buildx inline cache) Y/n (Default: Y)"
    else
        prompt_message="Use build cache? Y/n (Default: Y)"
    fi

    reply="$(prompt_yes_no "${prompt_message}" "yes")"
    if [ "${reply}" = "yes" ]; then
        USE_CACHE_BUILD=1
    else
        USE_CACHE_BUILD=0
    fi

    return 0
}

resolve_flatten_final_image_choice() {
    local reply=""
    local prompt_message=""
    local prompt_hint="Y/n"
    local prompt_default="n"
    local default_choice="no"

    if ! validate_toggle_config "DOCKER_BUILD_FLATTEN_FINAL_IMAGE" "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}"; then
        return 1
    fi

    if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" = "1" ]; then
        prompt_hint="Y/n"
        prompt_default="Y"
        default_choice="yes"
    fi

    prompt_message="Flatten final images into single-layer outputs? (slower; rebuilds each image) ${prompt_hint} (Default: ${prompt_default})"
    reply="$(prompt_yes_no "${prompt_message}" "${default_choice}")"
    if [ "${reply}" = "yes" ]; then
        DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1
    else
        DOCKER_BUILD_FLATTEN_FINAL_IMAGE=0
    fi

    return 0
}

resolve_security_hardening_choice() {
    local reply=""
    local override_choice="${SECURITY_HARDENING_CHOICE:-}"

    if [ -n "${override_choice}" ]; then
        reply="$(printf '%s' "${override_choice}" | tr '[:upper:]' '[:lower:]')"
        case "${reply}" in
            y|yes)
                APPLY_SECURITY_HARDENING=1
                echo "SECURITY_HARDENING_CHOICE=${override_choice}: Docker image security hardening enabled."
                return 0
                ;;
            n|no)
                APPLY_SECURITY_HARDENING=0
                echo "SECURITY_HARDENING_CHOICE=${override_choice}: Docker image security hardening disabled."
                return 0
                ;;
            *)
                echo "ERROR: SECURITY_HARDENING_CHOICE must be one of: y, yes, n, no. Got: ${override_choice}" >&2
                return 1
                ;;
        esac
    fi

    local prompt_hint="Y/n"
    local prompt_default="Y"
    local default_choice="yes"

    if [ -n "${APPLY_SECURITY_HARDENING}" ]; then
        if ! validate_toggle_config "APPLY_SECURITY_HARDENING" "${APPLY_SECURITY_HARDENING}"; then
            return 1
        fi
        if [ "${APPLY_SECURITY_HARDENING}" = "0" ]; then
            prompt_default="n"
            default_choice="no"
        fi
    fi

    reply="$(prompt_yes_no "Enable Docker image security hardening? (applies OS and Python security updates to all images) ${prompt_hint} (Default: ${prompt_default})" "${default_choice}")"
    if [ "${reply}" = "yes" ]; then
        APPLY_SECURITY_HARDENING=1
    else
        APPLY_SECURITY_HARDENING=0
    fi

    return 0
}

resolve_vulnerability_scan_choice() {
    local reply=""
    local override_choice="${VULNERABILITY_SCAN_CHOICE:-}"

    if [ -n "${override_choice}" ]; then
        reply="$(printf '%s' "${override_choice}" | tr '[:upper:]' '[:lower:]')"
        case "${reply}" in
            y|yes)
                ENABLE_VULNERABILITY_SCAN=1
                echo "VULNERABILITY_SCAN_CHOICE=${override_choice}: Docker Scout vulnerability scanning enabled."
                return 0
                ;;
            n|no)
                ENABLE_VULNERABILITY_SCAN=0
                echo "VULNERABILITY_SCAN_CHOICE=${override_choice}: Docker Scout vulnerability scanning disabled."
                return 0
                ;;
            *)
                echo "ERROR: VULNERABILITY_SCAN_CHOICE must be one of: y, yes, n, no. Got: ${override_choice}" >&2
                return 1
                ;;
        esac
    fi

    if ! validate_toggle_config "ENABLE_VULNERABILITY_SCAN" "${ENABLE_VULNERABILITY_SCAN}"; then
        return 1
    fi

    local prompt_hint="Y/n"
    local prompt_default="n"
    local default_choice="no"

    if [ "${ENABLE_VULNERABILITY_SCAN}" = "1" ]; then
        prompt_hint="Y/n"
        prompt_default="Y"
        default_choice="yes"
    fi

    reply="$(prompt_yes_no "Enable Docker Scout vulnerability scanning? (scans all images for known CVEs — adds several minutes) ${prompt_hint} (Default: ${prompt_default})" "${default_choice}")"
    if [ "${reply}" = "yes" ]; then
        ENABLE_VULNERABILITY_SCAN=1
    else
        ENABLE_VULNERABILITY_SCAN=0
    fi

    return 0
}

resolve_buildx_compressed_build_choice() {
    local reply=""
    local override_choice="${USE_BUILDX_CHOICE:-}"

    if [ -n "${override_choice}" ]; then
        reply="$(printf '%s' "${override_choice}" | tr '[:upper:]' '[:lower:]')"
        case "${reply}" in
            y|yes)
                USE_BUILDX_COMPRESSED_BUILD=1
                echo "USE_BUILDX_CHOICE=${override_choice}: Buildx compressed build enabled."
                return 0
                ;;
            n|no)
                USE_BUILDX_COMPRESSED_BUILD=0
                echo "USE_BUILDX_CHOICE=${override_choice}: using docker compose build (Buildx compressed build disabled)."
                return 0
                ;;
            *)
                echo "ERROR: USE_BUILDX_CHOICE must be one of: y, yes, n, no. Got: ${override_choice}" >&2
                return 1
                ;;
        esac
    fi

    reply="$(prompt_yes_no "Enable Buildx compressed build workflow? Y/n (Default: n)" "no")"
    if [ "${reply}" = "yes" ]; then
        USE_BUILDX_COMPRESSED_BUILD=1
    else
        USE_BUILDX_COMPRESSED_BUILD=0
    fi

    return 0
}

resolve_start_containers_choice() {
    local reply=""
    local override_choice="${START_CONTAINERS_CHOICE:-}"

    if [ -n "${override_choice}" ]; then
        reply="$(printf '%s' "${override_choice}" | tr '[:upper:]' '[:lower:]')"
        case "${reply}" in
            y|yes)
                START_CONTAINERS=1
                echo "START_CONTAINERS_CHOICE=${override_choice}: containers will be started."
                return 0
                ;;
            n|no)
                START_CONTAINERS=0
                echo "START_CONTAINERS_CHOICE=${override_choice}: skipping container startup."
                return 0
                ;;
            *)
                echo "ERROR: START_CONTAINERS_CHOICE must be one of: y, yes, n, no. Got: ${override_choice}" >&2
                return 1
                ;;
        esac
    fi

    reply="$(prompt_yes_no "Start containers after build? Y/n (Default: Y)" "yes")"
    if [ "${reply}" = "yes" ]; then
        START_CONTAINERS=1
    else
        START_CONTAINERS=0
    fi

    return 0
}

if ! resolve_delete_images_choice; then
    exit 1
fi

if ! resolve_buildx_compressed_build_choice; then
    exit 1
fi

if ! resolve_cache_build_choice; then
    exit 1
fi

if ! resolve_flatten_final_image_choice; then
    exit 1
fi

if ! resolve_security_hardening_choice; then
    exit 1
fi

if ! resolve_vulnerability_scan_choice; then
    exit 1
fi

if ! resolve_start_containers_choice; then
    exit 1
fi

if ! validate_toggle_config "INSTALLATION_AUTOMATION_MODE" "${INSTALLATION_AUTOMATION_MODE}"; then
    exit 1
fi

if ! validate_toggle_config "USE_BUILDX_COMPRESSED_BUILD" "${USE_BUILDX_COMPRESSED_BUILD}"; then
    exit 1
fi

if ! validate_toggle_config "DOCKER_BUILD_FLATTEN_FINAL_IMAGE" "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}"; then
    exit 1
fi

if [ -n "${APPLY_SECURITY_HARDENING}" ]; then
    if ! validate_toggle_config "APPLY_SECURITY_HARDENING" "${APPLY_SECURITY_HARDENING}"; then
        exit 1
    fi
fi

# Export for the buildx compressed build script (reads APPLY_SECURITY_HARDENING env var)
export APPLY_SECURITY_HARDENING

DEFAULT_OMERO_INSTALLATION_PATH="${OMERO_INSTALLATION_PATH}"
DEFAULT_OMERO_DATABASE_PATH="${OMERO_DATABASE_PATH}"
DEFAULT_OMERO_PLUGIN_DATABASE_PATH="${OMERO_PLUGIN_DATABASE_PATH}"
DEFAULT_OMERO_DATA_PATH="${OMERO_DATA_PATH}"
DEFAULT_OMERO_TMP_PATH="${OMERO_TMP_PATH}"
DEFAULT_OMERO_DATA_DIR="${OMERO_DATA_DIR}"

OMERO_INSTALLATION_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_INSTALLATION_PATH}" "OMERO installation path")"
OMERO_DATABASE_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_DATABASE_PATH}" "OMERO database path")"
OMERO_PLUGIN_DATABASE_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database path")"
OMERO_DATA_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_DATA_PATH}" "OMERO data path")"
OMERO_TMP_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_TMP_PATH}" "OMERO tmp path")"

if ! bootstrap_installation_checkout_if_missing "${OMERO_INSTALLATION_PATH}"; then
    exit 1
fi

COMPOSE_FILE="${OMERO_INSTALLATION_PATH%/}/docker-compose.yml"

OMERO_USER_DATA_PATH="${OMERO_DATA_PATH%/}/omero_user_data"
OMERO_IMPORT_PATH="${OMERO_TMP_PATH%/}/omeroweb-import"
OMERO_SERVER_VAR_PATH="${OMERO_DATA_PATH%/}/omero_server_var"
OMERO_WEB_VAR_PATH="${OMERO_DATA_PATH%/}/omero_web_var"
OMERO_SERVER_LOGS_PATH="${OMERO_DATA_PATH%/}/omero_server_logs"
OMERO_WEB_LOGS_PATH="${OMERO_DATA_PATH%/}/omero_web_logs"
OMERO_WEB_SUPERVISOR_LOGS_PATH="${OMERO_DATA_PATH%/}/omero_web_supervisor_logs"
PROMETHEUS_DATA_PATH="${OMERO_DATA_PATH%/}/prometheus_data"
GRAFANA_DATA_PATH="${OMERO_DATA_PATH%/}/grafana_data"
PORTAINER_DATA_PATH="${OMERO_DATA_PATH%/}/portainer_data"
LOKI_DATA_PATH="${OMERO_DATA_PATH%/}/loki_data"
ALLOY_DATA_PATH="${OMERO_DATA_PATH%/}/alloy_data"
PG_MAINTENANCE_DATA_PATH="${OMERO_DATA_PATH%/}/pg_maintenance_data"
NODE_EXPORTER_TEXTFILE_PATH="${OMERO_DATA_PATH%/}/node_exporter_textfile"
CROWDSEC_DB_PATH="${OMERO_DATA_PATH%/}/crowdsec_db"
CROWDSEC_CONFIG_PATH="${OMERO_DATA_PATH%/}/crowdsec_config"

# Ensure BUILDX_DATA_PATH has a fallback default if not provided by env file
# (This handles cases where the env file is from an older installation)
if [ -z "${BUILDX_DATA_PATH:-}" ]; then
    BUILDX_DATA_PATH="${OMERO_DATA_PATH%/}/buildx_cache"
fi

if declare -F install_transcript_publish_final_path_if_needed >/dev/null 2>&1; then
    install_transcript_publish_final_path_if_needed \
        "${OMERO_INSTALL_TRANSCRIPT_SOURCE_NAME:-${SCRIPT_NAME}}" \
        "${SCRIPT_ENV_FILE}" \
        "${OMERO_DATA_PATH}"
fi

if ! export_compose_interpolation_env; then
    exit 1
fi

if ! validate_retry_config; then
    exit 1
fi

if ! validate_crowdsec_install_auto_restart_config; then
    exit 1
fi

if [ -n "${OMERO_SERVER_UID}" ]; then
    if ! validate_numeric_id "OMERO_SERVER_UID" "${OMERO_SERVER_UID}"; then exit 1; fi
fi
if [ -n "${OMERO_SERVER_GID}" ]; then
    if ! validate_numeric_id "OMERO_SERVER_GID" "${OMERO_SERVER_GID}"; then exit 1; fi
fi
if [ -n "${OMERO_WEB_UID}" ]; then
    if ! validate_numeric_id "OMERO_WEB_UID" "${OMERO_WEB_UID}"; then exit 1; fi
fi
if [ -n "${OMERO_WEB_GID}" ]; then
    if ! validate_numeric_id "OMERO_WEB_GID" "${OMERO_WEB_GID}"; then exit 1; fi
fi
if [ -n "${PROMETHEUS_UID}" ]; then
    if ! validate_numeric_id "PROMETHEUS_UID" "${PROMETHEUS_UID}"; then exit 1; fi
fi
if [ -n "${PROMETHEUS_GID}" ]; then
    if ! validate_numeric_id "PROMETHEUS_GID" "${PROMETHEUS_GID}"; then exit 1; fi
fi
if [ -n "${GRAFANA_UID}" ]; then
    if ! validate_numeric_id "GRAFANA_UID" "${GRAFANA_UID}"; then exit 1; fi
fi
if [ -n "${GRAFANA_GID}" ]; then
    if ! validate_numeric_id "GRAFANA_GID" "${GRAFANA_GID}"; then exit 1; fi
fi
if [ -n "${LOKI_UID}" ]; then
    if ! validate_numeric_id "LOKI_UID" "${LOKI_UID}"; then exit 1; fi
fi
if [ -n "${LOKI_GID}" ]; then
    if ! validate_numeric_id "LOKI_GID" "${LOKI_GID}"; then exit 1; fi
fi
if [ -n "${ALLOY_UID}" ]; then
    if ! validate_numeric_id "ALLOY_UID" "${ALLOY_UID}"; then exit 1; fi
fi
if [ -n "${ALLOY_GID}" ]; then
    if ! validate_numeric_id "ALLOY_GID" "${ALLOY_GID}"; then exit 1; fi
fi
if is_crowdsec_enabled; then
    if [ -n "${CROWDSEC_UID}" ]; then
        if ! validate_numeric_id "CROWDSEC_UID" "${CROWDSEC_UID}"; then exit 1; fi
    fi
    if [ -n "${CROWDSEC_GID}" ]; then
        if ! validate_numeric_id "CROWDSEC_GID" "${CROWDSEC_GID}"; then exit 1; fi
    fi
fi

require_path_config_var "OMERO_INSTALLATION_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_DATABASE_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_PLUGIN_DATABASE_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_DATA_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_TMP_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_DATA_DIR" "${SCRIPT_ENV_FILE}"
require_nonempty_config_var "OMERO_DB_PASS" "${SECRETS_ENV_FILE}"
require_nonempty_config_var "OMP_PLUGIN_DB_PASS" "${SECRETS_ENV_FILE}"
require_nonempty_config_var "OMERO_WEB_HOST_PORT" "${OMERO_WEB_ENV_FILE}"
require_nonempty_config_var "CONFIG_omero_web_application__server_port" "${OMERO_WEB_ENV_FILE}"
require_nonempty_config_var "OMERO_SERVER_HOST_PORT" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_CLI_HOST" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_CLI_PORT" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_SERVER_HEALTHCHECK_RETRIES" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_JOB_SERVICE_HOST" "${OMERO_SERVER_ENV_FILE}"
require_nonempty_config_var "OMERO_JOB_SERVICE_PORT" "${OMERO_SERVER_ENV_FILE}"

if ! validate_tcp_port_config "OMERO_WEB_HOST_PORT" "${OMERO_WEB_HOST_PORT}"; then
    exit 1
fi

if ! validate_tcp_port_config "CONFIG_omero_web_application__server_port" "${CONFIG_omero_web_application__server_port}"; then
    exit 1
fi

if ! validate_tcp_port_config "OMERO_SERVER_HOST_PORT" "${OMERO_SERVER_HOST_PORT}"; then
    exit 1
fi

if ! validate_tcp_port_config "OMERO_CLI_PORT" "${OMERO_CLI_PORT}"; then
    exit 1
fi

if ! validate_tcp_port_config "OMERO_JOB_SERVICE_PORT" "${OMERO_JOB_SERVICE_PORT}"; then
    exit 1
fi

for healthcheck_config_name in \
    OMERO_SERVER_HEALTHCHECK_INTERVAL_SECONDS \
    OMERO_SERVER_HEALTHCHECK_TIMEOUT_SECONDS \
    OMERO_SERVER_HEALTHCHECK_RETRIES \
    OMERO_SERVER_HEALTHCHECK_START_PERIOD_SECONDS
do
    if ! is_positive_integer "${!healthcheck_config_name}"; then
        echo "ERROR: ${healthcheck_config_name} must be an integer >= 1. Got: ${!healthcheck_config_name}" >&2
        exit 1
    fi
done

if ! validate_installation_path "${OMERO_INSTALLATION_PATH}"; then
    echo "ERROR: Invalid OMERO_INSTALLATION_PATH from ${SCRIPT_ENV_FILE}: ${OMERO_INSTALLATION_PATH}" >&2
    exit 1
fi

if ! validate_installation_path "${OMERO_DATABASE_PATH}"; then
    echo "ERROR: Invalid OMERO_DATABASE_PATH from ${SCRIPT_ENV_FILE}: ${OMERO_DATABASE_PATH}" >&2
    exit 1
fi

if ! validate_installation_path "${OMERO_PLUGIN_DATABASE_PATH}"; then
    echo "ERROR: Invalid OMERO_PLUGIN_DATABASE_PATH from ${SCRIPT_ENV_FILE}: ${OMERO_PLUGIN_DATABASE_PATH}" >&2
    exit 1
fi

if ! validate_installation_path "${OMERO_DATA_PATH}"; then
    echo "ERROR: Invalid OMERO_DATA_PATH from ${SCRIPT_ENV_FILE}: ${OMERO_DATA_PATH}" >&2
    exit 1
fi

if ! validate_installation_path "${OMERO_TMP_PATH}"; then
    echo "ERROR: Invalid OMERO_TMP_PATH from ${SCRIPT_ENV_FILE}: ${OMERO_TMP_PATH}" >&2
    exit 1
fi

echo "Using installation paths from ${SCRIPT_ENV_FILE}"
echo "Using docker compose .env file: ${OMERO_INSTALLATION_PATH%/}/.env"
echo "OMERO_INSTALLATION_PATH=${OMERO_INSTALLATION_PATH}"
echo "OMERO_DATABASE_PATH=${OMERO_DATABASE_PATH}"
echo "OMERO_PLUGIN_DATABASE_PATH=${OMERO_PLUGIN_DATABASE_PATH}"
echo "OMERO_DATA_PATH=${OMERO_DATA_PATH}"
echo "OMERO_TMP_PATH=${OMERO_TMP_PATH}"
echo "OMERO_DATA_DIR=${OMERO_DATA_DIR}"

if ! ensure_installation_path "${OMERO_INSTALLATION_PATH}"; then
    echo "ERROR: Unable to prepare OMERO installation path: ${OMERO_INSTALLATION_PATH}" >&2
    exit 1
fi

warn_directory_not_empty "${OMERO_DATABASE_PATH}" "OMERO database directory"
warn_directory_not_empty "${OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database directory"
warn_directory_not_empty "${OMERO_DATA_PATH}" "OMERO data directory"
warn_directory_not_empty "${OMERO_TMP_PATH}" "OMERO temp directory"

if ! ensure_data_path "${OMERO_DATABASE_PATH}" "OMERO database directory"; then exit 1; fi
if ! ensure_data_path "${OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database directory"; then exit 1; fi
if ! ensure_data_path "${OMERO_DATA_PATH}" "OMERO data directory"; then exit 1; fi
if ! ensure_data_path "${OMERO_TMP_PATH}" "OMERO temp directory"; then exit 1; fi
if ! ensure_container_writable_path "${OMERO_USER_DATA_PATH}" "OMERO user data directory"; then exit 1; fi
if ! ensure_container_writable_path "${OMERO_USER_DATA_PATH%/}/certs" "OMERO certificate directory"; then exit 1; fi
if ! ensure_container_writable_path "${PORTAINER_DATA_PATH}" "Portainer data directory"; then exit 1; fi
if ! ensure_container_writable_path "${LOKI_DATA_PATH}" "Loki data directory"; then exit 1; fi
if ! ensure_container_writable_path "${ALLOY_DATA_PATH}" "Alloy data directory"; then exit 1; fi
if ! ensure_data_path "${PG_MAINTENANCE_DATA_PATH}" "PG maintenance data directory"; then exit 1; fi
if ! ensure_container_writable_path "${NODE_EXPORTER_TEXTFILE_PATH}" "Node exporter textfile directory"; then exit 1; fi
if is_crowdsec_enabled; then
    if ! ensure_data_path "${CROWDSEC_DB_PATH}" "Crowdsec database directory"; then exit 1; fi
    if ! ensure_data_path "${CROWDSEC_CONFIG_PATH}" "Crowdsec config directory"; then exit 1; fi
fi

OMERO_COMPOSE_PROJECT_NAME="$(derive_compose_project_name "${OMERO_INSTALLATION_PATH}")"

write_installation_paths_env "${SCRIPT_ENV_FILE}"
if ! verify_installation_paths_env_content "${SCRIPT_ENV_FILE}"; then
    echo "ERROR: Refusing to continue because installation paths were not persisted correctly to ${SCRIPT_ENV_FILE}." >&2
    exit 1
fi

write_compose_dot_env "${OMERO_INSTALLATION_PATH%/}/.env"
if ! run_runtime_env_contract_check "${OMERO_INSTALLATION_PATH%/}"; then
    exit 1
fi

# Workflow
# --------
cd "${OMERO_INSTALLATION_PATH}"

if [ "${DEFAULT_OMERO_INSTALLATION_PATH%/}" != "${OMERO_INSTALLATION_PATH%/}" ]; then
    stop_old_installation_containers \
        "${DEFAULT_OMERO_INSTALLATION_PATH}" \
        "${DEFAULT_OMERO_DATABASE_PATH}" \
        "${DEFAULT_OMERO_PLUGIN_DATABASE_PATH}" \
        "${DEFAULT_OMERO_DATA_PATH}" \
        "${DEFAULT_OMERO_DATA_DIR}" \
        "${KEEP_IMAGES}"
fi

echo "Recording pre-stop data path snapshots..."
log_path_snapshot "${OMERO_DATABASE_PATH}" "OMERO database directory (before docker compose down)"
log_path_snapshot "${OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database directory (before docker compose down)"
log_path_snapshot "${OMERO_DATA_PATH}" "OMERO data directory (before docker compose down)"
log_path_snapshot "${OMERO_TMP_PATH}" "OMERO temp directory (before docker compose down)"

echo "Stopping existing containers..."
if [ "${KEEP_IMAGES}" -eq 1 ]; then
    compose_with_installation_env "${COMPOSE_FILE}" down --remove-orphans || true
else
    compose_with_installation_env "${COMPOSE_FILE}" down --remove-orphans --rmi all || true
    echo "Removing ALL images referenced by docker-compose.yml..."
    COMPOSE_IMAGES="$(compose_images_with_installation_env "${COMPOSE_FILE}")"
    if [ -n "${COMPOSE_IMAGES}" ]; then
        missing_compose_images=0
        removed_compose_images=0
        while IFS= read -r compose_image; do
            [ -z "${compose_image}" ] && continue
            if docker image inspect "${compose_image}" >/dev/null 2>&1; then
                docker rmi -f "${compose_image}" || true
                removed_compose_images=$((removed_compose_images + 1))
            else
                missing_compose_images=$((missing_compose_images + 1))
            fi
        done <<< "${COMPOSE_IMAGES}"

        if [ "${missing_compose_images}" -gt 0 ]; then
            echo "Skipped ${missing_compose_images} compose image reference(s) that were not present locally."
        fi
        echo "Attempted removal for ${removed_compose_images} compose image(s) present locally."
    fi
fi

echo "Recording post-stop data path snapshots..."
log_path_snapshot "${OMERO_DATABASE_PATH}" "OMERO database directory (after docker compose down)"
log_path_snapshot "${OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database directory (after docker compose down)"
log_path_snapshot "${OMERO_DATA_PATH}" "OMERO data directory (after docker compose down)"
log_path_snapshot "${OMERO_TMP_PATH}" "OMERO temp directory (after docker compose down)"

echo "Removing stale OMERO repository lock files from OMERO user data path..."
if [ -d "${OMERO_USER_DATA_PATH}" ]; then
    find "${OMERO_USER_DATA_PATH}" -name "*.lock" -delete || true
else
    echo "WARNING: OMERO user data path ${OMERO_USER_DATA_PATH} not found; skipping lock cleanup."
fi

if ! cleanup_local_build_cache_if_disabled; then
    exit 1
fi

# ---------------------------------------------------------------------------
# Docker Scout vulnerability scanning
#
# Two-phase approach:
#   Phase 1 (pre-build):  When cache is disabled, pull and scan upstream base
#                         images referenced in docker/*.Dockerfile to establish
#                         a vulnerability baseline.  Tracks which images were
#                         pulled so they can be cleaned up after the report.
#   Phase 2 (post-build): Scan ALL images referenced in docker-compose.yml —
#                         both custom-built and third-party.  Shows a compact
#                         table with Before/After columns when baseline data
#                         is available, or a single Vulnerabilities column
#                         when it is not (cache was enabled).
#
# Docker Scout availability is checked once; if absent both phases are skipped
# with an informational message — scanning never blocks the installation.
# ---------------------------------------------------------------------------

# Temporary directory for baseline scan results.  Cleaned up after the report.
_SCOUT_BASELINE_DIR=""
# Images pulled solely for baseline scanning (removed after report).
declare -a _SCOUT_PULLED_FOR_BASELINE=()

_scout_is_available() {
    command -v docker >/dev/null 2>&1 || return 1

    # After buildx workflows the active builder may be a docker-container
    # driver that doesn't expose the Scout plugin.  Restore the default
    # builder so the CLI can reach the Scout plugin reliably.
    docker buildx use default >/dev/null 2>&1 || true

    # Fast path: Scout is on the default plugin search path.
    if docker scout version >/dev/null 2>&1; then
        return 0
    fi

    # When the script runs as root (e.g. via sudo), HOME is /root and Docker
    # cannot find a per-user Scout installation under the invoking user's
    # ~/.docker/cli-plugins/.  Discover the real user's DOCKER_CONFIG and
    # export it so all subsequent docker scout calls find the plugin.
    local probe_home=""
    if [ -n "${SUDO_USER:-}" ]; then
        probe_home="$(getent passwd "${SUDO_USER}" 2>/dev/null | cut -d: -f6)" || true
    fi
    if [ -z "${probe_home}" ] || [ ! -d "${probe_home}/.docker/cli-plugins" ]; then
        local candidate=""
        for candidate in /home/*/.docker/cli-plugins/docker-scout; do
            if [ -x "${candidate}" ]; then
                probe_home="${candidate%/.docker/cli-plugins/docker-scout}"
                break
            fi
        done
    fi
    if [ -n "${probe_home}" ] && [ -x "${probe_home}/.docker/cli-plugins/docker-scout" ]; then
        export DOCKER_CONFIG="${probe_home}/.docker"
        if docker scout version >/dev/null 2>&1; then
            return 0
        fi
        unset DOCKER_CONFIG
    fi

    return 1
}

# _scout_extract_summary <raw_output>
# Parses Docker Scout CVE output into a compact one-line format:
#   "73 (9C 58H 63M 51L)"
# Returns non-zero if parsing fails.
_scout_extract_summary() {
    local raw="${1:-}"
    if [ -z "${raw}" ]; then return 1; fi

    local total="" crit="" high="" med="" low=""
    total="$(printf '%s\n' "${raw}" | grep -oE '[0-9]+ vulnerabilities found' | tail -1 | grep -oE '[0-9]+' | head -1 || true)"
    if [ -z "${total}" ]; then
        total="$(printf '%s\n' "${raw}" | grep -oE '[0-9]+ vulnerabilit' | tail -1 | grep -oE '[0-9]+' | head -1 || true)"
    fi
    if [ -z "${total}" ]; then return 1; fi

    crit="$(printf '%s\n' "${raw}" | grep -iE '^\s*CRITICAL\s' | grep -oE '[0-9]+' | head -1 || true)"
    high="$(printf '%s\n' "${raw}" | grep -iE '^\s*HIGH\s' | grep -oE '[0-9]+' | head -1 || true)"
    med="$(printf '%s\n' "${raw}" | grep -iE '^\s*MEDIUM\s' | grep -oE '[0-9]+' | head -1 || true)"
    low="$(printf '%s\n' "${raw}" | grep -iE '^\s*LOW\s' | grep -oE '[0-9]+' | head -1 || true)"

    printf '%s (%sC %sH %sM %sL)' "${total}" "${crit:-0}" "${high:-0}" "${med:-0}" "${low:-0}"
    return 0
}

# _scout_extract_base_image <dockerfile_path>
# Reads the first FROM instruction and prints the image reference.
_scout_extract_base_image() {
    local dockerfile="${1:-}"
    [ -f "${dockerfile}" ] || return 1
    grep -m 1 '^FROM ' "${dockerfile}" | awk '{print $2}'
}

# _scout_scan_image <image_ref> [timeout_seconds]
# Runs `docker scout cves` and prints raw output.  Returns 1 on failure/timeout.
_scout_scan_image() {
    local image="${1:-}" scan_timeout="${2:-600}" output=""
    [ -n "${image}" ] || return 1
    output="$(timeout "${scan_timeout}" docker scout cves "local://${image}" 2>&1)" || true
    [ -n "${output}" ] || return 1
    printf '%s' "${output}"
    return 0
}

# ---------------------------------------------------------------------------
# Phase 1: Pre-build baseline scan
#
# When cache is disabled (USE_CACHE_BUILD=0), pulls upstream base images
# referenced in docker/*.Dockerfile and scans them.  Results are saved to
# $_SCOUT_BASELINE_DIR for the post-build report.  Images that were NOT
# already local before pulling are tracked in _SCOUT_PULLED_FOR_BASELINE
# and removed after the report to avoid stale images.
# ---------------------------------------------------------------------------
run_docker_scout_baseline_scan() {
    # Only scan baselines when cache is disabled (fresh pulls).
    if [ "${USE_CACHE_BUILD}" != "0" ]; then return 0; fi
    if ! _scout_is_available; then return 0; fi

    _SCOUT_BASELINE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/scout-baseline.XXXXXX")" || return 0

    local dockerfile="" base_image="" tag="" raw="" summary=""
    local -a base_images_seen=()

    echo ""
    echo "Scanning upstream base images for vulnerability baseline..."

    for dockerfile in "${REPO_ROOT_DIR}"/docker/*.Dockerfile; do
        [ -f "${dockerfile}" ] || continue
        base_image="$(_scout_extract_base_image "${dockerfile}")" || continue
        [ -n "${base_image}" ] || continue

        # Deduplicate (multiple Dockerfiles may share the same base).
        local already_seen="false" seen=""
        for seen in "${base_images_seen[@]+"${base_images_seen[@]}"}"; do
            if [ "${seen}" = "${base_image}" ]; then already_seen="true"; break; fi
        done
        [ "${already_seen}" = "false" ] || continue
        base_images_seen+=("${base_image}")

        # Track whether the image was already local before pulling.
        local was_local="false"
        if docker image inspect "${base_image}" >/dev/null 2>&1; then
            was_local="true"
        fi

        echo "  Pulling ${base_image} ..."
        if ! docker pull "${base_image}" >/dev/null 2>&1; then
            echo "  WARNING: Failed to pull ${base_image}; skipping baseline."
            continue
        fi

        # If it was NOT local before, mark for cleanup after report.
        if [ "${was_local}" = "false" ]; then
            _SCOUT_PULLED_FOR_BASELINE+=("${base_image}")
        fi

        echo "  Scanning ${base_image} ..."
        raw="$(_scout_scan_image "${base_image}")" || true
        if [ -n "${raw}" ]; then
            summary="$(_scout_extract_summary "${raw}")" || true
            if [ -n "${summary}" ]; then
                tag="$(printf '%s' "${base_image}" | tr '/:' '__')"
                printf '%s' "${summary}" > "${_SCOUT_BASELINE_DIR}/${tag}.summary"
            fi
        fi
    done

    echo "Baseline scan complete."
    echo ""
}

# Phase 1: Pull and scan upstream base images for baseline (only when cache disabled).
if [ "${ENABLE_VULNERABILITY_SCAN}" = "1" ]; then
    run_docker_scout_baseline_scan
fi

if ! run_image_build; then
    exit 1
fi

# ---------------------------------------------------------------------------
# Phase 2: Post-build vulnerability summary
#
# Discovers ALL images from docker-compose.yml:
#   - Custom-built images (those with a build: + dockerfile: block) are
#     matched to their Dockerfile's FROM base image for baseline lookup.
#   - Third-party images (no build: block) are scanned as-is; their
#     Before column shows "(not modified)" when baseline is available.
#
# Output is a compact table with one line per image.
# ---------------------------------------------------------------------------
run_docker_scout_summary() {
    echo ""
    echo "============================================================"
    echo "  Docker Scout — Vulnerability Report"
    echo "============================================================"

    if ! _scout_is_available; then
        echo "  Docker Scout is not installed or not accessible."
        echo "  Install the Docker Scout CLI plugin to enable"
        echo "  post-build vulnerability reports."
        echo "============================================================"
        echo ""
        return 0
    fi

    # --- Discover built images from docker-compose.yml ---
    # We parse the compose file for services that have both image: and
    # build:/dockerfile: directives.  These are the custom-built images.
    local -a built_images=() built_bases=()
    local -a thirdparty_images=()
    local dockerfile="" base_image="" built_tag=""

    # Map each Dockerfile referenced in docker-compose.yml to its image tag.
    local compose_config=""
    compose_config="$(compose_with_installation_env "${COMPOSE_FILE}" config 2>/dev/null || true)"

    if [ -n "${compose_config}" ]; then
        # Extract image tags for services that have a dockerfile: directive.
        # These are custom-built images.
        local -a compose_dockerfiles=()
        local -a compose_image_tags=()

        # Parse pairs: in `docker compose config` output, for built services
        # the dockerfile: line always appears before image:.  We reset state
        # on each dockerfile: to avoid mispairing with a prior third-party image.
        local current_image="" current_dockerfile="" line=""
        while IFS= read -r line; do
            case "${line}" in
                *dockerfile:*)
                    # New build service — reset any stale image from prior service.
                    current_image=""
                    current_dockerfile="$(printf '%s' "${line}" | sed 's/.*dockerfile:\s*//' | tr -d '"' | tr -d "'")"
                    ;;
                *image:*)
                    current_image="$(printf '%s' "${line}" | sed 's/.*image:\s*//' | tr -d '"' | tr -d "'")"
                    ;;
            esac
            # When we have both, record the pair and reset.
            if [ -n "${current_image}" ] && [ -n "${current_dockerfile}" ]; then
                compose_dockerfiles+=("${current_dockerfile}")
                compose_image_tags+=("${current_image}")
                current_image=""
                current_dockerfile=""
            fi
        done <<< "${compose_config}"

        # Build the built_images and built_bases arrays from discovered pairs.
        local idx=""
        for idx in "${!compose_dockerfiles[@]}"; do
            local df_path="${REPO_ROOT_DIR}/${compose_dockerfiles[$idx]}"
            built_tag="${compose_image_tags[$idx]}"
            base_image=""
            if [ -f "${df_path}" ]; then
                base_image="$(_scout_extract_base_image "${df_path}")" || true
            fi
            built_images+=("${built_tag}")
            built_bases+=("${base_image:-}")
        done

        # Third-party images: all image: entries NOT in the built list.
        local all_compose_images=""
        all_compose_images="$(printf '%s\n' "${compose_config}" | grep -E '^\s+image:' | sed 's/.*image:\s*//' | tr -d '"' | tr -d "'" | sort -u || true)"
        local ci="" is_built="" bi=""
        for ci in ${all_compose_images}; do
            is_built="false"
            for bi in "${built_images[@]+"${built_images[@]}"}"; do
                if [ "${bi}" = "${ci}" ]; then is_built="true"; break; fi
            done
            [ "${is_built}" = "false" ] || continue
            thirdparty_images+=("${ci}")
        done
    fi

    # --- Determine if baseline data is available ---
    local has_baseline="false"
    if [ -n "${_SCOUT_BASELINE_DIR}" ] && [ -d "${_SCOUT_BASELINE_DIR}" ]; then
        local any_file=""
        any_file="$(find "${_SCOUT_BASELINE_DIR}" -name '*.summary' -print -quit 2>/dev/null || true)"
        [ -z "${any_file}" ] || has_baseline="true"
    fi

    # --- Pull third-party images before printing the table ---
    # Third-party images may not be local yet (they are pulled during
    # docker compose up, which runs after this report).  Pull them now
    # so the table output is not interleaved with pull progress lines.
    local -a _scout_thirdparty_failed=()
    for image in "${thirdparty_images[@]+"${thirdparty_images[@]}"}"; do
        if ! docker image inspect "${image}" >/dev/null 2>&1; then
            echo "  Pulling ${image} for scanning..."
            if ! docker pull "${image}" >/dev/null 2>&1; then
                _scout_thirdparty_failed+=("${image}")
            fi
        fi
    done

    # --- Print table header ---
    echo ""
    if [ "${has_baseline}" = "true" ]; then
        printf '  %-48s %-24s %s\n' "Image" "Before (upstream)" "After (built)"
        printf '  %-48s %-24s %s\n' "------------------------------------------------" "------------------------" "------------------------"
    else
        printf '  %-48s %s\n' "Image" "Vulnerabilities"
        printf '  %-48s %s\n' "------------------------------------------------" "------------------------"
    fi

    # --- Scan custom-built images ---
    local i="" image="" base="" tag="" baseline_file="" baseline_summary="" raw="" summary=""
    for i in "${!built_images[@]}"; do
        image="${built_images[$i]}"
        base="${built_bases[$i]:-}"

        if ! docker image inspect "${image}" >/dev/null 2>&1; then
            if [ "${has_baseline}" = "true" ]; then
                printf '  %-48s %-24s %s\n' "${image}" "-" "(not found)"
            else
                printf '  %-48s %s\n' "${image}" "(not found)"
            fi
            continue
        fi

        # Look up baseline summary for this image's base.
        baseline_summary="-"
        if [ -n "${base}" ] && [ -n "${_SCOUT_BASELINE_DIR}" ]; then
            tag="$(printf '%s' "${base}" | tr '/:' '__')"
            baseline_file="${_SCOUT_BASELINE_DIR}/${tag}.summary"
            if [ -f "${baseline_file}" ]; then
                baseline_summary="$(cat "${baseline_file}")"
            fi
        fi

        raw="$(_scout_scan_image "${image}")" || true
        summary="$(_scout_extract_summary "${raw}")" || true
        [ -n "${summary}" ] || summary="(scan failed)"

        if [ "${has_baseline}" = "true" ]; then
            printf '  %-48s %-24s %s\n' "${image}" "${baseline_summary}" "${summary}"
        else
            printf '  %-48s %s\n' "${image}" "${summary}"
        fi
    done

    # --- Scan third-party images ---
    for image in "${thirdparty_images[@]+"${thirdparty_images[@]}"}"; do
        # Skip images that failed to pull earlier.
        local pull_failed="false" pf=""
        for pf in "${_scout_thirdparty_failed[@]+"${_scout_thirdparty_failed[@]}"}"; do
            if [ "${pf}" = "${image}" ]; then pull_failed="true"; break; fi
        done
        if [ "${pull_failed}" = "true" ]; then
            if [ "${has_baseline}" = "true" ]; then
                printf '  %-48s %-24s %s\n' "${image}" "-" "(pull failed)"
            else
                printf '  %-48s %s\n' "${image}" "(pull failed)"
            fi
            continue
        fi
        if ! docker image inspect "${image}" >/dev/null 2>&1; then
            continue
        fi
        raw="$(_scout_scan_image "${image}")" || true
        summary="$(_scout_extract_summary "${raw}")" || true
        [ -n "${summary}" ] || summary="(scan failed)"

        if [ "${has_baseline}" = "true" ]; then
            printf '  %-48s %-24s %s\n' "${image}" "(not modified)" "${summary}"
        else
            printf '  %-48s %s\n' "${image}" "${summary}"
        fi
    done

    # --- Footer ---
    echo ""
    echo "  ----------------------------------------"
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then
        echo "  Security hardening: ENABLED"
        echo "  Built images include OS-level and Python package security updates."
    else
        echo "  Security hardening: DISABLED"
        echo "  Interactive installs default this option to enabled; re-run with hardening enabled to reduce vulnerabilities."
    fi
    if [ "${has_baseline}" != "true" ]; then
        echo "  Baseline: not available (build cache was enabled)."
        echo "  Disable build cache for a before/after comparison."
    fi
    echo "============================================================"
    echo ""

    # --- Cleanup ---
    # Remove baseline temp directory.
    if [ -n "${_SCOUT_BASELINE_DIR}" ] && [ -d "${_SCOUT_BASELINE_DIR}" ]; then
        rm -rf "${_SCOUT_BASELINE_DIR}" 2>/dev/null || true
        _SCOUT_BASELINE_DIR=""
    fi
    # Remove base images that were pulled solely for baseline scanning,
    # but ONLY if they are not also used as runtime images in docker-compose.yml.
    local pulled_img="" is_runtime=""
    for pulled_img in "${_SCOUT_PULLED_FOR_BASELINE[@]+"${_SCOUT_PULLED_FOR_BASELINE[@]}"}"; do
        is_runtime="false"
        for ci in "${thirdparty_images[@]+"${thirdparty_images[@]}"}"; do
            if [ "${ci}" = "${pulled_img}" ]; then is_runtime="true"; break; fi
        done
        if [ "${is_runtime}" = "true" ]; then
            echo "  Keeping baseline image (used at runtime): ${pulled_img}"
        else
            echo "  Cleaning up baseline-only image: ${pulled_img}"
            docker rmi "${pulled_img}" >/dev/null 2>&1 || true
        fi
    done
    _SCOUT_PULLED_FOR_BASELINE=()
    # Third-party images pulled for scanning are NOT cleaned up here —
    # they will be used by docker compose up when containers start.
}

if [ "${ENABLE_VULNERABILITY_SCAN}" = "1" ]; then
    run_docker_scout_summary
fi

echo ""
echo "============================================"
echo "Discovering actual UID/GID from built images"
echo "============================================"
echo ""

discover_first_existing_user_or_die() {
    local image="$1"
    shift

    local candidate=""
    local found=""

    for candidate in "$@"; do
        [ -z "${candidate}" ] && continue
        if docker run --rm --name "omero-install-probe-user-$RANDOM" --entrypoint "" "${image}" sh -c "getent passwd '${candidate}' >/dev/null 2>&1" || true; then
            # We must verify if it successfully found it, wait, the previous line ignores exit codes via || true if not careful.
            # Actually, `docker run ... || true` will always succeed. Let's fix this.
            if docker run --rm --name "omero-install-probe-user-$RANDOM" --entrypoint "" "${image}" sh -c "getent passwd '${candidate}' >/dev/null 2>&1"; then
                found="${candidate}"
                break
            fi
        fi
        docker rm -fv "omero-install-probe-user-*" >/dev/null 2>&1 || true
    done

    if [ -z "${found}" ]; then
        echo "ERROR: Could not find any expected user inside image '${image}'." >&2
        echo "Tried candidates: $*" >&2
        echo "" >&2
        echo "DEBUG: Listing passwd entries containing 'omero' from image '${image}':" >&2
        local probe_name="omero-install-probe-users-$RANDOM"
        docker run --rm --name "${probe_name}" --entrypoint "" "${image}" sh -c "getent passwd | grep -i omero || true" >&2 || true
        docker rm -fv "${probe_name}" >/dev/null 2>&1 || true
        echo "" >&2
        return 1
    fi

    printf '%s' "${found}"
    return 0
}

discover_uid_gid_or_die() {
    local image="$1"
    local user_name="$2"
    local id_flag="$3"
    local probe_name="omero-install-probe-id-$RANDOM"

    local out=""

    if ! out="$(docker run --rm --name "${probe_name}" --entrypoint "" "${image}" sh -c "id ${id_flag} '${user_name}'" 2>/dev/null)"; then
        docker rm -fv "${probe_name}" >/dev/null 2>&1 || true
        echo "ERROR: Failed to discover id ${id_flag} for user '${user_name}' from image '${image}'." >&2
        local pass_probe="omero-install-probe-passwd-$RANDOM"
        docker run --rm --name "${pass_probe}" --entrypoint "" "${image}" sh -c "getent passwd '${user_name}' || true" >&2 || true
        docker rm -fv "${pass_probe}" >/dev/null 2>&1 || true
        return 1
    fi
    docker rm -fv "${probe_name}" >/dev/null 2>&1 || true

    if ! is_non_negative_integer "${out}"; then
        echo "ERROR: Discovered non-numeric id (${id_flag})='${out}' for user '${user_name}' in image '${image}'" >&2
        return 1
    fi

    printf '%s' "${out}"
    return 0
}


resolve_service_image_from_compose_or_die() {
    local compose_file="$1"
    local service_name="$2"

    if [ ! -f "${compose_file}" ]; then
        echo "ERROR: Cannot resolve image for service '${service_name}' because compose file is missing: ${compose_file}" >&2
        return 1
    fi

    local image=""
    image="$(awk -v svc="${service_name}" '
        BEGIN { in_services=0; in_service=0 }
        /^services:[[:space:]]*$/ { in_services=1; next }
        in_services && /^[^[:space:]]/ { in_services=0; in_service=0 }
        in_services && $0 ~ "^  " svc ":[[:space:]]*$" { in_service=1; next }
        in_service && /^  [a-zA-Z0-9_.-]+:[[:space:]]*$/ { in_service=0 }
        in_service && /^[[:space:]]{4}image:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]{4}image:[[:space:]]*/, "", line)
            gsub(/^"|"$/, "", line)
            gsub(/^\047|\047$/, "", line)
            print line
            exit
        }
    ' "${compose_file}")"

    if [ -z "${image}" ]; then
        echo "ERROR: Could not resolve image for service '${service_name}' from compose file: ${compose_file}" >&2
        return 1
    fi

    printf '%s' "${image}"
    return 0
}

discover_uid_gid_from_passwd_or_die() {
    local image="$1"
    local user_name="$2"
    local id_flag="$3"
    local container_name=""
    local passwd_file=""
    local uid=""
    local gid=""

    container_name="omero-install-probe-passwd-id-$RANDOM"
    if ! docker create --name "${container_name}" --entrypoint /bin/true "${image}" >/dev/null 2>&1; then
        if ! docker create --name "${container_name}" "${image}" >/dev/null 2>&1; then
            echo "ERROR: Failed to create probe container for image '${image}' while resolving passwd entry for user '${user_name}'." >&2
            return 1
        fi
    fi

    passwd_file="$(mktemp)"
    if ! docker cp "${container_name}:/etc/passwd" "${passwd_file}" >/dev/null 2>&1; then
        echo "ERROR: Unable to read /etc/passwd from image '${image}' while resolving user '${user_name}'." >&2
        docker rm -fv "${container_name}" >/dev/null 2>&1 || true
        rm -f "${passwd_file}" || true
        return 1
    fi

    uid="$(awk -F: -v user="${user_name}" '$1==user {print $3; exit}' "${passwd_file}")"
    gid="$(awk -F: -v user="${user_name}" '$1==user {print $4; exit}' "${passwd_file}")"

    docker rm -fv "${container_name}" >/dev/null 2>&1 || true
    rm -f "${passwd_file}" || true

    if [ "${id_flag}" = "-u" ]; then
        if ! is_non_negative_integer "${uid}"; then
            echo "ERROR: Failed to resolve numeric UID for user '${user_name}' from image '${image}' /etc/passwd." >&2
            return 1
        fi
        printf '%s' "${uid}"
        return 0
    fi

    if [ "${id_flag}" = "-g" ]; then
        if ! is_non_negative_integer "${gid}"; then
            echo "ERROR: Failed to resolve numeric GID for user '${user_name}' from image '${image}' /etc/passwd." >&2
            return 1
        fi
        printf '%s' "${gid}"
        return 0
    fi

    echo "ERROR: Unsupported id flag '${id_flag}' for image '${image}'." >&2
    return 1
}

discover_container_default_id_or_die() {
    local image="$1"
    local id_flag="$2"
    local fallback_user_name="${3:-}"
    local configured_user=""
    local configured_account=""
    local configured_group=""
    local container_name=""
    local passwd_file=""
    local group_file=""
    local resolved_uid=""
    local resolved_gid=""

    probe_effective_runtime_ids_from_proc() {
        local probe_image="$1"
        local probe_container=""
        local proc_status_file=""
        local proc_uid=""
        local proc_gid=""

        probe_container="omero-install-probe-runtime-id-$RANDOM"
        proc_status_file="$(mktemp)"

        if ! docker create --name "${probe_container}" "${probe_image}" >/dev/null 2>&1; then
            rm -f "${proc_status_file}" || true
            return 1
        fi

        if ! docker start "${probe_container}" >/dev/null 2>&1; then
            docker rm -fv "${probe_container}" >/dev/null 2>&1 || true
            rm -f "${proc_status_file}" || true
            return 1
        fi

        if ! docker cp "${probe_container}:/proc/1/status" "${proc_status_file}" >/dev/null 2>&1; then
            docker rm -fv "${probe_container}" >/dev/null 2>&1 || true
            rm -f "${proc_status_file}" || true
            return 1
        fi

        proc_uid="$(awk '/^Uid:/ {print $2; exit}' "${proc_status_file}")"
        proc_gid="$(awk '/^Gid:/ {print $2; exit}' "${proc_status_file}")"

        docker rm -fv "${probe_container}" >/dev/null 2>&1 || true
        rm -f "${proc_status_file}" || true

        if is_non_negative_integer "${proc_uid}" && is_non_negative_integer "${proc_gid}"; then
            printf '%s:%s' "${proc_uid}" "${proc_gid}"
            return 0
        fi

        return 1
    }

    if ! docker image inspect "${image}" >/dev/null 2>&1; then
        echo "INFO: Image '${image}' not found locally. Pulling to inspect configuration..." >&2
        if ! docker pull "${image}" >/dev/null; then
            echo "ERROR: Failed to pull image '${image}'" >&2
            return 1
        fi
    fi

    configured_user="$(docker image inspect --format '{{.Config.User}}' "${image}" 2>/dev/null || true)"
    configured_user="${configured_user// /}"

    # Some images intentionally leave Config.User empty and switch to a
    # non-root runtime UID/GID in the image entrypoint/binary defaults.
    # Probe the effective default process IDs first to avoid chowning
    # bind-mounted host data to root when the service actually runs unprivileged.
    if [ -z "${configured_user}" ]; then
        local runtime_uid=""
        local runtime_gid=""
        local runtime_id_pair=""

        runtime_uid="$(docker run --rm --entrypoint id "${image}" -u 2>/dev/null || true)"
        runtime_gid="$(docker run --rm --entrypoint id "${image}" -g 2>/dev/null || true)"

        if is_non_negative_integer "${runtime_uid}" && is_non_negative_integer "${runtime_gid}"; then
            if [ "${id_flag}" = "-u" ]; then
                printf '%s' "${runtime_uid}"
                return 0
            fi
            if [ "${id_flag}" = "-g" ]; then
                printf '%s' "${runtime_gid}"
                return 0
            fi
            echo "ERROR: Unsupported id flag '${id_flag}' for image '${image}'." >&2
            return 1
        fi

        runtime_id_pair="$(probe_effective_runtime_ids_from_proc "${image}" 2>/dev/null || true)"
        runtime_uid="${runtime_id_pair%%:*}"
        runtime_gid="${runtime_id_pair#*:}"

        if is_non_negative_integer "${runtime_uid}" && is_non_negative_integer "${runtime_gid}"; then
            if [ "${id_flag}" = "-u" ]; then
                printf '%s' "${runtime_uid}"
                return 0
            fi
            if [ "${id_flag}" = "-g" ]; then
                printf '%s' "${runtime_gid}"
                return 0
            fi
            echo "ERROR: Unsupported id flag '${id_flag}' for image '${image}'." >&2
            return 1
        fi
    fi

    if [ -z "${configured_user}" ]; then
        if [ -n "${fallback_user_name}" ]; then
            discover_uid_gid_from_passwd_or_die "${image}" "${fallback_user_name}" "${id_flag}"
            return $?
        fi

        echo "ERROR: Unable to determine default runtime ${id_flag} for image '${image}' with empty Config.User." >&2
        echo "ERROR: Set an explicit override (for example PROMETHEUS_UID/PROMETHEUS_GID) and rerun installation/installation_script.sh." >&2
        return 1
    fi

    configured_account="${configured_user%%:*}"
    if [ "${configured_user}" != "${configured_account}" ]; then
        configured_group="${configured_user#*:}"
    fi

    if is_non_negative_integer "${configured_account}"; then
        resolved_uid="${configured_account}"
    fi
    if [ -n "${configured_group}" ] && is_non_negative_integer "${configured_group}"; then
        resolved_gid="${configured_group}"
    fi

    if [ -n "${resolved_uid}" ] && { [ "${id_flag}" = "-u" ] || [ -n "${resolved_gid}" ]; }; then
        if [ "${id_flag}" = "-u" ]; then
            printf '%s' "${resolved_uid}"
            return 0
        fi
        printf '%s' "${resolved_gid}"
        return 0
    fi

    container_name="omero-install-probe-default-id-$RANDOM"
    if ! docker create --name "${container_name}" --entrypoint /bin/true "${image}" >/dev/null 2>&1; then
        if ! docker create --name "${container_name}" "${image}" >/dev/null 2>&1; then
            echo "ERROR: Failed to create probe container for image '${image}' while resolving ${id_flag}." >&2
            return 1
        fi
    fi

    passwd_file="$(mktemp)"
    group_file="$(mktemp)"

    if ! docker cp "${container_name}:/etc/passwd" "${passwd_file}" >/dev/null 2>&1; then
        echo "ERROR: Unable to read /etc/passwd from image '${image}' while resolving user '${configured_account}'." >&2
        docker rm -fv "${container_name}" >/dev/null 2>&1 || true
        rm -f "${passwd_file}" "${group_file}" || true
        return 1
    fi
    docker cp "${container_name}:/etc/group" "${group_file}" >/dev/null 2>&1 || true

    if [ -z "${resolved_uid}" ]; then
        resolved_uid="$(awk -F: -v user="${configured_account}" '$1==user {print $3; exit}' "${passwd_file}")"
    fi

    if [ -z "${resolved_gid}" ]; then
        if is_non_negative_integer "${configured_account}" && [ -z "${configured_group}" ]; then
            resolved_gid="$(awk -F: -v uid="${configured_account}" '$3==uid {print $4; exit}' "${passwd_file}")"
        fi

        if [ -n "${configured_group}" ]; then
            if is_non_negative_integer "${configured_group}"; then
                resolved_gid="${configured_group}"
            elif [ -s "${group_file}" ]; then
                resolved_gid="$(awk -F: -v grp="${configured_group}" '$1==grp {print $3; exit}' "${group_file}")"
            fi
        fi
        if [ -z "${resolved_gid}" ]; then
            resolved_gid="$(awk -F: -v user="${configured_account}" '$1==user {print $4; exit}' "${passwd_file}")"
        fi
    fi

    docker rm -fv "${container_name}" >/dev/null 2>&1 || true
    rm -f "${passwd_file}" "${group_file}" || true

    if [ "${id_flag}" = "-u" ]; then
        if ! is_non_negative_integer "${resolved_uid}"; then
            echo "ERROR: Failed to resolve numeric default runtime UID from image '${image}' (Config.User='${configured_user}')." >&2
            return 1
        fi
        printf '%s' "${resolved_uid}"
        return 0
    fi

    if [ "${id_flag}" = "-g" ]; then
        if ! is_non_negative_integer "${resolved_gid}"; then
            echo "ERROR: Failed to resolve numeric default runtime GID from image '${image}' (Config.User='${configured_user}')." >&2
            return 1
        fi
        printf '%s' "${resolved_gid}"
        return 0
    fi

    echo "ERROR: Unsupported id flag '${id_flag}' for image '${image}'." >&2
    return 1
}


SERVER_USER="$(discover_first_existing_user_or_die "${OMERO_SERVER_IMAGE}" "omero-server" "omero")"
WEB_USER="$(discover_first_existing_user_or_die "${OMERO_WEB_IMAGE}" "omero-web" "omero")"

echo "Detected OMERO.server image user: ${SERVER_USER}"
echo "Detected OMERO.web    image user: ${WEB_USER}"
echo ""

if [ -z "${OMERO_SERVER_UID}" ]; then OMERO_SERVER_UID="$(discover_uid_gid_or_die "${OMERO_SERVER_IMAGE}" "${SERVER_USER}" "-u")"; fi
if [ -z "${OMERO_SERVER_GID}" ]; then OMERO_SERVER_GID="$(discover_uid_gid_or_die "${OMERO_SERVER_IMAGE}" "${SERVER_USER}" "-g")"; fi
if [ -z "${OMERO_WEB_UID}" ]; then OMERO_WEB_UID="$(discover_uid_gid_or_die "${OMERO_WEB_IMAGE}" "${WEB_USER}" "-u")"; fi
if [ -z "${OMERO_WEB_GID}" ]; then OMERO_WEB_GID="$(discover_uid_gid_or_die "${OMERO_WEB_IMAGE}" "${WEB_USER}" "-g")"; fi

if [ -z "${PROMETHEUS_IMAGE}" ]; then PROMETHEUS_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "prometheus")"; fi
if [ -z "${GRAFANA_IMAGE}" ]; then GRAFANA_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "grafana")"; fi
if [ -z "${LOKI_IMAGE}" ]; then LOKI_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "loki")"; fi
if [ -z "${ALLOY_IMAGE}" ]; then ALLOY_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "alloy")"; fi
if [ -z "${DATABASE_IMAGE}" ]; then DATABASE_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "database")"; fi
if [ -z "${DATABASE_PLUGIN_IMAGE}" ]; then DATABASE_PLUGIN_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "database_plugin")"; fi

if [ -z "${PROMETHEUS_UID}" ]; then PROMETHEUS_UID="$(discover_container_default_id_or_die "${PROMETHEUS_IMAGE}" "-u")"; fi
if [ -z "${PROMETHEUS_GID}" ]; then PROMETHEUS_GID="$(discover_container_default_id_or_die "${PROMETHEUS_IMAGE}" "-g")"; fi
if [ -z "${GRAFANA_UID}" ]; then GRAFANA_UID="$(discover_container_default_id_or_die "${GRAFANA_IMAGE}" "-u")"; fi
if [ -z "${GRAFANA_GID}" ]; then GRAFANA_GID="$(discover_container_default_id_or_die "${GRAFANA_IMAGE}" "-g")"; fi
if [ -z "${LOKI_UID}" ]; then LOKI_UID="$(discover_container_default_id_or_die "${LOKI_IMAGE}" "-u" "loki")"; fi
if [ -z "${LOKI_GID}" ]; then LOKI_GID="$(discover_container_default_id_or_die "${LOKI_IMAGE}" "-g" "loki")"; fi
if [ -z "${ALLOY_UID}" ]; then ALLOY_UID="$(discover_container_default_id_or_die "${ALLOY_IMAGE}" "-u")"; fi
if [ -z "${ALLOY_GID}" ]; then ALLOY_GID="$(discover_container_default_id_or_die "${ALLOY_IMAGE}" "-g")"; fi
if [ -z "${DATABASE_UID}" ]; then DATABASE_UID="$(discover_container_default_id_or_die "${DATABASE_IMAGE}" "-u")"; fi
if [ -z "${DATABASE_GID}" ]; then DATABASE_GID="$(discover_container_default_id_or_die "${DATABASE_IMAGE}" "-g")"; fi
if [ -z "${DATABASE_PLUGIN_UID}" ]; then DATABASE_PLUGIN_UID="$(discover_container_default_id_or_die "${DATABASE_PLUGIN_IMAGE}" "-u")"; fi
if [ -z "${DATABASE_PLUGIN_GID}" ]; then DATABASE_PLUGIN_GID="$(discover_container_default_id_or_die "${DATABASE_PLUGIN_IMAGE}" "-g")"; fi
if [ -z "${PATH_USAGE_EXPORTER_UID}" ]; then PATH_USAGE_EXPORTER_UID="$(discover_container_default_id_or_die "${PATH_USAGE_EXPORTER_IMAGE}" "-u")"; fi
if [ -z "${PATH_USAGE_EXPORTER_GID}" ]; then PATH_USAGE_EXPORTER_GID="$(discover_container_default_id_or_die "${PATH_USAGE_EXPORTER_IMAGE}" "-g")"; fi
if is_crowdsec_enabled; then
    if [ -z "${CROWDSEC_UID}" ]; then CROWDSEC_UID="$(discover_container_default_id_or_die "${CROWDSEC_IMAGE}" "-u")"; fi
    if [ -z "${CROWDSEC_GID}" ]; then CROWDSEC_GID="$(discover_container_default_id_or_die "${CROWDSEC_IMAGE}" "-g")"; fi
else
    echo "CrowdSec is disabled (no enroll key). Skipping CrowdSec UID/GID discovery."
    CROWDSEC_UID=0
    CROWDSEC_GID=0
fi

echo ""
echo "OMERO.server UID:GID = ${OMERO_SERVER_UID}:${OMERO_SERVER_GID} (image=${OMERO_SERVER_IMAGE})"
echo "OMERO.web    UID:GID = ${OMERO_WEB_UID}:${OMERO_WEB_GID} (image=${OMERO_WEB_IMAGE})"
echo "Prometheus   UID:GID = ${PROMETHEUS_UID}:${PROMETHEUS_GID} (image=${PROMETHEUS_IMAGE})"
echo "Grafana      UID:GID = ${GRAFANA_UID}:${GRAFANA_GID} (image=${GRAFANA_IMAGE})"
echo "Loki         UID:GID = ${LOKI_UID}:${LOKI_GID} (image=${LOKI_IMAGE})"
echo "Alloy        UID:GID = ${ALLOY_UID}:${ALLOY_GID} (image=${ALLOY_IMAGE})"
echo "Database     UID:GID = ${DATABASE_UID}:${DATABASE_GID} (image=${DATABASE_IMAGE})"
echo "DB Plugin    UID:GID = ${DATABASE_PLUGIN_UID}:${DATABASE_PLUGIN_GID} (image=${DATABASE_PLUGIN_IMAGE})"
echo "Path export  UID:GID = ${PATH_USAGE_EXPORTER_UID}:${PATH_USAGE_EXPORTER_GID} (image=${PATH_USAGE_EXPORTER_IMAGE})"
if is_crowdsec_enabled; then
    echo "CrowdSec     UID:GID = ${CROWDSEC_UID}:${CROWDSEC_GID} (image=${CROWDSEC_IMAGE})"
else
    echo "CrowdSec:            disabled (no enroll key)"
fi
echo ""

echo "========================================================"
echo "Fixing host bind-mount ownership based on actual UID/GID"
echo "========================================================"
echo ""

chown_tree_or_die() {
    local path="$1"
    local label="$2"
    local uid="$3"
    local gid="$4"

    if [ -e "${path}" ] && [ ! -d "${path}" ]; then
        echo "ERROR: ${label} exists but is not a directory: ${path}" >&2
        return 1
    fi

    mkdir -p "${path}"

    echo "chown -R ${uid}:${gid} ${path}    (${label})"
    if ! chown -R "${uid}:${gid}" "${path}"; then
        echo "ERROR: Failed chown for ${label}: ${path}" >&2
        return 1
    fi

    chmod -R u+rwX "${path}" || true
    return 0
}

ensure_omero_tmp_layout() {
    local tmp_root="$1"
    local web_uid="$2"
    local web_gid="$3"
    local server_uid="$4"
    local server_gid="$5"
    local server_runtime_user="$6"
    local web_runtime_user="${7:-omero-web}"
    local server_namespace_dir="${tmp_root%/}/${server_runtime_user}"
    local server_tmp_dir="${server_namespace_dir}/tmp"
    local web_namespace_dir="${tmp_root%/}/${web_runtime_user}"
    local web_tmp_dir="${web_namespace_dir}/tmp"
    local top_level_entry=""

    if [ -e "${tmp_root}" ] && [ ! -d "${tmp_root}" ]; then
        echo "ERROR: OMERO temp directory exists but is not a directory: ${tmp_root}" >&2
        return 1
    fi

    mkdir -p "${server_tmp_dir}" "${web_tmp_dir}"

    if ! chown "${web_uid}:${web_gid}" "${tmp_root}"; then
        echo "ERROR: Failed to assign OMERO.web ownership for temp root: ${tmp_root}" >&2
        return 1
    fi

    if ! chmod u+rwx,go+rx "${tmp_root}"; then
        echo "ERROR: Failed to set traversal permissions on OMERO temp root: ${tmp_root}" >&2
        return 1
    fi

    while IFS= read -r -d '' top_level_entry; do
        if [ "${top_level_entry}" = "${server_namespace_dir}" ]; then
            continue
        fi

        echo "chown -R ${web_uid}:${web_gid} ${top_level_entry}    (OMERO web/plugin temp subtree)"
        if ! chown -R "${web_uid}:${web_gid}" "${top_level_entry}"; then
            echo "ERROR: Failed chown for OMERO web/plugin temp subtree: ${top_level_entry}" >&2
            return 1
        fi
        chmod -R u+rwX "${top_level_entry}" || true
    done < <(find "${tmp_root}" -mindepth 1 -maxdepth 1 -print0)

    echo "chown -R ${server_uid}:${server_gid} ${server_namespace_dir}    (OMERO.server temp namespace)"
    if ! chown -R "${server_uid}:${server_gid}" "${server_namespace_dir}"; then
        echo "ERROR: Failed to assign OMERO.server ownership for temp namespace: ${server_namespace_dir}" >&2
        return 1
    fi

    if ! chmod 0700 "${server_namespace_dir}" "${server_tmp_dir}"; then
        echo "ERROR: Failed to set secure permissions on OMERO.server temp namespace: ${server_tmp_dir}" >&2
        return 1
    fi

    echo "Prepared OMERO temp layout: root ${tmp_root} (owner ${web_uid}:${web_gid}), server namespace ${server_tmp_dir} (owner ${server_uid}:${server_gid})"
}

if ! chown_tree_or_die "${OMERO_USER_DATA_PATH}" "OMERO user data directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_USER_DATA_PATH%/}/certs" "OMERO certificate directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_SERVER_VAR_PATH}" "OMERO server var directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi

mkdir -p "${OMERO_SERVER_VAR_PATH%/}/tmp"
chown "${OMERO_SERVER_UID}:${OMERO_SERVER_GID}" "${OMERO_SERVER_VAR_PATH%/}/tmp" || true
chmod 1777 "${OMERO_SERVER_VAR_PATH%/}/tmp" || true

if ! chown_tree_or_die "${OMERO_SERVER_LOGS_PATH}" "OMERO server logs directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_WEB_VAR_PATH}" "OMERO web var directory" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_WEB_LOGS_PATH}" "OMERO web logs directory" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_WEB_SUPERVISOR_LOGS_PATH}" "OMERO web supervisor logs directory" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}"; then exit 1; fi
if ! ensure_omero_tmp_layout "${OMERO_TMP_PATH}" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}" "${OMERO_SERVER_RUNTIME_USER:-omero-server}" "${WEB_USER:-omero-web}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_DATABASE_PATH}" "OMERO database directory" "${DATABASE_UID}" "${DATABASE_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database directory" "${DATABASE_PLUGIN_UID}" "${DATABASE_PLUGIN_GID}"; then exit 1; fi
if ! chown_tree_or_die "${PROMETHEUS_DATA_PATH}" "Prometheus data directory" "${PROMETHEUS_UID}" "${PROMETHEUS_GID}"; then exit 1; fi
if ! chown_tree_or_die "${GRAFANA_DATA_PATH}" "Grafana data directory" "${GRAFANA_UID}" "${GRAFANA_GID}"; then exit 1; fi
if ! chown_tree_or_die "${LOKI_DATA_PATH}" "Loki data directory" "${LOKI_UID}" "${LOKI_GID}"; then exit 1; fi
if ! chown_tree_or_die "${ALLOY_DATA_PATH}" "Alloy data directory" "${ALLOY_UID}" "${ALLOY_GID}"; then exit 1; fi
if ! chown_tree_or_die "${NODE_EXPORTER_TEXTFILE_PATH}" "Node exporter textfile directory" "${PATH_USAGE_EXPORTER_UID}" "${PATH_USAGE_EXPORTER_GID}"; then exit 1; fi
if is_crowdsec_enabled; then
    if ! chown_tree_or_die "${CROWDSEC_DB_PATH}" "CrowdSec data directory" "${CROWDSEC_UID}" "${CROWDSEC_GID}"; then exit 1; fi
    if ! chown_tree_or_die "${CROWDSEC_CONFIG_PATH}" "CrowdSec config directory" "${CROWDSEC_UID}" "${CROWDSEC_GID}"; then exit 1; fi
fi

echo ""
echo "✔ Host ownership fix complete."
echo "==============================="
echo ""

# =====================================================
# Conditional CrowdSec monitoring probe
#
# prometheus.yml contains the CROWDSEC_PROBE_MARKER and may contain the
# CrowdSec health probe line. This install step makes the tracked/runtime file
# match the active credentials: enabled installations keep or inject the probe,
# disabled installations remove it to avoid recurring connection-refused probes.
# =====================================================
PROMETHEUS_CONFIG="${OMERO_INSTALLATION_PATH%/}/monitoring/prometheus/prometheus.yml"
CROWDSEC_PROBE_LINE="          - http://crowdsec:8080/health"  # DevSkim: ignore DS137138
if [ -f "${PROMETHEUS_CONFIG}" ]; then
    if is_crowdsec_enabled; then
        if ! grep -qF "http://crowdsec:8080/health" "${PROMETHEUS_CONFIG}"; then  # DevSkim: ignore DS137138
            sed -i "/# CROWDSEC_PROBE_MARKER/a\\${CROWDSEC_PROBE_LINE}" "${PROMETHEUS_CONFIG}"
            echo ""
            echo "Injected CrowdSec health probe into prometheus.yml"
        else
            echo ""
            echo "CrowdSec health probe already present in prometheus.yml"
        fi
    else
        if grep -qF "http://crowdsec:8080/health" "${PROMETHEUS_CONFIG}"; then  # DevSkim: ignore DS137138
            sed -i '\|http://crowdsec:8080/health|d' "${PROMETHEUS_CONFIG}"  # DevSkim: ignore DS137138
            echo ""
            echo "Removed CrowdSec health probe from prometheus.yml (CrowdSec disabled)"
        fi
    fi
fi

# =====================================================
# Quota enforcer installation (non-blocking)
#
# Detects whether the OMERO user-data filesystem supports ext4 project
# quotas.  When all prerequisites are met the host-side systemd timer
# is installed automatically.  When not, a non-blocking info message
# is printed and the Quotas tab in Admin Tools will be disabled.
# =====================================================
install_quota_enforcer_if_supported() {
    local omero_user_data_dir="$1"
    local installer_path="${OMERO_INSTALLATION_PATH%/}/scripts/install-quota-enforcer.sh"

    echo ""
    echo "=============================================="
    echo "Checking ext4 project quota support for quotas"
    echo "=============================================="
    echo ""

    if [ ! -f "${installer_path}" ]; then
        echo "INFO: Quota enforcer installer not found at ${installer_path}."
        echo "INFO: Skipping quota enforcer installation."
        return 0
    fi

    # ─── Detect filesystem type for OMERO user data path ───
    local quota_fs_type="" quota_mount_point="" quota_block_device=""
    while read -r line; do
        local parts
        # shellcheck disable=SC2206
        parts=($line)
        if [ "${#parts[@]}" -lt 3 ]; then continue; fi
        local mp="${parts[1]}"
        local ft="${parts[2]}"
        # Append trailing slash to both paths to ensure correct prefix matching.
        # Without this, mount point /data would incorrectly match /datafiles/OMERO.
        case "${omero_user_data_dir%/}/" in
            "${mp%/}/"*)
                if [ -z "${quota_mount_point}" ] || [ "${#mp}" -gt "${#quota_mount_point}" ]; then
                    quota_mount_point="${mp}"
                    quota_fs_type="${ft}"
                    quota_block_device="${parts[0]}"
                fi
                ;;
        esac
    done < /proc/mounts

    if [ "${quota_fs_type}" != "ext4" ]; then
        echo "INFO: Filesystem for ${omero_user_data_dir} is '${quota_fs_type:-unknown}', not ext4."
        echo "INFO: ext4 project quotas are not supported on this filesystem type."
        echo "INFO: The Quotas tab in Admin Tools will be disabled."
        echo "INFO: To enable quotas, use an ext4 filesystem with prjquota mount option."
        echo ""
        return 0
    fi

    # ─── Check prjquota mount option ───
    if ! mount | grep -qE "on ${quota_mount_point} .*prjquota"; then
        echo "INFO: Filesystem at ${quota_mount_point} is ext4 but NOT mounted with prjquota."
        echo "INFO: To enable quotas:"
        echo "INFO:   1. Add 'prjquota' to mount options in /etc/fstab"
        echo "INFO:   2. Remount: sudo mount -o remount,prjquota ${quota_mount_point}"
        echo "INFO:   3. Re-run this installation script."
        echo "INFO: The Quotas tab in Admin Tools will be disabled until then."
        echo ""
        return 0
    fi

    # ─── Check ext4 project feature in superblock ───
    if command -v tune2fs >/dev/null 2>&1 && [ -n "${quota_block_device}" ]; then
        if ! tune2fs -l "${quota_block_device}" 2>/dev/null | grep -q "project"; then
            echo "INFO: ext4 'project' feature is NOT enabled on ${quota_block_device}."
            echo "INFO: To enable quotas:"
            echo "INFO:   1. Enable project feature: sudo tune2fs -O project ${quota_block_device}"
            echo "INFO:   2. Re-run this installation script."
            echo "INFO: The Quotas tab in Admin Tools will be disabled until then."
            echo ""
            return 0
        fi
    fi

    echo "ext4 project quota support detected on ${quota_mount_point}."
    echo "Installing OMERO quota enforcer..."
    echo ""

    chmod +x "${installer_path}"
    if ! "${installer_path}" "${omero_user_data_dir}"; then
        echo ""
        echo "WARNING: Quota enforcer installation encountered errors (non-blocking)." >&2
        echo "WARNING: You can install it manually later with:" >&2
        echo "  sudo ${installer_path} ${omero_user_data_dir}" >&2
        echo ""
        return 0
    fi

    echo ""
    echo "✔ Quota enforcer installed successfully."
    return 0
}

install_quota_enforcer_if_supported "${OMERO_USER_DATA_PATH}" || true

# Ensure .admin-tools directory exists and is writable by omeroweb container.
# The quota enforcer installer creates this as root; the omeroweb container
# (OMERO_WEB_UID) needs write access to persist quota state from the UI.
admin_tools_dir="${OMERO_USER_DATA_PATH%/}/.admin-tools"
if [ -d "${admin_tools_dir}" ]; then
    chmod 0777 "${admin_tools_dir}" 2>/dev/null || true
    if [ -d "${admin_tools_dir}/quota" ]; then
        chmod 0777 "${admin_tools_dir}/quota" 2>/dev/null || true
    fi
    echo ""
    echo "Ensured .admin-tools directory permissions for omeroweb container (mode 0777, no sticky bit)."
else
    # Create it even if the quota enforcer wasn't installed, so the omeroweb
    # container can write the quota state file without permission errors.
    mkdir -p "${admin_tools_dir}/quota"
    chmod 0777 "${admin_tools_dir}" 2>/dev/null || true
    chmod 0777 "${admin_tools_dir}/quota" 2>/dev/null || true
    echo ""
    echo "Created .admin-tools directory with write permissions for omeroweb container (mode 0777, no sticky bit)."
fi

# =====================================================
# Tmp artifact cleaner installation (non-blocking)
#
# Installs a host-side systemd timer that periodically deletes temporary
# artifacts under OMERO_TMP_PATH that are older than 24 hours by default,
# while allowing plugin-written retention markers to extend specific paths.
#
# IMPORTANT:
# - This replaces all previous "cleanup on page load" mechanisms in plugins.
# - Immediate cleanup after successful jobs is handled inside the plugins.
# =====================================================
install_tmp_cleaner_if_available() {
    local omero_tmp_dir="$1"
    local installer_path="${OMERO_INSTALLATION_PATH%/}/scripts/install-tmp-cleaner.sh"

    echo ""
    echo "=============================================="
    echo "Installing host-side tmp artifact cleaner"
    echo "=============================================="
    echo ""

    if [ ! -f "${installer_path}" ]; then
        echo "INFO: Tmp cleaner installer not found at ${installer_path}."
        echo "INFO: Skipping tmp cleaner installation."
        return 0
    fi

    if [ -z "${omero_tmp_dir}" ] || [ ! -d "${omero_tmp_dir}" ]; then
        echo "INFO: OMERO_TMP_PATH is not a directory (${omero_tmp_dir:-unset})."
        echo "INFO: Skipping tmp cleaner installation."
        return 0
    fi

    chmod +x "${installer_path}"
    if ! "${installer_path}" "${omero_tmp_dir}"; then
        echo ""
        echo "WARNING: Tmp cleaner installation encountered errors (non-blocking)." >&2
        echo "WARNING: You can install it manually later with:" >&2
        echo "  sudo ${installer_path} ${omero_tmp_dir}" >&2
        echo ""
        return 0
    fi

    echo ""
    echo "✔ Tmp cleaner installed successfully."
    echo ""
    echo "Useful commands:"
    echo "  systemctl status omero-tmp-cleaner.timer"
    echo "  journalctl -u omero-tmp-cleaner.service"
    echo "  sudo /usr/local/sbin/omero-tmp-cleaner --tmp-dir ${omero_tmp_dir}"
    echo ""
    return 0
}

print_binary_repository_cleanse_notice() {
    local startup_state="${1:?BUG: print_binary_repository_cleanse_notice requires startup state}"
    local enabled="${OMERO_BINARY_REPO_CLEANSE_ON_START:-1}"
    local data_dir="${OMERO_BINARY_REPO_CLEANSE_DATA_DIR:-/OMERO}"

    if [ "${enabled}" = "1" ]; then
        if [ "${startup_state}" = "started" ]; then
            echo "OMERO binary repository cleanse is configured to run automatically on each omeroserver start (data dir: ${data_dir})."
        else
            echo "OMERO binary repository cleanse will run automatically on the next omeroserver start (data dir: ${data_dir})."
        fi
        echo "The runtime hook runs inside the omeroserver container after OMERO login is ready and does not block container startup."
        return 0
    fi

    echo "OMERO binary repository cleanse is disabled (OMERO_BINARY_REPO_CLEANSE_ON_START=${enabled})."
    return 0
}

install_tmp_cleaner_if_available "${OMERO_TMP_PATH}" || true
echo "================================================"
echo ""

prepare_crowdsec_install_bootstrap_enrollment
print_crowdsec_install_bootstrap_status

if [ "${START_CONTAINERS}" -eq 1 ]; then
    if [ "${CROWDSEC_INSTALL_AUTO_RESTART_REQUIRED}" = "1" ]; then
        print_crowdsec_install_enrollment_notice "${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS}"
    fi

    # Persist vm.overcommit_memory=1 on the host so Redis operates safely
    # across reboots.  The redis-sysctl-init container is profile-gated and
    # only needed for non-standard deployments; this host-level setting is
    # the primary mechanism for production installs.
    echo "vm.overcommit_memory = 1" > /etc/sysctl.d/99-redis-overcommit.conf
    sysctl -w vm.overcommit_memory=1 >/dev/null 2>&1 || true
    echo "Set vm.overcommit_memory=1 (persisted to /etc/sysctl.d/99-redis-overcommit.conf)"
    echo ""

    startup_sync_started_epoch="$(date +%s)"
    compose_up_with_retries "${COMPOSE_FILE}"
    schedule_crowdsec_install_auto_restart

    if ! create_omero_groups_from_list "${COMPOSE_FILE}" "${OMERO_INSTALL_GROUP_LIST:-}"; then
        exit 1
    fi

    if ! wait_for_repo_root_sync_ready "${startup_sync_started_epoch}"; then
        exit 1
    fi

    add_job_service_to_install_groups "${COMPOSE_FILE}" "${OMERO_INSTALL_GROUP_LIST:-}"

    set +e
    wait_for_dropbox_ice_bootstrap_ready "${startup_sync_started_epoch}"
    dropbox_ice_wait_rc=$?
    set -e
    if [ "${dropbox_ice_wait_rc}" -eq 2 ]; then
        exit 1
    fi

    set +e
    wait_for_dropbox_user_dir_sync_ready "${startup_sync_started_epoch}"
    dropbox_user_dir_wait_rc=$?
    set -e
    if [ "${dropbox_user_dir_wait_rc}" -eq 2 ]; then
        exit 1
    fi

    echo ""
    print_binary_repository_cleanse_notice "started"
else
    echo "Skipping container startup (START_CONTAINERS=0)."
    echo ""
    print_binary_repository_cleanse_notice "deferred"
fi

# Cleanup build containers
bash "${SCRIPT_DIR}/cleanup_build_containers.sh"

echo ""
echo "Done. Wait 30 seconds and check if the containers are up and running."
