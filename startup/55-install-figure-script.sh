#!/bin/bash
set -e
echo "Checking for Figure_To_Pdf.py script..."

# Get version from environment variable set in docker-compose.yml
FIGURE_VERSION="${OMERO_FIGURE_VERSION:-7.3.0}"
echo "Using OMERO.figure version: ${FIGURE_VERSION}"

SCRIPT_PATH="/opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py"

if [ -f "${SCRIPT_PATH}" ]; then
    SCRIPT_VERSION=$(grep -oP "(?<=__version__ = ')[^']*" "${SCRIPT_PATH}" 2>/dev/null || echo "unknown")
    echo "Current script version: ${SCRIPT_VERSION}"
    
    if [ "${SCRIPT_VERSION}" != "${FIGURE_VERSION}" ]; then
        echo "Version mismatch! Reinstalling script..."
        rm -f "${SCRIPT_PATH}"
    fi
fi

if [ ! -f "${SCRIPT_PATH}" ]; then
    echo "Installing Figure_To_Pdf.py script version ${FIGURE_VERSION}..."
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts
    
    git clone --depth 1 --branch "v${FIGURE_VERSION}" https://github.com/ome/omero-figure.git /tmp/omero-figure
    
    cp /tmp/omero-figure/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py "${SCRIPT_PATH}"
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts
    chmod -R 755 /opt/omero/server/OMERO.server/lib/scripts
    rm -rf /tmp/omero-figure
    echo "Script installed successfully"
else
    echo "Script already exists with correct version"
fi
