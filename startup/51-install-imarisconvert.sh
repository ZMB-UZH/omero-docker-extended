#!/usr/bin/env bash
set -euo pipefail

# Report failure and exit. Inputs: shell arguments and environment. Output: command status and side effects.
fail() {
    local message="$1"
    echo "ERROR: ${message}" >&2
    exit 1
}

INSTALL_MODE="verify"
case "${1:-}" in
    verify|--install-build-time)
        INSTALL_MODE="$1"
        ;;
esac
INSTALL_DIR="${IMARISCONVERT_INSTALL_DIR:-/opt/omero/imarisconvert}"
WRAPPER_PATH="${IMARISCONVERT_WRAPPER_PATH:-/usr/local/bin/imarisconvert}"
VERSION_FILE="${INSTALL_DIR}/.version"
TARGET_VERSION="1.0.0"
IMARISCONVERT_REPO_URL="${IMARISCONVERT_REPO_URL:-https://github.com/imaris/ImarisConvertBioformats.git}"
IMARISCONVERT_GIT_REF="${IMARISCONVERT_GIT_REF:-master}"
IMARISCONVERT_GIT_COMMIT="${IMARISCONVERT_GIT_COMMIT:-b363fe927914dfdcf1c7fdbf721e50e8cce67cc3}"
IMARISWRITER_REPO_URL="${IMARISWRITER_REPO_URL:-https://github.com/imaris/ImarisWriter.git}"
IMARISWRITER_GIT_REF="${IMARISWRITER_GIT_REF:-master}"
IMARISWRITER_GIT_COMMIT="${IMARISWRITER_GIT_COMMIT:-b128e6e7d1a147261e9d5caf24ebc6b5c9c63779}"
BIOFORMATS_SUBDIR="bioformats"
BIOFORMATS_JAR_NAME="bioformats_package.jar"
: "${BIOFORMATS_VERSION:?BIOFORMATS_VERSION must be set in env/omeroserver.env}"
: "${BIOFORMATS_SHA256:?BIOFORMATS_SHA256 must be set in env/omeroserver.env}"
BIOFORMATS_ARTIFACT_NAME="bioformats_package-${BIOFORMATS_VERSION}.jar"
BIOFORMATS_URL="https://artifacts.openmicroscopy.org/artifactory/maven/ome/bioformats_package/${BIOFORMATS_VERSION}/${BIOFORMATS_ARTIFACT_NAME}"
BIOFORMATS_SHA256_URL="${BIOFORMATS_URL}.sha256"
BIOFORMATS_MIN_SIZE_BYTES=10000000
BIOFORMATS_JAR="${INSTALL_DIR}/${BIOFORMATS_SUBDIR}/${BIOFORMATS_JAR_NAME}"
BIOFORMATS_CACHE_DIR="${INSTALL_DIR}/artifacts/${BIOFORMATS_SUBDIR}"
BIOFORMATS_CACHE_JAR="${BIOFORMATS_CACHE_DIR}/${BIOFORMATS_JAR_NAME}"
BIOFORMATS_CACHE_SHA256="${BIOFORMATS_CACHE_JAR}.sha256"

# Return whether valid bioformats jar. Inputs: shell arguments and environment. Output: success or failure status.
is_valid_bioformats_jar() {
    local jar_path="$1"
    [[ -s "${jar_path}" ]] && [[ "$(stat -c%s "${jar_path}")" -ge "${BIOFORMATS_MIN_SIZE_BYTES}" ]]
}

# Return whether lowercase sha256 hex. Inputs: shell arguments and environment. Output: success or failure status.
is_lowercase_sha256_hex() {
    local value="${1:-}"

    if [ "${#value}" -ne 64 ]; then
        return 1
    fi

    case "${value}" in
        *[!0-9a-f]*) return 1 ;;
        *) return 0 ;;
    esac
}

