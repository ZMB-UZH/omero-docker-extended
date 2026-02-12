################################################################################
# OMERO.server Custom Dockerfile
################################################################################
#
# PURPOSE:
#   Builds a custom OMERO.server container with:
#   - OMERO Python API (omero-py) with pinned setuptools for pkg_resources
#   - OMERO CLI plugins (render, metadata, duplicate, rdf)
#   - PDF export dependencies for OMERO.Figure (reportlab, markdown)
#   - Official OMERO scripts from ome/omero-scripts repo
#   - BIOP Export_CellProfiler_IDs.py script
#   - Custom IMS export script for Imaris conversion
#   - Build tools for ImarisConvertBioformats compilation
#   - Shared plugin utilities (omero_plugin_common)
#
# BUILD STRATEGY:
#   1. Start from official OMERO.server base image (pinned SHA)
#   2. Locate and validate OMERO.server venv (fails fast if missing)
#   3. Create stable symlink to versioned OMERO.server directory
#   4. Install/upgrade Python packaging tools with pinned setuptools
#   5. Install PDF export and CLI plugin dependencies
#   6. Clone and install official + BIOP OMERO scripts
#   7. Install build dependencies (cmake, gcc, Java, etc.)
#   8. Prepare directories for runtime-installed tools (downloader, imarisconvert)
#   9. Copy startup scripts and ensure correct permissions
#
# RUNTIME FLOW:
#   1. 10-server-bootstrap.sh runs at startup:
#      - Checks all required directories are writable
#      - Configures Python path for scripts
#      - Ensures SSL certificates have correct SANs
#      - Schedules async tasks (job service user creation, script registration)
#   2. 50-install-omero-downloader.sh installs OMERO downloader if needed
#   3. 51-install-imarisconvert.sh compiles ImarisConvertBioformats if needed
#   4. Base image entrypoint starts OMERO.server
#
# CRITICAL NOTES:
#   - setuptools version is PINNED to maintain pkg_resources compatibility
#   - All venv operations dynamically locate the venv to handle version changes
#   - Runtime directories are pre-owned by omero-server for write access
#   - Scripts are copied from official repos at build time (not runtime)
#
################################################################################

# Custom OMERO.server image with several plugins and OMERO.Figure PDF export dependencies installed

# Pull image
# ----------
FROM openmicroscopy/omero-server@sha256:990f257d4fb5a82d66d2c90f48308671f3b1b40434909de5f59751230b4aace7

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

# Keep setuptools on a pkg_resources-compatible release for omego startup.
# omego imports pkg_resources directly during DB initialization.
# --------------------------------------------------------------
ARG SETUPTOOLS_VERSION=80.9.0

# Locate OMERO.server venv and fail fast if layout changes
# --------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/server/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO server venv" >&2; \
        exit 1; \
    fi

# Ensure stable OMERO.server path points at the versioned installation
# --------------------------------------------------------------------
RUN set -euo pipefail; \
    SERVER_DIR="$(ls -d /opt/omero/server/OMERO.server-* 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${SERVER_DIR}" ]]; then \
        echo "ERROR: Could not find versioned OMERO.server directory." >&2; \
        exit 1; \
    fi; \
    if [[ ! -e /opt/omero/server/OMERO.server ]]; then \
        ln -s "${SERVER_DIR}" /opt/omero/server/OMERO.server; \
    fi

# Create Python symlink in OMERO.server/bin for bootstrap script
# --------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    SERVER_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || -z "${SERVER_DIR}" ]]; then \
        echo "ERROR: Could not find venv or OMERO.server directory" >&2; \
        exit 1; \
    fi; \
    mkdir -p "${SERVER_DIR}/bin"; \
    ln -sf "${VENV_DIR}/bin/python" "${SERVER_DIR}/bin/python"; \
    echo "Created symlink: ${SERVER_DIR}/bin/python -> ${VENV_DIR}/bin/python"

