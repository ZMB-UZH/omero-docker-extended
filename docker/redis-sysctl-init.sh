#!/bin/sh

set -eu

SYSCTL_KEY="${SYSCTL_KEY:-vm.overcommit_memory}"
SYSCTL_VALUE="${SYSCTL_VALUE:-1}"
CONTAINER_NAME="${CONTAINER_NAME:-redis-sysctl-init}"
GC_IMAGE="${GC_IMAGE:-docker:29.2.1-cli}"

sysctl -w "${SYSCTL_KEY}=${SYSCTL_VALUE}" || true

# Self-destruct: spawn a detached --rm container that waits for
# this container to exit, removes it, then auto-removes itself.
if [ -S /var/run/docker.sock ]; then
    docker run --rm -d \
        -v /var/run/docker.sock:/var/run/docker.sock \
        --name "${CONTAINER_NAME}-gc" \
        "${GC_IMAGE}" \
        sh -c "docker wait '${CONTAINER_NAME}' >/dev/null 2>&1; docker rm '${CONTAINER_NAME}' >/dev/null 2>&1 || true" \
        >/dev/null 2>&1 || true
fi

exit 0
