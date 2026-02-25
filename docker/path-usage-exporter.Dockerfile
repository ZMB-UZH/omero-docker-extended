FROM alpine:3.22.1

RUN apk add --no-cache \
    python3 \
    py3-pip \
    && pip3 install --no-cache-dir docker==7.1.0

COPY monitoring/path-usage-exporter/path_usage_exporter.py /opt/path_usage_exporter.py

ENTRYPOINT ["python3", "/opt/path_usage_exporter.py"]
