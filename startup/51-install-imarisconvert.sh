#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/omero/imarisconvert"
VERSION_FILE="${INSTALL_DIR}/.version"
TARGET_VERSION="1.0.0"

if [[ -f "${VERSION_FILE}" ]]; then
    INSTALLED_VERSION="$(cat "${VERSION_FILE}")"
else
    INSTALLED_VERSION=""
fi

BIOFORMATS_JAR="${INSTALL_DIR}/bioformats/bioformats_package.jar"

if [[ "${INSTALLED_VERSION}" == "${TARGET_VERSION}" \
      && -x "${INSTALL_DIR}/ImarisConvertBioformats" \
      && -s "${BIOFORMATS_JAR}" \
      && "$(stat -c%s "${BIOFORMATS_JAR}")" -gt 10000000 \
      && -x /usr/local/bin/imarisconvert ]]; then
    echo "ImarisConvertBioformats ${TARGET_VERSION} already installed (binary + VALID Bio-Formats jar)."
    exit 0
fi

echo "Installing ImarisConvertBioformats ${TARGET_VERSION}..."

# Clean up any previous failed attempts
rm -rf /tmp/ImarisConvertBioformats /tmp/ImarisWriter

cd /tmp

# Clone ImarisConvertBioformats
git clone --depth 1 https://github.com/imaris/ImarisConvertBioformats.git
cd ImarisConvertBioformats

# PATCH: Fix missing #include <limits> in bpUtils.cxx
echo "Patching bpUtils.cxx to add missing #include <limits>..."
sed -i '1i #include <limits>' ImarisConvertBioformats/meta/bpUtils.cxx

# Download bioformats jar
mkdir -p bioformats
curl -L --fail --retry 5 --retry-delay 3 \
    "https://downloads.openmicroscopy.org/bio-formats/8.4.0/artifacts/bioformats_package.jar" \
    -o bioformats/bioformats_package.jar

# Validate Bio-Formats jar (must be large; real file is ~80–90 MB)
if [[ ! -s bioformats/bioformats_package.jar ]] || \
   [[ "$(stat -c%s bioformats/bioformats_package.jar)" -lt 10000000 ]]; then
    echo "ERROR: bioformats_package.jar download failed or is invalid"
    ls -lh bioformats/bioformats_package.jar || true
    exit 1
fi

# Clone ImarisWriter
cd ..
git clone --depth 1 https://github.com/imaris/ImarisWriter.git
mv ImarisWriter ImarisConvertBioformats/

# Build
cd ImarisConvertBioformats/ImarisConvertBioformats
mkdir build
cd build

# Find FreeImage library
FREEIMAGE_LIB=$(find /usr/lib64 /usr/lib -name "libfreeimage.so*" 2>/dev/null | head -1)
if [[ -z "${FREEIMAGE_LIB}" ]]; then
    echo "ERROR: FreeImage library not found!"
    exit 1
fi
echo "Found FreeImage library: ${FREEIMAGE_LIB}"

cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DJAVA_HOME=/usr/lib/jvm/java-11-openjdk \
    -DJRE_HOME=/usr/lib/jvm/jre-11-openjdk \
    -DFreeImage_ROOT=/usr \
    -DFreeImage_LIBRARIES="${FREEIMAGE_LIB}"

make -j$(nproc)
make install

# Copy binary and ALL shared libraries to install directory
cp -f ImarisConvertBioformats "${INSTALL_DIR}/"
cp -f ../build/Release/*.so* "${INSTALL_DIR}/" 2>/dev/null || true
cp -f ../../fileiobioformats/build/*.so* "${INSTALL_DIR}/" 2>/dev/null || true
cp -f ../../ImarisWriter/build/*.so* "${INSTALL_DIR}/" 2>/dev/null || true
chmod +x "${INSTALL_DIR}/ImarisConvertBioformats"

# Copy Bio-Formats runtime into install directory.
# ImarisConvertBioformats expects to find the Bio-Formats jar at runtime.
mkdir -p "${INSTALL_DIR}/bioformats"
cp -f "../../bioformats/bioformats_package.jar" "${INSTALL_DIR}/bioformats/bioformats_package.jar"
chmod 0644 "${INSTALL_DIR}/bioformats/bioformats_package.jar"

# Create a wrapper instead of a symlink so runtime discovery works reliably
cat > /usr/local/bin/imarisconvert <<'SH'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="/opt/omero/imarisconvert"
cd "${INSTALL_DIR}"
exec "${INSTALL_DIR}/ImarisConvertBioformats" "$@"
SH
chmod 0755 /usr/local/bin/imarisconvert

# Mark version
echo "${TARGET_VERSION}" > "${VERSION_FILE}"

# Cleanup
cd /
rm -rf /tmp/ImarisConvertBioformats /tmp/ImarisWriter

echo "ImarisConvertBioformats installed successfully!"
