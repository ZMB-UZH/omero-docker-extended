#!/usr/bin/env bash

set -euo pipefail

marker_path="${CROWDSEC_AUTO_RESTART_MARKER:?Set CROWDSEC_AUTO_RESTART_MARKER}"
delay_seconds="${CROWDSEC_AUTO_RESTART_DELAY_SECONDS:-0}"
container_name="${CROWDSEC_AUTO_RESTART_CONTAINER_NAME:-crowdsec}"

# Return whether non negative integer. Inputs: shell arguments and environment. Output: success or failure status.
is_non_negative_integer() {
    case "${1:-}" in
        ""|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

if ! is_non_negative_integer "${delay_seconds}"; then
    echo "ERROR: CROWDSEC_AUTO_RESTART_DELAY_SECONDS must be an integer >= 0. Got: ${delay_seconds}" >&2
    exit 1
fi

# Cleanup marker. Inputs: shell arguments and environment. Output: command status and side effects.
cleanup_marker() {
    rm -f "${marker_path}" 2>/dev/null || true
}

trap cleanup_marker EXIT HUP INT TERM

sleep "${delay_seconds}"

if [ ! -f "${marker_path}" ]; then
    exit 0
fi

if ! docker inspect "${container_name}" >/dev/null 2>&1; then
    exit 0
fi

if [ "$(docker inspect --format '{{.State.Running}}' "${container_name}" 2>/dev/null || true)" != "true" ]; then
    exit 0
fi

docker restart "${container_name}" >/dev/null 2>&1 || true
