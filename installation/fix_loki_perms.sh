#!/bin/bash
set -e

# Load env
source env/omero_secrets.env 2>/dev/null || true
source installation_paths.env 2>/dev/null || true

echo "Checking Loki permissions on host..."
ls -ldn "${LOKI_DATA_PATH}"
ls -lan "${LOKI_DATA_PATH}"
ls -lan "${LOKI_DATA_PATH}/tsdb-shipper-cache" || true
ls -lan "${LOKI_DATA_PATH}/tsdb-shipper-cache/index_20510" || true

echo "Fixing permissions forcefully..."
sudo chown -R 10001:10001 "${LOKI_DATA_PATH}"
sudo chmod -R 777 "${LOKI_DATA_PATH}"

echo "Restarting loki..."
docker compose restart loki
docker compose logs loki --tail 20
