#!/bin/sh
# Session storage must be writable, durable, and protected from cache eviction.
set -eu

policy=$(redis-cli --raw CONFIG GET maxmemory-policy)
if [ "$(printf '%s' "$policy" | tr -d '\r')" != "$(printf 'maxmemory-policy\nnoeviction')" ]; then
    printf '%s\n' 'Redis session storage requires the noeviction policy.' >&2
    exit 1
fi

persistence=$(redis-cli --raw INFO persistence)
for field in loading:0 aof_enabled:1 aof_last_write_status:ok aof_last_bgrewrite_status:ok; do
    if ! printf '%s\n' "$persistence" | tr -d '\r' | grep -qx "$field"; then
        printf '%s\n' 'Redis session persistence is not ready.' >&2
        exit 1
    fi
done
