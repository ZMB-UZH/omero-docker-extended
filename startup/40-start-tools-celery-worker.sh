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

# Redact broker URL credentials for logs. Inputs: broker URL. Output: sanitized URL.
redact_broker_url_for_log() {
    local value="${1:-}"
    if [[ -z "${value}" ]]; then
        printf 'not set\n'
        return 0
    fi
    printf '%s\n' "${value}" | sed -E 's#^([A-Za-z][A-Za-z0-9+.-]*://)([^/@]+@)#\1[redacted]@#'
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
echo "  broker: $(redact_broker_url_for_log "${TOOLS_ENHANCED_SEARCH_CELERY_BROKER_URL:-}")"
echo "=========================================="

echo "Testing task import..."
"${venv_dir}/bin/python" -c "from omeroweb_tools.tasks import run_enhanced_search_scope_sync; print('Task import OK:', run_enhanced_search_scope_sync.name)"

exec "${celery_bin}" -A omeroweb_tools.celery_app worker \
    --loglevel="${celery_loglevel}" \
    --concurrency="${celery_concurrency}" \
    -Q "${celery_queue}" \
    --hostname="enhanced-search@%h"
