# Custom OMERO.server image with several plugins and OMERO.Figure PDF export dependencies installed

# Pull image
# ----------
FROM openmicroscopy/omero-server:5.6.18@sha256:895317a8dba185da6a08fe412d337e62fb6bbb9f6579d33e485439020a43217f

# Run image build steps as root
# -----------------------------
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
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp \
    OMERO_TMPDIR=/tmp

# Keep every direct Python build dependency reproducible. Setuptools remains on
# the newest pkg_resources-compatible release because omego imports that API
# directly during database initialization.
# ---------------------------------------------------------------------------
ARG PIP_VERSION=26.1.2
ARG SETUPTOOLS_VERSION=80.9.0
ARG WHEEL_VERSION=0.47.0
ARG CRYPTOGRAPHY_VERSION=49.0.0
ARG URLLIB3_VERSION=2.7.0
ARG CERTIFI_VERSION=2026.6.17
ARG IDNA_VERSION=3.18
ARG REQUESTS_VERSION=2.34.2
ARG JINJA2_VERSION=3.1.6
ARG PYOPENSSL_VERSION=26.3.0
ARG REPORTLAB_VERSION=5.0.0
ARG MARKDOWN_VERSION=3.10.2
ARG OMERO_CLI_RENDER_VERSION=0.8.1
ARG OMERO_METADATA_VERSION=0.13.0
ARG OMERO_CLI_DUPLICATE_VERSION=0.4.0
ARG OMERO_RDF_VERSION=0.7.2

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
ARG OMEZARR_READER_SHA256=26e5b2e99a64abd1ba83ee52eeb5fcbd560190fed1097afb404c38bf24579e55
ARG JZARR_SHA256=43f265b26dc8de384802853a2df34e18f0d836eae8bf4538f6c61c479b366cd8
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
    printf '%s  %s\n' "${OMEZARR_READER_SHA256}" /tmp/OMEZarrReader.jar | sha256sum -c -; \
    echo "Downloading JZarr ${JZARR_VERSION} from ${JZARR_URL}"; \
    curl -fsSL -o /tmp/jzarr.jar "${JZARR_URL}"; \
    printf '%s  %s\n' "${JZARR_SHA256}" /tmp/jzarr.jar | sha256sum -c -; \
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