# Optional (off by default): vulnerability-testing updates for OMERO.server venv Python tooling
# WARNING:
# - Affects OMERO.server Python gateway
# - Enable only for vulnerability testing
# - Disable immediately if Blitz / TLS / import issues occur
# ----------------------------------------------------------
ARG APPLY_OMERO_VENV_TOOLING_UPDATES=0
RUN set -euo pipefail; \
    if [[ "${APPLY_OMERO_VENV_TOOLING_UPDATES}" != "1" ]]; then \
        echo "Skipping optional OMERO.server venv tooling updates (APPLY_OMERO_VENV_TOOLING_UPDATES=${APPLY_OMERO_VENV_TOOLING_UPDATES})."; \
        exit 0; \
    fi; \
    mapfile -t VENV_DIRS < <(find /opt/omero/server -maxdepth 1 -mindepth 1 \( -type d -o -type l \) -name "venv*" | sort -u -V); \
    if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then \
        echo "ERROR: No OMERO.server virtual environments found under /opt/omero/server" >&2; \
        exit 1; \
    fi; \
    for VENV_DIR in "${VENV_DIRS[@]}"; do \
        if [[ ! -x "${VENV_DIR}/bin/python" ]]; then \
            echo "ERROR: Invalid OMERO.server virtual environment: ${VENV_DIR}" >&2; \
            exit 1; \
        fi; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade \
            pip \
            "setuptools==${SETUPTOOLS_VERSION}" \
            wheel \
            "cryptography>=42.0.0" \
            "urllib3>=2.6.3"; \
        "${VENV_DIR}/bin/python" -c "import importlib.metadata as metadata; import setuptools, wheel, cryptography, urllib3; print(\"Python packaging import check succeeded (setuptools={})\".format(metadata.version(\"setuptools\")))"; \
    done

# Install OMERO.Figure PDF export dependencies in the OMERO.server virtualenv
# ---------------------------------------------------------------------------
RUN set -euo pipefail; \
    mapfile -t VENV_DIRS < <(find /opt/omero/server -maxdepth 1 -mindepth 1 -type d -name 'venv*' | sort -V); \
    if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then \
        echo "ERROR: No OMERO.server virtual environments found under /opt/omero/server" >&2; \
        exit 1; \
    fi; \
    for VENV_DIR in "${VENV_DIRS[@]}"; do \
        if [[ ! -x "${VENV_DIR}/bin/python" ]]; then \
            echo "ERROR: Invalid OMERO.server virtual environment: ${VENV_DIR}" >&2; \
            exit 1; \
        fi; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir \
            reportlab \
            markdown; \
    done

# Install several OMERO CLI plugins (official + unofficial)
# ---------------------------------------------------------
RUN set -euo pipefail; \
    mapfile -t VENV_DIRS < <(find /opt/omero/server -maxdepth 1 -mindepth 1 -type d -name 'venv*' | sort -V); \
    if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then \
        echo "ERROR: No OMERO.server virtual environments found under /opt/omero/server" >&2; \
        exit 1; \
    fi; \
    for VENV_DIR in "${VENV_DIRS[@]}"; do \
        if [[ ! -x "${VENV_DIR}/bin/python" ]]; then \
            echo "ERROR: Invalid OMERO.server virtual environment: ${VENV_DIR}" >&2; \
            exit 1; \
        fi; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir \
            omero-cli-render \
            omero-metadata \
            omero-cli-duplicate \
            omero-rdf; \
    done

# Ensure packaging tooling exists in every OMERO.server venv and is writable by runtime user
# ------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    mapfile -t VENV_DIRS < <(find /opt/omero/server -maxdepth 1 -mindepth 1 -type d -name 'venv*' | sort -V); \
    if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then \
        echo "ERROR: No OMERO.server virtual environments found under /opt/omero/server" >&2; \
        exit 1; \
    fi; \
    for VENV_DIR in "${VENV_DIRS[@]}"; do \
        if [[ ! -x "${VENV_DIR}/bin/python" ]]; then \
            echo "ERROR: Invalid OMERO.server virtual environment: ${VENV_DIR}" >&2; \
            exit 1; \
        fi; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade \
            pip \
            "setuptools==${SETUPTOOLS_VERSION}" \
            wheel; \
        SITE_PACKAGES="$("${VENV_DIR}/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"; \
        chown -R omero-server:omero-server "${SITE_PACKAGES}"; \
    done

