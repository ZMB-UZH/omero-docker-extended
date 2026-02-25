#!/bin/sh
set -e

if [ -z "$CROWDSEC_BOUNCER_API_KEY" ]; then
    echo "CROWDSEC_BOUNCER_API_KEY is not set or empty."
    echo "CrowdSec will not start. Exiting cleanly (exit 0) to prevent restart loops."
    # Sleep forever so docker-compose doesn't constantly restart a successfully exited container
    # if restart: unless-stopped is used, or just exit 0 depending on compose setup.
    # To be safe with restart: unless-stopped and healthchecks, we just idle.
    exec tail -f /dev/null
fi

echo "CROWDSEC_BOUNCER_API_KEY is provided. Initializing CrowdSec..."

# Start CrowdSec in the background so we can configure it via cscli
/docker_start.sh &
CROWDSEC_PID=$!

echo "Waiting for CrowdSec API to become ready..."
# Wait for the local API to respond
until cscli lapi status >/dev/null 2>&1; do
    sleep 2
done

echo "CrowdSec API is ready."

BOUNCER_NAME="firewall-bouncer-auto"

# Check if a bouncer with this exact key already exists
# CrowdSec doesn't store the raw key to check against, so we check if our specific bouncer name exists.
if cscli bouncers list -o json | grep -q "\"name\":\"$BOUNCER_NAME\""; then
    echo "Bouncer '$BOUNCER_NAME' already exists."
    # We can't verify the exact key from the CLI because it's hashed in the DB.
    # To enforce the *current* ENV key, we delete the existing bouncer and recreate it.
    echo "Re-registering to ensure the API key matches the current CROWDSEC_BOUNCER_API_KEY."
    cscli bouncers delete "$BOUNCER_NAME"
fi

# Remove ANY other bouncers to ensure only our designated key/bouncer is active
echo "Cleaning up any other preexisting bouncers..."
EXISTING_BOUNCERS=$(cscli bouncers list -o json | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
for b in $EXISTING_BOUNCERS; do
    if [ "$b" != "$BOUNCER_NAME" ]; then
        echo "Deleting preexisting bouncer: $b"
        cscli bouncers delete "$b" || true
    fi
done

echo "Registering bouncer '$BOUNCER_NAME' with provided API key..."
cscli bouncers add "$BOUNCER_NAME" -k "$CROWDSEC_BOUNCER_API_KEY" >/dev/null

echo "Initialization complete. Bringing CrowdSec to foreground..."
wait $CROWDSEC_PID
