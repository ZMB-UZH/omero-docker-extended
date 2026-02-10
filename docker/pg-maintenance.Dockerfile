# ============================================================================
# pg-maintenance — lightweight cron sidecar for safe PostgreSQL maintenance
# ============================================================================
# Uses the same postgres:18.1 image as the database containers so the client
# tools (vacuumdb, reindexdb, pg_isready) match the server version exactly.
# ============================================================================

FROM postgres:18.1

# Install cron (available in Debian-based postgres images)
RUN apt-get update && \
    apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

# Copy the maintenance script and cron schedule
COPY maintenance/postgres/pg-maintenance.sh    /usr/local/bin/pg-maintenance.sh
COPY maintenance/postgres/pg-maintenance-cron  /etc/cron.d/pg-maintenance

# Make script executable, set correct cron permissions, create log file
RUN chmod +x /usr/local/bin/pg-maintenance.sh && \
    chmod 0644 /etc/cron.d/pg-maintenance && \
    touch /var/log/pg-maintenance.log

# Entrypoint: inject runtime env vars into the cron environment,
# then start cron in the foreground while tailing the log.
COPY maintenance/postgres/pg-maintenance-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