# Validate bioformats sha256 pin. Inputs: environment. Output: success or failure status.
validate_bioformats_sha256_pin() {
    if ! is_lowercase_sha256_hex "${BIOFORMATS_SHA256}"; then
        fail "BIOFORMATS_SHA256 must be a 64-character lowercase SHA-256 digest"
    fi
}

# Perform sha256 matches repository pin. Inputs: artifact path. Output: command status.
sha256_matches_pin() {
    local source_path="$1"
    local actual_sha

    actual_sha="$(sha256sum "${source_path}" | awk '{print $1}')"
    [[ "${actual_sha}" = "${BIOFORMATS_SHA256}" ]]
}

# Perform sha256 matches manifest. Inputs: shell arguments and environment. Output: command status and side effects.
sha256_matches_manifest() {
    local source_path="$1"
    local sha_path="$2"
    local expected_sha
    local actual_sha

    if [[ ! -f "${sha_path}" ]]; then
        return 1
    fi

    expected_sha="$(awk '{print tolower($1)}' "${sha_path}")"
    if ! is_lowercase_sha256_hex "${expected_sha}"; then
        return 1
    fi

    actual_sha="$(sha256sum "${source_path}" | awk '{print $1}')"
    [[ "${actual_sha}" = "${expected_sha}" ]]
}

# Return whether valid bioformats cache. Inputs: shell arguments and environment. Output: success or failure status.
is_valid_bioformats_cache() {
    is_valid_bioformats_jar "${BIOFORMATS_CACHE_JAR}" && \
        sha256_matches_pin "${BIOFORMATS_CACHE_JAR}" && \
        sha256_matches_manifest "${BIOFORMATS_CACHE_JAR}" "${BIOFORMATS_CACHE_SHA256}"
}

# Write bioformats sha256. Inputs: shell arguments and environment. Output: command status and side effects.
write_bioformats_sha256() {
    local source_path="$1"
    local sha_path="$2"
    local tmp_path="${sha_path}.tmp"
    local digest
    digest="$(sha256sum "${source_path}" | awk '{print $1}')"
    printf '%s  %s\n' "${digest}" "${BIOFORMATS_JAR_NAME}" > "${tmp_path}"
    chmod 0644 "${tmp_path}"
    mv -f "${tmp_path}" "${sha_path}"
}

# Copy bioformats jar. Inputs: shell arguments and environment. Output: command status and side effects.
copy_bioformats_jar() {
    local source_path="$1"
    local destination_path="$2"
    local file_mode="$3"
    local tmp_path="${destination_path}.tmp"
    local expected_sha
    local actual_sha

    expected_sha="$(sha256sum "${source_path}" | awk '{print $1}')"
    cp -f "${source_path}" "${tmp_path}"
    chmod "${file_mode}" "${tmp_path}"
    actual_sha="$(sha256sum "${tmp_path}" | awk '{print $1}')"
    if [[ "${actual_sha}" != "${expected_sha}" ]]; then
        rm -f "${tmp_path}"
        fail "Integrity verification failed while copying ${source_path} to ${destination_path}"
    fi
    mv -f "${tmp_path}" "${destination_path}"
}

