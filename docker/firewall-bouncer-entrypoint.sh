#!/bin/sh

set -e

# NOTE: Bouncer API Key logic has been removed.
# The crowdsec stack now uses the enroll key for central console registration.
# Local bouncer functionality will be initialized natively if required without a manually set API_KEY.

echo "Starting Firewall Bouncer..."
exec "$@"