# Install omero-zarr-pixel-buffer for serving OME-NGFF zarr pixel data
# ---------------------------------------------------------------------
# Required by omero-cli-zarr imported images.  Without this server-side
# plugin, zarr-imported images have no accessible pixel data.
ARG OMERO_ZARR_PIXEL_BUFFER_VERSION=0.6.1
ARG OMERO_ZARR_PIXEL_BUFFER_SHA256=9cb3d1ed491ef866bc1703415b809097693fda13eb4818dc0eb6959f8fe94f97
ARG CAFFEINE_3_1_8_SHA256=7dd15f9df1be238ffaa367ce6f556737a88031de4294dad18eef57c474ddf1d3
ARG AWS_JAVA_SDK_S3_1_12_659_SHA256=44ed3a329a14c486a3f1c3b46eb47d26db4d93426a630790d2eefe542983dfa9
ARG AWS_JAVA_SDK_CORE_1_12_659_SHA256=f7713aa96c49f3e9f8c2a67b2d9b2d431d746fbfa9a73083be67f914043d23eb
ARG AWS_JAVA_SDK_KMS_1_12_659_SHA256=828c441cb154326f9dec238c498eeb346ea2a19f60e36f5910cccc7570b9bd10
ARG S3FS_2_2_3_SHA256=a22e94403de3dcf6e08fe233718d9364b578cf91555eb0dd6edc628443f44602
ARG TIKA_CORE_1_28_5_SHA256=e64b3dc06c60b98ecbdfb9dbc3857f4ab54f9548eedd449ee0de39c0df5e3170
RUN set -euo pipefail; \
    SERVER_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${SERVER_DIR}" ]]; then \
        echo "ERROR: Could not find OMERO.server directory" >&2; \
        exit 1; \
    fi; \
    PIXEL_BUFFER_URL="https://artifacts.glencoesoftware.com/artifactory/gs-omero-snapshots-local/com/glencoesoftware/omero/omero-zarr-pixel-buffer/${OMERO_ZARR_PIXEL_BUFFER_VERSION}/omero-zarr-pixel-buffer-${OMERO_ZARR_PIXEL_BUFFER_VERSION}.jar"; \
    echo "Downloading omero-zarr-pixel-buffer ${OMERO_ZARR_PIXEL_BUFFER_VERSION}"; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/omero-zarr-pixel-buffer-${OMERO_ZARR_PIXEL_BUFFER_VERSION}.jar" "${PIXEL_BUFFER_URL}"; \
    printf '%s  %s\n' "${OMERO_ZARR_PIXEL_BUFFER_SHA256}" "${SERVER_DIR}/lib/server/omero-zarr-pixel-buffer-${OMERO_ZARR_PIXEL_BUFFER_VERSION}.jar" | sha256sum -c -; \
    echo "Downloading omero-zarr-pixel-buffer runtime dependencies"; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/caffeine-3.1.8.jar" \
        "https://repo1.maven.org/maven2/com/github/ben-manes/caffeine/caffeine/3.1.8/caffeine-3.1.8.jar"; \
    printf '%s  %s\n' "${CAFFEINE_3_1_8_SHA256}" "${SERVER_DIR}/lib/server/caffeine-3.1.8.jar" | sha256sum -c -; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/aws-java-sdk-s3-1.12.659.jar" \
        "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-s3/1.12.659/aws-java-sdk-s3-1.12.659.jar"; \
    printf '%s  %s\n' "${AWS_JAVA_SDK_S3_1_12_659_SHA256}" "${SERVER_DIR}/lib/server/aws-java-sdk-s3-1.12.659.jar" | sha256sum -c -; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/aws-java-sdk-core-1.12.659.jar" \
        "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-core/1.12.659/aws-java-sdk-core-1.12.659.jar"; \
    printf '%s  %s\n' "${AWS_JAVA_SDK_CORE_1_12_659_SHA256}" "${SERVER_DIR}/lib/server/aws-java-sdk-core-1.12.659.jar" | sha256sum -c -; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/aws-java-sdk-kms-1.12.659.jar" \
        "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-kms/1.12.659/aws-java-sdk-kms-1.12.659.jar"; \
    printf '%s  %s\n' "${AWS_JAVA_SDK_KMS_1_12_659_SHA256}" "${SERVER_DIR}/lib/server/aws-java-sdk-kms-1.12.659.jar" | sha256sum -c -; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/s3fs-2.2.3.jar" \
        "https://repo1.maven.org/maven2/org/lasersonlab/s3fs/2.2.3/s3fs-2.2.3.jar"; \
    printf '%s  %s\n' "${S3FS_2_2_3_SHA256}" "${SERVER_DIR}/lib/server/s3fs-2.2.3.jar" | sha256sum -c -; \
    curl -fsSL -o "${SERVER_DIR}/lib/server/tika-core-1.28.5.jar" \
        "https://repo1.maven.org/maven2/org/apache/tika/tika-core/1.28.5/tika-core-1.28.5.jar"; \
    printf '%s  %s\n' "${TIKA_CORE_1_28_5_SHA256}" "${SERVER_DIR}/lib/server/tika-core-1.28.5.jar" | sha256sum -c -; \
    chown omero-server:omero-server "${SERVER_DIR}"/lib/server/omero-zarr-pixel-buffer-*.jar \
        "${SERVER_DIR}"/lib/server/caffeine-*.jar \
        "${SERVER_DIR}"/lib/server/aws-java-sdk-*.jar \
        "${SERVER_DIR}"/lib/server/s3fs-*.jar \
        "${SERVER_DIR}"/lib/server/tika-core-*.jar; \
    echo "omero-zarr-pixel-buffer ${OMERO_ZARR_PIXEL_BUFFER_VERSION} + dependencies installed"

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
            "pip==${PIP_VERSION}" \
            "setuptools==${SETUPTOOLS_VERSION}" \
            "wheel==${WHEEL_VERSION}" \
            "cryptography==${CRYPTOGRAPHY_VERSION}" \
            "urllib3==${URLLIB3_VERSION}" \
            "certifi==${CERTIFI_VERSION}" \
            "idna==${IDNA_VERSION}" \
            "requests==${REQUESTS_VERSION}" \
            "jinja2==${JINJA2_VERSION}" \
            "pyopenssl==${PYOPENSSL_VERSION}"; \
        "${VENV_DIR}/bin/python" -c "import importlib.metadata as metadata; import setuptools, wheel, cryptography, urllib3; print(\"Python packaging import check succeeded (setuptools={})\".format(metadata.version(\"setuptools\")))"; \
    done

