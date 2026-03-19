# Custom OMERO.server image with several plugins and OMERO.Figure PDF export dependencies installed

# Pull image
# ----------
FROM openmicroscopy/omero-server:5.6.17

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

# Shared DNF retry settings for transient upstream mirror failures
# --------------------------------------------------------------
ARG DNF_MAX_ATTEMPTS=3
ARG DNF_RETRY_SLEEP_SECONDS=0
ARG DNF_USE_ROCKY_MIRRORLIST=1

# Locate OMERO.server venv and directories, then prepare stable symlinks
# ----------------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    SERVER_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || -z "${SERVER_DIR}" ]]; then \
        echo "ERROR: Could not find venv or OMERO.server directory" >&2; \
        exit 1; \
    fi; \
    if [[ ! -e /opt/omero/server/OMERO.server ]]; then \
        ln -s "${SERVER_DIR}" /opt/omero/server/OMERO.server; \
    fi; \
    mkdir -p "${SERVER_DIR}/bin"; \
    ln -sf "${VENV_DIR}/bin/python" "${SERVER_DIR}/bin/python"; \
    echo "Created symlink: ${SERVER_DIR}/bin/python -> ${VENV_DIR}/bin/python"

# Upgrade OMEZarrReader and JZarr to support modern OME-NGFF zarrs
# -----------------------------------------------------------------
# The base image ships OMEZarrReader 0.3.1 (Mar 2023) and JZarr 0.3.4 (Aug 2021).
# These are too old to handle many zarr layouts produced by modern tools.
# Update to OMEZarrReader 0.6.0 (Jan 2025) + JZarr 0.4.2 (Oct 2023).
ARG OMEZARR_READER_VERSION=0.6.0
ARG JZARR_VERSION=0.4.2
RUN set -euo pipefail; \
    SERVER_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${SERVER_DIR}" ]]; then \
        echo "ERROR: Could not find OMERO.server directory" >&2; \
        exit 1; \
    fi; \
    OMEZARR_URL="https://artifacts.openmicroscopy.org/artifactory/ome.releases/ome/OMEZarrReader/${OMEZARR_READER_VERSION}/OMEZarrReader-${OMEZARR_READER_VERSION}.jar"; \
    JZARR_URL="https://repo1.maven.org/maven2/dev/zarr/jzarr/${JZARR_VERSION}/jzarr-${JZARR_VERSION}.jar"; \
    echo "Downloading OMEZarrReader ${OMEZARR_READER_VERSION} from ${OMEZARR_URL}"; \
    curl -fsSL -o /tmp/OMEZarrReader.jar "${OMEZARR_URL}"; \
    echo "Downloading JZarr ${JZARR_VERSION} from ${JZARR_URL}"; \
    curl -fsSL -o /tmp/jzarr.jar "${JZARR_URL}"; \
    for subdir in lib/client lib/server; do \
        target="${SERVER_DIR}/${subdir}"; \
        if [[ -d "${target}" ]]; then \
            cp /tmp/OMEZarrReader.jar "${target}/OMEZarrReader.jar"; \
            cp /tmp/jzarr.jar "${target}/jzarr.jar"; \
            chown omero-server:omero-server "${target}/OMEZarrReader.jar" "${target}/jzarr.jar"; \
            echo "Updated ${target}/OMEZarrReader.jar and jzarr.jar"; \
        fi; \
    done; \
    rm -f /tmp/OMEZarrReader.jar /tmp/jzarr.jar; \
    echo "OMEZarrReader ${OMEZARR_READER_VERSION} + JZarr ${JZARR_VERSION} installed"

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
            "urllib3>=2.6.3" \
            "certifi" \
            "idna>=3.7" \
            "requests>=2.32.0" \
            "jinja2>=3.1.6" \
            "pyopenssl>=24.0.0"; \
        "${VENV_DIR}/bin/python" -c "import importlib.metadata as metadata; import setuptools, wheel, cryptography, urllib3; print(\"Python packaging import check succeeded (setuptools={})\".format(metadata.version(\"setuptools\")))"; \
    done

