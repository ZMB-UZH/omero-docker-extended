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
DOCKER_BUILD_COMPRESSION_LEVEL="${DOCKER_BUILD_COMPRESSION_LEVEL:-15}"
DOCKER_BUILD_USE_OCI_MEDIATYPES="${DOCKER_BUILD_USE_OCI_MEDIATYPES:-1}"
DOCKER_BUILD_PUSH_IMAGES="${DOCKER_BUILD_PUSH_IMAGES:-}"
DOCKER_BUILD_INLINE_CACHE="${DOCKER_BUILD_INLINE_CACHE:-1}"
DOCKER_BUILDX_BUILDER_NAME="${DOCKER_BUILDX_BUILDER_NAME:-omero-compression-builder}"

readonly SCRIPT_NAME
readonly SCRIPT_DIR
readonly REPO_ROOT_DIR

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

as_bool_literal() {
    local toggle_value="${1:?BUG: as_bool_literal requires a value}"

    if [ "${toggle_value}" = "1" ]; then
        printf 'true'
        return 0
    fi

    if [ "${toggle_value}" = "0" ]; then
        printf 'false'
        return 0
    fi

    echo "ERROR (${SCRIPT_NAME}): Internal toggle conversion failure for value: ${toggle_value}" >&2
    return 1
}

validate_compression_type() {
    case "${DOCKER_BUILD_COMPRESSION_TYPE}" in
        gzip|zstd|estargz)
            return 0
            ;;
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


resolve_build_targets_from_compose() {
    local discovered_targets=""

    discovered_targets="$(awk '
        /^services:[[:space:]]*$/ { in_services=1; current_service=""; service_has_build=0; next }
        in_services == 1 && /^[^[:space:]]/ {
            if (current_service != "" && service_has_build == 1) {
                printf "%s\n", current_service
            }
            in_services=0
            next
        }
        in_services == 1 {
            if ($0 ~ /^  [A-Za-z0-9_.-]+:[[:space:]]*$/) {
                if (current_service != "" && service_has_build == 1) {
                    printf "%s\n", current_service
                }
                service_line=$0
                sub(/^  /, "", service_line)
                sub(/:.*/, "", service_line)
                current_service=service_line
                service_has_build=0
                next
            }

            if (current_service != "" && $0 ~ /^    build:[[:space:]]*$/) {
                service_has_build=1
                next
            }
        }
        END {
            if (in_services == 1 && current_service != "" && service_has_build == 1) {
                printf "%s\n", current_service
            }
        }
    ' "${COMPOSE_FILE}" | paste -sd' ' -)"

    if [ -z "${discovered_targets}" ]; then
        echo "ERROR (${SCRIPT_NAME}): Could not auto-discover build targets from ${COMPOSE_FILE}." >&2
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

ensure_builder() {
    if ! docker buildx inspect "${DOCKER_BUILDX_BUILDER_NAME}" >/dev/null 2>&1; then
        docker buildx create \
            --name "${DOCKER_BUILDX_BUILDER_NAME}" \
            --driver docker-container \
            --use \
            >/dev/null
    else
        docker buildx use "${DOCKER_BUILDX_BUILDER_NAME}" >/dev/null
    fi

    docker buildx inspect --bootstrap >/dev/null
}

build_target_overrides() {
    local target=""
    local target_image_name=""
    local oci_mediatypes_bool=""
    local push_bool=""

    oci_mediatypes_bool="$(as_bool_literal "${DOCKER_BUILD_USE_OCI_MEDIATYPES}")"
    push_bool="$(as_bool_literal "${DOCKER_BUILD_PUSH_IMAGES}")"

    for target in ${DOCKER_BUILD_TARGETS}; do
        target_image_name="$(compose_target_image_name "${target}")"

        printf -- '--set\n%s.tags=%s\n' "${target}" "${target_image_name}"
        printf -- '--set\n%s.args.BUILDKIT_INLINE_CACHE=%s\n' "${target}" "${DOCKER_BUILD_INLINE_CACHE}"
        if [ "${DOCKER_BUILD_PUSH_IMAGES}" = "1" ]; then
            printf -- '--set\n%s.output=type=image,name=%s,push=%s,compression=%s,compression-level=%s,force-compression=true,oci-mediatypes=%s\n' \
                "${target}" \
                "${target_image_name}" \
                "${push_bool}" \
                "${DOCKER_BUILD_COMPRESSION_TYPE}" \
                "${DOCKER_BUILD_COMPRESSION_LEVEL}" \
                "${oci_mediatypes_bool}"
        else
            printf -- '--set\n%s.output=type=docker,name=%s\n' \
                "${target}" \
                "${target_image_name}"
        fi
    done
}

main() {
    local push_bool=""
    local oci_mediatypes_bool=""

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

    require_binary docker

    if ! docker buildx version >/dev/null 2>&1; then
        echo "ERROR (${SCRIPT_NAME}): docker buildx is required but not available." >&2
        echo "Install Docker Buildx and retry." >&2
        return 1
    fi

    ensure_builder

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
    echo "  Compression type     : ${DOCKER_BUILD_COMPRESSION_TYPE}"
    echo "  Compression level    : ${DOCKER_BUILD_COMPRESSION_LEVEL}"
    echo "  OCI mediatypes       : ${oci_mediatypes_bool}"
    echo "  Inline cache         : ${DOCKER_BUILD_INLINE_CACHE}"
    echo "  Push                 : ${push_bool}"

    export DOCKER_BUILDKIT=1

    docker buildx bake \
        --file "${COMPOSE_FILE}" \
        ${DOCKER_BUILD_TARGETS} \
        "${TARGET_OVERRIDES[@]}"
}

main "$@"
