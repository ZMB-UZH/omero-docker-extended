## ATTENTION!! Using the tag "latest" might be tempting but is extremely risky in production environments!
## ATTENTION!! The python venv lines will need to be changed to the correct/latest path
# when the OMERO developers update the container

# Pull image
# ----------
FROM openmicroscopy/omero-web-standalone@sha256:25c126b9cc555236957b0e59f6690ab892a9a008d407023e7cc739c51ce2a52e

# Run as root (REQUIRED)
# ----------------------
USER root

# Use bash with pipefail for safer RUN commands
# ---------------------------------------------
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_DNF_UPDATES=0

# Basic hardening for pip (no behavior change expected)
# -----------------------------------------------------
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Locate OMERO.web venv and fail fast if path or layout changes
# -------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi

# Ensure stable OMERO.web path points at the versioned installation
# -----------------------------------------------------------------
RUN set -euo pipefail; \
    WEB_DIR="$(find /opt/omero -maxdepth 4 -type d -name 'OMERO.web*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -n "${WEB_DIR}" ]]; then \
        mkdir -p /opt/omero/web; \
        if [[ ! -e /opt/omero/web/OMERO.web ]]; then \
            ln -s "${WEB_DIR}" /opt/omero/web/OMERO.web; \
        fi; \
    else \
        if [[ ! -d /opt/omero/web/OMERO.web ]]; then \
            echo "ERROR: Could not find OMERO.web directory under /opt/omero or fallback /opt/omero/web/OMERO.web." >&2; \
            exit 1; \
        fi; \
    fi

# NOT SUGGESTED!! USE ONLY FOR VULNERABILITY TESTING!!
# Optional: apply OS updates at build time
# ----------------------------------------
RUN set -euo pipefail; \
    if [[ "${APPLY_DNF_UPDATES}" == "1" ]]; then \
        dnf -y update --security || dnf -y update; \
    fi

