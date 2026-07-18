#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

web_root="${OMERO_WEB_ROOT:?OMERO_WEB_ROOT is required for OMERO.web startup}"
var_dir="${OMERO_WEB_VAR_DIR:-${web_root}/OMERO.web/var}"
runtime_dir="${OMERO_WEB_RUNTIME_DIR:-${var_dir}/run}"
control_socket="${OMERO_WEB_GUNICORN_CONTROL_SOCKET:-${runtime_dir}/gunicorn.ctl}"

# OMERO.web builds the Gunicorn argv with str.split(), not shell parsing.
# Whitespace therefore cannot be represented safely in WSGI argument paths.
if [[ "${runtime_dir}" =~ [[:space:]] || "${control_socket}" =~ [[:space:]] ]]; then
    echo "ERROR: Gunicorn runtime and control-socket paths must not contain whitespace: ${runtime_dir}, ${control_socket}" >&2
    exit 1
fi

if [[ -n "${OMERO_WEB_VENV:-}" ]]; then
    case "${OMERO_WEB_VENV}" in
        /*) venv_dir="${OMERO_WEB_VENV}" ;;
        *) venv_dir="${web_root}/${OMERO_WEB_VENV}" ;;
    esac
else
    venv_dir="$(find "${web_root}" -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"
fi

if [[ -z "${venv_dir}" || ! -f "${venv_dir}/bin/activate" || ! -x "${venv_dir}/bin/python" ]]; then
    echo "ERROR: Could not find a valid OMERO.web virtualenv under ${web_root} (OMERO_WEB_VENV=${OMERO_WEB_VENV:-unset})" >&2
    find "${web_root}" -maxdepth 1 -ls >&2 || true
    exit 1
fi

# shellcheck disable=SC1090,SC1091
source "${venv_dir}/bin/activate"
omero_bin="${OMERO_WEB_OMERO_BIN:-${venv_dir}/bin/omero}"
if [[ ! -x "${omero_bin}" ]]; then
    echo "ERROR: OMERO CLI is not executable: ${omero_bin}" >&2
    exit 1
fi

default_wsgi_args="--chdir ${runtime_dir} --control-socket=${control_socket}"
wsgi_args="${OMERO_WEB_WSGI_ARGS:-${default_wsgi_args}}"

# Gunicorn 25.1+ creates a control socket by default. Existing installations
# may still provide the pre-25 argument string, so add the private runtime
# socket unless the administrator already selected either control-socket mode.
case " ${wsgi_args} " in
    *" --control-socket "* | *" --control-socket="* | *" --no-control-socket "*) ;;
    *) wsgi_args="${wsgi_args} --control-socket=${control_socket}" ;;
esac

current_wsgi_args="$("${omero_bin}" config get omero.web.wsgi_args 2>/dev/null || true)"
if [[ "${current_wsgi_args}" != "${wsgi_args}" ]]; then
    "${omero_bin}" config set omero.web.wsgi_args "${wsgi_args}" >/dev/null
fi

exec "${omero_bin}" web start --foreground
