#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Validate a Docker-compatible SemVer release tag. Inputs: shell arguments and environment. Output: command status.
is_valid_release_version() {
    python3 "${REPO_ROOT_DIR}/tools/prebuilt_release_metadata.py" \
        --validate-release-version "${1:-}" \
        >/dev/null 2>&1
}

# Prompt for the prebuilt release version. Inputs: shell arguments and environment. Output: exported release value or failure.
prompt_release_version() {
    local reply=""

    if [ -n "${PREBUILT_IMAGE_RELEASE:-}" ]; then
        if ! is_valid_release_version "${PREBUILT_IMAGE_RELEASE}"; then
            echo "ERROR: PREBUILT_IMAGE_RELEASE must be a Docker-compatible SemVer release such as 0.1.0-beta.1." >&2
            return 1
        fi
        return 0
    fi

    if [ "${INSTALLATION_AUTOMATION_MODE:-0}" = "1" ] || [ ! -r /dev/tty ]; then
        echo "ERROR: PREBUILT_IMAGE_RELEASE is required when /dev/tty is unavailable or INSTALLATION_AUTOMATION_MODE=1." >&2
        return 1
    fi

    while true; do
        printf '%s\n' "Which prebuilt release version should be installed? (for example: 0.1.0-beta.1)" >/dev/tty
        printf '%s' '> ' >/dev/tty
        if ! IFS= read -r reply </dev/tty; then
            echo "ERROR: Could not read prebuilt release version." >&2
            return 1
        fi
        if is_valid_release_version "${reply}"; then
            PREBUILT_IMAGE_RELEASE="${reply}"
            export PREBUILT_IMAGE_RELEASE
            return 0
        fi
        printf '%s\n' "Invalid release version. Use Docker-compatible SemVer without v prefix, + metadata, slash, colon, or spaces." >/dev/tty
    done
}

if ! prompt_release_version; then
    exit 1
fi

export PREBUILT_IMAGE_MODE="require"

exec "${SCRIPT_DIR}/installation_script.sh" "$@"
