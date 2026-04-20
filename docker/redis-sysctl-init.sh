#!/bin/sh
set -eu

SYSCTL_KEY="${SYSCTL_KEY:-vm.overcommit_memory}"
SYSCTL_VALUE="${SYSCTL_VALUE:-1}"

if [ "${SYSCTL_KEY}" != "vm.overcommit_memory" ]; then
    echo "ERROR: unsupported SYSCTL_KEY for redis-sysctl-init: ${SYSCTL_KEY}" >&2
    exit 1
fi

case "${SYSCTL_VALUE}" in
    0 | 1 | 2) ;;
    *)
        echo "ERROR: unsupported vm.overcommit_memory value: ${SYSCTL_VALUE}" >&2
        exit 1
        ;;
esac

sysctl -w "${SYSCTL_KEY}=${SYSCTL_VALUE}"
exit 0
