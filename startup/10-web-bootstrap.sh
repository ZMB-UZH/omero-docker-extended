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

if [[ -L "${default_log_dir}" ]]; then
    current_target="$(readlink "${default_log_dir}")"
    if [[ "${current_target}" == "${log_dir}" ]]; then
        echo "[web-bootstrap] OMERO.web default log symlink already points to ${log_dir}"
        exit 0
    fi
fi

if mountpoint -q "${default_log_dir}"; then
    echo "[web-bootstrap] WARNING: ${default_log_dir} is a mounted filesystem; skipping symlink replacement."
    exit 0
fi

rm -rf "${default_log_dir}"
ln -s "${log_dir}" "${default_log_dir}"

echo "[web-bootstrap] OMERO.web log directory ready: ${log_dir}"
