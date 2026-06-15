FROM alpine:3.24@sha256:a2d49ea686c2adfe3c992e47dc3b5e7fa6e6b5055609400dc2acaeb241c829f4

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0
RUN set -eu; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi

COPY docker/redis-sysctl-init.sh /usr/local/bin/redis-sysctl-init
RUN addgroup -S redis-sysctl && \
    adduser -S -D -H -G redis-sysctl -s /sbin/nologin redis-sysctl && \
    chmod 0555 /usr/local/bin/redis-sysctl-init

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=1 \
    CMD test -x /usr/local/bin/redis-sysctl-init || exit 1

USER redis-sysctl

ENTRYPOINT ["/usr/local/bin/redis-sysctl-init"]
