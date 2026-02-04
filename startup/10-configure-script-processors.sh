#!/usr/bin/env bash
set -euo pipefail

processors_raw="${CONFIG_omero_scripts_processors:-}"
nodedescriptors_raw="${CONFIG_omero_server_nodedescriptors:-}"

count_processors() {
    local raw="${1:-}"
    local matches

    if [[ -z "${raw}" ]]; then
        echo 0
        return
    fi

    matches="$(printf '%s' "${raw}" | grep -o "Processor" || true)"
    if [[ -z "${matches}" ]]; then
        echo 0
        return
    fi

    printf '%s\n' "${matches}" | wc -l | tr -d ' '
}

if [[ -z "${processors_raw}" ]]; then
    derived_count="$(count_processors "${nodedescriptors_raw}")"
    if [[ "${derived_count}" -lt 1 ]]; then
        echo "ERROR: CONFIG_omero_scripts_processors must be set to a positive integer." >&2
        echo "ERROR: CONFIG_omero_server_nodedescriptors does not include Processor entries to derive a default." >&2
        exit 1
    fi
    processors_raw="${derived_count}"
    echo "CONFIG_omero_scripts_processors not set; derived ${processors_raw} from CONFIG_omero_server_nodedescriptors."
fi

if ! [[ "${processors_raw}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: CONFIG_omero_scripts_processors must be a positive integer; got '${processors_raw}'." >&2
    exit 1
fi

if [[ "${processors_raw}" -lt 1 ]]; then
    derived_count="$(count_processors "${nodedescriptors_raw}")"
    if [[ "${derived_count}" -ge 1 ]]; then
        echo "WARNING: CONFIG_omero_scripts_processors=${processors_raw}; using ${derived_count} derived from CONFIG_omero_server_nodedescriptors." >&2
        processors_raw="${derived_count}"
    else
        echo "ERROR: CONFIG_omero_scripts_processors must be >= 1; got '${processors_raw}'." >&2
        echo "ERROR: CONFIG_omero_server_nodedescriptors does not include Processor entries to derive a default." >&2
        exit 1
    fi
fi

/opt/omero/server/OMERO.server/bin/omero config set omero.scripts.processors "${processors_raw}"
echo "Configured omero.scripts.processors=${processors_raw}"