# Install runtime diagnostics + git
# ---------------------------------
RUN set -euo pipefail; \
    if [[ "${APPLY_DNF_UPDATES}" == "1" ]]; then \
        dnf -y update --security || dnf -y update; \
    fi; \
    dnf -y install \
        --allowerasing \
        --setopt=install_weak_deps=False \
        --setopt=tsflags=nodocs \
        --nodocs \
        curl \
        git \
        procps-ng \
        iproute \
        net-tools \
        lsof \
        unzip \
        cmake \
        gcc \
        gcc-c++ \
        make \
        java-11-openjdk-devel \
        boost-devel \
        hdf5-devel \
        zlib-devel \
        lz4-devel \
        freeimage-devel; \
    dnf clean all; \
    rm -rf /var/cache/dnf /var/tmp/*

# Prepare writable paths for startup-installed tools
# --------------------------------------------------
RUN set -euo pipefail; \
    mkdir -p /opt/omero/downloader; \
    mkdir -p /opt/omero/imarisconvert; \
    chown -R omero-server:omero-server /opt/omero/downloader; \
    chown -R omero-server:omero-server /opt/omero/imarisconvert; \
    chgrp omero-server /usr/local/bin; \
    chmod 0775 /usr/local/bin

# Install official OMERO scripts (ome/omero-scripts)
# --------------------------------------------------
ARG OME_OMERO_SCRIPTS_REPO="https://github.com/ome/omero-scripts.git"
ARG OME_OMERO_SCRIPTS_REF="develop" # Recommended branch: "develop"; change to "master" for old/stable scripts
RUN set -euo pipefail; \
    echo "Installing official OMERO scripts from ${OME_OMERO_SCRIPTS_REPO} @ ${OME_OMERO_SCRIPTS_REF}"; \
    \
    rm -rf /tmp/ome-omero-scripts; \
    git clone --depth 1 --branch "${OME_OMERO_SCRIPTS_REF}" \
        "${OME_OMERO_SCRIPTS_REPO}" \
        /tmp/ome-omero-scripts; \
    \
    if [[ ! -d /tmp/ome-omero-scripts/omero ]]; then \
        echo "ERROR: Expected path 'omero/' not found in omero-scripts repo" >&2; \
        echo "Repo layout:" >&2; \
        (cd /tmp/ome-omero-scripts && find . -maxdepth 2 -type d -print) >&2 || true; \
        exit 1; \
    fi; \
    \
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero; \
    \
    echo "Copying official OMERO scripts into OMERO.server lib/scripts/omero"; \
    cp -a /tmp/ome-omero-scripts/omero/. \
        /opt/omero/server/OMERO.server/lib/scripts/omero/; \
    \
    if [[ ! -d /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts ]]; then \
        echo "ERROR: figure_scripts not found after copy (expected from omero-scripts repo)" >&2; \
        ls -la /opt/omero/server/OMERO.server/lib/scripts/omero >&2 || true; \
        exit 1; \
    fi; \
    \
    chown -R omero-server:omero-server \
        /opt/omero/server/OMERO.server/lib/scripts/omero; \
    \
    find /opt/omero/server/OMERO.server/lib/scripts/omero -type d -exec chmod 0755 {} \; ; \
    find /opt/omero/server/OMERO.server/lib/scripts/omero -type f -exec chmod 0644 {} \; ; \
    \
    rm -rf /tmp/ome-omero-scripts

# Install BIOP OMERO script: Export_CellProfiler_IDs.py
# -----------------------------------------------------
ARG BIOP_OMERO_SCRIPTS_REPO="https://github.com/BIOP/OMERO-scripts.git"
ARG BIOP_OMERO_SCRIPTS_REF="main"
RUN set -euo pipefail; \
    echo "Installing BIOP OMERO scripts from ${BIOP_OMERO_SCRIPTS_REPO} @ ${BIOP_OMERO_SCRIPTS_REF}"; \
    rm -rf /tmp/biop-omero-scripts; \
    git clone --depth 1 --branch "${BIOP_OMERO_SCRIPTS_REF}" "${BIOP_OMERO_SCRIPTS_REPO}" /tmp/biop-omero-scripts; \
    \
    SCRIPT_SRC="$(find /tmp/biop-omero-scripts -type f -name 'Export_CellProfiler_IDs.py' -print -quit)"; \
    if [[ -z "${SCRIPT_SRC}" ]]; then \
        echo "ERROR: Export_CellProfiler_IDs.py not found anywhere in the cloned BIOP repo." >&2; \
        echo "Repo top-level layout is (FYI):" >&2; \
        (cd /tmp/biop-omero-scripts && find . -maxdepth 2 -type d -print) >&2 || true; \
        echo "Nearest matches (filenames containing 'CellProfiler'):" >&2; \
        (cd /tmp/biop-omero-scripts && find . -type f -iname '*cellprofiler*' -print) >&2 || true; \
        exit 1; \
    fi; \
    \
    echo "Found Export_CellProfiler_IDs.py at: ${SCRIPT_SRC}"; \
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero/util_scripts; \
    cp -f "${SCRIPT_SRC}" /opt/omero/server/OMERO.server/lib/scripts/omero/util_scripts/Export_CellProfiler_IDs.py; \
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts && \
    find /opt/omero/server/OMERO.server/lib/scripts -type d -exec chmod 0755 {} \; && \
    find /opt/omero/server/OMERO.server/lib/scripts -type f -exec chmod 0644 {} \; && \
    rm -rf /tmp/biop-omero-scripts

# Consolidated OMERO.server startup flow
# --------------------------------------
COPY startup/10-server-bootstrap.sh /startup/10-server-bootstrap.sh
RUN set -euo pipefail; \
    chown root:root /startup/10-server-bootstrap.sh; \
    chmod 0555 /startup/10-server-bootstrap.sh

# Install OMERO downloader
# ------------------------
COPY startup/50-install-omero-downloader.sh /startup/50-install-omero-downloader.sh
RUN set -euo pipefail; \
    chown root:root /startup/50-install-omero-downloader.sh; \
    chmod 0555 /startup/50-install-omero-downloader.sh

# Install ImarisConvertBioformats
# -------------------------------
COPY startup/51-install-imarisconvert.sh /startup/51-install-imarisconvert.sh
RUN set -euo pipefail; \
    chown root:root /startup/51-install-imarisconvert.sh; \
    chmod 0555 /startup/51-install-imarisconvert.sh

# Pre-configure library path for ImarisConvertBioformats
# ------------------------------------------------------
RUN set -euo pipefail; \
    echo "/opt/omero/imarisconvert" > /etc/ld.so.conf.d/imarisconvert.conf; \
    ldconfig

# Copy IMS export script to OMERO scripts directory
# -------------------------------------------------
RUN set -euo pipefail; \
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts; \
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts/omero

COPY omeroweb_imaris_connector/omero_scripts/IMS_Export.py /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py
RUN set -euo pipefail; \
    chown omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py; \
    chmod 0644 /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py

# Install shared plugin utilities into OMERO.server venv (used by scripts)
# ------------------------------------------------------------------------
COPY omero_plugin_common /tmp/omero_plugin_common
RUN set -euo pipefail; \
    VENV_DIR="$(ls -d /opt/omero/server/venv* 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    rm -rf "${SITE_PACKAGES}/omero_plugin_common"; \
    cp -a /tmp/omero_plugin_common "${SITE_PACKAGES}/omero_plugin_common"; \
    chown -R omero-server:omero-server "${SITE_PACKAGES}/omero_plugin_common"; \
    rm -rf /tmp/omero_plugin_common

# Ensure OMERO server runtime directories are owned by omero-server
# so named volumes inherit correct permissions on first run.
# ----------------------------------------------------------
RUN set -euo pipefail; \
    mkdir -p /opt/omero/server/OMERO.server/var/log; \
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/var; \
    chmod -R g+rwX /opt/omero/server/OMERO.server/var

# Drop privileges for runtime
# ---------------------------
USER omero-server
