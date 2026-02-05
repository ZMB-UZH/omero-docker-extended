#!/bin/bash

set -euo pipefail

use_celery_raw="${OMERO_IMS_USE_CELERY:-true}"
use_celery="$(echo "${use_celery_raw}" | tr '[:upper:]' '[:lower:]')"
if [[ "${use_celery}" != "true" ]]; then
    echo "Imaris Celery worker disabled (OMERO_IMS_USE_CELERY=${use_celery_raw})."
    exit 0
fi

venv_dir="/opt/omero/web/${OMERO_WEB_VENV:-venv3}"
celery_bin="${venv_dir}/bin/celery"

if [[ ! -x "${celery_bin}" ]]; then
    echo "ERROR: Celery binary not found at ${celery_bin}." >&2
    echo "Ensure celery is installed inside the OMERO.web virtualenv." >&2
    exit 1
fi

celery_queue="${OMERO_IMS_CELERY_QUEUE:-imaris}"
celery_loglevel="${OMERO_IMS_CELERY_LOGLEVEL:-info}"
celery_concurrency="${OMERO_IMS_CELERY_WORKER_CONCURRENCY:-1}"

echo "Starting Imaris Celery worker with queue '${celery_queue}' (loglevel=${celery_loglevel}, concurrency=${celery_concurrency})."
exec "${celery_bin}" -A omeroweb_imaris_connector.celery_app worker \
    --loglevel="${celery_loglevel}" \
    --concurrency="${celery_concurrency}" \
    -Q "${celery_queue}" \
    --hostname="imaris@%h"
