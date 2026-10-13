#!/usr/bin/env bash
set -euo pipefail

# Apply the existing CLI identity. Inputs: command argv. Output: child exit status.
as_server() {
    env USER=omero-server LOGNAME=omero-server LNAME=omero-server \
        USERNAME=omero-server HOME=/opt/omero/server \
        runuser -p -m -u omero-server -- "$@"
}

# Stop IceGrid before terminating its CLI wrapper. Inputs: active child. Output: shutdown status.
stop_startup_child() {
    trap '' TERM INT
    shutdown_requested=1
    if [ -z "$active_pid" ]; then
        return
    fi
    if [[ "$active_script" == */99-run.sh ]]; then
        as_server "$omero_cli" admin stop || shutdown_status=$?
    fi
    kill -TERM "$active_pid" 2>/dev/null || true
}

# Run a startup stage with termination handling. Inputs: script and argv. Output: stage status.
run_startup_script() {
    active_script=$1
    shift
    local status=0
    shutdown_requested=0
    shutdown_status=0
    active_pid=
    trap stop_startup_child TERM INT
    if [[ "$active_script" == *.py ]] || [[ "$active_script" == *60-database.sh ]]; then
        as_server "$active_script" "$@" &
    else
        "$active_script" "$@" &
    fi
    active_pid=$!
    if [ "$shutdown_requested" -eq 1 ]; then
        stop_startup_child
    fi
    wait "$active_pid" || status=$?
    if [ "$shutdown_requested" -eq 1 ]; then
        # wait was interrupted by the trap; reap the child after shutdown.
        wait "$active_pid" 2>/dev/null || true
        exit "$shutdown_status"
    fi
    trap - TERM INT
    return "$status"
}

# Initialize managed root starts, retaining direct unprivileged runs. Inputs: argv/env. Output: service status.
main() {
    if [ "$(id -u)" -ne 0 ]; then
        printf 'Running unprivileged; skipping root startup bootstrap and launching: %s\n' "$*"
        exec "$@"
    fi
    local venv_activate script
    venv_activate=$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' | sort -V | tail -n 1)/bin/activate
    if [ ! -f "$venv_activate" ]; then
        echo "FATAL: OMERO virtualenv activate script not found at $venv_activate" >&2
        exit 127
    fi
    # shellcheck source=/dev/null
    source "$venv_activate"
    omero_cli="${venv_activate%/activate}/omero"
    if [ -z "${CONFIG_omero_db_pass+x}" ] && [ -n "${OMERO_DB_PASS:-}" ]; then
        export CONFIG_omero_db_pass="$OMERO_DB_PASS"
    fi
    for script in /startup/*; do
        if [ -f "$script" ] && [ -x "$script" ]; then
            printf 'Running %s %s\n' "$script" "$*"
            run_startup_script "$script" "$@"
        fi
    done
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
