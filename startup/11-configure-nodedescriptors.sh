#!/usr/bin/env bash
set -euo pipefail

nodedescriptors_raw="${CONFIG_omero_server_nodedescriptors:-}"

if [[ -z "${nodedescriptors_raw}" ]]; then
    echo "ERROR: CONFIG_omero_server_nodedescriptors must be set to define OMERO services." >&2
    exit 1
fi

if [[ "${nodedescriptors_raw}" != *"Processor"* ]]; then
    echo "ERROR: CONFIG_omero_server_nodedescriptors must include a Processor service." >&2
    echo "Example: master:Blitz-0,Tables-0,Indexer-0,PixelData-0,DropBox,MonitorServer,FileServer,Processor-0" >&2
    exit 1
fi

/opt/omero/server/OMERO.server/bin/omero config set \
    omero.server.nodedescriptors "${nodedescriptors_raw}"
echo "Configured omero.server.nodedescriptors=${nodedescriptors_raw}"
