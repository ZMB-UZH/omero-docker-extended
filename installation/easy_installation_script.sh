#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASE_METADATA_TOOL="${REPO_ROOT_DIR}/tools/prebuilt_release_metadata.py"

# Validate a docker-compatible SemVer release tag. Inputs: shell arguments and environment. Output: command status.
is_valid_release_version() {
    python3 "${RELEASE_METADATA_TOOL}" \
        --validate-release-version "${1:-}" \
        >/dev/null 2>&1
}

# Verify the installation root contains the strict-prebuilt installer support.
# Inputs: environment. Output: command status and a precise diagnostic.
require_easy_installation_support() {
    local installer_path="${SCRIPT_DIR}/installation_script.sh"
    local loader_path="${SCRIPT_DIR}/load_prebuilt_carrier.sh"
    local compose_path="${REPO_ROOT_DIR}/docker-compose.yml"
    local env_guard_path="${REPO_ROOT_DIR}/tools/env_safety_guard.py"

    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 is required for easy installation release validation." >&2
        return 1
    fi

    if [ ! -r "${installer_path}" ]; then
        echo "ERROR: Missing canonical installer: ${installer_path}" >&2
        return 1
    fi

    if ! grep -q "PREBUILT_IMAGE_MODE" "${installer_path}" || \
        ! grep -q "run_prebuilt_image_load" "${installer_path}"; then
        echo "ERROR: This installation root is too old for easy installation: ${REPO_ROOT_DIR}" >&2
        echo "ERROR: Run ./github_pull_project_bash from the installation root to refresh repository-managed files, then rerun installation/easy_installation_script.sh." >&2
        return 1
    fi

    if [ ! -r "${RELEASE_METADATA_TOOL}" ]; then
        echo "ERROR: Missing release metadata validator: ${RELEASE_METADATA_TOOL}" >&2
        echo "ERROR: Run ./github_pull_project_bash from the installation root to refresh repository-managed files before easy installation." >&2
        return 1
    fi

    if ! python3 -m py_compile "${RELEASE_METADATA_TOOL}" >/dev/null 2>&1; then
        echo "ERROR: Release metadata validator is not executable Python: ${RELEASE_METADATA_TOOL}" >&2
        echo "ERROR: Run ./github_pull_project_bash from the installation root to refresh repository-managed files before easy installation." >&2
        return 1
    fi

    if [ ! -x "${loader_path}" ]; then
        echo "ERROR: Missing or non-executable prebuilt carrier loader: ${loader_path}" >&2
        echo "ERROR: Run ./github_pull_project_bash from the installation root to refresh repository-managed files, then rerun installation/easy_installation_script.sh." >&2
        return 1
    fi

    if [ ! -r "${compose_path}" ]; then
        echo "ERROR: Missing docker-compose.yml from installation root: ${compose_path}" >&2
        echo "ERROR: Run ./github_pull_project_bash from the installation root to refresh repository-managed files before easy installation." >&2
        return 1
    fi

    if [ ! -r "${env_guard_path}" ]; then
        echo "ERROR: Missing deployment env validator: ${env_guard_path}" >&2
        echo "ERROR: Run ./github_pull_project_bash from the installation root to refresh repository-managed files before easy installation." >&2
        return 1
    fi
}

# Prompt for the prebuilt docker image tag. Inputs: shell arguments and environment. Output: exported release value or failure.
has_controlling_tty() {
    [ -r /dev/tty ] && [ -w /dev/tty ] && { : </dev/tty >/dev/tty; } 2>/dev/null
}

# Prompt for the prebuilt docker image tag. Inputs: shell arguments and environment. Output: exported release value or failure.
prompt_release_version() {
    local reply=""

    if [ -n "${PREBUILT_IMAGE_RELEASE:-}" ]; then
        if ! is_valid_release_version "${PREBUILT_IMAGE_RELEASE}"; then
            echo "ERROR: PREBUILT_IMAGE_RELEASE must be a docker-compatible SemVer release without a v prefix, + metadata, slash, colon, or spaces." >&2
            return 1
        fi
        return 0
    fi

    if [ "${INSTALLATION_AUTOMATION_MODE:-0}" = "1" ] || ! has_controlling_tty; then
        echo "ERROR: PREBUILT_IMAGE_RELEASE is required when /dev/tty is unavailable or INSTALLATION_AUTOMATION_MODE=1." >&2
        return 1
    fi

    while true; do
        printf '%s\n' "Which prebuilt docker image tag should be installed?" >/dev/tty
        printf '%s' '> ' >/dev/tty
        if ! IFS= read -r reply </dev/tty; then
            echo "ERROR: Could not read prebuilt docker image tag." >&2
            return 1
        fi
        if is_valid_release_version "${reply}"; then
            PREBUILT_IMAGE_RELEASE="${reply}"
            export PREBUILT_IMAGE_RELEASE
            return 0
        fi
        printf '%s\n' "Invalid release version. Use docker-compatible SemVer without v prefix, + metadata, slash, colon, or spaces." >/dev/tty
    done
}

if ! require_easy_installation_support; then
    exit 1
fi

if ! prompt_release_version; then
    exit 1
fi

export PREBUILT_IMAGE_MODE="require"

exec "${SCRIPT_DIR}/installation_script.sh" "$@"