# APPLY_SECURITY_HARDENING is declared here for layer ordering but the
# broad upgrade runs at the end of the Dockerfile (after all pip/dnf installs)
# so that every transitive dependency is covered.
ARG APPLY_SECURITY_HARDENING=0

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
            pytest==7.4.4 \
            "setuptools==${SETUPTOOLS_VERSION}" \
            wheel; \
        SITE_PACKAGES="$("${VENV_DIR}/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"; \
        chown -R omero-server:omero-server "${SITE_PACKAGES}"; \
    done

# Install runtime diagnostics + git
# ---------------------------------
RUN set -euo pipefail; \
    dnf_retry() { \
        local attempt=1; \
        local max_attempts="${DNF_MAX_ATTEMPTS}"; \
        local fallback_applied=0; \
        while true; do \
            if dnf -y --refresh \
                --setopt=timeout=20 \
                --setopt=retries=2 \
                "$@"; then \
                return 0; \
            fi; \
            if [[ "${attempt}" -eq 1 && "${fallback_applied}" -eq 0 && "${DNF_USE_ROCKY_MIRRORLIST}" == "1" ]]; then \
                echo "WARNING: First dnf attempt failed; enabling Rocky baseurl fallback and cleaning metadata cache before retry." >&2; \
                for repo_file in /etc/yum.repos.d/rocky*.repo; do \
                    if [[ -f "${repo_file}" ]]; then \
                        sed -i -E 's|^mirrorlist=|#mirrorlist=|g' "${repo_file}"; \
                        sed -i -E 's|^#baseurl=|baseurl=|g' "${repo_file}"; \
                    fi; \
                done; \
                dnf clean all || true; \
                rm -rf /var/cache/dnf || true; \
                fallback_applied=1; \
            fi; \
            if [[ "${attempt}" -ge "${max_attempts}" ]]; then \
                echo "ERROR: dnf command failed after ${max_attempts} attempts: dnf $*" >&2; \
                return 1; \
            fi; \
            echo "WARNING: dnf command failed on attempt ${attempt}/${max_attempts}; retrying in ${DNF_RETRY_SLEEP_SECONDS}s..." >&2; \
            attempt=$((attempt + 1)); \
            sleep "${DNF_RETRY_SLEEP_SECONDS}"; \
        done; \
    }; \
    if [[ "${APPLY_DNF_UPDATES}" == "1" ]]; then \
        dnf_retry update --security || dnf_retry update; \
    fi; \
    dnf_retry install \
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
    dnf clean all || true; \
    rm -rf /var/cache/dnf /var/tmp/* || true

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
        find /opt/omero/server/OMERO.server/lib/scripts/omero -maxdepth 1 -ls >&2 || true; \
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

# Install the OMERO.Figure PDF export script at build time.
# Relying on a runtime download here makes PDF export nondeterministic and can
# leave OMERO.figure without Figure_To_Pdf.py when outbound network access fails.
ARG OME_OMERO_FIGURE_REPO="https://github.com/ome/omero-figure.git"
ARG OME_OMERO_FIGURE_REF="7.3.1"
RUN set -euo pipefail; \
    echo "Installing OMERO.Figure Figure_To_Pdf.py from ${OME_OMERO_FIGURE_REPO} @ ${OME_OMERO_FIGURE_REF}"; \
    rm -rf /tmp/ome-omero-figure; \
    git clone --depth 1 --branch "v${OME_OMERO_FIGURE_REF#v}" "${OME_OMERO_FIGURE_REPO}" /tmp/ome-omero-figure \
        || git clone --depth 1 --branch "${OME_OMERO_FIGURE_REF#v}" "${OME_OMERO_FIGURE_REPO}" /tmp/ome-omero-figure; \
    SCRIPT_SRC="/tmp/ome-omero-figure/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py"; \
    if [[ ! -f "${SCRIPT_SRC}" ]]; then \
        echo "ERROR: Figure_To_Pdf.py not found in the cloned OMERO.figure repo." >&2; \
        echo "Repo top-level layout is (FYI):" >&2; \
        (cd /tmp/ome-omero-figure && find . -maxdepth 3 -type d -print) >&2 || true; \
        exit 1; \
    fi; \
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts; \
    cp -f "${SCRIPT_SRC}" /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py; \
    chown omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py; \
    chmod 0644 /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py; \
    rm -rf /tmp/ome-omero-figure

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
COPY startup/50-install-omero-downloader.sh /startup/50-install-omero-downloader.sh
COPY startup/51-install-imarisconvert.sh /startup/51-install-imarisconvert.sh
RUN set -euo pipefail; \
    for startup_script in \
        /startup/10-server-bootstrap.sh \
        /startup/50-install-omero-downloader.sh \
        /startup/51-install-imarisconvert.sh; do \
        chown root:root "${startup_script}"; \
        chmod 0555 "${startup_script}"; \
    done

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
    VENV_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    rm -rf "${SITE_PACKAGES}/omero_plugin_common"; \
    cp -a /tmp/omero_plugin_common "${SITE_PACKAGES}/omero_plugin_common"; \
    chown -R omero-server:omero-server "${SITE_PACKAGES}/omero_plugin_common"; \
    rm -rf /tmp/omero_plugin_common

# Patch omero-py TempFileManager to physically remove fallbacks and force strictly the env var
# --------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    TEMP_FILES_PY="${SITE_PACKAGES}/omero/util/temp_files.py"; \
    if [[ -f "${TEMP_FILES_PY}" ]]; then \
        echo "Removing fallback directories from OMERO python TempFileManager..."; \
        sed -i -e '/targets\.append(get_omero_userdir() \/ "tmp")/d' "${TEMP_FILES_PY}"; \
        sed -i -e '/targets\.append(path(tempfile\.gettempdir()) \/ "omero" \/ "tmp")/d' "${TEMP_FILES_PY}"; \
    fi

# Ensure OMERO server runtime directories are owned by omero-server
# so named volumes inherit correct permissions on first run.
# ----------------------------------------------------------
RUN set -euo pipefail; \
    mkdir -p /opt/omero/server/OMERO.server/var/log; \
    mkdir -p /opt/omero/server/OMERO.server/etc/grid; \
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/etc/grid; \
    chmod -R u+rwX,g+rwX /opt/omero/server/OMERO.server/etc/grid; \
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/var; \
    chmod -R g+rwX /opt/omero/server/OMERO.server/var

# Fix base image start script to drop privileges and keep root as image user
# --------------------------------------------------------------------------
RUN set -euo pipefail; \
    rm -f /startup/99-run.sh; \
    printf '%s\n' \
        '#!/bin/bash' \
        'set -eu' \
        'omero=$(find /opt/omero/server -maxdepth 1 -type d -name "venv*" | sort -V | tail -n 1)/bin/omero' \
        'if [ ! -x "$omero" ]; then' \
        '    echo "FATAL: OMERO CLI executable not found at $omero" >&2' \
        '    exit 127' \
        'fi' \
        'cd /opt/omero/server' \
        'echo "Starting OMERO.server as omero-server"' \
        'exec runuser -p -m -u omero-server -- "$omero" admin start --foreground' \
        > /startup/99-run.sh; \
    chmod 0555 /startup/99-run.sh

# Wrap entrypoint so all /startup/*.py AND 60-database.sh scripts run as omero-server, avoiding permission corruption
# ----------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    mv /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint-original.sh; \
    printf '%s\n' \
        '#!/bin/bash' \
        'set -e' \
        'VENV_ACTIVATE=$(find /opt/omero/server -maxdepth 1 -type d -name "venv*" | sort -V | tail -n 1)/bin/activate' \
        'if [ ! -f "$VENV_ACTIVATE" ]; then' \
        '    echo "FATAL: OMERO virtualenv activate script not found at $VENV_ACTIVATE" >&2' \
        '    exit 127' \
        'fi' \
        'source "$VENV_ACTIVATE"' \
        'for f in /startup/*; do' \
        '    if [ -f "$f" -a -x "$f" ]; then' \
        '        echo "Running $f $@"' \
        '        if [[ "$f" == *.py ]] || [[ "$f" == *60-database.sh ]]; then' \
        '            runuser -p -m -u omero-server -- "$f" "$@"' \
        '        else' \
        '            "$f" "$@"' \
        '        fi' \
        '    fi' \
        'done' \
        > /usr/local/bin/entrypoint.sh; \
    chmod 0755 /usr/local/bin/entrypoint.sh

# IMPORTANT: Fix the Docker healthcheck!
# The official image defines: HEALTHCHECK CMD omero admin diagnostics
# Since the image user is now root, this runs as root and crashes with the permission error.
# We must redefine it to drop to the omero-server user.
# --------------------------------------------------------------------------------------
HEALTHCHECK --interval=60s --timeout=30s --start-period=300s --retries=5 \
    CMD runuser -p -m -u omero-server -- sh -c 'set -eu; omero_bin=$(find /opt/omero/server -maxdepth 1 -type d -name "venv*" | sort -V | tail -n 1)/bin/omero; [ -x "${omero_bin}" ] || { echo "FATAL: OMERO CLI executable not found at ${omero_bin}" >&2; exit 127; }; exec "${omero_bin}" admin diagnostics'

# ---------------------------------------------------------------------------
# Final security hardening pass (APPLY_SECURITY_HARDENING=1)
#
# Runs AFTER all dnf installs and pip installs are complete, so that every
# transitive dependency introduced by earlier layers is covered.
# ---------------------------------------------------------------------------
RUN set -euo pipefail; \
    if [[ "${APPLY_SECURITY_HARDENING}" != "1" ]]; then \
        echo "Skipping final security hardening pass (APPLY_SECURITY_HARDENING=${APPLY_SECURITY_HARDENING})."; \
        exit 0; \
    fi; \
    echo "=== Final security hardening: OS packages (dnf) ==="; \
    dnf_retry() { \
        local attempt=1; \
        while true; do \
            if dnf -y --refresh --setopt=timeout=20 --setopt=retries=2 "$@"; then return 0; fi; \
            if [[ "${attempt}" -ge 3 ]]; then echo "WARNING: dnf hardening update failed after 3 attempts (non-fatal)." >&2; return 0; fi; \
            attempt=$((attempt + 1)); \
            sleep 1; \
        done; \
    }; \
    dnf_retry update || true; \
    echo "=== Final security hardening: removing unnecessary packages ==="; \
    dnf -y remove --noautoremove \
        vim-minimal \
        || true; \
    dnf clean all || true; \
    rm -rf /var/cache/dnf /var/tmp/* /usr/share/doc/* /usr/share/man/* /usr/share/info/* || true; \
    echo "=== Final security hardening: Python packages (pip) ==="; \
    mapfile -t VENV_DIRS < <(find /opt/omero/server -maxdepth 1 -mindepth 1 \( -type d -o -type l \) -name "venv*" | sort -u -V); \
    for VENV_DIR in "${VENV_DIRS[@]}"; do \
        if [[ ! -x "${VENV_DIR}/bin/python" ]]; then continue; fi; \
        echo "Applying curated compatibility-safe Python security updates in ${VENV_DIR}..."; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade \
            pip \
            wheel \
            cryptography>=42.0.0 \
            urllib3>=2.2.2 \
            certifi \
            idna>=3.7 \
            requests>=2.32.0 \
            jinja2>=3.1.6 \
            pyopenssl>=24.0.0 || \
            echo "WARNING: Some curated Python hardening updates failed (non-fatal)."; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir "setuptools==${SETUPTOOLS_VERSION}" || true; \
        echo "Stripping test directories and bytecode caches from ${VENV_DIR}..."; \
        find "${VENV_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
        find "${VENV_DIR}" -type d \( -name "tests" -o -name "test" -o -name "testing" \) \
            -not -path "*/omero/*" -not -path "*/Ice/*" \
            -exec rm -rf {} + 2>/dev/null || true; \
        find "${VENV_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true; \
    done; \
    echo "=== Final security hardening: stripping shared libraries ==="; \
    find /usr/lib64 /usr/lib -type f -name "*.so*" -exec strip --strip-unneeded {} 2>/dev/null \; || true

# Keep root as image user so bootstrap scripts can reconcile runtime permissions
# before dropping to the application user in 99-run.sh and in entrypoint python scripts
USER root
