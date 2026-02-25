#!/bin/sh
set -e

if [ -z "$CROWDSEC_BOUNCER_API_KEY" ]; then
    echo "CROWDSEC_BOUNCER_API_KEY is not set or empty."
    echo "Firewall Bouncer will not start. Exiting cleanly."
    exec tail -f /dev/null
fi

echo "CROWDSEC_BOUNCER_API_KEY is provided. Starting Firewall Bouncer..."
# Pass execution back to the original entrypoint/command
exec /docker_start.sh "$@"
