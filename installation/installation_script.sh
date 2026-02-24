#!/usr/bin/env bash

# Configuration
# -------------
SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SCRIPT_ENV_FILE=""
USE_CACHE_BUILD="${USE_CACHE_BUILD:-1}"             # set to 1 to enable buildx inline cache
USE_BUILDX_COMPRESSED_BUILD="${USE_BUILDX_COMPRESSED_BUILD:-1}" # set to 0 to use plain docker compose build
KEEP_IMAGES="${KEEP_IMAGES:-0}"                     # set to 1 to keep existing images
START_CONTAINERS="${START_CONTAINERS:-1}"            # set to 0 to skip `docker compose up -d`
BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH="${BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH:-installation/docker_buildx_compressed_push.sh}"
INSTALLATION_AUTOMATION_MODE="${INSTALLATION_AUTOMATION_MODE:-0}" # set to 1 to run fully non-interactive (no /dev/tty prompts)
COMPOSE_UP_RETRIES="${COMPOSE_UP_RETRIES:-3}"
COMPOSE_UP_RETRY_DELAY_SECONDS="${COMPOSE_UP_RETRY_DELAY_SECONDS:-5}"
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
DATABASE_UID="${DATABASE_UID:-}"
DATABASE_GID="${DATABASE_GID:-}"
DATABASE_PLUGIN_UID="${DATABASE_PLUGIN_UID:-}"
DATABASE_PLUGIN_GID="${DATABASE_PLUGIN_GID:-}"
OMERO_SERVER_ENV_FILE="${REPO_ROOT_DIR}/env/omeroserver.env"

# Allow override, but default to the repo's current image names (adjust via env vars if you rename them in compose)
OMERO_SERVER_IMAGE="${OMERO_SERVER_IMAGE:-omeroserver:custom}"
OMERO_WEB_IMAGE="${OMERO_WEB_IMAGE:-omeroweb:custom}"
PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-}"
GRAFANA_IMAGE="${GRAFANA_IMAGE:-}"
LOKI_IMAGE="${LOKI_IMAGE:-}"
DATABASE_IMAGE="${DATABASE_IMAGE:-}"
DATABASE_PLUGIN_IMAGE="${DATABASE_PLUGIN_IMAGE:-}"

set -euo pipefail


