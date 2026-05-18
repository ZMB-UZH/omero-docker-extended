#!/bin/sh

set -eu

echo "ERROR: Standalone firewall bouncer container is disabled in this deployment."
echo "The firewall bouncer runs inside the main CrowdSec container which:"
echo "  - Auto-detects the host firewall backend (nftables or iptables-legacy)."
echo "  - Generates a matching bouncer config (mode=nftables on Ubuntu 26.04 LTS / Debian 13)."
echo "  - Adds INPUT-hook protection (host services) and FORWARD-hook protection (Docker containers)."
echo "See docker/crowdsec-entrypoint.sh for the full startup sequence."
exit 1
