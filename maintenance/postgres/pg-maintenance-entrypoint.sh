#!/usr/bin/env bash
# ============================================================================
# Entrypoint for the pg-maintenance container.
#
# Cron does not inherit the container's environment, so we dump all relevant
# variables into a file that the cron schedule sources before each job.
# Then we start cron in the foreground and tail the shared log file.
# ============================================================================

set -euo pipefail

ENV_FILE="/etc/pg-maintenance-env"

# Export every PG-related env var so the cron jobs can use them.
printenv | grep -E '^(OMERO_DB_|PLUGIN_DB_|TZ=|PGTZ=|PATH=)' > "$ENV_FILE"

# Rewrite the cron file to source the env file before each command.
# This ensures cron jobs see the database connection variables.
sed -i "s|/usr/local/bin/pg-maintenance.sh|. $ENV_FILE; /usr/local/bin/pg-maintenance.sh|g" \
    /etc/cron.d/pg-maintenance

# Register cron jobs
crontab /etc/cron.d/pg-maintenance

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] pg-maintenance container started."
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Cron schedule loaded. Maintenance will run automatically."
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] - VACUUM ANALYZE : every Sunday at 03:00"
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] - REINDEX CONCUR.: first Sunday of month at 04:00"
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Run manually:  docker exec pg-maintenance pg-maintenance.sh all"
echo ""

# Start cron daemon and tail the log so 'docker logs' shows output.
cron
exec tail -F /var/log/pg-maintenance.log
