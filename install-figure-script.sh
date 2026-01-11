#!/bin/bash
set -e
echo "Checking for Figure_To_Pdf.py script..."
if [ ! -f /OMERO/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py ]; then
    echo "Script not found, installing..."
    mkdir -p /OMERO/OMERO.server/lib/scripts/omero/figure_scripts
    git clone --depth 1 https://github.com/ome/omero-figure.git /tmp/omero-figure
    cp /tmp/omero-figure/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py \
        /OMERO/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py
    chown -R omero-server:omero-server /OMERO/OMERO.server/lib/scripts
    chmod -R 755 /OMERO/OMERO.server/lib/scripts
    rm -rf /tmp/omero-figure
    echo "Script installed successfully"
else
    echo "Script already exists, skipping installation"
fi