# Download Bio-Formats jar and verify the published checksum. Inputs: shell arguments and environment. Output: command status and side effects.
download_bioformats_jar() {
    local destination_path="$1"
    local sha256_path="${destination_path}.sha256.remote"
    local tmp_path="${destination_path}.download"
    local expected_sha
    local remote_sha
    local actual_sha

    rm -f "${tmp_path}" "${sha256_path}"
    if ! curl -L --fail --retry 5 --retry-delay 3 --max-time 1800 \
        --connect-timeout 20 --speed-time 30 --speed-limit 1024 \
        "${BIOFORMATS_URL}" \
        -o "${tmp_path}"; then
        rm -f "${tmp_path}" "${sha256_path}"
        fail "Failed to download ${BIOFORMATS_ARTIFACT_NAME}"
    fi

    if ! curl -L --fail --retry 5 --retry-delay 3 --max-time 300 \
        --connect-timeout 20 --speed-time 30 --speed-limit 1024 \
        "${BIOFORMATS_SHA256_URL}" \
        -o "${sha256_path}"; then
        rm -f "${tmp_path}" "${sha256_path}"
        fail "Failed to download ${BIOFORMATS_ARTIFACT_NAME}.sha256"
    fi

    remote_sha="$(awk '{print tolower($1)}' "${sha256_path}")"
    if ! is_lowercase_sha256_hex "${remote_sha}"; then
        rm -f "${tmp_path}" "${sha256_path}"
        fail "Invalid SHA-256 manifest for ${BIOFORMATS_ARTIFACT_NAME}"
    fi
    if [[ "${remote_sha}" != "${BIOFORMATS_SHA256}" ]]; then
        rm -f "${tmp_path}" "${sha256_path}"
        fail "Published Bio-Formats checksum does not match repository pin for ${BIOFORMATS_ARTIFACT_NAME}"
    fi

    expected_sha="${BIOFORMATS_SHA256}"
    actual_sha="$(sha256sum "${tmp_path}" | awk '{print $1}')"
    if [[ "${actual_sha}" != "${expected_sha}" ]]; then
        rm -f "${tmp_path}" "${sha256_path}"
        fail "Bio-Formats jar checksum mismatch for ${BIOFORMATS_ARTIFACT_NAME}"
    fi

    mv -f "${tmp_path}" "${destination_path}"
    rm -f "${sha256_path}"
}

# Install imarisconvert wrapper. Inputs: shell arguments and environment. Output: command status and side effects.
install_imarisconvert_wrapper() {
    local escaped_default_install_dir=""
    printf -v escaped_default_install_dir "%q" "${INSTALL_DIR}"

    cat > "${WRAPPER_PATH}" <<SH
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="\${IMARISCONVERT_INSTALL_DIR:-${escaped_default_install_dir}}"
cd "\${INSTALL_DIR}"
exec "\${INSTALL_DIR}/ImarisConvertBioformats" "\$@"
SH
    chmod 0755 "${WRAPPER_PATH}"
}

# Verify imarisconvert installation. Inputs: shell arguments and environment. Output: command status and side effects.
verify_imarisconvert_installation() {
    local installed_version=""

    validate_bioformats_sha256_pin

    if [[ -f "${VERSION_FILE}" ]]; then
        installed_version="$(cat "${VERSION_FILE}")"
    fi

    [[ "${installed_version}" = "${TARGET_VERSION}" ]] \
        || fail "ImarisConvertBioformats version marker is missing or unexpected: expected=${TARGET_VERSION} actual=${installed_version:-missing}"
    [[ -x "${INSTALL_DIR}/ImarisConvertBioformats" ]] \
        || fail "ImarisConvertBioformats binary is missing or not executable: ${INSTALL_DIR}/ImarisConvertBioformats"
    is_valid_bioformats_jar "${BIOFORMATS_JAR}" \
        || fail "Bio-Formats runtime jar is missing or invalid: ${BIOFORMATS_JAR}"
    sha256_matches_pin "${BIOFORMATS_JAR}" \
        || fail "Bio-Formats runtime jar checksum does not match repository pin: ${BIOFORMATS_JAR}"
    is_valid_bioformats_cache \
        || fail "Bio-Formats local artifact cache is missing or invalid: ${BIOFORMATS_CACHE_JAR}"
    [[ -x "${WRAPPER_PATH}" ]] \
        || fail "ImarisConvertBioformats wrapper is missing or not executable: ${WRAPPER_PATH}"

    echo "ImarisConvertBioformats ${TARGET_VERSION} verified (binary + runtime jar + local cache)."
}

# Perform seed bioformats cache from runtime. Inputs: shell arguments and environment. Output: command status and side effects.
seed_bioformats_cache_from_runtime() {
    mkdir -p "${BIOFORMATS_CACHE_DIR}"
    copy_bioformats_jar "${BIOFORMATS_JAR}" "${BIOFORMATS_CACHE_JAR}" 0644
    write_bioformats_sha256 "${BIOFORMATS_CACHE_JAR}" "${BIOFORMATS_CACHE_SHA256}"
}

