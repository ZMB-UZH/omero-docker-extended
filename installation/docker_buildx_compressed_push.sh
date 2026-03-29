#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT_DIR}/docker-compose.yml}"
DOCKER_BUILD_TARGETS="${DOCKER_BUILD_TARGETS:-}"
DOCKER_REGISTRY_PREFIX="${DOCKER_REGISTRY_PREFIX:-}"
DOCKER_IMAGE_TAG="${DOCKER_IMAGE_TAG:-custom}"
DOCKER_BUILD_COMPRESSION_TYPE="${DOCKER_BUILD_COMPRESSION_TYPE:-zstd}"
DOCKER_BUILD_COMPRESSION_LEVEL="${DOCKER_BUILD_COMPRESSION_LEVEL:-12}"
DOCKER_BUILD_USE_OCI_MEDIATYPES="${DOCKER_BUILD_USE_OCI_MEDIATYPES:-1}"
DOCKER_BUILD_PUSH_IMAGES="${DOCKER_BUILD_PUSH_IMAGES:-}"
DOCKER_BUILD_INLINE_CACHE="${DOCKER_BUILD_INLINE_CACHE:-1}"
DOCKER_BUILD_NO_CACHE="${DOCKER_BUILD_NO_CACHE:-0}"
DOCKER_BUILD_PROVENANCE="${DOCKER_BUILD_PROVENANCE:-0}"
DOCKER_BUILD_LOCAL_CACHE_ENABLED="${DOCKER_BUILD_LOCAL_CACHE_ENABLED:-1}"
DOCKER_BUILD_LOCAL_CACHE_MODE="${DOCKER_BUILD_LOCAL_CACHE_MODE:-min}"
DOCKER_BUILD_BAKE_RETRY_COUNT="${DOCKER_BUILD_BAKE_RETRY_COUNT:-3}"
DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS="${DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS:-2}"
DOCKER_BUILD_BAKE_SERIAL_MODE="${DOCKER_BUILD_BAKE_SERIAL_MODE:-auto}"
DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE:-0}"
DOCKER_BUILD_FLATTEN_ONLY="${DOCKER_BUILD_FLATTEN_ONLY:-0}"
# Named docker-container driver builder. The docker (default) driver does NOT
# support cache-to=type=local; only the docker-container driver does.
DOCKER_BUILDX_BUILDER_NAME="${DOCKER_BUILDX_BUILDER_NAME:-omero-builder}"
DOCKER_BUILDX_DRIVER="${DOCKER_BUILDX_DRIVER:-docker-container}"
DOCKER_BUILDX_DRIVER_OPTS="${DOCKER_BUILDX_DRIVER_OPTS:-}"
DOCKER_BUILDX_FORCE_RECREATE_BUILDER="${DOCKER_BUILDX_FORCE_RECREATE_BUILDER:-0}"
DOCKER_BUILDX_KEEP_BUILDER="${DOCKER_BUILDX_KEEP_BUILDER:-0}"
# Buildx/BuildKit bootstrap can hang indefinitely when the docker-container
# driver builder is in a broken state. Enforce a timeout and recreate the
# builder on failure.
DOCKER_BUILDX_BOOTSTRAP_TIMEOUT_SECONDS="${DOCKER_BUILDX_BOOTSTRAP_TIMEOUT_SECONDS:-60}"
DOCKER_BUILDX_BOOTSTRAP_ATTEMPTS="${DOCKER_BUILDX_BOOTSTRAP_ATTEMPTS:-2}"

readonly SCRIPT_NAME
readonly SCRIPT_DIR
readonly REPO_ROOT_DIR

LAST_BUILDX_FAILURE_TRANSIENT_LOCK=0
LAST_BUILDX_FAILURE_TRANSIENT_CACHE_EXPORT=0
LOCAL_CACHE_ROTATION_TOKEN=""
FLATTEN_TEMP_IMAGES=()
FLATTEN_TEMP_DIRS=()
FLATTEN_TEMP_CONTAINERS=()
BUILDX_RUNTIME_CLEANUP_ARMED=0

require_binary() {
    local binary_name="${1:?BUG: require_binary requires a binary name}"
    if ! command -v "${binary_name}" >/dev/null 2>&1; then
        echo "ERROR (${SCRIPT_NAME}): Required binary not found: ${binary_name}" >&2
        return 1
    fi
    return 0
}

require_non_empty() {
    local variable_name="${1:?BUG: require_non_empty requires a variable name}"
    local variable_value="${2-}"
    if [ -z "${variable_value}" ]; then
        echo "ERROR (${SCRIPT_NAME}): Missing required variable: ${variable_name}" >&2
        return 1
    fi
    return 0
}

validate_toggle() {
    local variable_name="${1:?BUG: validate_toggle requires variable name}"
    local variable_value="${2-}"
    if [ "${variable_value}" != "0" ] && [ "${variable_value}" != "1" ]; then
        echo "ERROR (${SCRIPT_NAME}): ${variable_name} must be 0 or 1. Got: ${variable_value}" >&2
        return 1
    fi
    return 0
}

validate_positive_integer() {
    local variable_name="${1:?BUG: validate_positive_integer requires variable name}"
    local variable_value="${2-}"
    if ! [[ "${variable_value}" =~ ^[0-9]+$ ]]; then
        echo "ERROR (${SCRIPT_NAME}): ${variable_name} must be a non-negative integer. Got: ${variable_value}" >&2
        return 1
    fi
    return 0
}

validate_local_cache_mode() {
    case "${DOCKER_BUILD_LOCAL_CACHE_MODE}" in
        min|max) return 0 ;;
        *)
            echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILD_LOCAL_CACHE_MODE must be one of: min, max. Got: ${DOCKER_BUILD_LOCAL_CACHE_MODE}" >&2
            return 1
            ;;
    esac
}

validate_serial_mode() {
    case "${DOCKER_BUILD_BAKE_SERIAL_MODE}" in
        auto|always|never) return 0 ;;
        *)
            echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILD_BAKE_SERIAL_MODE must be one of: auto, always, never. Got: ${DOCKER_BUILD_BAKE_SERIAL_MODE}" >&2
            return 1
            ;;
    esac
}

validate_buildx_driver() {
    case "${DOCKER_BUILDX_DRIVER}" in
        docker-container)
            return 0
            ;;
        *)
            echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILDX_DRIVER must be docker-container. Got: ${DOCKER_BUILDX_DRIVER}" >&2
            return 1
            ;;
    esac
}

resolve_builder_driver() {
    local builder_name="${1:?BUG: resolve_builder_driver requires builder name}"
    docker buildx inspect "${builder_name}" 2>/dev/null | awk '/^Driver:/ {print $2; exit}' || true
}

is_transient_layer_lock_error() {
    local output_file="${1:?BUG: is_transient_layer_lock_error requires output file path}"
    if [ ! -r "${output_file}" ]; then
        return 1
    fi

    if grep -Eq "ERROR: \(\*service\)\.Write failed: rpc error: code = Unavailable desc = ref layer-sha256:.* locked .*: unavailable" "${output_file}"; then
        return 0
    fi
    return 1
}