# APPLY_SECURITY_HARDENING is declared here for layer ordering but the
# broad upgrade runs at the end of the Dockerfile (after all pip/dnf installs)
# so that every transitive dependency is covered.
ARG APPLY_SECURITY_HARDENING=0

# Install OMERO.Figure PDF export dependencies in the OMERO.server virtualenv
# ---------------------------------------------------------------------------
ARG TIFFFILE_VERSION
RUN set -euo pipefail; \
    : "${TIFFFILE_VERSION:?TIFFFILE_VERSION must be provided from env/omeroserver.env}"; \
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
            "reportlab==${REPORTLAB_VERSION}" \
            "markdown==${MARKDOWN_VERSION}" \
            "tifffile==${TIFFFILE_VERSION}"; \
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
            "omero-cli-render==${OMERO_CLI_RENDER_VERSION}" \
            "omero-metadata==${OMERO_METADATA_VERSION}" \
            "omero-cli-duplicate==${OMERO_CLI_DUPLICATE_VERSION}" \
            "omero-rdf==${OMERO_RDF_VERSION}"; \
    done

# Install OMERO.dropbox into the OMERO.server virtualenv
# ------------------------------------------------------
ARG OMERO_DROPBOX_VERSION
RUN set -euo pipefail; \
    if [[ -z "${OMERO_DROPBOX_VERSION:-}" ]]; then \
        echo "ERROR: OMERO_DROPBOX_VERSION must be provided from env/omeroserver.env" >&2; \
        exit 1; \
    fi; \
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
            "omero-dropbox==${OMERO_DROPBOX_VERSION}"; \
        "${VENV_DIR}/bin/python" -c "import fsDropBox, fsMonitorServer"; \
    done

