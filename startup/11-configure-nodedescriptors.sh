#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CONFIG_omero_server_nodedescriptors:-}" ]]; then
    echo "ERROR: CONFIG_omero_server_nodedescriptors must be set." >&2
    exit 1
fi

echo "Using node descriptors from CONFIG_omero_server_nodedescriptors:"
echo "${CONFIG_omero_server_nodedescriptors}"

# DO NOT call 'omero config set' here.
# 50-config.py applies CONFIG_* before OMERO.server starts.
# Mutating grid config at runtime can cause processors to disappear.
