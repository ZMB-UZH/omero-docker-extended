# Shared PostgreSQL runtime and maintenance images.

FROM postgres:16.15@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97 AS postgres-base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PG_VERSION=16.16-1.pgdg13+1
LABEL org.opencontainers.image.version="16.16"

# Retain the tested PGDG container helpers without adding a second init
# system. The upstream entrypoint still handles ownership and privilege drop.
RUN set -euo pipefail; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        apt=3.0.4 \
        libapt-pkg7.0=3.0.4 \
        "postgresql-16=${PG_VERSION}" \
        "postgresql-client-16=${PG_VERSION}" \
        postgresql-client-common=293.pgdg13+1 \
        postgresql-common=293.pgdg13+1; \
    apt-get check; \
    test -z "$(dpkg --audit)"; \
    rm -rf /var/lib/apt/lists/*

FROM postgres-base AS maintenance

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Optional: enable OS package security updates at build time
# ----------------------------------------------------------
ARG APPLY_SECURITY_HARDENING=0

# Install cron
# ------------
RUN set -euo pipefail; \
    apt-get update; \
    require_apt_version() { \
        local package="$1"; \
        local version=""; \
        version="$(apt-cache madison "${package}" | awk 'NR==1 {print $3}')"; \
        if [ -z "${version}" ]; then \
            echo "ERROR: Failed to resolve apt version for ${package}" >&2; \
            exit 1; \
        fi; \
        printf '%s' "${version}"; \
    }; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        "cron=$(require_apt_version cron)"; \
    if [ "${APPLY_SECURITY_HARDENING}" = "1" ]; then \
        echo "Applying optional security updates (APPLY_SECURITY_HARDENING=1)..."; \
        database_packages=(postgresql-16 postgresql-client-16 postgresql-client-common postgresql-common); \
        apt-mark hold "${database_packages[@]}"; \
        DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends; \
        apt-mark unhold "${database_packages[@]}"; \
    fi; \
    apt-get check; \
    test -z "$(dpkg --audit)"; \
    rm -rf /var/lib/apt/lists/*

# Copy the maintenance script and cron schedule
# ---------------------------------------------
COPY maintenance/postgres/pg-maintenance.sh    /usr/local/bin/pg-maintenance.sh
COPY maintenance/postgres/pg-maintenance-cron-runner /usr/local/bin/pg-maintenance-cron-runner
COPY maintenance/postgres/pg-maintenance-cron  /etc/cron.d/pg-maintenance

# Make script executable, set correct cron permissions, create log file
# ---------------------------------------------------------------------
RUN chmod 0555 /usr/local/bin/pg-maintenance.sh /usr/local/bin/pg-maintenance-cron-runner && \
    chmod 0644 /etc/cron.d/pg-maintenance && \
    touch /var/log/pg-maintenance.log

# Entrypoint: inject runtime env vars into the cron environment,
# then start cron in the foreground while tailing the log
# -------------------------------------------------------
COPY maintenance/postgres/pg-maintenance-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0555 /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=10s --timeout=10s --start-period=10s --retries=30 \
    CMD pgrep -x cron >/dev/null || exit 1

USER postgres

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
