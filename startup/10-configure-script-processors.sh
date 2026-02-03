#!/usr/bin/env bash
set -euo pipefail

processors_raw="${CONFIG_omero_scripts_processors:-}"

if [[ -z "${processors_raw}" ]]; then
    echo "ERROR: CONFIG_omero_scripts_processors must be set to a positive integer." >&2
    exit 1
fi

if ! [[ "${processors_raw}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: CONFIG_omero_scripts_processors must be a positive integer; got '${processors_raw}'." >&2
    exit 1
fi

if [[ "${processors_raw}" -lt 1 ]]; then
    echo "ERROR: CONFIG_omero_scripts_processors must be >= 1; got '${processors_raw}'." >&2
    exit 1
fi

/opt/omero/server/OMERO.server/bin/omero config set omero.scripts.processors "${processors_raw}"
echo "Configured omero.scripts.processors=${processors_raw}"
