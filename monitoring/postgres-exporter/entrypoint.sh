#!/usr/bin/env sh
set -eu

# Print an error and exit. Inputs: shell arguments and environment. Output: command status and side effects.
die() {
    printf 'FATAL: %s\n' "$*" >&2
    exit 1
}

exporter_source="${OMERO_POSTGRES_EXPORTER_SOURCE:-}"
case "$exporter_source" in
    main)
        db_user="omero"
        db_host="database"
        db_port="5432"
        db_name="omero"
        password_var="OMERO_DB_PASS"
        ;;
    plugin)
        db_user="omero-plugin"
        db_host="database-plugin"
        db_port="5433"
        db_name="omero-plugin"
        password_var="OMP_PLUGIN_DB_PASS"
        ;;
    *)
        die "OMERO_POSTGRES_EXPORTER_SOURCE must be main or plugin"
        ;;
esac

case "$password_var" in
    OMERO_DB_PASS)
        db_password="${OMERO_DB_PASS:-}" # skipcq: SCT-A000
        ;;
    OMP_PLUGIN_DB_PASS)
        db_password="${OMP_PLUGIN_DB_PASS:-}" # skipcq: SCT-A000
        ;;
esac
if [ -z "$db_password" ]; then
    die "Missing required environment variable: $password_var"
fi

export DATA_SOURCE_NAME="postgresql://${db_user}:${db_password}@${db_host}:${db_port}/${db_name}?sslmode=disable"
unset db_password

exec /bin/postgres_exporter "$@"
