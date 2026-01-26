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

mkdir -p "${INSTALL_DIR}"
cd /tmp

dnf install -y cmake gcc gcc-c++ make git java-11-openjdk-devel boost-devel hdf5-devel zlib-devel lz4-devel freeimage-devel

git clone --depth 1 https://github.com/imaris/ImarisConvertBioformats.git
cd ImarisConvertBioformats

mkdir -p bioformats
curl -L "https://downloads.openmicroscopy.org/bio-formats/7.4.0/artifacts/bioformats_package.jar" -o bioformats/bioformats_package.jar

cd ..
git clone --depth 1 https://github.com/imaris/ImarisWriter.git
mv ImarisWriter ImarisConvertBioformats/

cd ImarisConvertBioformats/ImarisConvertBioformats
mkdir build
cd build

cmake .. -DCMAKE_BUILD_TYPE=Release -DJAVA_HOME=/usr/lib/jvm/java-11-openjdk -DJRE_HOME=/usr/lib/jvm/jre-11-openjdk

make -j$(nproc)
make install

cp -f ../build/ImarisConvertBioformats "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}/ImarisConvertBioformats"

ln -sf "${INSTALL_DIR}/ImarisConvertBioformats" /usr/local/bin/imarisconvert

echo "${TARGET_VERSION}" > "${VERSION_FILE}"

cd /
rm -rf /tmp/ImarisConvertBioformats /tmp/ImarisWriter

echo "ImarisConvertBioformats installed successfully!"
