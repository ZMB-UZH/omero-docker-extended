#!/bin/sh
set -eu
sysctl -w "${SYSCTL_KEY:-vm.overcommit_memory}=${SYSCTL_VALUE:-1}" || true
exit 0
