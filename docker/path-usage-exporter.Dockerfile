FROM alpine:3.23.3

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0

RUN set -eu; \
    apk add --no-cache python3; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi

COPY monitoring/path-usage-exporter/path_usage_exporter.py /opt/path_usage_exporter.py

ENTRYPOINT ["python3", "/opt/path_usage_exporter.py"]
