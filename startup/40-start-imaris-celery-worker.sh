#!/bin/bash
# shellcheck shell=bash

set -euo pipefail

runtime_user="${OMERO_WEB_RUNTIME_USER:-${OMERO_WEB_RUN_USER:-omero-web}}"
runtime_home="${OMERO_WEB_ROOT:-/opt/omero/web}"
if [[ "$(id -u)" -eq 0 && "${runtime_user}" != "root" ]]; then
    if ! id "${runtime_user}" >/dev/null 2>&1; then
        echo "ERROR: OMERO.web runtime user '${runtime_user}' does not exist." >&2
        exit 1
    fi
    exec env \
        USER="${runtime_user}" \
        LOGNAME="${runtime_user}" \
        LNAME="${runtime_user}" \
        USERNAME="${runtime_user}" \
        HOME="${runtime_home}" \
        runuser -p -m -u "${runtime_user}" -- "${BASH_SOURCE[0]}" "$@"
fi

use_celery_raw="${OMERO_IMS_USE_CELERY:-true}"
use_celery="$(echo "${use_celery_raw}" | tr '[:upper:]' '[:lower:]')"
if [[ "${use_celery}" != "true" ]]; then
    echo "Imaris Celery worker disabled (OMERO_IMS_USE_CELERY=${use_celery_raw})."
    exit 0
fi

web_root="${OMERO_WEB_ROOT:?OMERO_WEB_ROOT is required for OMERO.web virtualenv discovery}"

# Resolve OMERO.web virtualenv directory. Inputs: environment variables. Output: stdout path.
resolve_web_venv_dir() {
    local configured_venv="${OMERO_WEB_VENV:-}"
    local candidate=""

    if [[ -n "${configured_venv}" ]]; then
        case "${configured_venv}" in
            /*)
                candidate="${configured_venv}"
                ;;
            *)
                candidate="${web_root%/}/${configured_venv}"
                ;;
        esac
        if [[ -d "${candidate}" ]]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    fi

    find "${web_root}" -maxdepth 1 -type d -name 'venv*' -print 2>/dev/null | sort -V | tail -n 1
}

venv_dir="$(resolve_web_venv_dir)"

if [[ ! -d "${venv_dir}" ]]; then
    echo "ERROR: Could not find OMERO.web virtualenv" >&2
    echo "Tried: ${web_root}/venv* and OMERO_WEB_VENV=${OMERO_WEB_VENV:-unset}" >&2
    ls -la "${web_root}/" >&2 || true
    exit 1
fi

celery_bin="${venv_dir}/bin/celery"

if [[ ! -x "${celery_bin}" ]]; then
    echo "ERROR: Celery binary not found at ${celery_bin}." >&2
    echo "Ensure celery is installed inside the OMERO.web virtualenv." >&2
    echo "Contents of ${venv_dir}/bin/:" >&2
    ls -la "${venv_dir}/bin/" >&2 || true
    exit 1
fi

# Add defaults to prevent empty string issues
celery_queue="${OMERO_IMS_CELERY_QUEUE:-imaris_export}"
celery_loglevel="${OMERO_IMS_CELERY_LOGLEVEL:-info}"
default_celery_concurrency="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf '4\n')"
celery_concurrency="${OMERO_IMS_CELERY_WORKER_CONCURRENCY:-${default_celery_concurrency}}"
case "${celery_concurrency}" in
    '' | *[!0-9]*)
        echo "ERROR: OMERO_IMS_CELERY_WORKER_CONCURRENCY must be a positive integer." >&2
        exit 1
        ;;
esac
if [[ "${celery_concurrency}" -lt 1 ]]; then
    echo "ERROR: OMERO_IMS_CELERY_WORKER_CONCURRENCY must be a positive integer." >&2
    exit 1
fi

echo "=========================================="
echo "Starting Imaris Celery worker"
echo "  venv_dir: ${venv_dir}"
echo "  celery_bin: ${celery_bin}"
echo "  queue: ${celery_queue}"
echo "  loglevel: ${celery_loglevel}"
echo "  concurrency: ${celery_concurrency}"
echo "  broker: ${OMERO_IMS_CELERY_BROKER_URL:-not set}"
echo "=========================================="

# Test the import before starting the worker
echo "Testing task import..."
if ! "${venv_dir}/bin/python" -c "from omero_imaris_connector.tasks import run_ims_export_task; print('Task import OK:', run_ims_export_task.name)"; then
    echo "ERROR: Failed to import Celery tasks" >&2
    exit 1
fi

exec "${celery_bin}" -A omero_imaris_connector.celery_app worker \
    --loglevel="${celery_loglevel}" \
    --concurrency="${celery_concurrency}" \
    -Q "${celery_queue}" \
    --hostname="imaris@%h"