# Prevent DropBox from auto-starting before Blitz accepts sessions. The
# startup bootstrap enables and starts DropBox explicitly after API readiness.
RUN set -euo pipefail; \
    SERVER_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'OMERO.server-*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${SERVER_DIR}" ]]; then \
        echo "ERROR: Could not find OMERO.server directory" >&2; \
        exit 1; \
    fi; \
    mapfile -t TEMPLATE_FILES < <(find "${SERVER_DIR}/etc" -type f -path '*/grid/templates.xml' | sort -u); \
    if [[ "${#TEMPLATE_FILES[@]}" -eq 0 ]]; then \
        echo "ERROR: No OMERO grid templates.xml files found below ${SERVER_DIR}/etc" >&2; \
        exit 1; \
    fi; \
    for template_file in "${TEMPLATE_FILES[@]}"; do \
        sed -i -E "s/(<server id=\"DropBox\" exe=\"[$][{]exe[}]\" activation=)\"always\"/\1\"manual\"/" "${template_file}"; \
        grep -Fq "<server id=\"DropBox\" exe=\"\${exe}\" activation=\"manual\"" "${template_file}" || { \
            echo "ERROR: Failed to set DropBox IceGrid activation to manual in ${template_file}" >&2; \
            exit 1; \
        }; \
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
            "pip==${PIP_VERSION}" \
            pytest==9.1.1 \
            "setuptools==${SETUPTOOLS_VERSION}" \
            "wheel==${WHEEL_VERSION}"; \
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
ARG OME_OMERO_SCRIPTS_COMMIT="5b4d76862a7141257c9ff221ff7f009f7ec416c0"
RUN set -euo pipefail; \
    echo "Installing official OMERO scripts from ${OME_OMERO_SCRIPTS_REPO} @ ${OME_OMERO_SCRIPTS_REF}"; \
    \
    rm -rf /tmp/ome-omero-scripts; \
    git clone --depth 1 --branch "${OME_OMERO_SCRIPTS_REF}" \
        "${OME_OMERO_SCRIPTS_REPO}" \
        /tmp/ome-omero-scripts; \
    actual_commit="$(git -C /tmp/ome-omero-scripts rev-parse HEAD)"; \
    if [[ "${actual_commit}" != "${OME_OMERO_SCRIPTS_COMMIT}" ]]; then \
        echo "ERROR: omero-scripts commit mismatch: expected=${OME_OMERO_SCRIPTS_COMMIT} actual=${actual_commit}" >&2; \
        exit 1; \
    fi; \
    \
    if [[ ! -d /tmp/ome-omero-scripts/omero ]]; then \
        echo "ERROR: Expected path 'omero/' not found in omero-scripts repo" >&2; \
        echo "Repo layout:" >&2; \
        find /tmp/ome-omero-scripts -maxdepth 2 -type d -print >&2 || true; \
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
ARG OME_OMERO_FIGURE_REF="7.4.1"
RUN set -euo pipefail; \
    echo "Installing OMERO.Figure Figure_To_Pdf.py from ${OME_OMERO_FIGURE_REPO} @ ${OME_OMERO_FIGURE_REF}"; \
    rm -rf /tmp/ome-omero-figure; \
    git clone --depth 1 --branch "v${OME_OMERO_FIGURE_REF#v}" "${OME_OMERO_FIGURE_REPO}" /tmp/ome-omero-figure \
        || git clone --depth 1 --branch "${OME_OMERO_FIGURE_REF#v}" "${OME_OMERO_FIGURE_REPO}" /tmp/ome-omero-figure; \
    SCRIPT_SRC="/tmp/ome-omero-figure/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py"; \
    if [[ ! -f "${SCRIPT_SRC}" ]]; then \
        echo "ERROR: Figure_To_Pdf.py not found in the cloned OMERO.figure repo." >&2; \
        echo "Repo top-level layout is (FYI):" >&2; \
        find /tmp/ome-omero-figure -maxdepth 3 -type d -print >&2 || true; \
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
ARG BIOP_OMERO_SCRIPTS_COMMIT="c9cc4615b1fab11450faa1e65e083dc59b825083"
RUN set -euo pipefail; \
    echo "Installing BIOP OMERO scripts from ${BIOP_OMERO_SCRIPTS_REPO} @ ${BIOP_OMERO_SCRIPTS_REF}"; \
    rm -rf /tmp/biop-omero-scripts; \
    git clone --depth 1 --branch "${BIOP_OMERO_SCRIPTS_REF}" "${BIOP_OMERO_SCRIPTS_REPO}" /tmp/biop-omero-scripts; \
    actual_commit="$(git -C /tmp/biop-omero-scripts rev-parse HEAD)"; \
    if [[ "${actual_commit}" != "${BIOP_OMERO_SCRIPTS_COMMIT}" ]]; then \
        echo "ERROR: BIOP OMERO-scripts commit mismatch: expected=${BIOP_OMERO_SCRIPTS_COMMIT} actual=${actual_commit}" >&2; \
        exit 1; \
    fi; \
    \
    SCRIPT_SRC="$(find /tmp/biop-omero-scripts -type f -name 'Export_CellProfiler_IDs.py' -print -quit)"; \
    if [[ -z "${SCRIPT_SRC}" ]]; then \
        echo "ERROR: Export_CellProfiler_IDs.py not found anywhere in the cloned BIOP repo." >&2; \
        echo "Repo top-level layout is (FYI):" >&2; \
        find /tmp/biop-omero-scripts -maxdepth 2 -type d -print >&2 || true; \
        echo "Nearest matches (filenames containing 'CellProfiler'):" >&2; \
        find /tmp/biop-omero-scripts -type f -iname '*cellprofiler*' -print >&2 || true; \
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
COPY startup/healthcheck-omeroserver.sh /startup/healthcheck-omeroserver.sh
COPY startup/50-config.py /startup/50-config.py
COPY startup/repo_root_sync_helper.py /startup/repo_root_sync_helper.py
COPY startup/dropbox_user_dir_sync.py /startup/dropbox_user_dir_sync.py
COPY startup/job_service_group_sync.py /startup/job_service_group_sync.py
COPY startup/50-install-omero-downloader.sh /startup/50-install-omero-downloader.sh
COPY startup/51-install-imarisconvert.sh /startup/51-install-imarisconvert.sh
RUN set -euo pipefail; \
    for startup_script in \
        /startup/10-server-bootstrap.sh \
        /startup/healthcheck-omeroserver.sh \
        /startup/50-config.py \
        /startup/repo_root_sync_helper.py \
        /startup/dropbox_user_dir_sync.py \
        /startup/50-install-omero-downloader.sh \
        /startup/51-install-imarisconvert.sh; do \
        chown root:root "${startup_script}"; \
        chmod 0555 "${startup_script}"; \
    done; \
    chown root:root /startup/job_service_group_sync.py; \
    chmod 0444 /startup/job_service_group_sync.py

