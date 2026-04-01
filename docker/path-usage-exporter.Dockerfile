FROM alpine:3.23.3@sha256:25109184c71bdad752c8312a8623239686a9a2071e8825f20acb8f2198c3f659

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

HEALTHCHECK --interval=10s --timeout=10s --start-period=20s --retries=30 \
    CMD test -f /textfile/omero_paths.prom || exit 1

ENTRYPOINT ["python3", "/opt/path_usage_exporter.py"]
