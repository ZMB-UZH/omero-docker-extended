FROM alpine:3.24.2@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0
RUN set -eu; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi

COPY docker/firewall-bouncer-entrypoint.sh /usr/local/bin/custom-entrypoint.sh
RUN chmod +x /usr/local/bin/custom-entrypoint.sh && \
    addgroup -S firewallbouncer && \
    adduser -S -D -H -G firewallbouncer -s /sbin/nologin firewallbouncer

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD test -x /usr/local/bin/custom-entrypoint.sh || exit 1

USER firewallbouncer

ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
