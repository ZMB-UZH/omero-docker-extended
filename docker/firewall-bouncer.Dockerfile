FROM alpine:3.24@sha256:a2d49ea686c2adfe3c992e47dc3b5e7fa6e6b5055609400dc2acaeb241c829f4

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
