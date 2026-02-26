#!/bin/bash
echo "Testing Loki Permissions..."
docker exec omero-loki-1 id || docker run --rm --entrypoint "" grafana/loki:3.2.0 id
docker run --rm --entrypoint "" -v "${LOKI_DATA_PATH}:/loki" grafana/loki:3.2.0 ls -ln /loki/tsdb-shipper-cache || true
docker run --rm --entrypoint "" -v "${LOKI_DATA_PATH}:/loki" grafana/loki:3.2.0 ls -ldn /loki/tsdb-shipper-cache/index_20510 || true
