#!/bin/sh
set -eu

CROWDSEC_REQUIRE_BOUNCERS="${CROWDSEC_REQUIRE_BOUNCERS:-false}"

is_true() {
    case "$(echo "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

install_alpine_bouncers() {
    missing_packages=""
    for package_name in cs-firewall-bouncer iptables ipset; do
        if apk info -e "${package_name}" >/dev/null 2>&1; then
            echo "Package already installed: ${package_name}"
        else
            missing_packages="${missing_packages} ${package_name}"
        fi
    done

    if [ -n "${missing_packages# }" ]; then
        echo "Installing missing CrowdSec bouncer package(s):${missing_packages}"
        apk update
        apk add --no-cache ${missing_packages}
    fi
}

install_deb_bouncers() {
    missing_packages=""
    for package_name in crowdsec-firewall-bouncer-iptables; do
        if dpkg-query -W -f='${Status}' "${package_name}" 2>/dev/null | grep -q "install ok installed"; then
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
}

ensure_bouncer_packages_installed() {
    if command -v apk >/dev/null 2>&1; then
        install_alpine_bouncers
        return 0
    elif command -v dpkg-query >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
        install_deb_bouncers
        return 0
    fi

    if is_true "${CROWDSEC_REQUIRE_BOUNCERS}"; then
        echo "ERROR: CROWDSEC_REQUIRE_BOUNCERS=true but unsupported base image package manager." >&2
        exit 1
    fi

    echo "WARNING: Unsupported base image package manager. Skipping automatic bouncer package installation." >&2
}

validate_bouncer_binaries() {
    if command -v crowdsec-firewall-bouncer >/dev/null 2>&1; then
        echo "Installed bouncer binaries detected: crowdsec-firewall-bouncer"
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

if command -v crowdsec-firewall-bouncer >/dev/null 2>&1; then
    echo "Configuring and starting crowdsec-firewall-bouncer..."
    
    if cscli bouncers list | grep -q "firewall-bouncer"; then
        cscli bouncers delete firewall-bouncer || true
    fi
    cscli bouncers add firewall-bouncer -o raw > /tmp/bouncer-key
    API_KEY=$(cat /tmp/bouncer-key)
    rm -f /tmp/bouncer-key
    
    mkdir -p /etc/crowdsec/bouncers
    cat > /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml <<EOF
mode: iptables
pid_dir: /var/run/
update_frequency: 10s
daemonize: false
log_mode: stdout
log_level: info
api_url: http://127.0.0.1:8080/
api_key: \${API_KEY}
disable_ipv6: false
iptables_chains:
  - DOCKER-USER
  - INPUT
EOF

    echo "Starting crowdsec-firewall-bouncer in background..."
    crowdsec-firewall-bouncer -c /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml &
fi

if [ -n "${CROWDSEC_ENROLL_KEY:-}" ]; then
    CLEAN_TOKEN=$(echo "$CROWDSEC_ENROLL_KEY" | awk '{print $NF}')
    cscli console enroll "$CLEAN_TOKEN" || echo "WARNING: Failed to enroll to CrowdSec Console."
fi

wait $CROWDSEC_PID