load_installation_paths_env() {
    local env_file_path="${1:?BUG: load_installation_paths_env requires a path}"
    local env_line
    local env_key
    local env_value

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
                eval "${env_key}=\"${env_value}\""
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

if [ -r "${OMERO_SERVER_ENV_FILE}" ]; then
    set -a
    load_installation_paths_env "${OMERO_SERVER_ENV_FILE}"
    set +a
fi

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
    if ! [[ "${COMPOSE_UP_RETRIES}" =~ ^[0-9]+$ ]] || [ "${COMPOSE_UP_RETRIES}" -lt 1 ]; then
        echo "ERROR: COMPOSE_UP_RETRIES must be an integer >= 1. Got: ${COMPOSE_UP_RETRIES}" >&2
        return 1
    fi

    if ! [[ "${COMPOSE_UP_RETRY_DELAY_SECONDS}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: COMPOSE_UP_RETRY_DELAY_SECONDS must be an integer >= 0. Got: ${COMPOSE_UP_RETRY_DELAY_SECONDS}" >&2
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

# ---------------------------------------------------------------------------
# run_image_build
#
# Buildx compressed build (zstd) is always used - fully automatic.
# Cache is controlled by USE_CACHE_BUILD (from the "Use cache?" prompt),
# which applies to both buildx inline cache and docker build cache.
# ---------------------------------------------------------------------------
run_image_build() {
    local inline_cache_setting=""
    local buildx_helper_path="${OMERO_INSTALLATION_PATH%/}/${BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH}"

    if [ "${USE_BUILDX_COMPRESSED_BUILD}" = "0" ]; then
        echo "Building OMERO images via docker compose build workflow..."
        echo "  Compose file   : ${COMPOSE_FILE}"
        echo "  Cache enabled  : ${USE_CACHE_BUILD}"

        if [ "${USE_CACHE_BUILD}" = "0" ]; then
            compose_with_installation_env "${COMPOSE_FILE}" build --no-cache
        else
            compose_with_installation_env "${COMPOSE_FILE}" build
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

    # Derive no-cache flag: if cache is disabled (0), also disable docker layer cache
    local no_cache_setting="0"
    if [ "${inline_cache_setting}" = "0" ]; then
        no_cache_setting="1"
    fi

    COMPOSE_FILE="${COMPOSE_FILE}" \
        DOCKER_BUILD_INLINE_CACHE="${inline_cache_setting}" \
        DOCKER_BUILD_NO_CACHE="${no_cache_setting}" \
        "${buildx_helper_path}"
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
        OMERO_USER_DATA_PATH
        OMERO_UPLOAD_PATH
        OMERO_SERVER_VAR_PATH
        OMERO_SERVER_LOGS_PATH
        OMERO_WEB_LOGS_PATH
        OMERO_WEB_SUPERVISOR_LOGS_PATH
        PORTAINER_DATA_PATH
        PROMETHEUS_DATA_PATH
        GRAFANA_DATA_PATH
        LOKI_DATA_PATH
        PG_MAINTENANCE_DATA_PATH
        OMERO_DB_PASS
        OMP_PLUGIN_DB_PASS
    )

    for env_var_name in "${required_compose_env_vars[@]}"; do
        if [ -z "${!env_var_name:-}" ]; then
            echo "ERROR: Missing required docker compose interpolation variable: ${env_var_name}" >&2
            return 1
        fi

        export "${env_var_name}=${!env_var_name}"
    done

    return 0
}

validate_numeric_id() {
    local id_label="$1"
    local id_value="$2"

    if ! [[ "${id_value}" =~ ^[0-9]+$ ]]; then
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

    local failed_services
    failed_services="$(compose_with_installation_env "${compose_file}" ps --services --filter "status=exited" 2>/dev/null || true)"

    if [ -z "${failed_services}" ]; then
        failed_services="$(compose_with_installation_env "${compose_file}" ps --services --filter "status=restarting" 2>/dev/null || true)"
    fi

    if [ -z "${failed_services}" ]; then
        echo "ERROR: Could not identify exited/restarting services. Inspect health status and logs manually." >&2
        return 0
    fi

    local service_name
    while IFS= read -r service_name; do
        if [ -z "${service_name}" ]; then
            continue
        fi
        echo "----- BEGIN LOGS: ${service_name} -----" >&2
        compose_with_installation_env "${compose_file}" logs --tail 120 "${service_name}" >&2 || true
        echo "----- END LOGS: ${service_name} -----" >&2
    done <<< "${failed_services}"
}

compose_up_with_retries() {
    local compose_file="$1"
    local attempt=1

    while [ "${attempt}" -le "${COMPOSE_UP_RETRIES}" ]; do
        echo "Starting containers (attempt ${attempt}/${COMPOSE_UP_RETRIES})..."

        if compose_with_installation_env "${compose_file}" up -d; then
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
        if [[ "${group_entry}" != *:* ]]; then
            echo "ERROR: Invalid OMERO_INSTALL_GROUP_LIST entry (missing ':'): ${group_entry}" >&2
            return 1
        fi

        group_name="${group_entry%%:*}"
        group_permission="${group_entry#*:}"

        if [ -z "${group_name}" ]; then
            echo "ERROR: OMERO_INSTALL_GROUP_LIST contains an entry with empty group name: ${group_entry}" >&2
            return 1
        fi

        if ! [[ "${group_name}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
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
            add_output="$(compose_with_installation_env "${compose_file}" exec -T \
                -e ROOTPASS="${ROOTPASS}" \
                -e TARGET_GROUP_NAME="${group_name}" \
                -e TARGET_GROUP_PERMISSION="${group_permission}" \
                omeroserver bash -lc 'set -euo pipefail; discover_omero_cli() { local candidate=""; while IFS= read -r candidate; do [ -z "${candidate}" ] && continue; if "${candidate}" --help >/dev/null 2>&1; then printf "%s" "${candidate}"; return 0; fi; done < <(find / -xdev -type f -name omero -perm -u+x 2>/dev/null | sort -u); echo "Unable to locate a working OMERO CLI executable inside omeroserver container (searched executable files named omero on local mounts)." >&2; return 127; }; OMERO_BIN="$(discover_omero_cli)"; "${OMERO_BIN}" login root@localhost -w "${ROOTPASS}" >/dev/null; "${OMERO_BIN}" group add "${TARGET_GROUP_NAME}" --type="${TARGET_GROUP_PERMISSION}"' 2>&1)"
            add_exit_code=$?
            set -e

            if [ "${add_exit_code}" -eq 0 ] || printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|exists"; then
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

stop_old_installation_containers() {
    local old_install_path="${1%/}"
    local old_database_path="$2"
    local old_plugin_database_path="$3"
    local old_data_path="${4%/}"
    local keep_images="$5"
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
OMERO_USER_DATA_PATH=${old_data_path}/omero_user_data
OMERO_UPLOAD_PATH=${old_data_path}/omero_upload
OMERO_SERVER_VAR_PATH=${old_data_path}/omero_server_var
OMERO_SERVER_LOGS_PATH=${old_data_path}/omero_server_logs
OMERO_WEB_LOGS_PATH=${old_data_path}/omero_web_logs
OMERO_WEB_SUPERVISOR_LOGS_PATH=${old_data_path}/omero_web_supervisor_logs
PORTAINER_DATA_PATH=${old_data_path}/portainer_data
PROMETHEUS_DATA_PATH=${old_data_path}/prometheus_data
GRAFANA_DATA_PATH=${old_data_path}/grafana_data
LOKI_DATA_PATH=${old_data_path}/loki_data
PG_MAINTENANCE_DATA_PATH=${old_data_path}/pg_maintenance_data
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
            docker rm -f "${fixed_name}" 2>/dev/null || true
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
    if [ -z "${SCRIPT_ENV_FILE}" ] || [ ! -r "${SCRIPT_ENV_FILE}" ]; then
        return 0
    fi

    (
        local env_line
        while IFS= read -r env_line || [ -n "${env_line}" ]; do
            case "${env_line}" in
                ''|'#'*) continue ;;
                [A-Za-z_]*=*) eval "${env_line}" ;;
            esac
        done < "${SCRIPT_ENV_FILE}"

        local _install_root="${OMERO_INSTALLATION_PATH:-}"
        _install_root="${_install_root%/}"

        local _path
        for _path in \
            "${OMERO_DATABASE_PATH:-}" \
            "${OMERO_PLUGIN_DATABASE_PATH:-}" \
            "${OMERO_DATA_PATH:-}" \
            "${OMERO_USER_DATA_PATH:-}" \
            "${OMERO_UPLOAD_PATH:-}" \
            "${OMERO_SERVER_VAR_PATH:-}" \
            "${OMERO_SERVER_LOGS_PATH:-}" \
            "${OMERO_WEB_LOGS_PATH:-}" \
            "${OMERO_WEB_SUPERVISOR_LOGS_PATH:-}" \
            "${PORTAINER_DATA_PATH:-}" \
            "${PROMETHEUS_DATA_PATH:-}" \
            "${GRAFANA_DATA_PATH:-}" \
            "${LOKI_DATA_PATH:-}" \
            "${PG_MAINTENANCE_DATA_PATH:-}"; do

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

    if [ -z "${SCRIPT_ENV_FILE}" ] || [ ! -r "${SCRIPT_ENV_FILE}" ]; then
        return 0
    fi

    (
        local env_line
        while IFS= read -r env_line || [ -n "${env_line}" ]; do
            case "${env_line}" in
                ''|'#'*) continue ;;
                [A-Za-z_]*=*) eval "${env_line}" ;;
            esac
        done < "${SCRIPT_ENV_FILE}"

        local _path
        for _path in \
            "${OMERO_DATABASE_PATH:-}" \
            "${OMERO_PLUGIN_DATABASE_PATH:-}" \
            "${OMERO_DATA_PATH:-}" \
            "${OMERO_USER_DATA_PATH:-}" \
            "${OMERO_UPLOAD_PATH:-}" \
            "${OMERO_SERVER_VAR_PATH:-}" \
            "${OMERO_SERVER_LOGS_PATH:-}" \
            "${OMERO_WEB_LOGS_PATH:-}" \
            "${OMERO_WEB_SUPERVISOR_LOGS_PATH:-}" \
            "${PORTAINER_DATA_PATH:-}" \
            "${PROMETHEUS_DATA_PATH:-}" \
            "${GRAFANA_DATA_PATH:-}" \
            "${LOKI_DATA_PATH:-}" \
            "${PG_MAINTENANCE_DATA_PATH:-}"; do

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
# Load both path and secrets env files automatically for all docker compose
# commands, including manual lifecycle commands such as `docker compose down`.
COMPOSE_ENV_FILES=installation_paths.env:env/omero_secrets.env
#
# This file contains fully-resolved paths so that docker compose
# commands (up, down, ps, logs, ...) work out of the box without
# requiring --env-file or COMPOSE_ENV_FILES support.
#
# NOTE: OMERO_DB_PASS and OMP_PLUGIN_DB_PASS are intentionally mirrored here
# because docker compose interpolation happens before service-level env_file
# loading. This guarantees manual commands like `docker compose down` work.
OMERO_INSTALLATION_PATH=${OMERO_INSTALLATION_PATH}
OMERO_DATABASE_PATH=${OMERO_DATABASE_PATH}
OMERO_PLUGIN_DATABASE_PATH=${OMERO_PLUGIN_DATABASE_PATH}
OMERO_DATA_PATH=${OMERO_DATA_PATH}
OMERO_USER_DATA_PATH=${OMERO_USER_DATA_PATH}
OMERO_UPLOAD_PATH=${OMERO_UPLOAD_PATH}
OMERO_SERVER_VAR_PATH=${OMERO_SERVER_VAR_PATH}
OMERO_SERVER_LOGS_PATH=${OMERO_SERVER_LOGS_PATH}
OMERO_WEB_LOGS_PATH=${OMERO_WEB_LOGS_PATH}
OMERO_WEB_SUPERVISOR_LOGS_PATH=${OMERO_WEB_SUPERVISOR_LOGS_PATH}
PORTAINER_DATA_PATH=${PORTAINER_DATA_PATH}
PROMETHEUS_DATA_PATH=${PROMETHEUS_DATA_PATH}
GRAFANA_DATA_PATH=${GRAFANA_DATA_PATH}
LOKI_DATA_PATH=${LOKI_DATA_PATH}
PG_MAINTENANCE_DATA_PATH=${PG_MAINTENANCE_DATA_PATH}
OMERO_DB_PASS=${OMERO_DB_PASS}
OMP_PLUGIN_DB_PASS=${OMP_PLUGIN_DB_PASS}
DOTENV

    chmod 0600 "${dot_env_path}"

    if [ -n "${SUDO_UID:-}" ] && [ -n "${SUDO_GID:-}" ]; then
        if ! [[ "${SUDO_UID}" =~ ^[0-9]+$ ]] || ! [[ "${SUDO_GID}" =~ ^[0-9]+$ ]]; then
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
#   OMERO_USER_DATA_PATH
#   OMERO_UPLOAD_PATH
#   OMERO_SERVER_VAR_PATH
#   OMERO_SERVER_LOGS_PATH
#   OMERO_WEB_LOGS_PATH
#   OMERO_WEB_SUPERVISOR_LOGS_PATH
#   PROMETHEUS_DATA_PATH
#   GRAFANA_DATA_PATH
#   PORTAINER_DATA_PATH
#   LOKI_DATA_PATH
#   PG_MAINTENANCE_DATA_PATH

OMERO_INSTALLATION_PATH=${OMERO_INSTALLATION_PATH}
OMERO_DATABASE_PATH=${OMERO_DATABASE_PATH}
OMERO_PLUGIN_DATABASE_PATH=${OMERO_PLUGIN_DATABASE_PATH}
OMERO_DATA_PATH=${OMERO_DATA_PATH}
#
OMERO_USER_DATA_PATH=\${OMERO_DATA_PATH}/omero_user_data
OMERO_UPLOAD_PATH=\${OMERO_DATA_PATH}/omero_upload
OMERO_SERVER_VAR_PATH=\${OMERO_DATA_PATH}/omero_server_var
OMERO_SERVER_LOGS_PATH=\${OMERO_DATA_PATH}/omero_server_logs
OMERO_WEB_LOGS_PATH=\${OMERO_DATA_PATH}/omero_web_logs
OMERO_WEB_SUPERVISOR_LOGS_PATH=\${OMERO_DATA_PATH}/omero_web_supervisor_logs
PROMETHEUS_DATA_PATH=\${OMERO_DATA_PATH}/prometheus_data
GRAFANA_DATA_PATH=\${OMERO_DATA_PATH}/grafana_data
PORTAINER_DATA_PATH=\${OMERO_DATA_PATH}/portainer_data
LOKI_DATA_PATH=\${OMERO_DATA_PATH}/loki_data
PG_MAINTENANCE_DATA_PATH=\${OMERO_DATA_PATH}/pg_maintenance_data
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
        OMERO_USER_DATA_PATH
        OMERO_UPLOAD_PATH
        OMERO_SERVER_VAR_PATH
        OMERO_SERVER_LOGS_PATH
        OMERO_WEB_LOGS_PATH
        OMERO_WEB_SUPERVISOR_LOGS_PATH
        PROMETHEUS_DATA_PATH
        GRAFANA_DATA_PATH
        PORTAINER_DATA_PATH
        LOKI_DATA_PATH
        PG_MAINTENANCE_DATA_PATH
    )

    for expected_var in "${required_vars[@]}"; do
        expected_value="${!expected_var:-}"
        actual_value="$(
            (
                # shellcheck disable=SC1090
                . "${env_file_path}" 2>/dev/null || exit 1
                printf '%s' "${!expected_var:-}"
            )
        )"

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
            echo "Please choose a different ${path_label}." > /dev/tty
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

    echo "Delete all container images? Y/n (Default: n)"

    while true; do
        printf '> ' > /dev/tty
        if ! IFS= read -r reply < /dev/tty; then
            KEEP_IMAGES=1
            echo "WARNING: Could not read confirmation input; defaulting to keep existing images." >&2
            return 0
        fi

        reply="$(printf '%s' "${reply}" | tr '[:upper:]' '[:lower:]')"

        if [ -z "${reply}" ] || [ "${reply}" = "n" ] || [ "${reply}" = "no" ]; then
            KEEP_IMAGES=1
            return 0
        fi

        if [ "${reply}" = "y" ] || [ "${reply}" = "yes" ]; then
            KEEP_IMAGES=0
            return 0
        fi

        echo "Wrong choice. Please type Y or n." > /dev/tty
    done
}

resolve_path_with_default_prompt() {
    local default_path="$1"
    local path_label="$2"
    local reply=""
    local chosen_path=""

    if [ "${INSTALLATION_AUTOMATION_MODE}" = "1" ] || [ ! -r /dev/tty ]; then
        printf '%s' "${default_path}"
        return 0
    fi

    while true; do
        echo "Use default ${path_label} (${default_path})? Y/n (Default: Y)" > /dev/tty
        printf '> ' > /dev/tty

        if ! IFS= read -r reply < /dev/tty; then
            printf '%s' "${default_path}"
            return 0
        fi

        reply="$(printf '%s' "${reply}" | tr '[:upper:]' '[:lower:]')"

        if [ -z "${reply}" ] || [ "${reply}" = "y" ] || [ "${reply}" = "yes" ]; then
            printf '%s' "${default_path}"
            return 0
        fi

        if [ "${reply}" = "n" ] || [ "${reply}" = "no" ]; then
            while true; do
                printf '%s: (Current: %s) ' "${path_label}" "${default_path}" > /dev/tty

                if ! IFS= read -r chosen_path < /dev/tty; then
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

                echo "Wrong ${path_label}, try again: (Current: ${default_path})" > /dev/tty
            done
        fi

        echo "Wrong choice. Please type Y or n." > /dev/tty
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
        echo "${prompt_message}" > /dev/tty
        printf '> ' > /dev/tty

        if ! IFS= read -r reply < /dev/tty; then
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
                echo "Wrong choice. Please type Y or n." > /dev/tty
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

    reply="$(prompt_yes_no "Enable Buildx compressed build workflow? Y/n (Default: Y)" "yes")"
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

if ! resolve_start_containers_choice; then
    exit 1
fi

if ! validate_toggle_config "INSTALLATION_AUTOMATION_MODE" "${INSTALLATION_AUTOMATION_MODE}"; then
    exit 1
fi

if ! validate_toggle_config "USE_BUILDX_COMPRESSED_BUILD" "${USE_BUILDX_COMPRESSED_BUILD}"; then
    exit 1
fi

DEFAULT_OMERO_INSTALLATION_PATH="${OMERO_INSTALLATION_PATH}"
DEFAULT_OMERO_DATABASE_PATH="${OMERO_DATABASE_PATH}"
DEFAULT_OMERO_PLUGIN_DATABASE_PATH="${OMERO_PLUGIN_DATABASE_PATH}"
DEFAULT_OMERO_DATA_PATH="${OMERO_DATA_PATH}"

OMERO_INSTALLATION_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_INSTALLATION_PATH}" "OMERO installation path")"
OMERO_DATABASE_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_DATABASE_PATH}" "OMERO database path")"
OMERO_PLUGIN_DATABASE_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_PLUGIN_DATABASE_PATH}" "OMERO plugin database path")"
OMERO_DATA_PATH="$(prompt_for_preparable_path "${DEFAULT_OMERO_DATA_PATH}" "OMERO data path")"

