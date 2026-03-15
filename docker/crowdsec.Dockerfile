FROM crowdsecurity/crowdsec:v1.7.6

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0

# Pre-install the firewall bouncer binary and both firewall backends at build
# time so the entrypoint does not need network access for package installation.
#
# nftables: native backend on Ubuntu 24.04+ and Debian 13+ (Trixie).
# iptables + ipset: legacy fallback for older host kernels.
#
# The same crowdsec-firewall-bouncer binary supports both modes; the entrypoint
# auto-detects the host backend at startup and generates the matching config.
RUN apk update \
    && apk add --no-cache \
        cs-firewall-bouncer \
        nftables \
        iptables \
        ip6tables \
        ipset \
    && if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi \
    && rm -rf /var/cache/apk/*

COPY docker/crowdsec-entrypoint.sh /usr/local/bin/custom-entrypoint.sh
RUN chmod +x /usr/local/bin/custom-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