# Install build dependencies required for installing OMERO Python API (omero-py)
# NOTE: omero-py depends on ZeroC Ice (native extension) and cannot be installed without a compiler
# -------------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    dnf -y install \
        gcc \
        gcc-c++ \
        make \
        python3-devel \
        supervisor; \
    dnf clean all; \
    rm -rf /var/cache/dnf /var/tmp/*

# Install OMERO Python API into OMERO.web venv (needed for BlitzGateway + TXT attachments)
# IMPORTANT: Pin omero-py to match server stack (OMERO.server 5.6.x -> omero-py 5.21.2)
# -------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir "omero-py==5.21.2"

## Optional: remove build dependencies again to keep image smaller
## ---------------------------------------------------------------
#RUN set -euo pipefail; \
#    dnf -y remove \
#        gcc \
#        gcc-c++ \
#        make \
#        python3-devel || true; \
#    dnf -y autoremove || true; \
#    dnf clean all; \
#    rm -rf /var/cache/dnf /var/tmp/*

# Remove old copies of the plugins inside the container (if any)
# --------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    rm -rf "${SITE_PACKAGES}/omeroweb_omp_plugin" \
        "${SITE_PACKAGES}/omeroweb_upload" \
        "${SITE_PACKAGES}/omeroweb_admin_tools" \
        "${SITE_PACKAGES}/omeroweb_imaris_connector" \
        "${SITE_PACKAGES}/omero_plugin_common"

# Copy the plugins into the container
# -----------------------------------
COPY omeroweb_omp_plugin /tmp/omeroweb_omp_plugin
COPY omeroweb_upload /tmp/omeroweb_upload
COPY omeroweb_admin_tools /tmp/omeroweb_admin_tools
COPY omeroweb_imaris_connector /tmp/omeroweb_imaris_connector
COPY omero_plugin_common /tmp/omero_plugin_common

# Install psycopg2-binary
# Add redis and django-redis for shared cache across workers
# Fix permissions in the end (plugin should be owned by omero-web)
# ----------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    cp -a /tmp/omeroweb_omp_plugin "${SITE_PACKAGES}/omeroweb_omp_plugin"; \
    cp -a /tmp/omeroweb_upload "${SITE_PACKAGES}/omeroweb_upload"; \
    cp -a /tmp/omeroweb_admin_tools "${SITE_PACKAGES}/omeroweb_admin_tools"; \
    cp -a /tmp/omeroweb_imaris_connector "${SITE_PACKAGES}/omeroweb_imaris_connector"; \
    cp -a /tmp/omero_plugin_common "${SITE_PACKAGES}/omero_plugin_common"; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir \
        matplotlib \
        psycopg2-binary \
        celery==5.3.6 \
        redis==5.0.8 \
        django-redis>=5.4.0 \
        omero-fpbioimage \
        omero-gallery \
        omero-parade \
        "zarr<3" \
        omero-web-zarr; \
    chown -R omero-web:omero-web \
        "${SITE_PACKAGES}/omeroweb_omp_plugin" \
        "${SITE_PACKAGES}/omeroweb_upload" \
        "${SITE_PACKAGES}/omeroweb_admin_tools" \
        "${SITE_PACKAGES}/omeroweb_imaris_connector" \
        "${SITE_PACKAGES}/omero_plugin_common"; \
    rm -rf /tmp/omeroweb_omp_plugin /tmp/omeroweb_upload /tmp/omeroweb_admin_tools /tmp/omeroweb_imaris_connector /tmp/omero_plugin_common

# Pre-create ALL Django static directories and own them (maybe unnecessary)
# -------------------------------------------------------------------------
RUN set -euo pipefail; \
    mkdir -p \
        /opt/omero/web/OMERO.web/var \
        /opt/omero/web/OMERO.web/var/log \
        /opt/omero/web/OMERO.web/var/static \
        /opt/omero/web/OMERO.web/var/static/branding \
        /opt/omero/web/OMERO.web/var/static/omero_figure \
        /opt/omero/web/OMERO.web/var/static/omeroweb_omp_plugin \
        /opt/omero/web/OMERO.web/var/static/omeroweb_upload \
        /opt/omero/web/OMERO.web/var/static/omeroweb_admin_tools \
        /opt/omero/web/OMERO.web/var/static/omeroweb_imaris_connector \
        /opt/omero/web/OMERO.web/var/static/omero_web_zarr; \
    chown -R omero-web:omero-web /opt/omero/web/OMERO.web/var

# Copy branding logo (skip cleanly if it doesn't exist)
# -----------------------------------------------------
RUN set -euo pipefail; \
    touch /tmp/logo.png.dummy
COPY logo.png* /tmp/
RUN set -euo pipefail; \
    rm -f /tmp/logo.png.dummy; \
    if [[ -f /tmp/logo.png ]]; then \
        cp /tmp/logo.png /opt/omero/web/OMERO.web/var/static/branding/logo.png; \
        chown omero-web:omero-web /opt/omero/web/OMERO.web/var/static/branding/logo.png; \
        chmod 0444 /opt/omero/web/OMERO.web/var/static/branding/logo.png; \
        echo "Logo copied to final static directory"; \
    else \
        echo "No logo.png found in build context, skipping logo setup"; \
    fi; \
    rm -f /tmp/logo.png*

# Sync OMERO.web static + media files
# -----------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    su -s /bin/bash omero-web -c "\
        source \"${VENV_DIR}/bin/activate\" && \
        omero web syncmedia \
    "

# Optional (off by default): vulnerability-testing updates for OMERO.web venv Python tooling
# WARNING:
# - Affects OMERO.web Python runtime
# - Enable only for vulnerability testing
# - Disable immediately if persistent OMERO.web issues occur
# ----------------------------------------------------------
ARG APPLY_OMEROWEB_VENV_TOOLING_UPDATES=0
RUN set -euo pipefail; \
    if [[ "${APPLY_OMEROWEB_VENV_TOOLING_UPDATES}" != "1" ]]; then \
        echo "Skipping optional OMERO.web venv tooling updates (APPLY_OMEROWEB_VENV_TOOLING_UPDATES=${APPLY_OMEROWEB_VENV_TOOLING_UPDATES})."; \
        exit 0; \
    fi; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade \
        pip \
        setuptools>=78.1.1 \
        wheel \
        cryptography>=42.0.0 \
        urllib3>=2.6.3

# Configure supervisord to run OMERO.web and Imaris Celery worker
# ---------------------------------------------------------------
COPY supervisord.conf /etc/supervisord.conf
COPY startup/40-start-imaris-celery-worker.sh /opt/omero/web/bin/start-imaris-celery-worker.sh
RUN set -euo pipefail; \
    mkdir -p /opt/omero/web/bin /opt/omero/web/logs; \
    chmod 0555 /opt/omero/web/bin/start-imaris-celery-worker.sh; \
    chown -R omero-web:omero-web /opt/omero/web/logs

# FIX: The base image's /startup/99-run.sh executes
#   "omero web start --foreground"
# which blocks forever. The base image entrypoint loops over /startup/* and
# never reaches exec "$@", so our CMD (supervisord) never runs.
#
# Solution:
#  1. Delete 99-run.sh — supervisord manages gunicorn instead.
#  2. Replace entrypoint with one that exec's "$@" after startup scripts.
# -----------------------------------------------------------------------
RUN rm -f /startup/99-run.sh

RUN set -euo pipefail; \
    printf '%s\n' \
        '#!/usr/local/bin/dumb-init /bin/bash' \
        'set -e' \
        'source /opt/omero/web/venv3/bin/activate' \
        'for f in /startup/*; do' \
        '    if [ -f "$f" ] && [ -x "$f" ]; then' \
        '        echo "Running $f $@"' \
        '        "$f" "$@"' \
        '    fi' \
        'done' \
        'echo "Startup scripts complete. Launching: $@"' \
        'exec "$@"' \
        > /usr/local/bin/entrypoint-supervisord.sh; \
    chmod 0555 /usr/local/bin/entrypoint-supervisord.sh

# Drop privileges for runtime
# ---------------------------
USER omero-web

ENTRYPOINT ["/usr/local/bin/entrypoint-supervisord.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
