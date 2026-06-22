## ATTENTION!! Using the tag "latest" might be tempting but is extremely risky in production environments!
## ATTENTION!! The python venv lines will need to be changed to the correct/latest path
# when the OMERO developers update the container

# Pull image
# ----------
FROM openmicroscopy/omero-web-standalone:5.32.0@sha256:21eda1b301b6e68fab4382df31a4b797218de3aaff3bba08c05b498c20eec8b7

# Run image build steps as root
# -----------------------------
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
ARG DNF_MAX_ATTEMPTS=3
ARG DNF_RETRY_SLEEP_SECONDS=0
ARG DNF_USE_ROCKY_MIRRORLIST=1

# Basic hardening for pip (no behavior change expected)
# -----------------------------------------------------
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Locate OMERO.web venv, validate layout, and ensure stable OMERO.web symlink
# ---------------------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi; \
    WEB_DIR="$(find /opt/omero -maxdepth 4 -type d -name 'OMERO.web*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -n "${WEB_DIR}" ]]; then \
        mkdir -p /opt/omero/web; \
        if [[ ! -e /opt/omero/web/OMERO.web ]]; then \
            ln -s "${WEB_DIR}" /opt/omero/web/OMERO.web; \
        fi; \
    elif [[ ! -d /opt/omero/web/OMERO.web ]]; then \
        echo "ERROR: Could not find OMERO.web directory under /opt/omero or fallback /opt/omero/web/OMERO.web." >&2; \
        exit 1; \
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
    dnf -y upgrade --refresh --security || dnf -y upgrade --refresh; \
    dnf clean all || true; \
    rm -rf /var/cache/dnf /var/tmp/* || true

# Install build dependencies required for installing OMERO Python API (omero-py)
# NOTE: omero-py depends on ZeroC Ice (native extension) and cannot be installed without a compiler
# -------------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    curl -fsSL https://download.docker.com/linux/centos/docker-ce.repo -o /etc/yum.repos.d/docker-ce.repo; \
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
    dnf_retry install \
        gcc \
        gcc-c++ \
        make \
        blosc \
        python3-devel \
        supervisor \
        procps-ng \
        quota \
        e2fsprogs \
        docker-ce-cli \
        docker-compose-plugin; \
    dnf clean all || true; \
    rm -rf /var/cache/dnf /var/tmp/* || true

# Install OMERO Python API into OMERO.web venv (needed for BlitzGateway + TXT attachments)
# IMPORTANT: Pin omero-py to match OMERO.server stack
# ---------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir "omero-py==5.22.1"

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
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    rm -rf "${SITE_PACKAGES}/omeroweb_omp_plugin" \
        "${SITE_PACKAGES}/omero_web_zarr" \
        "${SITE_PACKAGES}/omeroweb_import" \
        "${SITE_PACKAGES}/omeroweb_tools" \
        "${SITE_PACKAGES}/omeroweb_admin_tools" \
        "${SITE_PACKAGES}/omero_imaris_connector" \
        "${SITE_PACKAGES}/omero_plugin_common"

# Copy the plugins into the container
# -----------------------------------
COPY omeroweb_omp_plugin /tmp/omeroweb_omp_plugin
COPY omeroweb_import /tmp/omeroweb_import
COPY omeroweb_tools /tmp/omeroweb_tools
COPY omeroweb_admin_tools /tmp/omeroweb_admin_tools
COPY omero_imaris_connector /tmp/omero_imaris_connector
COPY omero_plugin_common /tmp/omero_plugin_common
COPY omero_web_zarr /tmp/omero_web_zarr
COPY third_party /tmp/third_party
COPY docs/help /tmp/omero_plugin_help_docs
COPY docker/patch_omeroweb_api_servers.py /tmp/patch_omeroweb_api_servers.py
COPY docker/patch_omeroweb_logo_context.py /tmp/patch_omeroweb_logo_context.py

COPY tools/write_branding_logo_fallback.py /opt/omero/tools/write_branding_logo_fallback.py
# Install psycopg2-binary
# Add redis and django-redis for shared cache across workers
# Fix permissions in the end (plugin should be owned by omero-web)
# ----------------------------------------------------------------
ARG OMERO_CLI_ZARR_VERSION
ARG OME_ZARR_PY_VERSION
ARG BIOFORMATS2RAW_VERSION
ARG BIOFORMATS2RAW_SHA256=ea5352eb684ed989622559e2cd594077ce5f58b6fe375ede08518856622a3864
ARG TIFFFILE_VERSION
RUN set -euo pipefail; \
    : "${OMERO_CLI_ZARR_VERSION:?OMERO_CLI_ZARR_VERSION must be provided from env/omeroserver.env}"; \
    : "${OME_ZARR_PY_VERSION:?OME_ZARR_PY_VERSION must be provided from env/omeroserver.env}"; \
    : "${BIOFORMATS2RAW_VERSION:?BIOFORMATS2RAW_VERSION must be provided from env/omeroserver.env}"; \
    : "${TIFFFILE_VERSION:?TIFFFILE_VERSION must be provided from env/omeroserver.env}"; \
    mapfile -t VIZARR_BUILD_DIRS < <(find /tmp/third_party -mindepth 1 -maxdepth 1 -type d -name 'vizarr-*' | sort); \
    if [[ "${#VIZARR_BUILD_DIRS[@]}" -ne 1 ]]; then \
        echo "ERROR: Expected exactly one vendored Vizarr build under /tmp/third_party, found ${#VIZARR_BUILD_DIRS[@]}" >&2; \
        exit 1; \
    fi; \
    VIZARR_BUILD_DIR="${VIZARR_BUILD_DIRS[0]}"; \
    VIZARR_COMMIT="${VIZARR_BUILD_DIR##*/vizarr-}"; \
    if [[ ! "${VIZARR_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then \
        echo "ERROR: Vendored Vizarr directory must be named vizarr-<40-hex-commit>: ${VIZARR_BUILD_DIR}" >&2; \
        exit 1; \
    fi; \
    if [[ ! -f "${VIZARR_BUILD_DIR}/dist/index.html" ]]; then \
        echo "ERROR: Vendored Vizarr build is missing dist/index.html: ${VIZARR_BUILD_DIR}" >&2; \
        exit 1; \
    fi; \
    if find "${VIZARR_BUILD_DIR}/dist" -type f -name '*.map' | grep -q .; then \
        echo "ERROR: Vendored Vizarr build must not contain source maps: ${VIZARR_BUILD_DIR}" >&2; \
        exit 1; \
    fi; \
    rm -rf /tmp/omero_web_zarr/static/omero_web_zarr/vendor/vizarr; \
    mkdir -p /tmp/omero_web_zarr/static/omero_web_zarr/vendor/vizarr; \
    cp -a "${VIZARR_BUILD_DIR}/dist" "/tmp/omero_web_zarr/static/omero_web_zarr/vendor/vizarr/${VIZARR_COMMIT}"; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    cp -a /tmp/omeroweb_omp_plugin "${SITE_PACKAGES}/omeroweb_omp_plugin"; \
    cp -a /tmp/omeroweb_import "${SITE_PACKAGES}/omeroweb_import"; \
    cp -a /tmp/omeroweb_tools "${SITE_PACKAGES}/omeroweb_tools"; \
    cp -a /tmp/omeroweb_admin_tools "${SITE_PACKAGES}/omeroweb_admin_tools"; \
    cp -a /tmp/omero_imaris_connector "${SITE_PACKAGES}/omero_imaris_connector"; \
    cp -a /tmp/omero_plugin_common "${SITE_PACKAGES}/omero_plugin_common"; \
    mkdir -p "${SITE_PACKAGES}/docs"; \
    cp -a /tmp/omero_plugin_help_docs "${SITE_PACKAGES}/docs/help"; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir \
        matplotlib \
        pytest==7.4.4 \
        psycopg2-binary==2.9.12 \
        celery==5.6.3 \
        redis==5.0.8 \
        "django-redis>=5.4.0" \
        omero-fpbioimage \
        omero-gallery \
        omero-parade \
        omero-web-zarr \
        "ome-zarr==${OME_ZARR_PY_VERSION}" \
        "omero-cli-zarr==${OMERO_CLI_ZARR_VERSION}" \
        "tifffile==${TIFFFILE_VERSION}"; \
    rm -rf "${SITE_PACKAGES}/omero_web_zarr"; \
    cp -a /tmp/omero_web_zarr "${SITE_PACKAGES}/omero_web_zarr"; \
    chown -R omero-web:omero-web \
        "${SITE_PACKAGES}/omeroweb_omp_plugin" \
        "${SITE_PACKAGES}/omero_web_zarr" \
        "${SITE_PACKAGES}/omeroweb_import" \
        "${SITE_PACKAGES}/omeroweb_tools" \
        "${SITE_PACKAGES}/omeroweb_admin_tools" \
        "${SITE_PACKAGES}/omero_imaris_connector" \
        "${SITE_PACKAGES}/omero_plugin_common" \
        "${SITE_PACKAGES}/docs/help"; \
    rm -rf \
        /tmp/omeroweb_omp_plugin \
        /tmp/omero_web_zarr \
        /tmp/omeroweb_import \
        /tmp/omeroweb_tools \
        /tmp/omeroweb_admin_tools \
        /tmp/omero_imaris_connector \
        /tmp/omero_plugin_common \
        /tmp/omero_plugin_help_docs \
        /tmp/third_party

RUN set -euo pipefail; \
    archive="/tmp/bioformats2raw-${BIOFORMATS2RAW_VERSION}.zip"; \
    install_dir="/opt/bioformats2raw-${BIOFORMATS2RAW_VERSION}"; \
    stable_link="/opt/bioformats2raw"; \
    curl -fsSL "https://github.com/glencoesoftware/bioformats2raw/releases/download/v${BIOFORMATS2RAW_VERSION}/bioformats2raw-${BIOFORMATS2RAW_VERSION}.zip" -o "${archive}"; \
    printf '%s  %s\n' "${BIOFORMATS2RAW_SHA256}" "${archive}" | sha256sum -c -; \
    rm -rf "${install_dir}" "${stable_link}"; \
    unzip -q "${archive}" -d /opt; \
    if [[ ! -d "${install_dir}" ]]; then \
        echo "ERROR: Expected extracted directory ${install_dir} was not created" >&2; \
        exit 1; \
    fi; \
    ln -s "${install_dir}" "${stable_link}"; \
    ln -sf "${stable_link}/bin/bioformats2raw" /usr/local/bin/bioformats2raw; \
    chmod 0755 "${install_dir}/bin/bioformats2raw"; \
    /usr/local/bin/bioformats2raw --help >/dev/null; \
    rm -f "${archive}"

# Patch OMERO.web API server discovery and keep optional top-logo context keys
# defined when unset. The API patch makes `/api/v0/servers/` return the
# explicit public host or allowlisted request host for this deployment's
# configured OMERO endpoint, so desktop clients do not see Docker-only names.
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    API_VIEWS_PY="${SITE_PACKAGES}/omeroweb/api/views.py"; \
    "${VENV_DIR}/bin/python" /tmp/patch_omeroweb_api_servers.py "${API_VIEWS_PY}"; \
    chown omero-web:omero-web "${API_VIEWS_PY}"; \
    DECORATORS_PY="${SITE_PACKAGES}/omeroweb/webclient/decorators.py"; \
    "${VENV_DIR}/bin/python" /tmp/patch_omeroweb_logo_context.py "${DECORATORS_PY}"; \
    chown omero-web:omero-web "${DECORATORS_PY}"; \
    rm -f /tmp/patch_omeroweb_api_servers.py; \
    rm -f /tmp/patch_omeroweb_logo_context.py

# Patch omero-py TempFileManager to physically remove fallbacks and force strictly the env var
# --------------------------------------------------------------------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    TEMP_FILES_PY="${SITE_PACKAGES}/omero/util/temp_files.py"; \
    if [[ -f "${TEMP_FILES_PY}" ]]; then \
        echo "Removing fallback directories from OMERO python TempFileManager..."; \
        sed -i -e '/targets\.append(get_omero_userdir() \/ "tmp")/d' "${TEMP_FILES_PY}"; \
        sed -i -e '/targets\.append(path(tempfile\.gettempdir()) \/ "omero" \/ "tmp")/d' "${TEMP_FILES_PY}"; \
    fi

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
        /opt/omero/web/OMERO.web/var/static/omeroweb_import \
        /opt/omero/web/OMERO.web/var/static/omeroweb_admin_tools \
        /opt/omero/web/OMERO.web/var/static/omero_imaris_connector \
        /opt/omero/web/OMERO.web/var/static/omero_web_zarr; \
    chown -R omero-web:omero-web /opt/omero/web/OMERO.web/var

# Copy a site-local branding logo (skip cleanly if it doesn't exist)
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
        echo "Site-local logo copied to final static directory"; \
    else \
        echo "No site-local logo/logo.png found in build context, skipping logo setup"; \
    fi

# Pre-create a strict temp root for build-time OMERO CLI commands.
# TempFileManager fallbacks are removed above, so syncmedia must get an explicit
# writable location under the omero-web account.
RUN set -euo pipefail; \
    install -d -o omero-web -g omero-web -m 0700 /opt/omero/web/tmp/build-syncmedia

# Sync OMERO.web static + media files
# -----------------------------------
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    su -s /bin/bash omero-web -c "\
        export TMPDIR=/opt/omero/web/tmp/build-syncmedia && \
        export OMERO_TMPDIR=/opt/omero/web/tmp/build-syncmedia && \
        export OMERO_TEMPDIR=/opt/omero/web/tmp/build-syncmedia && \
        source \"${VENV_DIR}/bin/activate\" && \
        omero web syncmedia \
    "

# Force the repo-tracked Vizarr static assets into the final collected tree.
# syncmedia can otherwise retain an older upstream copy when the destination
# already contains the same relative path from the base image.
RUN set -euo pipefail; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    PY_VER="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
    SITE_PACKAGES="${VENV_DIR}/lib/python${PY_VER}/site-packages"; \
    OMEROWEB_ZARR_STATIC_SOURCE="${SITE_PACKAGES}/omero_web_zarr/static/omero_web_zarr"; \
    OMEROWEB_ZARR_STATIC_TARGET="/opt/omero/web/OMERO.web/var/static/omero_web_zarr"; \
    rm -rf "${OMEROWEB_ZARR_STATIC_TARGET}"; \
    mkdir -p "${OMEROWEB_ZARR_STATIC_TARGET}"; \
    cp -a "${OMEROWEB_ZARR_STATIC_SOURCE}/." "${OMEROWEB_ZARR_STATIC_TARGET}/"; \
    chown -R omero-web:omero-web "${OMEROWEB_ZARR_STATIC_TARGET}"

# Backup static files so they can be restored if the host bind-mount shadows var/
# -------------------------------------------------------------------------------
RUN cp -a /opt/omero/web/OMERO.web/var/static /opt/omero/web/static_backup

# Stage updated OMEZarrReader + JZarr for runtime upgrade of OMERO CLI JAR cache
# -------------------------------------------------------------------------------
# The OMERO CLI downloads OMERO.java JARs into the bind-mounted var/ directory on
# first use.  The bundled OMEZarrReader 0.3.1 and JZarr 0.3.4 are too old for
# modern OME-NGFF zarrs.  Stage the updated JARs here; the bootstrap script
# (10-web-bootstrap.sh) copies them into the cache at container start.
ARG OMEZARR_READER_VERSION=0.6.0
ARG JZARR_VERSION=0.4.2
RUN set -euo pipefail; \
    mkdir -p /opt/omero/web/zarr-jar-upgrade; \
    OMEZARR_URL="https://artifacts.openmicroscopy.org/artifactory/ome.releases/ome/OMEZarrReader/${OMEZARR_READER_VERSION}/OMEZarrReader-${OMEZARR_READER_VERSION}.jar"; \
    JZARR_URL="https://repo1.maven.org/maven2/dev/zarr/jzarr/${JZARR_VERSION}/jzarr-${JZARR_VERSION}.jar"; \
    echo "Downloading OMEZarrReader ${OMEZARR_READER_VERSION}"; \
    curl -fsSL -o /opt/omero/web/zarr-jar-upgrade/OMEZarrReader.jar "${OMEZARR_URL}"; \
    echo "Downloading JZarr ${JZARR_VERSION}"; \
    curl -fsSL -o /opt/omero/web/zarr-jar-upgrade/jzarr.jar "${JZARR_URL}"; \
    chown -R omero-web:omero-web /opt/omero/web/zarr-jar-upgrade; \
    echo "Staged OMEZarrReader ${OMEZARR_READER_VERSION} + JZarr ${JZARR_VERSION} for runtime upgrade"

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
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "ERROR: Could not find valid OMERO.web venv" >&2; \
        exit 1; \
    fi; \
    "${VENV_DIR}/bin/python" -m pip install --no-cache-dir --upgrade \
        pip \
        "setuptools>=78.1.1" \
        wheel \
        "cryptography>=42.0.0" \
        "urllib3>=2.6.3" \
        certifi \
        "idna>=3.7" \
        "requests>=2.32.0" \
        "jinja2>=3.1.6" \
        "pyopenssl>=24.0.0"

# ---------------------------------------------------------------------------
# Final security hardening pass (APPLY_SECURITY_HARDENING=1)
#
# Runs AFTER all dnf installs and pip installs are complete, so that every
# transitive dependency introduced by earlier layers is covered.
# ---------------------------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0
RUN set -euo pipefail; \
    if [[ "${APPLY_SECURITY_HARDENING}" != "1" ]]; then \
        echo "Skipping final security hardening pass (APPLY_SECURITY_HARDENING=${APPLY_SECURITY_HARDENING})."; \
        exit 0; \
    fi; \
    echo "=== Final security hardening: OS packages (dnf) ==="; \
    dnf -y upgrade --refresh || echo "WARNING: dnf upgrade failed (non-fatal for hardening)."; \
    dnf clean all || true; \
    rm -rf /var/cache/dnf /var/tmp/* || true; \
    echo "=== Final security hardening: removing unnecessary packages ==="; \
    dnf -y remove --noautoremove \
        vim-minimal \
        || true; \
    dnf clean all || true; \
    rm -rf /var/cache/dnf /var/tmp/* /usr/share/doc/* /usr/share/man/* /usr/share/info/* || true; \
    echo "=== Final security hardening: Python packages (pip) ==="; \
    VENV_DIR="$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)"; \
    if [[ -z "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python" ]]; then \
        echo "WARNING: Could not find valid OMERO.web venv; skipping Python hardening." >&2; \
        exit 0; \
    fi; \
    echo "Skipping blanket OMERO.web venv upgrades to preserve pinned/plugin-dependent packages."; \
    echo "Only curated compatibility-safe Python tooling updates are applied in this image."

# Configure supervisord to run OMERO.web and plugin background workers
# -------------------------------------------------------------------
COPY supervisord.conf /etc/supervisord.conf
COPY startup/40-start-imaris-celery-worker.sh /opt/omero/web/bin/start-imaris-celery-worker.sh
COPY startup/40-start-tools-celery-worker.sh /opt/omero/web/bin/start-tools-celery-worker.sh
RUN set -euo pipefail; \
    rm -f /startup/50-config.py /startup/60-default-web-config.sh /startup/98-cleanprevious.sh /startup/99-run.sh
COPY startup/10-web-bootstrap.sh /startup/10-web-bootstrap.sh
COPY startup/50-config.py /startup/50-config.py
COPY startup/60-default-web-config.sh /startup/60-default-web-config.sh
COPY startup/98-cleanprevious.sh /startup/98-cleanprevious.sh
COPY startup/60-enforce-ext4-project-quota.sh /opt/omero/web/bin/enforce-ext4-project-quota.sh
COPY startup/61-storage-quota-reconcile-loop.sh /opt/omero/web/bin/storage-quota-reconcile-loop.sh
RUN set -euo pipefail; \
    mkdir -p /opt/omero/web/bin /opt/omero/web/logs; \
    chmod 0555 /opt/omero/web/bin/start-imaris-celery-worker.sh /opt/omero/web/bin/start-tools-celery-worker.sh /startup/10-web-bootstrap.sh /startup/50-config.py /startup/60-default-web-config.sh /startup/98-cleanprevious.sh /opt/omero/web/bin/enforce-ext4-project-quota.sh /opt/omero/web/bin/storage-quota-reconcile-loop.sh; \
    chown -R omero-web:omero-web /opt/omero/web/logs

# FIX: Take ownership of the base image startup chain.
#
# Solution:
#  1. Remove inherited startup scripts that hardcode stale paths such as venv3.
#  2. Replace them with repo-tracked startup scripts.
#  3. Replace entrypoint with one that execs "$@" after startup scripts.
# -----------------------------------------------------------------------
RUN set -euo pipefail; \
    printf '%s\n' \
        "#!/usr/local/bin/dumb-init /bin/bash" \
        "set -e" \
        "if [ \"\$(id -u)\" -ne 0 ]; then" \
        "    printf 'Running unprivileged; skipping root startup bootstrap and launching: %s\n' \"\$*\"" \
        "    exec \"\$@\"" \
        "fi" \
        "VENV_DIR=\"\${OMERO_WEB_VENV:-}\"" \
        "if [ -n \"\${VENV_DIR}\" ]; then" \
        "    VENV_DIR=\"/opt/omero/web/\${VENV_DIR}\"" \
        "else" \
        "    VENV_DIR=\"\$(find /opt/omero/web -maxdepth 1 -type d -name 'venv*' 2>/dev/null | sort -V | tail -n 1)\"" \
        "fi" \
        "if [ -z \"\${VENV_DIR}\" ] || [ ! -f \"\${VENV_DIR}/bin/activate\" ]; then" \
        "    echo \"ERROR: Could not find OMERO.web venv under /opt/omero/web (OMERO_WEB_VENV=\${OMERO_WEB_VENV:-unset})\" >&2" \
        "    find /opt/omero/web -maxdepth 1 -ls >&2 || true" \
        "    exit 1" \
        "fi" \
        "source \"\${VENV_DIR}/bin/activate\"" \
        "for f in /startup/*; do" \
        "    if [ -f \"\$f\" ] && [ -x \"\$f\" ]; then" \
        "        printf 'Running %s %s\n' \"\$f\" \"\$*\"" \
        "        if [ \"\$(basename \"\$f\")\" = \"10-web-bootstrap.sh\" ]; then" \
        "            \"\$f\" \"\$@\"" \
        "        else" \
        "            # STRICT ENV: Preserve the PATH and OMERO_TMPDIR environment variables" \
        "            env USER=omero-web LOGNAME=omero-web LNAME=omero-web USERNAME=omero-web HOME=/opt/omero/web runuser -p -u omero-web -- \"\$f\" \"\$@\"" \
        "        fi" \
        "    fi" \
        "done" \
        "printf 'Startup scripts complete. Launching as omero-web: %s\n' \"\$*\"" \
        "exec env USER=omero-web LOGNAME=omero-web LNAME=omero-web USERNAME=omero-web HOME=/opt/omero/web runuser -p -m -u omero-web -- \"\$@\"" \
        > /usr/local/bin/entrypoint-supervisord.sh; \
    chmod 0555 /usr/local/bin/entrypoint-supervisord.sh


# Default the image to the application user. Compose explicitly requests root
# only for managed startup bootstrap, then the entrypoint drops privileges.
USER omero-web

ENTRYPOINT ["/usr/local/bin/entrypoint-supervisord.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]

# Mirror the compose healthcheck in the image so standalone runs also verify
# that OMERO.web is serving the web gateway before the container is considered
# healthy.
HEALTHCHECK --interval=10s --timeout=10s --start-period=20s --retries=30 \
    CMD port="${CONFIG_omero_web_application__server_port:?Set CONFIG_omero_web_application__server_port}" && curl -fsS "http://127.0.0.1:${port}/webgateway/" >/dev/null || exit 1
