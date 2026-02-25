FROM python:3.12-alpine

RUN pip install --no-cache-dir docker

COPY monitoring/path-usage-exporter/path_usage_exporter.py /opt/path_usage_exporter.py

ENTRYPOINT ["python", "/opt/path_usage_exporter.py"]
