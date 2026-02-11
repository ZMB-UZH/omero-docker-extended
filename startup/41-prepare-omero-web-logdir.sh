#!/usr/bin/env bash
set -euo pipefail

# Ensure the OMERO.web log directory exists before Django configures
# RotatingFileHandler. This avoids startup failure when LOGDIR points to
# a writable runtime path (e.g. /tmp/omero-web-logs).
log_dir="${CONFIG_omero_web_logdir:-}"

if [[ -z "${log_dir}" ]]; then
    echo "[startup] CONFIG_omero_web_logdir is not set; skipping explicit log directory creation."
    exit 0
fi

mkdir -p "${log_dir}"

if [[ ! -d "${log_dir}" ]]; then
    echo "[startup] ERROR: failed to create OMERO.web log directory: ${log_dir}" >&2
    exit 1
fi

if [[ ! -w "${log_dir}" ]]; then
    echo "[startup] ERROR: OMERO.web log directory is not writable: ${log_dir}" >&2
    exit 1
fi

echo "[startup] OMERO.web log directory ready: ${log_dir}"
