#!/bin/sh

set -eu

echo "ERROR: Standalone firewall bouncer container is disabled in this deployment."
echo "CrowdSec now installs bouncers locally inside the crowdsec container:"
echo "  - crowdsec-firewall-bouncer-iptables"
echo "  - crowdsec-nginx-bouncer"
exit 1