if ! bootstrap_installation_checkout_if_missing "${OMERO_INSTALLATION_PATH}"; then
    exit 1
fi

COMPOSE_FILE="${OMERO_INSTALLATION_PATH%/}/docker-compose.yml"

OMERO_USER_DATA_PATH="${OMERO_DATA_PATH%/}/omero_user_data"
OMERO_UPLOAD_PATH="${OMERO_DATA_PATH%/}/omero_upload"
OMERO_SERVER_VAR_PATH="${OMERO_DATA_PATH%/}/omero_server_var"
OMERO_SERVER_LOGS_PATH="${OMERO_DATA_PATH%/}/omero_server_logs"
OMERO_WEB_LOGS_PATH="${OMERO_DATA_PATH%/}/omero_web_logs"
OMERO_WEB_SUPERVISOR_LOGS_PATH="${OMERO_DATA_PATH%/}/omero_web_supervisor_logs"
PROMETHEUS_DATA_PATH="${OMERO_DATA_PATH%/}/prometheus_data"
GRAFANA_DATA_PATH="${OMERO_DATA_PATH%/}/grafana_data"
PORTAINER_DATA_PATH="${OMERO_DATA_PATH%/}/portainer_data"
LOKI_DATA_PATH="${OMERO_DATA_PATH%/}/loki_data"
PG_MAINTENANCE_DATA_PATH="${OMERO_DATA_PATH%/}/pg_maintenance_data"