# Restore runtime jar from cache. Inputs: shell arguments and environment. Output: command status and side effects.
restore_runtime_jar_from_cache() {
    mkdir -p "${INSTALL_DIR}/${BIOFORMATS_SUBDIR}"
    copy_bioformats_jar "${BIOFORMATS_CACHE_JAR}" "${BIOFORMATS_JAR}" 0644
}

case "${INSTALL_MODE}" in
    verify)
        verify_imarisconvert_installation
        exit 0
        ;;
    --install-build-time)
        ;;
esac

validate_bioformats_sha256_pin

if [[ -f "${VERSION_FILE}" ]]; then
    INSTALLED_VERSION="$(cat "${VERSION_FILE}")"
else
    INSTALLED_VERSION=""
fi

if [[ "${INSTALLED_VERSION}" = "${TARGET_VERSION}" && -x "${INSTALL_DIR}/ImarisConvertBioformats" ]]; then
    if ! [[ -x "${WRAPPER_PATH}" ]]; then
        echo "Recreating missing ImarisConvert wrapper..."
        install_imarisconvert_wrapper
    fi

    if is_valid_bioformats_jar "${BIOFORMATS_JAR}" && ! is_valid_bioformats_cache; then
        sha256_matches_pin "${BIOFORMATS_JAR}" \
            || fail "Bio-Formats runtime jar checksum does not match repository pin: ${BIOFORMATS_JAR}"
        echo "Seeding Bio-Formats cache from existing runtime jar..."
        seed_bioformats_cache_from_runtime
    fi

    if ! is_valid_bioformats_jar "${BIOFORMATS_JAR}" && is_valid_bioformats_cache; then
        echo "Restoring Bio-Formats runtime jar from local cache..."
        restore_runtime_jar_from_cache
    fi

    if is_valid_bioformats_jar "${BIOFORMATS_JAR}" && sha256_matches_pin "${BIOFORMATS_JAR}" && is_valid_bioformats_cache; then
        echo "ImarisConvertBioformats ${TARGET_VERSION} already installed (binary + runtime jar + local cache)."
        exit 0
    fi
fi

echo "Installing ImarisConvertBioformats ${TARGET_VERSION}..."
mkdir -p "${INSTALL_DIR}"

# Clean up any previous failed attempts
BUILD_ROOT="${IMARISCONVERT_BUILD_ROOT:-${TMPDIR:-/tmp}/ImarisConvertBioformats-build}"
rm -rf "${BUILD_ROOT}"
mkdir -p "${BUILD_ROOT}"

cd "${BUILD_ROOT}"

# Clone ImarisConvertBioformats and verify the exact expected commit.
if ! git clone --depth 1 --branch "${IMARISCONVERT_GIT_REF}" "${IMARISCONVERT_REPO_URL}" ImarisConvertBioformats; then
    fail "Failed to clone ImarisConvertBioformats repository"
fi
cd ImarisConvertBioformats
actual_commit="$(git rev-parse HEAD)"
if [[ "${actual_commit}" != "${IMARISCONVERT_GIT_COMMIT}" ]]; then
    fail "ImarisConvertBioformats commit mismatch: expected=${IMARISCONVERT_GIT_COMMIT} actual=${actual_commit}"
fi

# PATCH: Fix missing #include <limits> in bpUtils.cxx
echo "Patching bpUtils.cxx to add missing #include <limits>..."
sed -i '1i #include <limits>' ImarisConvertBioformats/meta/bpUtils.cxx

# Download bioformats jar
mkdir -p bioformats
download_bioformats_jar "bioformats/bioformats_package.jar"

# Validate Bio-Formats jar before build consumes it.
if ! is_valid_bioformats_jar bioformats/bioformats_package.jar; then
    echo "ERROR: bioformats_package.jar download failed or is invalid" >&2
    ls -lh bioformats/bioformats_package.jar >&2 || true
    fail "Invalid bioformats_package.jar"
