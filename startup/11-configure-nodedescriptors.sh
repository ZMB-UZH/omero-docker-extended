#!/usr/bin/env bash
set -euo pipefail

nodedescriptors_raw="${CONFIG_omero_server_nodedescriptors:-}"
processors_raw="${CONFIG_omero_scripts_processors:-}"

if [[ -n "${processors_raw}" ]]; then
    if ! [[ "${processors_raw}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: CONFIG_omero_scripts_processors must be a positive integer; got '${processors_raw}'." >&2
        exit 1
    fi
    if [[ "${processors_raw}" -lt 1 ]]; then
        echo "ERROR: CONFIG_omero_scripts_processors must be >= 1; got '${processors_raw}'." >&2
        exit 1
    fi
fi

if [[ -z "${nodedescriptors_raw}" ]]; then
    echo "ERROR: CONFIG_omero_server_nodedescriptors must be set to define OMERO services." >&2
    exit 1
fi

append_processor() {
    local name="$1"
    if [[ "${nodedescriptors_raw}" =~ (^|,)${name}(,|$) ]]; then
        return 0
    fi
    if [[ -z "${nodedescriptors_raw}" ]]; then
        nodedescriptors_raw="${name}"
    else
        nodedescriptors_raw="${nodedescriptors_raw},${name}"
    fi
    return 1
}

if [[ -n "${processors_raw}" ]]; then
    appended=0
    for idx in $(seq 0 $((processors_raw - 1))); do
        if ! append_processor "Processor-${idx}"; then
            appended=1
        fi
    done
    if [[ "${appended}" -eq 1 ]]; then
        echo "WARNING: CONFIG_omero_server_nodedescriptors missing Processor entries; appended Processor-0..$((processors_raw - 1))." >&2
    fi
elif [[ "${nodedescriptors_raw}" != *"Processor"* ]]; then
    echo "WARNING: CONFIG_omero_server_nodedescriptors missing Processor entry; appending Processor-0." >&2
    nodedescriptors_raw="${nodedescriptors_raw},Processor-0"
fi

/opt/omero/server/OMERO.server/bin/omero config set \
    omero.server.nodedescriptors "${nodedescriptors_raw}"
echo "Configured omero.server.nodedescriptors=${nodedescriptors_raw}"
