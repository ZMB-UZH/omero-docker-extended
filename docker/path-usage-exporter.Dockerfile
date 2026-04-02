FROM alpine:3.23.3@sha256:25109184c71bdad752c8312a8623239686a9a2071e8825f20acb8f2198c3f659

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0

RUN set -eu; \
    apk update; \
    require_apk_version() { \
        package_name="$1"; \
        apk policy "${package_name}" >/tmp/apk-policy.txt; \
        package_version="$(awk '/^[[:space:]]*[0-9][^:]*:$/ { gsub(":", "", $1); print $1; exit }' /tmp/apk-policy.txt)"; \
        if [ -z "${package_version}" ]; then \
            echo "ERROR: Failed to resolve apk version for ${package_name}" >&2; \
            exit 1; \
        fi; \
        printf '%s' "${package_version}"; \
    }; \
    apk add --no-cache "python3=$(require_apk_version python3)"; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi

RUN addgroup -S omero-path-exporter && \
    adduser -S -D -H -G omero-path-exporter omero-path-exporter

COPY monitoring/path-usage-exporter/path_usage_exporter.py /opt/path_usage_exporter.py

USER omero-path-exporter

HEALTHCHECK --interval=10s --timeout=10s --start-period=20s --retries=30 \
    CMD test -f /textfile/omero_paths.prom || exit 1

ENTRYPOINT ["python3", "/opt/path_usage_exporter.py"]
