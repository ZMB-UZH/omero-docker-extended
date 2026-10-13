#!/bin/sh
set -eu

# Runs as the database account, without network access or database credentials.
# Reload keeps active transactions alive and replaces native SSL state.
: "${PGDATA:?PostgreSQL data directory is required}"
: "${OMERO_POSTGRES_TLS_CERT:?PostgreSQL TLS certificate is required}"
: "${OMERO_POSTGRES_TLS_CA:?PostgreSQL TLS authority is required}"
previous=""
while :; do
    if [ -s "$PGDATA/postmaster.pid" ] && [ -s "$OMERO_POSTGRES_TLS_CERT" ]; then
        current="$(cksum < "$OMERO_POSTGRES_TLS_CERT")"
        if [ "$current" != "$previous" ] &&
            openssl verify -CAfile "$OMERO_POSTGRES_TLS_CA" "$OMERO_POSTGRES_TLS_CERT" >/dev/null 2>&1; then
            if pg_ctl reload -D "$PGDATA" >/dev/null; then
                previous="$current"
                printf '%s\n' 'PostgreSQL TLS material reloaded.' >&2
            fi
        fi
    fi
    sleep 5
done
