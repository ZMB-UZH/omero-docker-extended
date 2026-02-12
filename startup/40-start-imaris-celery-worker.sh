#!/bin/bash
################################################################################
# Imaris Celery Worker Startup Script
################################################################################
#
# PURPOSE:
#   Starts the Celery worker for processing Imaris export tasks.
#   This worker runs inside the omeroweb container and processes async
#   conversion jobs from the imaris_export queue.
#
# WHAT IT DOES:
#   1. Checks if Celery is enabled (OMERO_IMS_USE_CELERY env var)
#   2. Dynamically locates OMERO.web venv (handles version changes)
#   3. Validates celery binary exists in venv
#   4. Tests that Celery tasks can be imported
#   5. Starts Celery worker with configured queue and concurrency
#
# WHY THIS IS NEEDED:
#   - Imaris conversions are CPU/time intensive and must run async
#   - Celery worker provides reliable task processing with retries
#   - Running in omeroweb container shares code and dependencies
#
# HOW IT WORKS:
#   - Managed by supervisord (defined in supervisord.conf)
#   - Connects to Redis broker (OMERO_IMS_CELERY_BROKER_URL)
#   - Consumes tasks from queue (OMERO_IMS_CELERY_QUEUE)
#   - Calls ImarisConvertBioformats via OMERO.server scripts
#
# CONFIGURATION:
#   - OMERO_IMS_USE_CELERY: Enable/disable worker (default: true)
#   - OMERO_IMS_CELERY_BROKER_URL: Redis connection string (required)
#   - OMERO_IMS_CELERY_QUEUE: Queue name (default: imaris_export)
#   - OMERO_IMS_CELERY_LOGLEVEL: Logging level (default: info)
#   - OMERO_IMS_CELERY_WORKER_CONCURRENCY: Parallel tasks (default: 1)
#
# IMPORTANT:
#   - This script is executed by supervisord, not directly
#   - The venv path is detected dynamically (same method as Dockerfile)
#   - Task import is tested before starting to fail fast on errors
#   - Worker hostname includes container hostname for distributed setups
#
################################################################################

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