is_transient_cache_export_error() {
    local output_file="${1:?BUG: is_transient_cache_export_error requires output file path}"
    if [ ! -r "${output_file}" ]; then
        return 1
    fi

    if grep -Eq "failed to receive status: rpc error: code = Unavailable desc = error reading from server: EOF" "${output_file}"; then
        return 0
    fi

    if grep -Eq "exporting cache to client directory" "${output_file}" && grep -Eq "rpc error: code = Unavailable" "${output_file}"; then
        return 0
    fi

    return 1
}

run_buildx_bake_with_retries() {
    local max_attempts="${DOCKER_BUILD_BAKE_RETRY_COUNT}"
    local sleep_seconds="${DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS}"
    local attempt=1
    local output_file=""
    local saw_transient_lock="0"
    local saw_transient_cache_export="0"

    LAST_BUILDX_FAILURE_TRANSIENT_LOCK=0
    LAST_BUILDX_FAILURE_TRANSIENT_CACHE_EXPORT=0

    while [ "${attempt}" -le "${max_attempts}" ]; do
        output_file="$(mktemp)"
        set +e
        docker buildx bake \
            --file "${COMPOSE_FILE}" \
            --provenance "$(as_bool_literal "${DOCKER_BUILD_PROVENANCE}")" \
            ${DOCKER_BUILD_TARGETS} \
            "${TARGET_OVERRIDES[@]}" 2>&1 | tee "${output_file}"
        local build_exit_code=${PIPESTATUS[0]}
        set -e

        if [ "${build_exit_code}" -eq 0 ]; then
            rm -f "${output_file}"
            return 0
        fi

        if is_transient_layer_lock_error "${output_file}" && [ "${attempt}" -lt "${max_attempts}" ]; then
            saw_transient_lock="1"
            echo "WARNING (${SCRIPT_NAME}): Buildx bake failed due to transient layer lock contention; retrying (${attempt}/${max_attempts}) in ${sleep_seconds}s..." >&2
            rm -f "${output_file}"
            sleep "${sleep_seconds}"
            attempt=$((attempt + 1))
            continue
        fi

        if is_transient_cache_export_error "${output_file}" && [ "${attempt}" -lt "${max_attempts}" ]; then
            saw_transient_cache_export="1"
            echo "WARNING (${SCRIPT_NAME}): Buildx bake failed during cache export transport (BuildKit Unavailable/EOF); retrying (${attempt}/${max_attempts}) in ${sleep_seconds}s..." >&2
            rm -f "${output_file}"
            sleep "${sleep_seconds}"
            attempt=$((attempt + 1))
            continue
        fi

        if is_transient_layer_lock_error "${output_file}"; then
            saw_transient_lock="1"
        fi
        if is_transient_cache_export_error "${output_file}"; then
            saw_transient_cache_export="1"
        fi

        echo "ERROR (${SCRIPT_NAME}): Buildx bake failed on attempt ${attempt}/${max_attempts}." >&2
        rm -f "${output_file}"
        LAST_BUILDX_FAILURE_TRANSIENT_LOCK="${saw_transient_lock}"
        LAST_BUILDX_FAILURE_TRANSIENT_CACHE_EXPORT="${saw_transient_cache_export}"
        return "${build_exit_code}"
    done

    echo "ERROR (${SCRIPT_NAME}): Buildx bake failed after ${max_attempts} attempt(s)." >&2
    LAST_BUILDX_FAILURE_TRANSIENT_LOCK="${saw_transient_lock}"
    LAST_BUILDX_FAILURE_TRANSIENT_CACHE_EXPORT="${saw_transient_cache_export}"
    return 1
}

count_build_targets() {
    local count=0
    local target=""
    for target in ${DOCKER_BUILD_TARGETS}; do
        count=$((count + 1))
    done
    printf '%s' "${count}"
}

as_bool_literal() {
    local toggle_value="${1:?BUG: as_bool_literal requires a value}"
    if [ "${toggle_value}" = "1" ]; then printf 'true'; return 0; fi
    if [ "${toggle_value}" = "0" ]; then printf 'false'; return 0; fi
    echo "ERROR (${SCRIPT_NAME}): Internal toggle conversion failure for value: ${toggle_value}" >&2
    return 1
}

validate_compression_type() {
    case "${DOCKER_BUILD_COMPRESSION_TYPE}" in
        gzip|zstd|estargz) return 0 ;;
        *)
            echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILD_COMPRESSION_TYPE must be one of: gzip, zstd, estargz. Got: ${DOCKER_BUILD_COMPRESSION_TYPE}" >&2
            return 1
            ;;
    esac
}

validate_compression_level() {
    if ! [[ "${DOCKER_BUILD_COMPRESSION_LEVEL}" =~ ^[0-9]+$ ]]; then
        echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILD_COMPRESSION_LEVEL must be an integer. Got: ${DOCKER_BUILD_COMPRESSION_LEVEL}" >&2
        return 1
    fi
    if [ "${DOCKER_BUILD_COMPRESSION_LEVEL}" -lt 0 ] || [ "${DOCKER_BUILD_COMPRESSION_LEVEL}" -gt 22 ]; then
        echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILD_COMPRESSION_LEVEL must be between 0 and 22. Got: ${DOCKER_BUILD_COMPRESSION_LEVEL}" >&2
        return 1
    fi
    return 0
}

validate_compose_file() {
    if [ ! -r "${COMPOSE_FILE}" ]; then
        echo "ERROR (${SCRIPT_NAME}): Compose file is missing or unreadable: ${COMPOSE_FILE}" >&2
        return 1
    fi
    return 0
}

validate_build_targets() {
    local target=""
    require_non_empty "DOCKER_BUILD_TARGETS" "${DOCKER_BUILD_TARGETS}"
    for target in ${DOCKER_BUILD_TARGETS}; do
        if [[ "${target}" =~ [^a-zA-Z0-9._-] ]]; then
            echo "ERROR (${SCRIPT_NAME}): Invalid build target '${target}'. Allowed characters: a-z A-Z 0-9 . _ -" >&2
            return 1
        fi
    done
    return 0
}

compose_target_image_name() {
    local target="${1:?BUG: compose_target_image_name requires a target}"
    if [ -n "${DOCKER_REGISTRY_PREFIX}" ]; then
        printf '%s/%s:%s' "${DOCKER_REGISTRY_PREFIX}" "${target}" "${DOCKER_IMAGE_TAG}"
        return 0
    fi
    printf '%s:%s' "${target}" "${DOCKER_IMAGE_TAG}"
    return 0
}

resolve_target_image_name_from_compose() {
    local target="${1:?BUG: resolve_target_image_name_from_compose requires a target}"
    local rendered_compose=""
    local rendered_image=""

    if ! rendered_compose="$(render_active_compose_config)"; then
        echo "ERROR (${SCRIPT_NAME}): Failed to render active docker compose config from ${COMPOSE_FILE} while resolving image for target '${target}'." >&2
        return 1
    fi

    rendered_image="$(
        printf '%s\n' "${rendered_compose}" | awk -v service_name="${target}" '
            /^services:[[:space:]]*$/ { in_services=1; current_service=""; next }
            in_services == 1 && /^[^[:space:]]/ { exit }
            in_services == 1 {
                if ($0 ~ /^  [A-Za-z0-9_.-]+:[[:space:]]*$/) {
                    current_service=$0
                    sub(/^  /, "", current_service)
                    sub(/:.*/, "", current_service)
                    next
                }
                if (current_service == service_name && $0 ~ /^    image:[[:space:]]*/) {
                    image_line=$0
                    sub(/^    image:[[:space:]]*/, "", image_line)
                    print image_line
                    exit
                }
            }
        '
    )"

    if [ -n "${rendered_image}" ]; then
        printf '%s' "${rendered_image}"
        return 0
    fi

    compose_target_image_name "${target}"
    return 0
}

