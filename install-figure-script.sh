#!/bin/bash
set -e
echo "Checking for Figure_To_Pdf.py script..."
if [ ! -f /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py ]; then
    echo "Script not found, installing..."
    
    # Detect installed OMERO.figure version
    FIGURE_VERSION=$(/opt/omero/server/venv*/bin/pip show omero-figure | grep Version | cut -d' ' -f2)
    echo "Detected OMERO.figure version: ${FIGURE_VERSION}"
    
    mkdir -p /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts
    git clone --depth 1 --branch "v${FIGURE_VERSION}" https://github.com/ome/omero-figure.git /tmp/omero-figure || \
        git clone --depth 1 https://github.com/ome/omero-figure.git /tmp/omero-figure
    
    cp /tmp/omero-figure/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py \
        /opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py
    chown -R omero-server:omero-server /opt/omero/server/OMERO.server/lib/scripts
    chmod -R 755 /opt/omero/server/OMERO.server/lib/scripts
    rm -rf /tmp/omero-figure
    echo "Script installed successfully"
else
    echo "Script already exists, skipping installation"
fi
