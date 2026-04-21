#!/bin/bash

set -euo pipefail

use_celery_raw="${TOOLS_ENHANCED_SEARCH_USE_CELERY:-true}"
use_celery="$(echo "${use_celery_raw}" | tr '[:upper:]' '[:lower:]')"
if [[ "${use_celery}" != "true" ]]; then
    echo "Enhanced-search Celery worker disabled (TOOLS_ENHANCED_SEARCH_USE_CELERY=${use_celery_raw})."
    exit 0
fi

venv_dir=""
if [[ -d /opt/omero/web ]]; then
    venv_dir="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' -print | sort -V | tail -n 1)"
fi
if [[ -z "${venv_dir}" || ! -d "${venv_dir}" ]]; then
    venv_dir="/opt/omero/web/${OMERO_WEB_VENV:-venv}"
fi

if [[ ! -d "${venv_dir}" ]]; then
    echo "ERROR: Could not find OMERO.web virtualenv" >&2
    echo "Tried: /opt/omero/web/venv* and /opt/omero/web/${OMERO_WEB_VENV:-venv}" >&2
    ls -la /opt/omero/web/ >&2 || true
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
