#!/usr/bin/env bash
set -euo pipefail

log_dir="${CONFIG_omero_web_logdir:-/tmp/omero-web-logs}"
default_log_dir="/opt/omero/web/OMERO.web/var/log"

mkdir -p "${log_dir}"

if [[ ! -d "${log_dir}" || ! -w "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: log directory is not writable: ${log_dir}" >&2
    exit 1
fi

mkdir -p "$(dirname "${default_log_dir}")"
rm -rf "${default_log_dir}"
ln -s "${log_dir}" "${default_log_dir}"

echo "[web-bootstrap] OMERO.web log directory ready: ${log_dir}"
