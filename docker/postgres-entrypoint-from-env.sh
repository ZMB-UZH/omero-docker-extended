#!/usr/bin/env sh
set -eu

# Print an error and exit. Inputs: shell arguments and environment. Output: command status and side effects.
die() {
    printf 'FATAL: %s\n' "$*" >&2
    exit 1
}

password_source="${OMERO_POSTGRES_PASSWORD_SOURCE:-}"
case "$password_source" in
    main)
        password_var="OMERO_DB_PASS"
        ;;
    plugin)
        password_var="OMP_PLUGIN_DB_PASS"
        ;;
    *)
        die "OMERO_POSTGRES_PASSWORD_SOURCE must be main or plugin"
        ;;
esac

case "$password_var" in
    OMERO_DB_PASS)
        postgres_password="${OMERO_DB_PASS:-}" # skipcq: SCT-A000
        ;;
    OMP_PLUGIN_DB_PASS)
        postgres_password="${OMP_PLUGIN_DB_PASS:-}" # skipcq: SCT-A000
        ;;
esac
if [ -z "$postgres_password" ]; then
    die "Missing required environment variable: $password_var"
fi

export POSTGRES_PASSWORD="$postgres_password"
unset postgres_password

exec docker-entrypoint.sh "$@"
