#!/usr/bin/env bash
# ============================================================================
# pg-maintenance.sh — Safe, non-locking PostgreSQL maintenance for OMERO
# ============================================================================
#
# This script performs two safe maintenance operations on both OMERO databases:
#
#   1. VACUUM ANALYZE  — reclaims dead-tuple space and refreshes planner stats.
#                        Non-blocking: runs alongside normal reads and writes.
#
#   2. REINDEX (CONCURRENTLY) — rebuilds all indexes without exclusive locks.
#                               Safe for online use since PostgreSQL 12+.
#
# What this script does NOT do (by design):
#
#   - VACUUM FULL — requires ACCESS EXCLUSIVE lock (blocks ALL reads/writes).
#                   Only ever run manually during a planned maintenance window.
#
# Usage (typically called via cron inside the pg-maintenance container):
#
#   pg-maintenance.sh vacuum_analyze     # run VACUUM ANALYZE on both DBs
#   pg-maintenance.sh reindex            # run REINDEX CONCURRENTLY on both DBs
#   pg-maintenance.sh all                # run both (vacuum first, then reindex)
#
# Environment variables (all required):
#
#   OMERO_DB_HOST, OMERO_DB_PORT, OMERO_DB_NAME, OMERO_DB_USER, OMERO_DB_PASS
#   PLUGIN_DB_HOST, PLUGIN_DB_PORT, PLUGIN_DB_NAME, PLUGIN_DB_USER, PLUGIN_DB_PASS
#
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"; }

die() { log "FATAL: $*" >&2; exit 1; }

check_env() {
    local missing=()
    for var in OMERO_DB_HOST OMERO_DB_PORT OMERO_DB_NAME OMERO_DB_USER OMERO_DB_PASS \
               PLUGIN_DB_HOST PLUGIN_DB_PORT PLUGIN_DB_NAME PLUGIN_DB_USER PLUGIN_DB_PASS; do
        [[ -z "${!var:-}" ]] && missing+=("$var")
    done
    if (( ${#missing[@]} )); then
        die "Missing required environment variables: ${missing[*]}"
    fi
}

wait_for_db() {
    local host="$1" port="$2" user="$3" dbname="$4" retries=30 delay=5
    log "Waiting for $dbname at $host:$port ..."
    for (( i=1; i<=retries; i++ )); do
        if pg_isready -h "$host" -p "$port" -U "$user" -d "$dbname" -q 2>/dev/null; then
            log "  $dbname is ready."
            return 0
        fi
        log "  Attempt $i/$retries — not ready, retrying in ${delay}s ..."
        sleep "$delay"
    done
    die "Database $dbname at $host:$port did not become ready after $((retries * delay))s"
}

# ---------------------------------------------------------------------------
# Core maintenance functions
# ---------------------------------------------------------------------------

# run_vacuum_analyze <host> <port> <dbname> <user> <password>
run_vacuum_analyze() {
    local host="$1" port="$2" dbname="$3" user="$4"
    export PGPASSWORD="$5"

    log "--- VACUUM ANALYZE on $dbname ($host:$port) ---"
    # vacuumdb --analyze runs plain VACUUM + ANALYZE on every table.
    # It does NOT acquire exclusive locks — fully safe while the DB is online.
    if vacuumdb --host="$host" --port="$port" --username="$user" \
                --dbname="$dbname" --analyze --verbose 2>&1 | \
                while IFS= read -r line; do log "  $line"; done; then
        log "VACUUM ANALYZE completed successfully on $dbname."
    else
        log "WARNING: VACUUM ANALYZE reported issues on $dbname (exit $?)."
    fi
    unset PGPASSWORD
}

# run_reindex <host> <port> <dbname> <user> <password>
run_reindex() {
    local host="$1" port="$2" dbname="$3" user="$4"
    export PGPASSWORD="$5"

    log "--- REINDEX (CONCURRENTLY) on $dbname ($host:$port) ---"
    # reindexdb --concurrently rebuilds every index with only a
    # SHARE UPDATE EXCLUSIVE lock — reads and writes continue normally.
    # Available since PostgreSQL 12. The stack uses PostgreSQL 16.12.
    if reindexdb --host="$host" --port="$port" --username="$user" \
                 --dbname="$dbname" --concurrently --verbose 2>&1 | \
                 while IFS= read -r line; do log "  $line"; done; then
        log "REINDEX CONCURRENTLY completed successfully on $dbname."
    else
        log "WARNING: REINDEX CONCURRENTLY reported issues on $dbname (exit $?)."
    fi
    unset PGPASSWORD
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

do_vacuum_analyze() {
    log "========== Starting VACUUM ANALYZE =========="
    wait_for_db "$OMERO_DB_HOST" "$OMERO_DB_PORT" "$OMERO_DB_USER" "$OMERO_DB_NAME"
    run_vacuum_analyze "$OMERO_DB_HOST" "$OMERO_DB_PORT" "$OMERO_DB_NAME" "$OMERO_DB_USER" "$OMERO_DB_PASS"

    wait_for_db "$PLUGIN_DB_HOST" "$PLUGIN_DB_PORT" "$PLUGIN_DB_USER" "$PLUGIN_DB_NAME"
    run_vacuum_analyze "$PLUGIN_DB_HOST" "$PLUGIN_DB_PORT" "$PLUGIN_DB_NAME" "$PLUGIN_DB_USER" "$PLUGIN_DB_PASS"
    log "========== VACUUM ANALYZE finished =========="
}

do_reindex() {
    log "========== Starting REINDEX (CONCURRENTLY) =========="
    wait_for_db "$OMERO_DB_HOST" "$OMERO_DB_PORT" "$OMERO_DB_USER" "$OMERO_DB_NAME"
    run_reindex "$OMERO_DB_HOST" "$OMERO_DB_PORT" "$OMERO_DB_NAME" "$OMERO_DB_USER" "$OMERO_DB_PASS"

    wait_for_db "$PLUGIN_DB_HOST" "$PLUGIN_DB_PORT" "$PLUGIN_DB_USER" "$PLUGIN_DB_NAME"
    run_reindex "$PLUGIN_DB_HOST" "$PLUGIN_DB_PORT" "$PLUGIN_DB_NAME" "$PLUGIN_DB_USER" "$PLUGIN_DB_PASS"
    log "========== REINDEX (CONCURRENTLY) finished =========="
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main() {
    local action="${1:-}"

    [[ -z "$action" ]] && die "Usage: $0 {vacuum_analyze|reindex|all}"

    check_env

    case "$action" in
        vacuum_analyze)
            do_vacuum_analyze
            ;;
        reindex)
            do_reindex
            ;;
        all)
            do_vacuum_analyze
            do_reindex
            ;;
        *)
            die "Unknown action '$action'. Use: vacuum_analyze | reindex | all"
            ;;
    esac

    log "All maintenance tasks completed."
}

main "$@"
