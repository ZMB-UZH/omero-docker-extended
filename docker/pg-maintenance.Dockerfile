# pg-maintenance — lightweight cron sidecar for safe PostgreSQL maintenance

# Pull image (needs to match the tag in docker-compose.yml)
# ---------------------------------------------------------
FROM postgres:16.12

# Install cron
# ------------
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

# Copy the maintenance script and cron schedule
# ---------------------------------------------
COPY maintenance/postgres/pg-maintenance.sh    /usr/local/bin/pg-maintenance.sh
COPY maintenance/postgres/pg-maintenance-cron  /etc/cron.d/pg-maintenance

# Make script executable, set correct cron permissions, create log file
# ---------------------------------------------------------------------
RUN chmod +x /usr/local/bin/pg-maintenance.sh && \
    chmod 0644 /etc/cron.d/pg-maintenance && \
    touch /var/log/pg-maintenance.log

# Entrypoint: inject runtime env vars into the cron environment,
# then start cron in the foreground while tailing the log
# -------------------------------------------------------
COPY maintenance/postgres/pg-maintenance-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
