#!/bin/bash
set -e
echo "Checking for Figure_To_Pdf.py script..."

# Find the correct venv directory
VENV_DIR=$(ls -d /opt/omero/server/venv* 2>/dev/null | head -n 1)
if [ -z "${VENV_DIR}" ]; then
    echo "ERROR: Could not find venv directory"
    exit 1
fi

# Detect installed OMERO.figure version
FIGURE_VERSION=$(${VENV_DIR}/bin/python -c "import pkg_resources; print(pkg_resources.get_distribution('omero-figure').version)")

if [ -z "${FIGURE_VERSION}" ]; then
    echo "ERROR: Could not detect omero-figure version"
    exit 1
fi

echo "Detected OMERO.figure version: ${FIGURE_VERSION}"

SCRIPT_PATH="/opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py"

# Check if script exists and get its version
if [ -f "${SCRIPT_PATH}" ]; then
    SCRIPT_VERSION=$(grep -oP "(?<=__version__ = ')[^']*" "${SCRIPT_PATH}" 2>/dev/null || echo "unknown")
    echo "Current script version: ${SCRIPT_VERSION}"
    
    # If versions don't match, reinstall
    if [ "${SCRIPT_VERSION}" != "${FIGURE_VERSION}" ]; then
        echo "Version mismatch! Reinstalling script..."
        rm -f "${SCRIPT_PATH}"
    fi
fi

# Install if missing or was removed due to version mismatch
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