if ! export_compose_interpolation_env; then
    exit 1
fi

if ! validate_retry_config; then
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

require_path_config_var "OMERO_INSTALLATION_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_DATABASE_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_PLUGIN_DATABASE_PATH" "${SCRIPT_ENV_FILE}"
require_path_config_var "OMERO_DATA_PATH" "${SCRIPT_ENV_FILE}"
require_nonempty_config_var "OMERO_DB_PASS" "${SECRETS_ENV_FILE}"
require_nonempty_config_var "OMP_PLUGIN_DB_PASS" "${SECRETS_ENV_FILE}"

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

echo "Using installation paths from ${SCRIPT_ENV_FILE}"
echo "Using docker compose .env file: ${OMERO_INSTALLATION_PATH%/}/.env"
echo "OMERO_INSTALLATION_PATH=${OMERO_INSTALLATION_PATH}"
echo "OMERO_DATABASE_PATH=${OMERO_DATABASE_PATH}"
echo "OMERO_PLUGIN_DATABASE_PATH=${OMERO_PLUGIN_DATABASE_PATH}"
echo "OMERO_DATA_PATH=${OMERO_DATA_PATH}"

if ! ensure_installation_path "${OMERO_INSTALLATION_PATH}"; then
    echo "ERROR: Unable to prepare OMERO installation path: ${OMERO_INSTALLATION_PATH}" >&2
    exit 1