fi

# Clone ImarisWriter and verify the exact expected commit.
cd ..
if ! git clone --depth 1 --branch "${IMARISWRITER_GIT_REF}" "${IMARISWRITER_REPO_URL}" ImarisWriter; then
    fail "Failed to clone ImarisWriter repository"
fi
cd ImarisWriter
actual_commit="$(git rev-parse HEAD)"
if [[ "${actual_commit}" != "${IMARISWRITER_GIT_COMMIT}" ]]; then
    fail "ImarisWriter commit mismatch: expected=${IMARISWRITER_GIT_COMMIT} actual=${actual_commit}"
fi
cd ..
mv ImarisWriter ImarisConvertBioformats/

# Build
cd ImarisConvertBioformats/ImarisConvertBioformats
mkdir build
cd build

# Find FreeImage library
FREEIMAGE_LIB=$(find /usr/lib64 /usr/lib -name "libfreeimage.so*" 2>/dev/null | head -1)
if [[ -z "${FREEIMAGE_LIB}" ]]; then
    fail "FreeImage library not found"
fi
echo "Found FreeImage library: ${FREEIMAGE_LIB}"

PARALLEL_JOBS="$(nproc)"
NINJA_GENERATOR=()
if command -v ninja >/dev/null 2>&1; then
    NINJA_GENERATOR=(-G Ninja)
fi

CCACHE_LAUNCHER=()
if command -v ccache >/dev/null 2>&1; then
    CCACHE_LAUNCHER=(
        -DCMAKE_C_COMPILER_LAUNCHER=ccache
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
    )
fi

if ! cmake .. \
    "${NINJA_GENERATOR[@]}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DJAVA_HOME=/usr/lib/jvm/java-11-openjdk \
    -DJRE_HOME=/usr/lib/jvm/jre-11-openjdk \
    -DFreeImage_ROOT=/usr \
    -DFreeImage_LIBRARIES="${FREEIMAGE_LIB}" \
    "${CCACHE_LAUNCHER[@]}"; then
    fail "CMake configuration failed for ImarisConvertBioformats"
fi

if ! cmake --build . --parallel "${PARALLEL_JOBS}"; then
    fail "Build failed for ImarisConvertBioformats"
fi

if ! cmake --install .; then
    fail "Install step failed for ImarisConvertBioformats"
fi

# Copy binary and ALL shared libraries to install directory
cp -f ImarisConvertBioformats "${INSTALL_DIR}/"
cp -f ../build/Release/*.so* "${INSTALL_DIR}/" 2>/dev/null || true
cp -f ../../fileiobioformats/build/*.so* "${INSTALL_DIR}/" 2>/dev/null || true
cp -f ../../ImarisWriter/build/*.so* "${INSTALL_DIR}/" 2>/dev/null || true
chmod +x "${INSTALL_DIR}/ImarisConvertBioformats"

# Copy Bio-Formats runtime into install directory.
# ImarisConvertBioformats expects to find the Bio-Formats jar at runtime.
mkdir -p "${INSTALL_DIR}/bioformats"
copy_bioformats_jar "../../bioformats/bioformats_package.jar" "${BIOFORMATS_JAR}" 0644

# Keep a second local copy so runtime repairs never need outbound network access.
mkdir -p "${BIOFORMATS_CACHE_DIR}"
copy_bioformats_jar "../../bioformats/bioformats_package.jar" "${BIOFORMATS_CACHE_JAR}" 0644
write_bioformats_sha256 "${BIOFORMATS_CACHE_JAR}" "${BIOFORMATS_CACHE_SHA256}"

# Create a wrapper instead of a symlink so runtime discovery works reliably
install_imarisconvert_wrapper

# Mark version
echo "${TARGET_VERSION}" > "${VERSION_FILE}"

# Cleanup
cd /
rm -rf "${BUILD_ROOT}"

echo "ImarisConvertBioformats installed successfully!"
