FROM alpine:3.23@sha256:25109184c71bdad752c8312a8623239686a9a2071e8825f20acb8f2198c3f659

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
