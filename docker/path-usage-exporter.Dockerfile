FROM alpine:3.22.1

RUN apk add --no-cache \
    python3 \
    py3-pip \
    && python3 -m venv /opt/path-usage-exporter-venv \
    && /opt/path-usage-exporter-venv/bin/pip install --no-cache-dir docker==7.1.0

COPY monitoring/path-usage-exporter/path_usage_exporter.py /opt/path_usage_exporter.py

ENTRYPOINT ["/opt/path-usage-exporter-venv/bin/python", "/opt/path_usage_exporter.py"]