fi

warn_directory_not_empty "${OMERO_DATABASE_PATH}" "OMERO database directory"
warn_directory_not_empty "${OMERO_PLUGIN_DATABASE_PATH}" "OMP plugin database directory"
warn_directory_not_empty "${OMERO_DATA_PATH}" "OMERO data directory"

if ! ensure_data_path "${OMERO_DATABASE_PATH}" "OMERO database directory"; then exit 1; fi
if ! ensure_data_path "${OMERO_PLUGIN_DATABASE_PATH}" "OMP plugin database directory"; then exit 1; fi
if ! ensure_data_path "${OMERO_DATA_PATH}" "OMERO data directory"; then exit 1; fi
if ! ensure_container_writable_path "${OMERO_USER_DATA_PATH}" "OMERO user data directory"; then exit 1; fi
if ! ensure_container_writable_path "${OMERO_USER_DATA_PATH%/}/certs" "OMERO certificate directory"; then exit 1; fi
if ! ensure_container_writable_path "${PORTAINER_DATA_PATH}" "Portainer data directory"; then exit 1; fi
if ! ensure_container_writable_path "${LOKI_DATA_PATH}" "Loki data directory"; then exit 1; fi
if ! ensure_data_path "${PG_MAINTENANCE_DATA_PATH}" "PG maintenance data directory"; then exit 1; fi

