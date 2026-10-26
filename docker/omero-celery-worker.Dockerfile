# Standalone OMERO Imaris worker using the server-compatible Python 3.11 runtime.

FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944

USER root

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Zurich \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp \
    OMERO_TMPDIR=/tmp

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Apply OS and curated Python security updates unless explicitly disabled.
ARG APPLY_SECURITY_HARDENING=1

# Keep direct Python dependencies reproducible. OMERO.py 5.23 uses supported
# resource APIs; its CLI and database tooling no longer require pkg_resources.
# --------------------------------------------------------------------------
ARG PIP_VERSION=26.2.2
ARG SETUPTOOLS_VERSION=84.2.1
ARG WHEEL_VERSION=0.48.0
ARG CRYPTOGRAPHY_VERSION=50.0.2
ARG URLLIB3_VERSION=2.8.0
ARG CERTIFI_VERSION=2026.10.23
ARG IDNA_VERSION=3.20
ARG REQUESTS_VERSION=2.34.2
ARG JINJA2_VERSION=3.1.6
ARG PILLOW_VERSION=13.0.0
ARG NUMPY_VERSION=2.4.6

RUN set -euo pipefail; \
    apt-get update; \
    require_apt_version() { \
        local package="$1"; \
        local version=""; \
        version="$(apt-cache madison "${package}" | awk 'NR==1 {print $3}')"; \
        if [ -z "${version}" ]; then \
            echo "ERROR: Failed to resolve apt version for ${package}" >&2; \
            exit 1; \
        fi; \
        printf '%s' "${version}"; \
    }; \
    apt-get install -y --no-install-recommends \
        "ca-certificates=$(require_apt_version ca-certificates)" \
        "curl=$(require_apt_version curl)" \
        "tzdata=$(require_apt_version tzdata)" \
        "software-properties-common=$(require_apt_version software-properties-common)" \
        "gnupg=$(require_apt_version gnupg)"; \
    add-apt-repository -y ppa:deadsnakes/ppa; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "python3.11=$(require_apt_version python3.11)" \
        "python3.11-dev=$(require_apt_version python3.11-dev)" \
        "python3.11-venv=$(require_apt_version python3.11-venv)" \
        "python3.11-distutils=$(require_apt_version python3.11-distutils)" \
        "patch=$(require_apt_version patch)" \
        "gcc=$(require_apt_version gcc)" \
        "g++=$(require_apt_version g++)" \
        "libedit-dev=$(require_apt_version libedit-dev)" \
        "libbz2-dev=$(require_apt_version libbz2-dev)" \
        "libstdc++6=$(require_apt_version libstdc++6)" \
        "libssl3t64=$(require_apt_version libssl3t64)" \
        "libssl-dev=$(require_apt_version libssl-dev)"; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apt-get upgrade -y --no-install-recommends; \
        apt-get autoremove -y --purge || true; \
    fi; \
    rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

# Create a venv to not depend on "system pip" state
ENV VENV=/opt/venv
COPY docker/install-ice-python.sh /tmp/install-ice-python.sh
RUN set -euo pipefail; \
    python3.11 -m venv "$VENV"; \
    "$VENV/bin/python" -m pip install --upgrade \
        "pip==${PIP_VERSION}" \
        "setuptools==${SETUPTOOLS_VERSION}" \
        "wheel==${WHEEL_VERSION}"; \
    /bin/bash /tmp/install-ice-python.sh "$VENV/bin/python"; \
    rm -f /tmp/install-ice-python.sh; \
    "$VENV/bin/python" -m pip install \
        "celery==5.6.3" \
        "redis==8.1.0" \
        "omero-py==5.23.0" \
        "pillow==${PILLOW_VERSION}" \
        "numpy==${NUMPY_VERSION}"

# Non-root runtime user
RUN set -euo pipefail; \
    groupadd --gid 10001 celery; \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin celery

# Install your in-tree python packages into the venv site-packages
COPY omero_imaris_connector /tmp/omero_imaris_connector
COPY omero_plugin_common /tmp/omero_plugin_common

RUN set -euo pipefail; \
    SITE_PACKAGES="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"; \
    rm -rf "${SITE_PACKAGES}/omero_imaris_connector" "${SITE_PACKAGES}/omero_plugin_common"; \
    cp -a /tmp/omero_imaris_connector "${SITE_PACKAGES}/omero_imaris_connector"; \
    cp -a /tmp/omero_plugin_common "${SITE_PACKAGES}/omero_plugin_common"; \
    chown -R celery:celery \
        "${SITE_PACKAGES}/omero_imaris_connector" \
        "${SITE_PACKAGES}/omero_plugin_common"; \
    rm -rf /tmp/omero_imaris_connector /tmp/omero_plugin_common

# Curated compatibility-safe Python hardening
# ----------------------------------------------------------
RUN set -euo pipefail; \
    if [ "${APPLY_SECURITY_HARDENING}" != "1" ]; then \
        echo "Skipping curated Python hardening (APPLY_SECURITY_HARDENING=${APPLY_SECURITY_HARDENING})."; \
        exit 0; \
    fi; \
    echo "Applying curated compatibility-safe Python hardening in ${VENV}..."; \
    "$VENV/bin/python" -m pip install --no-cache-dir --upgrade \
        "pip==${PIP_VERSION}" \
        "setuptools==${SETUPTOOLS_VERSION}" \
        "wheel==${WHEEL_VERSION}" \
        "cryptography==${CRYPTOGRAPHY_VERSION}" \
        "certifi==${CERTIFI_VERSION}" \
        "idna==${IDNA_VERSION}" \
        "requests==${REQUESTS_VERSION}" \
        "jinja2==${JINJA2_VERSION}" \
        "urllib3==${URLLIB3_VERSION}"; \
    "$VENV/bin/python" -m pip check; \
    echo "Skipping blanket celery-worker venv upgrades to preserve pinned/runtime-integrated packages."

USER celery
ENV PATH="/opt/venv/bin:${PATH}"

# This image is primarily reused by standalone smoke/debug runs, so the
# healthcheck validates that the packaged worker environment is importable.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD /opt/venv/bin/python -c 'import celery, omero_imaris_connector, omero_plugin_common' || exit 1
