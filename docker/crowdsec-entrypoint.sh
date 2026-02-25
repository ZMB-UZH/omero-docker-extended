#!/bin/sh
set -eu

REQUIRED_BOUNCER_PACKAGES="crowdsec-firewall-bouncer-iptables crowdsec-nginx-bouncer"
CROWDSEC_REQUIRE_BOUNCERS="${CROWDSEC_REQUIRE_BOUNCERS:-false}"

is_true() {
    case "$(echo "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_installed_deb() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}

ensure_bouncer_packages_installed() {
    if command -v dpkg-query >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
        missing_packages=""
        for package_name in ${REQUIRED_BOUNCER_PACKAGES}; do
            if is_installed_deb "${package_name}"; then
                echo "Package already installed: ${package_name}"
            else
                missing_packages="${missing_packages} ${package_name}"
            fi
        done

        if [ -n "${missing_packages# }" ]; then
            echo "Installing missing CrowdSec bouncer package(s):${missing_packages}"
            apt-get update
            apt-get install -y --no-install-recommends ${missing_packages}
            rm -rf /var/lib/apt/lists/*
        fi

        return 0
    fi

    if is_true "${CROWDSEC_REQUIRE_BOUNCERS}"; then
        echo "ERROR: CROWDSEC_REQUIRE_BOUNCERS=true but unsupported base image package manager (requires apt/dpkg)." >&2
        exit 1
    fi

    echo "WARNING: Unsupported base image package manager. Skipping automatic bouncer package installation." >&2
    echo "WARNING: Set CROWDSEC_REQUIRE_BOUNCERS=true to fail fast when bouncers are required." >&2
}

validate_bouncer_binaries() {
    if command -v crowdsec-firewall-bouncer >/dev/null 2>&1 && command -v crowdsec-nginx-bouncer >/dev/null 2>&1; then
        echo "Installed bouncer binaries detected: crowdsec-firewall-bouncer, crowdsec-nginx-bouncer"
        return 0
    fi

    if is_true "${CROWDSEC_REQUIRE_BOUNCERS}"; then
        echo "ERROR: CROWDSEC_REQUIRE_BOUNCERS=true but one or more bouncer binaries are missing." >&2
        exit 1
    fi

    echo "WARNING: Bouncer binaries not found; continuing because CROWDSEC_REQUIRE_BOUNCERS=false." >&2
}

ensure_bouncer_packages_installed
validate_bouncer_binaries

if [ -n "${CROWDSEC_ENROLL_KEY:-}" ]; then
    echo "CROWDSEC_ENROLL_KEY is provided. CrowdSec Console enrollment will be attempted after startup."
fi

/docker_start.sh &
CROWDSEC_PID=$!

echo "Waiting for CrowdSec API to become ready..."
until cscli lapi status >/dev/null 2>&1; do
    sleep 2
done

echo "CrowdSec API is ready."

if [ -n "${CROWDSEC_ENROLL_KEY:-}" ]; then
    CLEAN_TOKEN=$(echo "$CROWDSEC_ENROLL_KEY" | awk '{print $NF}')
    cscli console enroll "$CLEAN_TOKEN" || echo "WARNING: Failed to enroll to CrowdSec Console."
fi

wait $CROWDSEC_PID