# Remove "config drop default" and "certificates -v" from the base image's
# /opt/omero/server/config/00-omero-server.omero.
#
# Problem: the base image's 50-config.py runs  omero load --glob  on this file
# AFTER our 10-server-bootstrap.sh has already configured certificate SANs,
# omero.scripts.python, and other runtime properties.  The "config drop default"
# wipes all of those settings, and "certificates -v" regenerates certificates
# WITHOUT the SAN entries (DNS:omeroserver) that our bootstrap added —
# silently undoing the bootstrap's work.
#
# Fix: strip both lines so the file only retains "config set omero.data.dir".
# Our bootstrap now runs "config drop default" itself, BEFORE setting any
# properties, so the clean-slate guarantee is preserved in the correct order.
# --------------------------------------------------------------------------
RUN set -euo pipefail; \
    cfg="/opt/omero/server/config/00-omero-server.omero"; \
    if [ -f "${cfg}" ]; then \
        sed -i '/^config drop default$/d; /^certificates/d' "${cfg}"; \
    fi

# Pre-configure library path for ImarisConvertBioformats
# ------------------------------------------------------
ARG BIOFORMATS_VERSION
ARG BIOFORMATS_SHA256
RUN set -euo pipefail; \
    if [[ -z "${BIOFORMATS_VERSION:-}" ]]; then \
        echo "ERROR: BIOFORMATS_VERSION must be provided from env/omeroserver.env" >&2; \
        exit 1; \
    fi; \
    if [[ -z "${BIOFORMATS_SHA256:-}" ]]; then \
        echo "ERROR: BIOFORMATS_SHA256 must be provided from env/omeroserver.env" >&2; \
        exit 1; \
    fi; \
    BIOFORMATS_VERSION="${BIOFORMATS_VERSION}" BIOFORMATS_SHA256="${BIOFORMATS_SHA256}" /startup/51-install-imarisconvert.sh --install-build-time; \
    chown -R omero-server:omero-server /opt/omero/imarisconvert

RUN set -euo pipefail; \
    echo "/opt/omero/imarisconvert" > /etc/ld.so.conf.d/imarisconvert.conf; \
    ldconfig

# Copy IMS export script to OMERO scripts directory
# -------------------------------------------------
RUN set -euo pipefail; \
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts; \
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts/omero

COPY omero_imaris_connector/omero_scripts/IMS_Export.py /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py
RUN set -euo pipefail; \
    chown omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py; \
    chmod 0644 /opt/omero/server/OMERO.server/lib/scripts/omero/export_scripts/IMS_Export.py

COPY omeroweb_import/omero_scripts/Manage_Zarr_ManagedRepository.py /opt/omero/server/OMERO.server/lib/scripts/omero/import_scripts/Manage_Zarr_ManagedRepository.py
RUN set -euo pipefail; \
    chown omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts/omero/import_scripts/Manage_Zarr_ManagedRepository.py; \
    chmod 0644 /opt/omero/server/OMERO.server/lib/scripts/omero/import_scripts/Manage_Zarr_ManagedRepository.py

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

# Permit the environment-driven IMS export directory to reach Processor scripts.
# OMERO's Processor copies only an explicit environment allowlist into script
# subprocesses, so Compose-provided variables otherwise disappear before
# IMS_Export.py starts.
COPY docker/patch_omero_processor_env.py /tmp/patch_omero_processor_env.py
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    "${VENV_DIR}/bin/python" /tmp/patch_omero_processor_env.py "${SITE_PACKAGES}/omero/processor.py"; \
    rm -f /tmp/patch_omero_processor_env.py

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

# Fix base image start script to drop privileges when startup runs as root
# -----------------------------------------------------------------------
RUN set -euo pipefail; \
    rm -f /startup/99-run.sh; \
    printf '%s\n' \
        "#!/bin/bash" \
        "set -eu" \
        "omero=\$(find /opt/omero/server -maxdepth 1 -type d -name \"venv*\" | sort -V | tail -n 1)/bin/omero" \
        "if [ ! -x \"\$omero\" ]; then" \
        "    echo \"FATAL: OMERO CLI executable not found at \$omero\" >&2" \
        "    exit 127" \
        "fi" \
        "if [ \"\$(id -u)\" -eq 0 ]; then" \
        "    echo \"Starting OMERO.server as omero-server\"" \
        "    exec env USER=omero-server LOGNAME=omero-server LNAME=omero-server USERNAME=omero-server HOME=/opt/omero/server runuser -p -m -u omero-server -- \"\$omero\" admin start --foreground" \
        "fi" \
        "echo \"Starting OMERO.server as \$(id -un)\"" \
        "exec \"\$omero\" admin start --foreground" \
        > /startup/99-run.sh; \
    chmod 0555 /startup/99-run.sh

