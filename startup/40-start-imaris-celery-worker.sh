#!/bin/bash

set -euo pipefail

use_celery_raw="${OMERO_IMS_USE_CELERY:-true}"
use_celery="$(echo "${use_celery_raw}" | tr '[:upper:]' '[:lower:]')"
if [[ "${use_celery}" != "true" ]]; then
    echo "Imaris Celery worker disabled (OMERO_IMS_USE_CELERY=${use_celery_raw})."
    exit 0
fi

# Find venv dynamically - same method as Dockerfile uses
venv_dir="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"

if [[ -z "${venv_dir}" || ! -d "${venv_dir}" ]]; then
    # Fallback to env variable
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

# Add defaults to prevent empty string issues
celery_queue="${OMERO_IMS_CELERY_QUEUE:-imaris_export}"
celery_loglevel="${OMERO_IMS_CELERY_LOGLEVEL:-info}"
celery_concurrency="${OMERO_IMS_CELERY_WORKER_CONCURRENCY:-1}"

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
"${venv_dir}/bin/python" -c "from omeroweb_imaris_connector.tasks import run_ims_export_task; print('Task import OK:', run_ims_export_task.name)"

if [[ $? -ne 0 ]]; then
    echo "ERROR: Failed to import Celery tasks" >&2
    exit 1
fi

exec "${celery_bin}" -A omeroweb_imaris_connector.celery_app worker \
    --loglevel="${celery_loglevel}" \
    --concurrency="${celery_concurrency}" \
    -Q "${celery_queue}" \
    --hostname="imaris@%h"
