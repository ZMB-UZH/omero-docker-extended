#!/bin/sh

set -eu

SYSCTL_KEY="${SYSCTL_KEY:-vm.overcommit_memory}"
SYSCTL_VALUE="${SYSCTL_VALUE:-1}"
CONTAINER_NAME="${CONTAINER_NAME:-redis-sysctl-init}"
ACTION="${ACTION:-init}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-60}"

wait_for_container_stop() {
    elapsed=0
    while [ "${elapsed}" -lt "${WAIT_TIMEOUT_SECONDS}" ]; do
        running_state="$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || true)"

        if [ -z "${running_state}" ]; then
            return 0
        fi

        if [ "${running_state}" = "false" ]; then
            return 0
        fi

        sleep 1
        elapsed=$((elapsed + 1))
    done

    echo "Timed out waiting ${WAIT_TIMEOUT_SECONDS}s for ${CONTAINER_NAME} to stop before deletion." >&2
    return 1
}

run_init() {
    sysctl -w "${SYSCTL_KEY}=${SYSCTL_VALUE}" || true
}

run_cleanup() {
    if [ -S /var/run/docker.sock ]; then
        wait_for_container_stop
        docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
        # Self-destruct: spawn a detached --rm container that waits for
        # this container to stop, removes it, then auto-removes itself.
        SELF_NAME="${SELF_CONTAINER_NAME:-}"
        if [ -n "${SELF_NAME}" ]; then
            docker run --rm -d \
                -v /var/run/docker.sock:/var/run/docker.sock \
                --name "${SELF_NAME}-gc" \
                docker:29.2.1-cli \
                sh -c "docker wait '${SELF_NAME}' >/dev/null 2>&1; docker rm '${SELF_NAME}' >/dev/null 2>&1 || true" \
                >/dev/null 2>&1 || true
        fi
    fi
}

case "${ACTION}" in
    init)
        run_init
        ;;
    cleanup)
        run_cleanup
        ;;
    *)
        echo "Invalid ACTION: ${ACTION}. Expected 'init' or 'cleanup'." >&2
        exit 1
        ;;
esac

exit 0
