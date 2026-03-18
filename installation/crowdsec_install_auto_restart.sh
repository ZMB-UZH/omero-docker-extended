#!/usr/bin/env bash

set -euo pipefail

marker_path="${CROWDSEC_AUTO_RESTART_MARKER:?Set CROWDSEC_AUTO_RESTART_MARKER}"
delay_seconds="${CROWDSEC_AUTO_RESTART_DELAY_SECONDS:-0}"
container_name="${CROWDSEC_AUTO_RESTART_CONTAINER_NAME:-crowdsec}"

if ! [[ "${delay_seconds}" =~ ^[0-9]+$ ]] || [ "${delay_seconds}" -lt 0 ]; then
    echo "ERROR: CROWDSEC_AUTO_RESTART_DELAY_SECONDS must be an integer >= 0. Got: ${delay_seconds}" >&2
    exit 1
fi

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
