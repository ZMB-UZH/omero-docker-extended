#!/bin/bash
# shellcheck shell=bash

set -euo pipefail

use_celery_raw="${TOOLS_ENHANCED_SEARCH_USE_CELERY:-true}"
use_celery="$(echo "${use_celery_raw}" | tr '[:upper:]' '[:lower:]')"
if [[ "${use_celery}" != "true" ]]; then
    echo "Enhanced-search Celery worker disabled (TOOLS_ENHANCED_SEARCH_USE_CELERY=${use_celery_raw})."
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

celery_queue="${TOOLS_ENHANCED_SEARCH_CELERY_QUEUE:-enhanced_search}"
celery_loglevel="${TOOLS_ENHANCED_SEARCH_CELERY_LOGLEVEL:-info}"
celery_concurrency="${TOOLS_ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY:-1}"

echo "=========================================="
echo "Starting Enhanced-search Celery worker"
echo "  venv_dir: ${venv_dir}"
echo "  celery_bin: ${celery_bin}"
echo "  queue: ${celery_queue}"
echo "  loglevel: ${celery_loglevel}"
echo "  concurrency: ${celery_concurrency}"
echo "  broker: ${TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL:-not set}"
echo "=========================================="

echo "Testing task import..."
"${venv_dir}/bin/python" -c "from omeroweb_tools.tasks import run_enhanced_search_scope_sync; print('Task import OK:', run_enhanced_search_scope_sync.name)"

exec "${celery_bin}" -A omeroweb_tools.celery_app worker \
    --loglevel="${celery_loglevel}" \
    --concurrency="${celery_concurrency}" \
    -Q "${celery_queue}" \
    --hostname="enhanced-search@%h"