resolve_target_final_image_name() {
    local target="${1:?BUG: resolve_target_final_image_name requires a target}"

    if [ -n "${DOCKER_REGISTRY_PREFIX}" ]; then
        compose_target_image_name "${target}"
        return 0
    fi

    resolve_target_image_name_from_compose "${target}"
    return 0
}

compose_flatten_source_image_name() {
    local target="${1:?BUG: compose_flatten_source_image_name requires a target}"
    local final_image_name=""

    final_image_name="$(resolve_target_final_image_name "${target}")"
    printf '%s__flatten_source_%s' "${final_image_name}" "${LOCAL_CACHE_ROTATION_TOKEN}"
    return 0
}

compose_build_output_image_name() {
    local target="${1:?BUG: compose_build_output_image_name requires a target}"
    if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" = "1" ]; then
        compose_flatten_source_image_name "${target}"
        return 0
    fi

    compose_target_image_name "${target}"
    return 0
}

register_flatten_temp_image() {
    local image_name="${1:?BUG: register_flatten_temp_image requires an image name}"
    FLATTEN_TEMP_IMAGES+=("${image_name}")
    return 0
}

register_flatten_temp_dir() {
    local dir_path="${1:?BUG: register_flatten_temp_dir requires a directory path}"
    FLATTEN_TEMP_DIRS+=("${dir_path}")
    return 0
}

register_flatten_temp_source_images() {
    local target=""

    if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" != "1" ]; then
        return 0
    fi

    for target in ${DOCKER_BUILD_TARGETS}; do
        register_flatten_temp_image "$(compose_flatten_source_image_name "${target}")"
    done

    return 0
}

cleanup_flatten_artifacts() {
    local image_name=""
    local dir_path=""
    local container_name=""

    for container_name in "${FLATTEN_TEMP_CONTAINERS[@]:-}"; do
        if [ -n "${container_name}" ]; then
            docker container rm -f "${container_name}" >/dev/null 2>&1 || true
        fi
    done

    for image_name in "${FLATTEN_TEMP_IMAGES[@]:-}"; do
        if [ -n "${image_name}" ]; then
            docker image rm -f "${image_name}" >/dev/null 2>&1 || true
        fi
    done

    for dir_path in "${FLATTEN_TEMP_DIRS[@]:-}"; do
        if [ -n "${dir_path}" ]; then
            rm -rf "${dir_path}" >/dev/null 2>&1 || true
        fi
    done

    return 0
}

register_flatten_temp_container() {
    local container_name="${1:?BUG: register_flatten_temp_container requires a container name}"
    FLATTEN_TEMP_CONTAINERS+=("${container_name}")
    return 0
}

prepare_flatten_source_images_from_existing_tags() {
    local target=""
    local source_image_name=""
    local final_image_name=""

    if [ "${DOCKER_BUILD_FLATTEN_ONLY}" != "1" ]; then
        return 0
    fi

    for target in ${DOCKER_BUILD_TARGETS}; do
        final_image_name="$(resolve_target_final_image_name "${target}")"
        source_image_name="$(compose_flatten_source_image_name "${target}")"

        if ! docker image inspect "${final_image_name}" >/dev/null 2>&1; then
            echo "ERROR (${SCRIPT_NAME}): Cannot flatten '${target}' because the source image is missing: ${final_image_name}" >&2
            return 1
        fi

        docker image tag "${final_image_name}" "${source_image_name}"
        register_flatten_temp_image "${source_image_name}"
    done

    return 0
}

render_active_compose_config() {
    docker compose -f "${COMPOSE_FILE}" config
    return $?
}

resolve_build_targets_from_compose() {
    local rendered_compose=""
    local discovered_targets=""

    if ! rendered_compose="$(render_active_compose_config)"; then
        echo "ERROR (${SCRIPT_NAME}): Failed to render active docker compose config from ${COMPOSE_FILE} while discovering build targets." >&2
        return 1
    fi

    discovered_targets="$(printf '%s\n' "${rendered_compose}" | awk '
        /^services:[[:space:]]*$/ { in_services=1; current_service=""; service_has_build=0; next }
        in_services == 1 && /^[^[:space:]]/ {
            if (current_service != "" && service_has_build == 1) { printf "%s\n", current_service }
            in_services=0; next
        }
        in_services == 1 {
            if ($0 ~ /^  [A-Za-z0-9_.-]+:[[:space:]]*$/) {
                if (current_service != "" && service_has_build == 1) { printf "%s\n", current_service }
                service_line=$0
                sub(/^  /, "", service_line)
                sub(/:.*/, "", service_line)
                current_service=service_line
                service_has_build=0
                next
            }
            if (current_service != "" && $0 ~ /^    build:[[:space:]]*$/) { service_has_build=1; next }
        }
        END { if (in_services == 1 && current_service != "" && service_has_build == 1) { printf "%s\n", current_service } }
    ' | paste -sd' ' -)"

    if [ -z "${discovered_targets}" ]; then
        echo "ERROR (${SCRIPT_NAME}): Could not auto-discover active build targets from ${COMPOSE_FILE}." >&2
        echo "Set DOCKER_BUILD_TARGETS explicitly (space-separated service names) and retry." >&2
        return 1
    fi

    DOCKER_BUILD_TARGETS="${discovered_targets}"
    return 0
}

resolve_push_images_default() {
    if [ -n "${DOCKER_BUILD_PUSH_IMAGES}" ]; then
        printf '%s' "${DOCKER_BUILD_PUSH_IMAGES}"
        return 0
    fi

    if [ -n "${DOCKER_REGISTRY_PREFIX}" ]; then
        printf '1'
        return 0
    fi

    printf '0'
    return 0
}

resolve_local_cache_dir() {
    if [ -n "${BUILDX_DATA_PATH:-}" ]; then
        printf '%s' "${BUILDX_DATA_PATH}"
        return 0
    fi

    # Fallback to old behavior
    local base="${OMERO_DATA_PATH:-}"
    if [ -z "${base}" ]; then
        echo "ERROR (${SCRIPT_NAME}): BUILDX_DATA_PATH is not set, and OMERO_DATA_PATH is not set." >&2
        echo "       Cannot determine build cache location." >&2
        return 1
    fi

    base="${base%/}"
    printf '%s' "${base}/buildx_cache"
    return 0
}

resolve_target_cache_dir() {
    local cache_root="${1:?BUG: resolve_target_cache_dir requires cache root}"
    local target_name="${2:?BUG: resolve_target_cache_dir requires target name}"
    printf '%s' "${cache_root%/}/${target_name}"
    return 0
}

