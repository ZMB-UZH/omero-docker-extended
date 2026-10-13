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

command_name="${1:-}"
if [ -n "${OMERO_POSTGRES_TLS_CERT:-}" ] &&
    { [ "$command_name" = postgres ] || [ "${command_name#-}" != "$command_name" ]; }; then
    : "${OMERO_POSTGRES_TLS_KEY:?PostgreSQL TLS key is required}"
    : "${OMERO_POSTGRES_TLS_CA:?PostgreSQL TLS authority is required}"
    # Native startup may precede the issuer after a host reboot. Wait for valid
    # material without falling back to plaintext or resetting persistent data.
    until openssl verify -CAfile "$OMERO_POSTGRES_TLS_CA" "$OMERO_POSTGRES_TLS_CERT" >/dev/null 2>&1; do
        sleep 1
    done
    if [ "$(id -u)" -eq 0 ]; then
        gosu postgres /bin/sh /usr/local/bin/postgres-tls-reload.sh &
    else
        /bin/sh /usr/local/bin/postgres-tls-reload.sh &
    fi
    set -- "$@" -c ssl=on -c ssl_min_protocol_version=TLSv1.2 # DevSkim: ignore DS440001 -- minimum only; no maximum restriction
    set -- "$@" \
        -c "ssl_cert_file=$OMERO_POSTGRES_TLS_CERT" \
        -c "ssl_key_file=$OMERO_POSTGRES_TLS_KEY"
fi

exec docker-entrypoint.sh "$@"