write_installation_paths_env "${SCRIPT_ENV_FILE}"
if ! verify_installation_paths_env_content "${SCRIPT_ENV_FILE}"; then
    echo "ERROR: Refusing to continue because installation paths were not persisted correctly to ${SCRIPT_ENV_FILE}." >&2
    exit 1
fi

write_compose_dot_env "${OMERO_INSTALLATION_PATH%/}/.env"

# Workflow
# --------
cd "${OMERO_INSTALLATION_PATH}"

if [ "${DEFAULT_OMERO_INSTALLATION_PATH%/}" != "${OMERO_INSTALLATION_PATH%/}" ]; then
    stop_old_installation_containers \
        "${DEFAULT_OMERO_INSTALLATION_PATH}" \
        "${DEFAULT_OMERO_DATABASE_PATH}" \
        "${DEFAULT_OMERO_PLUGIN_DATABASE_PATH}" \
        "${DEFAULT_OMERO_DATA_PATH}" \
        "${KEEP_IMAGES}"
fi

echo "Recording pre-stop data path snapshots..."
log_path_snapshot "${OMERO_DATABASE_PATH}" "OMERO database directory (before docker compose down)"
log_path_snapshot "${OMERO_PLUGIN_DATABASE_PATH}" "OMP plugin database directory (before docker compose down)"
log_path_snapshot "${OMERO_DATA_PATH}" "OMERO data directory (before docker compose down)"

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
log_path_snapshot "${OMERO_PLUGIN_DATABASE_PATH}" "OMP plugin database directory (after docker compose down)"
log_path_snapshot "${OMERO_DATA_PATH}" "OMERO data directory (after docker compose down)"