resolve_target_cache_staging_dir() {
    local target_cache_dir="${1:?BUG: resolve_target_cache_staging_dir requires cache dir}"
    local rotation_token="${2:?BUG: resolve_target_cache_staging_dir requires rotation token}"
    printf '%s' "${target_cache_dir}.staging.${rotation_token}"
    return 0
}

prepare_target_cache_staging_dir() {
    local target_cache_staging_dir="${1:?BUG: prepare_target_cache_staging_dir requires staging dir}"
    rm -rf "${target_cache_staging_dir}"
    mkdir -p "${target_cache_staging_dir}"
    return 0
}

swap_target_cache_staging_dir() {
    local target_cache_dir="${1:?BUG: swap_target_cache_staging_dir requires cache dir}"
    local target_cache_staging_dir="${2:?BUG: swap_target_cache_staging_dir requires staging dir}"
    local target_cache_previous_dir="${target_cache_dir}.previous"

    if [ ! -d "${target_cache_staging_dir}" ]; then
        echo "ERROR (${SCRIPT_NAME}): Expected staging cache directory is missing: ${target_cache_staging_dir}" >&2
        return 1
    fi

    rm -rf "${target_cache_previous_dir}"
    if [ -d "${target_cache_dir}" ]; then
        mv "${target_cache_dir}" "${target_cache_previous_dir}"
    fi
    mv "${target_cache_staging_dir}" "${target_cache_dir}"
    rm -rf "${target_cache_previous_dir}"
    return 0
}

cleanup_target_cache_staging_dir() {
    local target_cache_staging_dir="${1:?BUG: cleanup_target_cache_staging_dir requires staging dir}"
    rm -rf "${target_cache_staging_dir}"
    return 0
}

