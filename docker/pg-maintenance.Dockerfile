# pg-maintenance — lightweight cron sidecar for safe PostgreSQL maintenance

# Pull image (needs to match the tag in docker-compose.yml)
# ---------------------------------------------------------
FROM postgres:16.12@sha256:23af655ba1ddf74eaa002e3deaf5fce022ab8791672336a7c1fb0ef2d57efb7f

# Use bash with pipefail for safer RUN commands
# ---------------------------------------------
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
        DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# Copy the maintenance script and cron schedule
# ---------------------------------------------
COPY maintenance/postgres/pg-maintenance.sh    /usr/local/bin/pg-maintenance.sh
COPY maintenance/postgres/pg-maintenance-cron-runner /usr/local/bin/pg-maintenance-cron-runner
COPY maintenance/postgres/pg-maintenance-cron  /etc/cron.d/pg-maintenance

# Make script executable, set correct cron permissions, create log file
# ---------------------------------------------------------------------
RUN chmod +x /usr/local/bin/pg-maintenance.sh /usr/local/bin/pg-maintenance-cron-runner && \
    chmod 0644 /etc/cron.d/pg-maintenance && \
    touch /var/log/pg-maintenance.log

# Entrypoint: inject runtime env vars into the cron environment,
# then start cron in the foreground while tailing the log
# -------------------------------------------------------
COPY maintenance/postgres/pg-maintenance-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=10s --timeout=10s --start-period=10s --retries=30 \
    CMD pgrep -x cron >/dev/null || exit 1

USER postgres

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