echo "Removing stale OMERO repository lock files from OMERO user data path..."
if [ -d "${OMERO_USER_DATA_PATH}" ]; then
    find "${OMERO_USER_DATA_PATH}" -name "*.lock" -delete || true
else
    echo "WARNING: OMERO user data path ${OMERO_USER_DATA_PATH} not found; skipping lock cleanup."
fi

if ! run_image_build; then
    exit 1
fi

echo "================================================"
echo "Discovering ACTUAL OMERO UID/GID from built images"
echo "================================================"

discover_first_existing_user_or_die() {
    local image="$1"
    shift

    local candidate=""
    local found=""

    for candidate in "$@"; do
        [ -z "${candidate}" ] && continue
        if docker run --rm --entrypoint "" "${image}" sh -c "getent passwd '${candidate}' >/dev/null 2>&1"; then
            found="${candidate}"
            break
        fi
    done

    if [ -z "${found}" ]; then
        echo "ERROR: Could not find any expected user inside image '${image}'." >&2
        echo "Tried candidates: $*" >&2
        echo "" >&2
        echo "DEBUG: Listing passwd entries containing 'omero' from image '${image}':" >&2
        docker run --rm --entrypoint "" "${image}" sh -c "getent passwd | grep -i omero || true" >&2 || true
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

    local out=""

    if ! out="$(docker run --rm --entrypoint "" "${image}" sh -c "id ${id_flag} '${user_name}'" 2>/dev/null)"; then
        echo "ERROR: Failed to discover id ${id_flag} for user '${user_name}' from image '${image}'." >&2
        docker run --rm --entrypoint "" "${image}" sh -c "getent passwd '${user_name}' || true" >&2 || true
        return 1
    fi

    if ! [[ "${out}" =~ ^[0-9]+$ ]]; then
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

discover_container_default_id_or_die() {
    local image="$1"
    local id_flag="$2"

    local out=""

    if ! out="$(docker run --rm --entrypoint "" "${image}" sh -c "id ${id_flag}" 2>/dev/null)"; then
        echo "ERROR: Failed to discover default runtime id ${id_flag} from image '${image}'." >&2
        return 1
    fi

    if ! [[ "${out}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Discovered non-numeric default runtime id (${id_flag})='${out}' in image '${image}'." >&2
        return 1
    fi

    printf '%s' "${out}"
    return 0
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
if [ -z "${DATABASE_IMAGE}" ]; then DATABASE_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "database")"; fi
if [ -z "${DATABASE_PLUGIN_IMAGE}" ]; then DATABASE_PLUGIN_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "database_plugin")"; fi

if [ -z "${PROMETHEUS_UID}" ]; then PROMETHEUS_UID="$(discover_container_default_id_or_die "${PROMETHEUS_IMAGE}" "-u")"; fi
if [ -z "${PROMETHEUS_GID}" ]; then PROMETHEUS_GID="$(discover_container_default_id_or_die "${PROMETHEUS_IMAGE}" "-g")"; fi
if [ -z "${GRAFANA_UID}" ]; then GRAFANA_UID="$(discover_container_default_id_or_die "${GRAFANA_IMAGE}" "-u")"; fi
if [ -z "${GRAFANA_GID}" ]; then GRAFANA_GID="$(discover_container_default_id_or_die "${GRAFANA_IMAGE}" "-g")"; fi
if [ -z "${LOKI_UID}" ]; then LOKI_UID="$(discover_container_default_id_or_die "${LOKI_IMAGE}" "-u")"; fi
if [ -z "${LOKI_GID}" ]; then LOKI_GID="$(discover_container_default_id_or_die "${LOKI_IMAGE}" "-g")"; fi
if [ -z "${DATABASE_UID}" ]; then DATABASE_UID="$(discover_container_default_id_or_die "${DATABASE_IMAGE}" "-u")"; fi
if [ -z "${DATABASE_GID}" ]; then DATABASE_GID="$(discover_container_default_id_or_die "${DATABASE_IMAGE}" "-g")"; fi
if [ -z "${DATABASE_PLUGIN_UID}" ]; then DATABASE_PLUGIN_UID="$(discover_container_default_id_or_die "${DATABASE_PLUGIN_IMAGE}" "-u")"; fi
if [ -z "${DATABASE_PLUGIN_GID}" ]; then DATABASE_PLUGIN_GID="$(discover_container_default_id_or_die "${DATABASE_PLUGIN_IMAGE}" "-g")"; fi

echo "OMERO.server UID:GID = ${OMERO_SERVER_UID}:${OMERO_SERVER_GID} (image=${OMERO_SERVER_IMAGE})"
echo "OMERO.web    UID:GID = ${OMERO_WEB_UID}:${OMERO_WEB_GID} (image=${OMERO_WEB_IMAGE})"
echo "Prometheus   UID:GID = ${PROMETHEUS_UID}:${PROMETHEUS_GID} (image=${PROMETHEUS_IMAGE})"
echo "Grafana      UID:GID = ${GRAFANA_UID}:${GRAFANA_GID} (image=${GRAFANA_IMAGE})"
echo "Loki         UID:GID = ${LOKI_UID}:${LOKI_GID} (image=${LOKI_IMAGE})"
echo "Database     UID:GID = ${DATABASE_UID}:${DATABASE_GID} (image=${DATABASE_IMAGE})"
echo "DB Plugin    UID:GID = ${DATABASE_PLUGIN_UID}:${DATABASE_PLUGIN_GID} (image=${DATABASE_PLUGIN_IMAGE})"
echo ""

echo "================================================"
echo "Fixing host bind-mount ownership based on ACTUAL UID/GID"
echo "================================================"

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

if ! chown_tree_or_die "${OMERO_USER_DATA_PATH}" "OMERO user data directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_USER_DATA_PATH%/}/certs" "OMERO certificate directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_SERVER_VAR_PATH}" "OMERO server var directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi

mkdir -p "${OMERO_SERVER_VAR_PATH%/}/tmp"
chown "${OMERO_SERVER_UID}:${OMERO_SERVER_GID}" "${OMERO_SERVER_VAR_PATH%/}/tmp" || true
chmod 1777 "${OMERO_SERVER_VAR_PATH%/}/tmp" || true

if ! chown_tree_or_die "${OMERO_SERVER_LOGS_PATH}" "OMERO server logs directory" "${OMERO_SERVER_UID}" "${OMERO_SERVER_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_WEB_LOGS_PATH}" "OMERO web logs directory" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_WEB_SUPERVISOR_LOGS_PATH}" "OMERO web supervisor logs directory" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_UPLOAD_PATH}" "OMERO upload directory" "${OMERO_WEB_UID}" "${OMERO_WEB_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_DATABASE_PATH}" "OMERO database directory" "${DATABASE_UID}" "${DATABASE_GID}"; then exit 1; fi
if ! chown_tree_or_die "${OMERO_PLUGIN_DATABASE_PATH}" "OMP plugin database directory" "${DATABASE_PLUGIN_UID}" "${DATABASE_PLUGIN_GID}"; then exit 1; fi
if ! chown_tree_or_die "${PROMETHEUS_DATA_PATH}" "Prometheus data directory" "${PROMETHEUS_UID}" "${PROMETHEUS_GID}"; then exit 1; fi
if ! chown_tree_or_die "${GRAFANA_DATA_PATH}" "Grafana data directory" "${GRAFANA_UID}" "${GRAFANA_GID}"; then exit 1; fi
if ! chown_tree_or_die "${LOKI_DATA_PATH}" "Loki data directory" "${LOKI_UID}" "${LOKI_GID}"; then exit 1; fi

echo ""
echo "✔ Host ownership fix complete."
echo "================================================"
echo ""

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

    echo "================================================"
    echo "Checking ext4 project quota support for Quotas"
    echo "================================================"

    if [ ! -f "${installer_path}" ]; then
        echo "INFO: Quota enforcer installer not found at ${installer_path}."
        echo "INFO: Skipping quota enforcer installation."
        return 0
    fi

    # ── Detect filesystem type for OMERO user data path ──
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

    # ── Check prjquota mount option ──
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

    # ── Check ext4 project feature in superblock ──
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
    echo "Ensured .admin-tools directory permissions for omeroweb container (mode 0777, no sticky bit)."
else
    # Create it even if the quota enforcer wasn't installed, so the omeroweb
    # container can write the quota state file without permission errors.
    mkdir -p "${admin_tools_dir}/quota"
    chmod 0777 "${admin_tools_dir}" 2>/dev/null || true
    chmod 0777 "${admin_tools_dir}/quota" 2>/dev/null || true
    echo "Created .admin-tools directory with write permissions for omeroweb container (mode 0777, no sticky bit)."
fi

echo "================================================"
echo ""

if [ "${START_CONTAINERS}" -eq 1 ]; then
    compose_up_with_retries "${COMPOSE_FILE}"

    if ! create_omero_groups_from_list "${COMPOSE_FILE}" "${OMERO_INSTALL_GROUP_LIST:-}"; then
        exit 1
    fi
else
    echo "Skipping container startup (START_CONTAINERS=0)."
fi

echo "Done. Wait 30 seconds and check if the containers are up and running."