commit_local_cache_staging_dirs() {
    local cache_root=""
    local target=""
    local target_cache_dir=""
    local target_cache_staging_dir=""

    if [ "${DOCKER_BUILD_NO_CACHE}" = "1" ] || [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" != "1" ]; then
        return 0
    fi

    cache_root="$(resolve_local_cache_dir)"
    for target in ${DOCKER_BUILD_TARGETS}; do
        target_cache_dir="$(resolve_target_cache_dir "${cache_root}" "${target}")"
        target_cache_staging_dir="$(resolve_target_cache_staging_dir "${target_cache_dir}" "${LOCAL_CACHE_ROTATION_TOKEN}")"
        swap_target_cache_staging_dir "${target_cache_dir}" "${target_cache_staging_dir}"
    done

    return 0
}

cleanup_local_cache_staging_dirs() {
    local cache_root=""
    local target=""
    local target_cache_dir=""
    local target_cache_staging_dir=""

    if [ "${DOCKER_BUILD_NO_CACHE}" = "1" ] || [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" != "1" ]; then
        return 0
    fi

    cache_root="$(resolve_local_cache_dir)"
    for target in ${DOCKER_BUILD_TARGETS}; do
        target_cache_dir="$(resolve_target_cache_dir "${cache_root}" "${target}")"
        target_cache_staging_dir="$(resolve_target_cache_staging_dir "${target_cache_dir}" "${LOCAL_CACHE_ROTATION_TOKEN}")"
        cleanup_target_cache_staging_dir "${target_cache_staging_dir}"
    done

    return 0
}

generate_flatten_filesystem_dockerfile() {
    local source_image_name="${1:?BUG: generate_flatten_filesystem_dockerfile requires a source image name}"
    local dockerfile_path="${2:?BUG: generate_flatten_filesystem_dockerfile requires a dockerfile path}"

    if ! python3 - "${source_image_name}" >"${dockerfile_path}" <<'PY'
import sys

source_image_name = sys.argv[1]
for line in (
    f"FROM {source_image_name} AS source",
    "FROM scratch",
    "COPY --from=source / /",
):
    print(line)
PY
    then
        echo "ERROR (${SCRIPT_NAME}): Failed to generate flatten Dockerfile for source image '${source_image_name}'." >&2
        return 1
    fi

    return 0
}

build_flatten_import_changes() {
    local source_image_name="${1:?BUG: build_flatten_import_changes requires a source image name}"
    local image_metadata_json=""

    if ! image_metadata_json="$(docker image inspect "${source_image_name}" --format '{{json .}}')"; then
        echo "ERROR (${SCRIPT_NAME}): Failed to inspect metadata for source image '${source_image_name}' during flattening." >&2
        return 1
    fi

    if [ -z "${image_metadata_json}" ]; then
        echo "ERROR (${SCRIPT_NAME}): Flatten metadata inspection returned empty output for source image '${source_image_name}'." >&2
        return 1
    fi

    if ! IMAGE_METADATA_JSON="${image_metadata_json}" python3 - <<'PY'
import json
import os
import sys


def _compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _positive_int(value):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def _emit_healthcheck(config):
    healthcheck = config.get("Healthcheck") or {}
    test = healthcheck.get("Test") or []
    if not test:
        return []
    if test[0] == "NONE":
        return ["HEALTHCHECK NONE"]
    if test[0] == "CMD":
        command = "CMD " + _compact_json(test[1:] or [])
    elif test[0] == "CMD-SHELL":
        shell = config.get("Shell") or ["/bin/sh", "-c"]
        joined = " ".join(str(part) for part in (test[1:] or []))
        command = "CMD " + _compact_json(list(shell) + [joined])
    else:
        return []

    options = []
    for field_name, flag_name in (
        ("Interval", "--interval="),
        ("Timeout", "--timeout="),
        ("StartPeriod", "--start-period="),
        ("StartInterval", "--start-interval="),
    ):
        value = _positive_int(healthcheck.get(field_name))
        if value > 0:
            options.append(f"{flag_name}{value}ns")
    retries = _positive_int(healthcheck.get("Retries"))
    if retries > 0:
        options.append(f"--retries={retries}")
    if options:
        return [f"HEALTHCHECK {' '.join(options)} {command}"]
    return [f"HEALTHCHECK {command}"]


def _emit_import_changes(image_metadata):
    config = image_metadata.get("Config") or {}
    lines = []

    for env_entry in config.get("Env") or []:
        key, separator, value = str(env_entry).partition("=")
        if not separator or not key:
            continue
        lines.append(f"ENV {key}={_compact_json(value)}")

    labels = config.get("Labels") or {}
    for key in sorted(labels):
        lines.append(f"LABEL {key}={_compact_json(labels[key])}")

    exposed_ports = config.get("ExposedPorts") or {}
    for port_name in sorted(exposed_ports):
        lines.append(f"EXPOSE {port_name}")

    volumes = sorted((config.get("Volumes") or {}).keys())
    if volumes:
        lines.append(f"VOLUME {_compact_json(volumes)}")

    for dockerfile_key, config_key in (
        ("WORKDIR", "WorkingDir"),
        ("USER", "User"),
        ("STOPSIGNAL", "StopSignal"),
    ):
        raw_value = str(config.get(config_key) or "")
        if raw_value:
            lines.append(f"{dockerfile_key} {raw_value}")

    lines.extend(_emit_healthcheck(config))

    if config.get("Entrypoint") is not None:
        lines.append(f"ENTRYPOINT {_compact_json(config.get('Entrypoint') or [])}")
    if config.get("Cmd") is not None:
        lines.append(f"CMD {_compact_json(config.get('Cmd') or [])}")

    for onbuild_entry in config.get("OnBuild") or []:
        lines.append(f"ONBUILD {onbuild_entry}")

    return lines


raw_metadata = os.environ.get("IMAGE_METADATA_JSON", "")
if not raw_metadata:
    raise SystemExit(1)

try:
    metadata = json.loads(raw_metadata)
except json.JSONDecodeError:
    raise SystemExit(1)

for change_line in _emit_import_changes(metadata):
    if change_line:
        print(change_line)
PY
    then
        echo "ERROR (${SCRIPT_NAME}): Failed to derive flatten import metadata for source image '${source_image_name}'." >&2
        return 1
    fi

    return 0
}

flatten_target_image() {
    local target="${1:?BUG: flatten_target_image requires a target}"
    local source_image_name=""
    local final_image_name=""
    local flatten_context_dir=""
    local flatten_dockerfile=""
    local flatten_filesystem_image_name=""
    local flatten_container_name=""
    local flatten_import_changes_file=""
    local -a import_change_args=()
    local change_line=""

    source_image_name="$(compose_flatten_source_image_name "${target}")"
    final_image_name="$(resolve_target_final_image_name "${target}")"
    flatten_context_dir="$(mktemp -d)"
    register_flatten_temp_dir "${flatten_context_dir}"
    flatten_dockerfile="${flatten_context_dir}/Dockerfile"
    flatten_filesystem_image_name="${final_image_name}__flatten_fs_${LOCAL_CACHE_ROTATION_TOKEN}"
    flatten_container_name="flatten-${target//[^a-zA-Z0-9_.-]/-}-${LOCAL_CACHE_ROTATION_TOKEN}"
    flatten_import_changes_file="${flatten_context_dir}/import-changes.txt"
    register_flatten_temp_image "${flatten_filesystem_image_name}"
    register_flatten_temp_container "${flatten_container_name}"

    if ! docker image inspect "${source_image_name}" >/dev/null 2>&1; then
        echo "ERROR (${SCRIPT_NAME}): Flatten source image is missing for target '${target}': ${source_image_name}" >&2
        return 1
    fi

    if ! generate_flatten_filesystem_dockerfile "${source_image_name}" "${flatten_dockerfile}"; then
        return 1
    fi

    echo "INFO (${SCRIPT_NAME}): Flattening '${target}' into single-layer image '${final_image_name}'." >&2
    if ! docker build \
        --provenance "$(as_bool_literal "${DOCKER_BUILD_PROVENANCE}")" \
        --file "${flatten_dockerfile}" \
        --tag "${flatten_filesystem_image_name}" \
        "${flatten_context_dir}" >/dev/null; then
        echo "ERROR (${SCRIPT_NAME}): Failed to build temporary flatten filesystem image for target '${target}'." >&2
        return 1
    fi

    if ! build_flatten_import_changes "${source_image_name}" >"${flatten_import_changes_file}"; then
        return 1
    fi

    while IFS= read -r change_line; do
        if [ -n "${change_line}" ]; then
            import_change_args+=(--change "${change_line}")
        fi
    done < "${flatten_import_changes_file}"

    if ! docker container create --name "${flatten_container_name}" "${flatten_filesystem_image_name}" /bin/sh >/dev/null; then
        echo "ERROR (${SCRIPT_NAME}): Failed to create temporary flatten container for target '${target}'." >&2
        return 1
    fi

    if ! docker export "${flatten_container_name}" | docker image import "${import_change_args[@]}" - "${final_image_name}" >/dev/null; then
        echo "ERROR (${SCRIPT_NAME}): Failed to import flattened single-layer image for target '${target}'." >&2
        return 1
    fi

    if [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ]; then
        echo "INFO (${SCRIPT_NAME}): Pushing flattened image '${final_image_name}' via docker push." >&2
        if ! docker image push "${final_image_name}"; then
            echo "ERROR (${SCRIPT_NAME}): Failed to push flattened image '${final_image_name}'." >&2
            return 1
        fi
    fi

    echo "INFO (${SCRIPT_NAME}): Flattened '${target}' successfully." >&2
    docker container rm -f "${flatten_container_name}" >/dev/null 2>&1 || true
    docker image rm -f "${flatten_filesystem_image_name}" >/dev/null 2>&1 || true
    docker image rm -f "${source_image_name}" >/dev/null 2>&1 || true
    return 0
}

flatten_final_images_if_requested() {
    local target=""

    if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" != "1" ]; then
        return 0
    fi

    for target in ${DOCKER_BUILD_TARGETS}; do
        flatten_target_image "${target}"
    done

    return 0
}

finalize_build_outputs() {
    commit_local_cache_staging_dirs
    flatten_final_images_if_requested
    return 0
}

has_timeout() {
    command -v timeout >/dev/null 2>&1
}

run_with_optional_timeout() {
    local timeout_seconds="${1:?BUG: run_with_optional_timeout requires seconds}"
    shift

    if has_timeout; then
        timeout --preserve-status "${timeout_seconds}s" "$@"
        return $?
    fi

    "$@"
    return $?
}

cleanup_buildx_builder() {
    local builder_name="${1:?BUG: cleanup_buildx_builder requires a builder name}"

    # Remove the buildx builder (attempts to also remove the buildkit container)
    docker buildx rm -f "${builder_name}" >/dev/null 2>&1 || true

    # If any buildkit containers remain, force remove them.
    # Common name patterns:
    # - buildx_buildkit_<builder>0
    # - buildx_buildkit_<builder>1
    local ids=""
    ids="$(docker ps -a --filter "name=buildx_buildkit_${builder_name}" -q 2>/dev/null || true)"
    if [ -n "${ids}" ]; then
        # shellcheck disable=SC2086
        docker rm -f ${ids} >/dev/null 2>&1 || true
    fi

    return 0
}

cleanup_buildx_builder_volumes() {
    local builder_name="${1:?BUG: cleanup_buildx_builder_volumes requires a builder name}"
    local ids=""

    ids="$(docker volume ls -q --filter "name=buildx_buildkit_${builder_name}" 2>/dev/null || true)"
    if [ -n "${ids}" ]; then
        # shellcheck disable=SC2086
        docker volume rm -f ${ids} >/dev/null 2>&1 || true
    fi

    return 0
}

cleanup_buildx_runtime_artifacts() {
    if [ "${BUILDX_RUNTIME_CLEANUP_ARMED}" != "1" ]; then
        return 0
    fi

    cleanup_buildx_builder "${DOCKER_BUILDX_BUILDER_NAME}" || true
    cleanup_buildx_builder_volumes "${DOCKER_BUILDX_BUILDER_NAME}" || true
    BUILDX_RUNTIME_CLEANUP_ARMED=0
    return 0
}

ensure_builder() {
    # The docker (default) driver only supports inline cache export.
    # type=local cache-to requires the docker-container driver, which runs
    # BuildKit in a dedicated container and keeps the gRPC session alive for
    # the full bake, including the cache export phase (#33).

    local bootstrap_timeout="${DOCKER_BUILDX_BOOTSTRAP_TIMEOUT_SECONDS}"
    local bootstrap_attempts="${DOCKER_BUILDX_BOOTSTRAP_ATTEMPTS}"
    local existing_driver=""
    local create_cmd=()
    local driver_opt=""
    local -a driver_opts=()
    local attempt

    validate_positive_integer "DOCKER_BUILDX_BOOTSTRAP_TIMEOUT_SECONDS" "${bootstrap_timeout}"
    validate_positive_integer "DOCKER_BUILDX_BOOTSTRAP_ATTEMPTS" "${bootstrap_attempts}"
    if [ "${bootstrap_timeout}" -lt 1 ]; then
        echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILDX_BOOTSTRAP_TIMEOUT_SECONDS must be >= 1. Got: ${bootstrap_timeout}" >&2
        return 1
    fi
    if [ "${bootstrap_attempts}" -lt 1 ]; then
        echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILDX_BOOTSTRAP_ATTEMPTS must be >= 1. Got: ${bootstrap_attempts}" >&2
        return 1
    fi

    if [ "${DOCKER_BUILDX_FORCE_RECREATE_BUILDER}" = "1" ]; then
        echo "INFO (${SCRIPT_NAME}): DOCKER_BUILDX_FORCE_RECREATE_BUILDER=1, recreating buildx builder '${DOCKER_BUILDX_BUILDER_NAME}'." >&2
        cleanup_buildx_builder "${DOCKER_BUILDX_BUILDER_NAME}" || true
    fi

    if [ -n "${DOCKER_BUILDX_DRIVER_OPTS}" ]; then
        IFS=',' read -r -a driver_opts <<<"${DOCKER_BUILDX_DRIVER_OPTS}"
    fi

    for attempt in $(seq 1 "${bootstrap_attempts}"); do
        if ! docker buildx inspect "${DOCKER_BUILDX_BUILDER_NAME}" >/dev/null 2>&1; then
            create_cmd=(
                docker buildx create
                --name "${DOCKER_BUILDX_BUILDER_NAME}"
                --driver "${DOCKER_BUILDX_DRIVER}"
                --use
            )
            for driver_opt in "${driver_opts[@]}"; do
                if [ -n "${driver_opt}" ]; then
                    create_cmd+=(--driver-opt "${driver_opt}")
                fi
            done
            "${create_cmd[@]}" >/dev/null 2>&1
        else
            existing_driver="$(resolve_builder_driver "${DOCKER_BUILDX_BUILDER_NAME}")"
            if [ "${existing_driver}" != "${DOCKER_BUILDX_DRIVER}" ]; then
                echo "WARNING (${SCRIPT_NAME}): Existing builder '${DOCKER_BUILDX_BUILDER_NAME}' uses driver '${existing_driver}', expected '${DOCKER_BUILDX_DRIVER}'. Recreating builder to enforce deterministic driver selection." >&2
                cleanup_buildx_builder "${DOCKER_BUILDX_BUILDER_NAME}" || true
                continue
            fi
            docker buildx use "${DOCKER_BUILDX_BUILDER_NAME}" >/dev/null 2>&1 || true
        fi

        # NOTE: This can hang indefinitely on broken builders; enforce timeout.
        if run_with_optional_timeout "${bootstrap_timeout}" docker buildx inspect --bootstrap "${DOCKER_BUILDX_BUILDER_NAME}" >/dev/null 2>&1; then
            return 0
        fi

        if [ "${attempt}" -lt "${bootstrap_attempts}" ]; then
            echo "WARNING (${SCRIPT_NAME}): Buildx builder bootstrap failed or timed out (attempt ${attempt}/${bootstrap_attempts}, timeout ${bootstrap_timeout}s)." >&2
            echo "WARNING (${SCRIPT_NAME}): Recreating buildx builder '${DOCKER_BUILDX_BUILDER_NAME}'..." >&2
            cleanup_buildx_builder "${DOCKER_BUILDX_BUILDER_NAME}" || true
            sleep 1
            continue
        fi

        echo "ERROR (${SCRIPT_NAME}): Buildx builder bootstrap failed or timed out after ${bootstrap_attempts} attempt(s) (timeout ${bootstrap_timeout}s)." >&2
        echo "ERROR (${SCRIPT_NAME}): Try manual cleanup: docker buildx rm -f ${DOCKER_BUILDX_BUILDER_NAME} ; docker rm -f \"\$(docker ps -aq --filter name=buildx_buildkit_${DOCKER_BUILDX_BUILDER_NAME})\"" >&2
        return 1
    done

    return 1
}

build_target_overrides() {
    local target=""
    local target_image_name=""
    local oci_mediatypes_bool=""
    local push_bool=""
    local cache_dir=""
    local target_cache_dir=""
    local target_cache_staging_dir=""

    oci_mediatypes_bool="$(as_bool_literal "${DOCKER_BUILD_USE_OCI_MEDIATYPES}")"
    push_bool="$(as_bool_literal "${DOCKER_BUILD_PUSH_IMAGES}")"

    if [ "${DOCKER_BUILD_NO_CACHE}" = "0" ] && [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" = "1" ]; then
        cache_dir="$(resolve_local_cache_dir)"
        mkdir -p "${cache_dir}"
    fi

    for target in ${DOCKER_BUILD_TARGETS}; do
        target_image_name="$(compose_build_output_image_name "${target}")"

        printf -- '--set\n%s.tags=%s\n' "${target}" "${target_image_name}"
        printf -- '--set\n%s.args.BUILDKIT_INLINE_CACHE=%s\n' "${target}" "${DOCKER_BUILD_INLINE_CACHE}"

        # Optional Docker image security hardening build args
        # Controlled by APPLY_SECURITY_HARDENING from the installation script
        if [ "${APPLY_SECURITY_HARDENING:-0}" = "1" ]; then
            printf -- '--set\n%s.args.APPLY_SECURITY_HARDENING=1\n' "${target}"
            printf -- '--set\n%s.args.APPLY_DNF_UPDATES=1\n' "${target}"
            printf -- '--set\n%s.args.APPLY_OMERO_VENV_TOOLING_UPDATES=1\n' "${target}"
            printf -- '--set\n%s.args.APPLY_OMEROWEB_DNF_UPDATES=1\n' "${target}"
            printf -- '--set\n%s.args.APPLY_OMEROWEB_VENV_TOOLING_UPDATES=1\n' "${target}"
        fi

        if [ "${DOCKER_BUILD_NO_CACHE}" = "1" ]; then
            printf -- '--set\n%s.no-cache=true\n' "${target}"
        elif [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" = "1" ]; then
            # Buildx can run service builds in parallel. Exporting every target
            # to the same local cache path causes transient layer lock
            # contention ("ref layer-sha256 ... locked ... unavailable").
            # Keep each target cache isolated while retaining deterministic
            # cache persistence under a single configured root.
            target_cache_dir="$(resolve_target_cache_dir "${cache_dir}" "${target}")"
            mkdir -p "${target_cache_dir}"
            if [ -f "${target_cache_dir}/index.json" ]; then
                printf -- '--set\n%s.cache-from=type=local,src=%s\n' "${target}" "${target_cache_dir}"
            else
                echo "INFO (${SCRIPT_NAME}): Skipping cache import for '${target}' (no existing cache index at ${target_cache_dir}/index.json)." >&2
            fi
            target_cache_staging_dir="$(resolve_target_cache_staging_dir "${target_cache_dir}" "${LOCAL_CACHE_ROTATION_TOKEN}")"
            prepare_target_cache_staging_dir "${target_cache_staging_dir}"
            printf -- '--set\n%s.cache-to=type=local,dest=%s,mode=%s\n' "${target}" "${target_cache_staging_dir}" "${DOCKER_BUILD_LOCAL_CACHE_MODE}"
        fi

        if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" = "1" ]; then
            # Flattening requires local source images so a follow-up docker build
            # can reconstruct a scratch-based single-layer final image.
            printf -- '--set\n%s.output=type=docker\n' \
                "${target}"
        elif [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ]; then
            # Registry push: apply full compression settings.
            # force-compression=true is intentional here — it ensures all
            # layers in the pushed manifest use the target codec regardless
            # of how they were originally built.
            printf -- '--set\n%s.output=type=image,name=%s,push=%s,compression=%s,compression-level=%s,force-compression=true,oci-mediatypes=%s\n' \
                "${target}" \
                "${target_image_name}" \
                "${push_bool}" \
                "${DOCKER_BUILD_COMPRESSION_TYPE}" \
                "${DOCKER_BUILD_COMPRESSION_LEVEL}" \
                "${oci_mediatypes_bool}"
        else
            # Local build only (no registry push).
            # DO NOT use force-compression=true here.
            # force-compression causes BuildKit to decompress EVERY cached
            # layer back into memory and re-encode it with the target codec.
            # For large images this loads all layer data into RAM simultaneously
            # and causes a massive memory spike — completely pointless for a
            # local build where compression format is irrelevant.
            # With docker-container driver, type=image,push=false keeps the image
            # INSIDE the BuildKit daemon — NOT visible to the host Docker daemon.
            # type=docker exports it back to the host daemon via the Docker socket.
            printf -- '--set\n%s.output=type=docker\n' \
                "${target}"
        fi
    done
}

run_buildx_bake_serial_fallback() {
    local original_targets="${DOCKER_BUILD_TARGETS}"
    local target=""
    local target_count="$(count_build_targets)"

    if [ "${target_count}" -le 1 ]; then
        return 1
    fi

    echo "WARNING (${SCRIPT_NAME}): Falling back to serial per-target Buildx bake to avoid cache export lock contention." >&2

    for target in ${original_targets}; do
        echo "INFO (${SCRIPT_NAME}): Serial Buildx bake target: ${target}" >&2
        DOCKER_BUILD_TARGETS="${target}"

        set +e
        mapfile -t TARGET_OVERRIDES < <(build_target_overrides)
        OVERRIDES_EXIT_CODE=$?
        set -e

        if [ "${OVERRIDES_EXIT_CODE}" -ne 0 ]; then
            echo "ERROR (${SCRIPT_NAME}): Failed to construct build target overrides for target '${target}'." >&2
            DOCKER_BUILD_TARGETS="${original_targets}"
            return 1
        fi

        if ! run_buildx_bake_with_retries; then
            cleanup_local_cache_staging_dirs || true
            DOCKER_BUILD_TARGETS="${original_targets}"
            return 1
        fi

        commit_local_cache_staging_dirs
    done

    DOCKER_BUILD_TARGETS="${original_targets}"
    flatten_final_images_if_requested
    return 0
}

run_buildx_bake_without_local_cache_fallback() {
    local original_local_cache_enabled="${DOCKER_BUILD_LOCAL_CACHE_ENABLED}"

    if [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" != "1" ]; then
        return 1
    fi

    echo "WARNING (${SCRIPT_NAME}): Retrying Buildx bake with local cache export disabled due to cache-export transport failure (rpc Unavailable/EOF)." >&2
    DOCKER_BUILD_LOCAL_CACHE_ENABLED="0"

    set +e
    mapfile -t TARGET_OVERRIDES < <(build_target_overrides)
    OVERRIDES_EXIT_CODE=$?
    set -e

    if [ "${OVERRIDES_EXIT_CODE}" -ne 0 ]; then
        echo "ERROR (${SCRIPT_NAME}): Failed to construct build target overrides for no-local-cache fallback." >&2
        DOCKER_BUILD_LOCAL_CACHE_ENABLED="${original_local_cache_enabled}"
        return 1
    fi

    if run_buildx_bake_with_retries; then
        finalize_build_outputs
        DOCKER_BUILD_LOCAL_CACHE_ENABLED="${original_local_cache_enabled}"
        return 0
    fi

    cleanup_local_cache_staging_dirs || true
    DOCKER_BUILD_LOCAL_CACHE_ENABLED="${original_local_cache_enabled}"
    return 1
}

should_run_serial_mode() {
    local target_count
    target_count="$(count_build_targets)"

    case "${DOCKER_BUILD_BAKE_SERIAL_MODE}" in
        always) return 0 ;;
        never) return 1 ;;
        auto)
            # BuildKit local cache exporter is still prone to transient layer
            # lock contention during parallel multi-target exports. Prefer
            # serial target execution up front to avoid long retry loops.
            if [ "${target_count}" -gt 1 ] && [ "${DOCKER_BUILD_NO_CACHE}" = "0" ] && [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" = "1" ]; then
                return 0
            fi
            return 1
            ;;
        *)
            echo "ERROR (${SCRIPT_NAME}): Internal invalid serial mode value: ${DOCKER_BUILD_BAKE_SERIAL_MODE}" >&2
            return 1
            ;;
    esac
}

main() {
    local push_bool=""
    local oci_mediatypes_bool=""
    local now_epoch=""

    require_non_empty "DOCKER_IMAGE_TAG" "${DOCKER_IMAGE_TAG}"

    DOCKER_BUILD_PUSH_IMAGES="$(resolve_push_images_default)"

    if [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ]; then
        require_non_empty "DOCKER_REGISTRY_PREFIX" "${DOCKER_REGISTRY_PREFIX}"
    fi

    validate_compose_file

    if [ -z "${DOCKER_BUILD_TARGETS}" ]; then
        if ! resolve_build_targets_from_compose; then
            return 1
        fi
    fi

    validate_build_targets
    validate_compression_type
    validate_compression_level
    validate_toggle "DOCKER_BUILD_USE_OCI_MEDIATYPES" "${DOCKER_BUILD_USE_OCI_MEDIATYPES}"
    validate_toggle "DOCKER_BUILD_PUSH_IMAGES" "${DOCKER_BUILD_PUSH_IMAGES}"
    validate_toggle "DOCKER_BUILD_INLINE_CACHE" "${DOCKER_BUILD_INLINE_CACHE}"
    validate_toggle "DOCKER_BUILD_NO_CACHE" "${DOCKER_BUILD_NO_CACHE}"
    validate_toggle "DOCKER_BUILD_PROVENANCE" "${DOCKER_BUILD_PROVENANCE}"
    validate_toggle "DOCKER_BUILD_LOCAL_CACHE_ENABLED" "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}"
    validate_toggle "DOCKER_BUILD_FLATTEN_FINAL_IMAGE" "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}"
    validate_toggle "DOCKER_BUILD_FLATTEN_ONLY" "${DOCKER_BUILD_FLATTEN_ONLY}"
    validate_local_cache_mode
    validate_positive_integer "DOCKER_BUILD_BAKE_RETRY_COUNT" "${DOCKER_BUILD_BAKE_RETRY_COUNT}"
    validate_positive_integer "DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS" "${DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS}"
    validate_buildx_driver
    validate_toggle "DOCKER_BUILDX_FORCE_RECREATE_BUILDER" "${DOCKER_BUILDX_FORCE_RECREATE_BUILDER}"
    validate_toggle "DOCKER_BUILDX_KEEP_BUILDER" "${DOCKER_BUILDX_KEEP_BUILDER}"
    validate_serial_mode

    if [ "${DOCKER_BUILD_FLATTEN_ONLY}" = "1" ] && [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" != "1" ]; then
        echo "ERROR (${SCRIPT_NAME}): DOCKER_BUILD_FLATTEN_ONLY=1 requires DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1." >&2
        return 1
    fi

    now_epoch="$(date +%s)"
    LOCAL_CACHE_ROTATION_TOKEN="${now_epoch}.$$"

    require_binary docker

    if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" = "1" ]; then
        require_binary python3
        trap cleanup_flatten_artifacts EXIT
        if [ "${DOCKER_BUILD_FLATTEN_ONLY}" = "1" ]; then
            prepare_flatten_source_images_from_existing_tags
        else
            register_flatten_temp_source_images
        fi
    fi

    if [ "${DOCKER_BUILD_FLATTEN_ONLY}" = "1" ]; then
        echo "Running image flatten-only workflow with settings:"
        echo "  Compose file         : ${COMPOSE_FILE}"
        echo "  Build targets        : ${DOCKER_BUILD_TARGETS}"
        echo "  Provenance           : $(as_bool_literal "${DOCKER_BUILD_PROVENANCE}")"
        echo "  Flatten final image  : ${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}"
        echo "  Push                 : $(as_bool_literal "${DOCKER_BUILD_PUSH_IMAGES}")"
        flatten_final_images_if_requested
        return $?
    fi

    if ! docker buildx version >/dev/null 2>&1; then
        echo "ERROR (${SCRIPT_NAME}): docker buildx is required but not available." >&2
        echo "Install Docker Buildx and retry." >&2
        return 1
    fi

    ensure_builder
    if [ "${DOCKER_BUILDX_KEEP_BUILDER}" != "1" ]; then
        BUILDX_RUNTIME_CLEANUP_ARMED=1
        trap 'cleanup_buildx_runtime_artifacts; cleanup_flatten_artifacts' EXIT
    fi

    push_bool="$(as_bool_literal "${DOCKER_BUILD_PUSH_IMAGES}")"
    oci_mediatypes_bool="$(as_bool_literal "${DOCKER_BUILD_USE_OCI_MEDIATYPES}")"

    set +e
    mapfile -t TARGET_OVERRIDES < <(build_target_overrides)
    OVERRIDES_EXIT_CODE=$?
    set -e

    if [ "${OVERRIDES_EXIT_CODE}" -ne 0 ]; then
        echo "ERROR (${SCRIPT_NAME}): Failed to construct build target overrides." >&2
        return 1
    fi

    echo "Running Buildx bake for compressed images with settings:"
    echo "  Compose file         : ${COMPOSE_FILE}"
    echo "  Build targets        : ${DOCKER_BUILD_TARGETS}"
    if [ -n "${DOCKER_REGISTRY_PREFIX}" ]; then
        echo "  Registry prefix      : ${DOCKER_REGISTRY_PREFIX}"
    else
        echo "  Registry prefix      : (not set; building local images only)"
    fi
    echo "  Image tag            : ${DOCKER_IMAGE_TAG}"
    if [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ] && [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" != "1" ]; then
        echo "  Compression type     : ${DOCKER_BUILD_COMPRESSION_TYPE}"
        echo "  Compression level    : ${DOCKER_BUILD_COMPRESSION_LEVEL}"
        echo "  OCI mediatypes       : ${oci_mediatypes_bool}"
    elif [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ]; then
        echo "  Compression          : bypassed for final flattened publish (docker push)"
    else
        echo "  Compression          : disabled for local build (only applies on registry push)"
    fi
    echo "  Inline cache         : ${DOCKER_BUILD_INLINE_CACHE}"
    echo "  No-cache             : ${DOCKER_BUILD_NO_CACHE}"
    echo "  Provenance           : $(as_bool_literal "${DOCKER_BUILD_PROVENANCE}")"
    echo "  Local cache export   : ${DOCKER_BUILD_LOCAL_CACHE_ENABLED}"
    echo "  Local cache mode     : ${DOCKER_BUILD_LOCAL_CACHE_MODE}"
    echo "  Flatten final image  : ${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}"
    echo "  Push                 : ${push_bool}"
    echo "  Retry attempts       : ${DOCKER_BUILD_BAKE_RETRY_COUNT}"
    echo "  Retry delay (sec)    : ${DOCKER_BUILD_BAKE_RETRY_SLEEP_SECONDS}"
    echo "  Serial mode          : ${DOCKER_BUILD_BAKE_SERIAL_MODE}"
    echo "  Buildx driver        : ${DOCKER_BUILDX_DRIVER}"
    if [ -n "${DOCKER_BUILDX_DRIVER_OPTS}" ]; then
        echo "  Buildx driver opts   : ${DOCKER_BUILDX_DRIVER_OPTS}"
    else
        echo "  Buildx driver opts   : (none)"
    fi
    if [ "${DOCKER_BUILD_FLATTEN_FINAL_IMAGE}" = "1" ] && [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ]; then
        echo "  Push note            : flattened images are pushed via docker push; buildx compression settings do not apply to the final publish step"
    fi


    export DOCKER_BUILDKIT=1

    if should_run_serial_mode; then
        echo "INFO (${SCRIPT_NAME}): Running Buildx bake in serial mode to reduce cache export lock contention." >&2
        run_buildx_bake_serial_fallback
        cleanup_buildx_runtime_artifacts || true
        return $?
    fi

    if run_buildx_bake_with_retries; then
        finalize_build_outputs
        cleanup_buildx_runtime_artifacts || true
        return 0
    fi

    cleanup_local_cache_staging_dirs || true

    if [ "${LAST_BUILDX_FAILURE_TRANSIENT_LOCK}" = "1" ] && [ "$(count_build_targets)" -gt 1 ]; then
        run_buildx_bake_serial_fallback
        cleanup_buildx_runtime_artifacts || true
        return $?
    fi

    if [ "${LAST_BUILDX_FAILURE_TRANSIENT_CACHE_EXPORT}" = "1" ] && [ "${DOCKER_BUILD_LOCAL_CACHE_ENABLED}" = "1" ]; then
        run_buildx_bake_without_local_cache_fallback
        cleanup_buildx_runtime_artifacts || true
        return $?
    fi

    cleanup_buildx_runtime_artifacts || true
    return 1
}

main "$@"
