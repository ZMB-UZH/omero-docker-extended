FROM crowdsecurity/crowdsec:v1.7.6@sha256:63b595fef92de1778573b375897a45dd226637ee9a3d3db9f57ac7355c369493

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0

# Pre-install the firewall bouncer binary and both firewall backends at build
# time so the entrypoint does not need network access for package installation.
#
# nftables: native backend on Ubuntu 24.04+ and Debian 13+ (Trixie).
# iptables + ipset: legacy fallback for older host kernels.
# Alpine 3.21 exposes the IPv6 frontend via the iptables package, so there is
# no separate ip6tables package to install or pin here.
#
# The same crowdsec-firewall-bouncer binary supports both modes; the entrypoint
# auto-detects the host backend at startup and generates the matching config.
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
    apk add --no-cache \
        "cs-firewall-bouncer=$(require_apk_version cs-firewall-bouncer)" \
        "nftables=$(require_apk_version nftables)" \
        "iptables=$(require_apk_version iptables)" \
        "ipset=$(require_apk_version ipset)"; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        apk upgrade --no-cache; \
    fi; \
    rm -rf /var/cache/apk/*

COPY docker/crowdsec-entrypoint.sh /usr/local/bin/custom-entrypoint.sh
RUN chmod +x /usr/local/bin/custom-entrypoint.sh

HEALTHCHECK --interval=10s --timeout=10s --start-period=30s --retries=30 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

RUN addgroup -S crowdsec-runtime && \
    adduser -S -D -H -G crowdsec-runtime crowdsec-runtime

USER crowdsec-runtime

ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
