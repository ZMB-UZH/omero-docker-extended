#!/bin/sh
set -eu

# Grafana loads Go's system roots once. Native leaf renewal is hot-reloaded;
# replacing the public authority bundle requires a graceful process restart.
: "${SSL_CERT_FILE:?A verified public trust bundle is required}"
[ "$#" -gt 0 ] || exit 64

child=""
watcher=""
stopping=0
# Inputs: managed process IDs. Output: graceful stop of child and trust watcher.
stop() {
    stopping=1
    if [ -n "$watcher" ]; then kill -TERM "$watcher" 2>/dev/null || true; fi
    if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; fi
}
trap stop TERM INT

while :; do
    until [ -s "$SSL_CERT_FILE" ]; do
        [ "$stopping" -eq 0 ] || exit 0
        sleep 1
    done
    [ "$stopping" -eq 0 ] || exit 0
    previous="$(cksum < "$SSL_CERT_FILE")"
    "$@" &
    child=$!
    (
        while kill -0 "$child" 2>/dev/null; do
            sleep 5
            current="$(cksum < "$SSL_CERT_FILE")"
            if [ "$current" != "$previous" ]; then
                printf '%s\n' 'Public trust changed; reloading the service trust store.' >&2
                kill -TERM "$child" 2>/dev/null || true
                exit 0
            fi
        done
    ) &
    watcher=$!
    result=0
    wait "$child" || result=$?
    if [ "$stopping" -eq 1 ]; then
        wait "$child" 2>/dev/null || true
        wait "$watcher" 2>/dev/null || true
        exit "$result"
    fi
    kill -TERM "$watcher" 2>/dev/null || true
    wait "$watcher" 2>/dev/null || true
    watcher=""
    child=""
    current="$(cksum < "$SSL_CERT_FILE")"
    if [ "$current" = "$previous" ]; then exit "$result"; fi
done
