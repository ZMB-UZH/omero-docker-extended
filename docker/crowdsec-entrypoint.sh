#!/bin/sh
set -e

if [ -z "$CROWDSEC_BOUNCER_API_KEY" ]; then
    echo "CROWDSEC_BOUNCER_API_KEY is not set or empty."
    echo "CrowdSec will not start. Exiting cleanly (exit 0) to prevent restart loops."
    exec tail -f /dev/null
fi

echo "CROWDSEC_BOUNCER_API_KEY is provided. Initializing CrowdSec..."

# Start CrowdSec in the background so we can configure it via cscli
/docker_start.sh &
CROWDSEC_PID=$!

echo "Waiting for CrowdSec API to become ready..."
until cscli lapi status >/dev/null 2>&1; do
    sleep 2
done

echo "CrowdSec API is ready."

BOUNCER_NAME="firewall-bouncer-auto"

if cscli bouncers list -o json | grep -q "\"name\":\"$BOUNCER_NAME\""; then
    echo "Bouncer '$BOUNCER_NAME' already exists."
    echo "Re-registering to ensure the API key matches the current CROWDSEC_BOUNCER_API_KEY."
    cscli bouncers delete "$BOUNCER_NAME"
fi

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

# Enroll to Console if token is provided
if [ -n "$CROWDSEC_ENROLL_KEY" ]; then
    echo "CROWDSEC_ENROLL_KEY is provided. Enrolling to CrowdSec Console..."
    # Support both bare token and full command paste (strip everything but the token)
    # E.g. "sudo cscli console enroll cmm1sivky000..." -> "cmm1sivky000..."
    CLEAN_TOKEN=$(echo "$CROWDSEC_ENROLL_KEY" | awk '{print $NF}')
    cscli console enroll "$CLEAN_TOKEN" || echo "WARNING: Failed to enroll to CrowdSec Console."
else
    echo "No CROWDSEC_ENROLL_KEY provided. Skipping Console enrollment."
fi

echo "Initialization complete. Bringing CrowdSec to foreground..."
wait $CROWDSEC_PID