# Wrap entrypoint so root startup can repair bind mounts before privilege drop.
# Direct non-root image runs skip root-only bootstrap and launch the requested command.
# --------------------------------------------------------------------------------
RUN set -euo pipefail; \
    mv /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint-original.sh; \
    printf '%s\n' \
        "#!/bin/bash" \
        "set -e" \
        "if [ \"\$(id -u)\" -ne 0 ]; then" \
        "    printf 'Running unprivileged; skipping root startup bootstrap and launching: %s\n' \"\$*\"" \
        "    exec \"\$@\"" \
        "fi" \
        "VENV_ACTIVATE=\$(find /opt/omero/server -maxdepth 1 -type d -name \"venv*\" | sort -V | tail -n 1)/bin/activate" \
        "if [ ! -f \"\$VENV_ACTIVATE\" ]; then" \
        "    echo \"FATAL: OMERO virtualenv activate script not found at \$VENV_ACTIVATE\" >&2" \
        "    exit 127" \
        "fi" \
        "source \"\$VENV_ACTIVATE\"" \
        "if [ -z \"\${CONFIG_omero_db_pass+x}\" ] && [ -n \"\${OMERO_DB_PASS:-}\" ]; then" \
        "    export CONFIG_omero_db_pass=\"\$OMERO_DB_PASS\"" \
        "fi" \
        "for f in /startup/*; do" \
        "    if [ -f \"\$f\" ] && [ -x \"\$f\" ]; then" \
        "        printf 'Running %s %s\n' \"\$f\" \"\$*\"" \
        "        if [[ \"\$f\" == *.py ]] || [[ \"\$f\" == *60-database.sh ]]; then" \
        "            env USER=omero-server LOGNAME=omero-server LNAME=omero-server USERNAME=omero-server HOME=/opt/omero/server runuser -p -m -u omero-server -- \"\$f\" \"\$@\"" \
        "        else" \
        "            \"\$f\" \"\$@\"" \
        "        fi" \
        "    fi" \
        "done" \
        > /usr/local/bin/entrypoint.sh; \
    chmod 0755 /usr/local/bin/entrypoint.sh

# Keep the image healthcheck valid for both managed root-bootstrap starts and
# direct non-root image starts.
# --------------------------------------------------------------------------
HEALTHCHECK --interval=60s --timeout=30s --start-period=300s --retries=5 \
    CMD sh -c 'set -eu; omero_bin=$(find /opt/omero/server -maxdepth 1 -type d -name "venv*" | sort -V | tail -n 1)/bin/omero; [ -x "${omero_bin}" ] || { echo "FATAL: OMERO CLI executable not found at ${omero_bin}" >&2; exit 127; }; if [ "$(id -u)" -eq 0 ]; then exec env USER=omero-server LOGNAME=omero-server LNAME=omero-server USERNAME=omero-server HOME=/opt/omero/server runuser -p -m -u omero-server -- "${omero_bin}" admin diagnostics; fi; exec "${omero_bin}" admin diagnostics'

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
    dnf_retry upgrade --refresh || true; \
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
            "pip==${PIP_VERSION}" \
            "wheel==${WHEEL_VERSION}" \
            "cryptography==${CRYPTOGRAPHY_VERSION}" \
            "urllib3==${URLLIB3_VERSION}" \
            "certifi==${CERTIFI_VERSION}" \
            "idna==${IDNA_VERSION}" \
            "requests==${REQUESTS_VERSION}" \
            "jinja2==${JINJA2_VERSION}" \
            "pyopenssl==${PYOPENSSL_VERSION}" || \
            echo "WARNING: Some curated Python hardening updates failed (non-fatal)."; \
        "${VENV_DIR}/bin/python" -m pip install --no-cache-dir "setuptools==${SETUPTOOLS_VERSION}" || true; \
        echo "Stripping test directories and bytecode caches from ${VENV_DIR}..."; \
        find "${VENV_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true; \
        find "${VENV_DIR}" -type d \( -name "tests" -o -name "test" -o -name "testing" \) \
            -not -path "*/omero/*" -not -path "*/Ice/*" \
            -exec rm -rf {} + 2>/dev/null || true; \
        find "${VENV_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true; \
    done; \
    echo "=== Final security hardening: preserving shared libraries ==="; \
    echo "Skipping blanket shared-library stripping because it can corrupt critical runtime libraries."

# Default the image to the application user. Compose explicitly requests root
# only for managed startup bootstrap, then the entrypoint drops privileges.
USER omero-server
