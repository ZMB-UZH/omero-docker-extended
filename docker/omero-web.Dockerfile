## ATTENTION!! Using the tag "latest" might be tempting but is extremely risky in production environments!
## ATTENTION!! The python venv lines will need to be changed to the correct/latest path
# when the OMERO developers update the container

# Pull image
# ----------
FROM openmicroscopy/omero-web-standalone:5.31.0

# Run as root (REQUIRED)
# ----------------------
USER root

# Use bash with pipefail for safer RUN commands
# ---------------------------------------------
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
# NOTE:
# - Keep disabled by default for deterministic builds.
# - Enable only for vulnerability testing.
# - APPLY_DNF_UPDATES is kept as a backward-compatible alias.
ARG APPLY_OMEROWEB_DNF_UPDATES=0
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

# Optional (off by default): vulnerability-testing updates for OS packages
# WARNING:
# - Affects reproducibility and cache stability
# - Enable only for vulnerability testing
# ---------------------------------------
RUN set -euo pipefail; \
    APPLY_UPDATES="${APPLY_OMEROWEB_DNF_UPDATES}"; \
    if [[ "${APPLY_DNF_UPDATES}" == "1" ]]; then \
        APPLY_UPDATES="1"; \
    fi; \
    if [[ "${APPLY_UPDATES}" != "1" ]]; then \
        echo "Skipping optional OS updates (APPLY_OMEROWEB_DNF_UPDATES=${APPLY_OMEROWEB_DNF_UPDATES}, APPLY_DNF_UPDATES=${APPLY_DNF_UPDATES})."; \
        exit 0; \
    fi; \
    dnf -y update --security || dnf -y update

# Install build dependencies required for installing OMERO Python API (omero-py)
# NOTE: omero-py depends on ZeroC Ice (native extension) and cannot be installed without a compiler
# -------------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    dnf -y install \
        gcc \
        gcc-c++ \
        make \
        python3-devel \
        supervisor \
        quota \
        e2fsprogs; \
    dnf clean all; \
    rm -rf /var/cache/dnf /var/tmp/*

# Install OMERO Python API into OMERO.web venv (needed for BlitzGateway + TXT attachments)
# IMPORTANT: Pin omero-py to match OMERO.server stack
# ---------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir "omero-py==5.22.0"

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
# NOTE: The source repo may be updated by workflows that temporarily remove
# the local logo/ directory. Mounting the full build context avoids hard
# failures from COPY when logo/logo.png is absent.
RUN --mount=type=bind,source=.,target=/tmp/build-context,readonly \
    set -euo pipefail; \
    if [[ -f /tmp/build-context/logo/logo.png ]]; then \
        cp /tmp/build-context/logo/logo.png /opt/omero/web/OMERO.web/var/static/branding/logo.png; \
        chown omero-web:omero-web /opt/omero/web/OMERO.web/var/static/branding/logo.png; \
        chmod 0444 /opt/omero/web/OMERO.web/var/static/branding/logo.png; \
        echo "Logo copied to final static directory"; \
    else \
        echo "No logo/logo.png found in build context, skipping logo setup"; \
    fi

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
COPY startup/10-web-bootstrap.sh /startup/10-web-bootstrap.sh
COPY startup/60-enforce-ext4-project-quota.sh /opt/omero/web/bin/enforce-ext4-project-quota.sh
COPY startup/61-storage-quota-reconcile-loop.sh /opt/omero/web/bin/storage-quota-reconcile-loop.sh
RUN set -euo pipefail; \
    mkdir -p /opt/omero/web/bin /opt/omero/web/logs; \
    chmod 0555 /opt/omero/web/bin/start-imaris-celery-worker.sh /startup/10-web-bootstrap.sh /opt/omero/web/bin/enforce-ext4-project-quota.sh /opt/omero/web/bin/storage-quota-reconcile-loop.sh; \
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
        'VENV_DIR="${OMERO_WEB_VENV:-}"' \
        'if [ -n "${VENV_DIR}" ]; then' \
        '    VENV_DIR="/opt/omero/web/${VENV_DIR}"' \
        'else' \
        '    VENV_DIR="$(ls -d /opt/omero/web/venv* 2>/dev/null | sort -V | tail -n 1)"' \
        'fi' \
        'if [ -z "${VENV_DIR}" ] || [ ! -f "${VENV_DIR}/bin/activate" ]; then' \
        '    echo "ERROR: Could not find OMERO.web venv under /opt/omero/web (OMERO_WEB_VENV=${OMERO_WEB_VENV:-unset})" >&2' \
        '    ls -la /opt/omero/web >&2 || true' \
        '    exit 1' \
        'fi' \
        'source "${VENV_DIR}/bin/activate"' \
        'for f in /startup/*; do' \
        '    if [ -f "$f" ] && [ -x "$f" ]; then' \
        '        echo "Running $f $@"' \
        '        if [ "$(basename "$f")" = "10-web-bootstrap.sh" ]; then' \
        '            "$f" "$@"' \
        '        else' \
        '            runuser -u omero-web -- "$f" "$@"' \
        '        fi' \
        '    fi' \
        'done' \
        'echo "Startup scripts complete. Launching as omero-web: $@"' \
        'exec runuser -u omero-web -- "$@"' \
        > /usr/local/bin/entrypoint-supervisord.sh; \
    chmod 0555 /usr/local/bin/entrypoint-supervisord.sh


# Keep root as image user so bootstrap scripts can reconcile runtime permissions
# before dropping to the application user in the entrypoint.
USER root

ENTRYPOINT ["/usr/local/bin/entrypoint-supervisord.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
