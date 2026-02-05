#!/bin/sh

set -eu

SYSCTL_KEY="${SYSCTL_KEY:-vm.overcommit_memory}"
SYSCTL_VALUE="${SYSCTL_VALUE:-1}"
CONTAINER_NAME="${CONTAINER_NAME:-redis-sysctl-init}"
SELF_IMAGE="${SELF_IMAGE:-omero-redis-sysctl-init:custom}"

sysctl -w "${SYSCTL_KEY}=${SYSCTL_VALUE}" || true

do_cleanup() {
    if [ -S /var/run/docker.sock ]; then
        docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
        docker rmi -f "${SELF_IMAGE}" >/dev/null 2>&1 || true
    fi
}

(do_cleanup &) >/dev/null 2>&1

exit 0
