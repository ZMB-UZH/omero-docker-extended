FROM alpine:3.24.4@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0
RUN set -eu; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi

COPY docker/firewall-bouncer-entrypoint.sh /usr/local/bin/custom-entrypoint.sh
RUN chmod 0555 /usr/local/bin/custom-entrypoint.sh && \
    addgroup -S firewallbouncer && \
    adduser -S -D -H -G firewallbouncer -s /sbin/nologin firewallbouncer

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD test -x /usr/local/bin/custom-entrypoint.sh || exit 1

USER firewallbouncer

ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
