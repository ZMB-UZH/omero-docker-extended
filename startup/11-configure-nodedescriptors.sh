#!/usr/bin/env bash
set -euo pipefail

nodedescriptors_raw="${CONFIG_omero_server_nodedescriptors:-}"

if [[ -z "${nodedescriptors_raw}" ]]; then
    echo "ERROR: CONFIG_omero_server_nodedescriptors must be set to define OMERO services." >&2
    exit 1
fi

if [[ "${nodedescriptors_raw}" != *"Processor"* ]]; then
    echo "WARNING: CONFIG_omero_server_nodedescriptors missing Processor entry; appending Processor-0." >&2
    nodedescriptors_raw="${nodedescriptors_raw},Processor-0"
fi

/opt/omero/server/OMERO.server/bin/omero config set \
    omero.server.nodedescriptors "${nodedescriptors_raw}"
echo "Configured omero.server.nodedescriptors=${nodedescriptors_raw}"
