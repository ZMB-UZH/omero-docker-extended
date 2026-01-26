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

if [[ "${INSTALLED_VERSION}" == "${TARGET_VERSION}" && -x "${INSTALL_DIR}/ImarisConvertBioformats" ]]; then
    echo "ImarisConvertBioformats ${TARGET_VERSION} already installed."
    exit 0
fi

echo "Installing ImarisConvertBioformats ${TARGET_VERSION}..."

cd /tmp

# Clone ImarisConvertBioformats
git clone --depth 1 https://github.com/imaris/ImarisConvertBioformats.git
cd ImarisConvertBioformats

# Download bioformats jar
mkdir -p bioformats
curl -L "https://downloads.openmicroscopy.org/bio-formats/7.4.0/artifacts/bioformats_package.jar" \
    -o bioformats/bioformats_package.jar

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

# Copy binary to install directory
cp -f ../build/ImarisConvertBioformats "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}/ImarisConvertBioformats"

# Create symlink
ln -sf "${INSTALL_DIR}/ImarisConvertBioformats" /usr/local/bin/imarisconvert

# Mark version
echo "${TARGET_VERSION}" > "${VERSION_FILE}"

# Cleanup
cd /
rm -rf /tmp/ImarisConvertBioformats /tmp/ImarisWriter

echo "ImarisConvertBioformats installed successfully!"
