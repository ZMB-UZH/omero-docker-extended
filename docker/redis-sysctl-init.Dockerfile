FROM alpine:3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0
RUN set -eu; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi

COPY docker/redis-sysctl-init.sh /usr/local/bin/redis-sysctl-init
RUN chmod 0555 /usr/local/bin/redis-sysctl-init

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=1 \
    CMD test -x /usr/local/bin/redis-sysctl-init || exit 1

ENTRYPOINT ["/usr/local/bin/redis-sysctl-init"]
