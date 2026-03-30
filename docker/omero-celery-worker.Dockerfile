## Dedicated Celery worker image for OMERO Imaris exports
# Keeps Celery runtime separate from OMERO.web and OMERO.server images.

## Dedicated Celery worker image for OMERO Imaris exports
## Ubuntu 24.04 base (NOT slim), pinned Python packages.

FROM ubuntu:24.04@sha256:186072bba1b2f436cbb91ef2567abca677337cfc786c86e107d25b7072feef0c

USER root

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Zurich \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0

RUN set -euo pipefail; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
        software-properties-common \
        gnupg; \
    add-apt-repository -y ppa:deadsnakes/ppa; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        python3.9 \
        python3.9-dev \
        python3.9-venv \
        python3.9-distutils \
        gcc \
        g++ \
        libedit-dev \
        libbz2-dev \
        libstdc++6 \
        libssl3; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apt-get upgrade -y --no-install-recommends; \
        apt-get autoremove -y --purge || true; \
    fi; \
    rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

# Create a venv to not depend on "system pip" state
ENV VENV=/opt/venv
RUN set -euo pipefail; \
    python3.9 -m venv "$VENV"; \
    "$VENV/bin/python" -m pip install --upgrade pip setuptools wheel; \
    "$VENV/bin/python" -m pip install \
        "celery==5.3.6" \
        "redis==5.0.8" \
        "omero-py==5.22.0"

# Non-root runtime user
RUN set -euo pipefail; \
    groupadd --gid 10001 celery; \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin celery

# Install your in-tree python packages into the venv site-packages
COPY omeroweb_imaris_connector /tmp/omeroweb_imaris_connector
COPY omero_plugin_common /tmp/omero_plugin_common

RUN set -euo pipefail; \
    SITE_PACKAGES="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"; \
    rm -rf "${SITE_PACKAGES}/omeroweb_imaris_connector" "${SITE_PACKAGES}/omero_plugin_common"; \
    cp -a /tmp/omeroweb_imaris_connector "${SITE_PACKAGES}/omeroweb_imaris_connector"; \
    cp -a /tmp/omero_plugin_common "${SITE_PACKAGES}/omero_plugin_common"; \
    chown -R celery:celery \
        "${SITE_PACKAGES}/omeroweb_imaris_connector" \
        "${SITE_PACKAGES}/omero_plugin_common"; \
    rm -rf /tmp/omeroweb_imaris_connector /tmp/omero_plugin_common

# Optional (off by default): curated compatibility-safe Python hardening
# ----------------------------------------------------------
RUN set -euo pipefail; \
    if [ "${APPLY_SECURITY_HARDENING}" != "1" ]; then \
        echo "Skipping curated Python hardening (APPLY_SECURITY_HARDENING=${APPLY_SECURITY_HARDENING})."; \
        exit 0; \
    fi; \
    echo "Applying curated compatibility-safe Python hardening in ${VENV}..."; \
    "$VENV/bin/python" -m pip install --no-cache-dir --upgrade \
        pip setuptools wheel cryptography certifi idna requests jinja2 urllib3; \
    echo "Skipping blanket celery-worker venv upgrades to preserve pinned/runtime-integrated packages."

USER celery
ENV PATH="/opt/venv/bin:${PATH}"
