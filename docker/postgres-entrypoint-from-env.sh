#!/usr/bin/env sh
set -eu

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

eval "postgres_password=\${$password_var:-}"
if [ -z "$postgres_password" ]; then
    die "Missing required environment variable: $password_var"
fi

export POSTGRES_PASSWORD="$postgres_password"
unset postgres_password

exec docker-entrypoint.sh "$@"
