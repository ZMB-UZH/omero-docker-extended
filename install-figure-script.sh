#!/bin/bash
set -e
echo "Checking for Figure_To_Pdf.py script..."

# omero-figure is installed in OMERO.web, not OMERO.server
# We'll check what version is in the existing scripts directory
SCRIPT_PATH="/opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py"

# Check existing script files for version hints
if ls /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/*.py 1> /dev/null 2>&1; then
    # Scripts exist, try to get version from an existing script
    FIGURE_VERSION=$(grep -oP "(?<=# OMERO.figure version )[0-9.]+" /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Movie_Figure.py 2>/dev/null || echo "7.3.0")
else
    # No scripts, use default
    FIGURE_VERSION="7.3.0"
fi

echo "Using OMERO.figure version: ${FIGURE_VERSION}"

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
