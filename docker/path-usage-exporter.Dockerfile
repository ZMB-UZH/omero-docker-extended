FROM alpine:3.22.1

RUN apk add --no-cache \
    python3 \
    py3-docker

COPY monitoring/path-usage-exporter/path_usage_exporter.py /opt/path_usage_exporter.py

ENTRYPOINT ["python", "/opt/path_usage_exporter.py"]
