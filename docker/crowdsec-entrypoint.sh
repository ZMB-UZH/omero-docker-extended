#!/bin/sh
# ---------------------------------------------------------------------------
# CrowdSec custom entrypoint with host-firewall-aware bouncer configuration.
#
# Compatible with free/community CrowdSec — no paid features required.
#
# This script:
#   1. Detects the HOST firewall backend (nftables vs iptables-legacy).
#   2. Validates that the bouncer binary and firewall access work.
#   3. Starts the CrowdSec daemon and waits for the LOCAL LAPI.
#   4. Registers the firewall bouncer with the local LAPI (generates a local
#      API key — no cloud/paid API involved), generates its config for the
#      detected backend, and starts it.
#   5. For nftables mode: injects supplementary FORWARD-hook chains so that
#      Docker-bridged containers are also protected (the bouncer's built-in
#      nftables mode only creates INPUT-hook chains).
#   6. Optionally enrolls to the CrowdSec Console (free tier; skipped when
#      CROWDSEC_ENROLL_KEY is empty or a placeholder value).
#
# Guaranteed host compatibility: Ubuntu 24.04+, Debian 13 (Trixie).
# Both use nftables as the default kernel firewall backend.
# ---------------------------------------------------------------------------
set -eu

CROWDSEC_REQUIRE_BOUNCERS="${CROWDSEC_REQUIRE_BOUNCERS:-false}"
CROWDSEC_CONFIG_DIR="${CROWDSEC_CONFIG_DIR:-/etc/crowdsec}"
CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="${CROWDSEC_INSTALL_BOOTSTRAP_ENROLL:-0}"
CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR="${CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR:-/var/lib/crowdsec/data}"

is_true() {
    case "$(echo "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

is_placeholder_value() {
    local legacy_placeholder_prefix="CHANGE"

    case "${1:-}" in
        "${legacy_placeholder_prefix}VALUE"*) return 0 ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Firewall backend detection
# ---------------------------------------------------------------------------
# Determines whether the HOST kernel uses nftables or legacy iptables.
# Since we run with network_mode=host and NET_ADMIN, firewall commands
# executed inside the container operate directly on the host's network stack.
#
# Detection order:
#   1. Try 'nft list tables' — succeeds when the nf_tables kernel module is
#      loaded and the nft binary is available in this container.
#   2. Check for the nft binary on the mounted host root filesystem (/host).
#   3. Fallback: assume iptables (legacy).
# ---------------------------------------------------------------------------
detect_firewall_backend() {
    # Method 1: nft binary available inside the container AND kernel supports it.
    if command -v nft >/dev/null 2>&1 && nft list tables >/dev/null 2>&1; then
        echo "nftables"
        return 0
    fi

    # Method 2: host has nft (visible via the read-only / mount at /host).
    # Even if our container's nft binary failed above, the host's presence of
    # nft indicates the system is an nftables host.
    if [ -x "/host/usr/sbin/nft" ] || [ -x "/host/usr/bin/nft" ]; then
        echo "nftables"
        return 0
    fi

    echo "iptables"
    return 0
}

# ---------------------------------------------------------------------------
# Bouncer binary validation
# ---------------------------------------------------------------------------
validate_bouncer_binary() {
    if command -v crowdsec-firewall-bouncer >/dev/null 2>&1; then
        echo "Firewall bouncer binary detected: $(command -v crowdsec-firewall-bouncer)"
        return 0
    fi

    if is_true "${CROWDSEC_REQUIRE_BOUNCERS}"; then
        echo "ERROR: CROWDSEC_REQUIRE_BOUNCERS=true but crowdsec-firewall-bouncer binary is missing." >&2
        exit 1
    fi

    echo "WARNING: crowdsec-firewall-bouncer binary not found; continuing without firewall bouncer." >&2
    return 1
}

# ---------------------------------------------------------------------------
# Validate that the container can manipulate the host firewall
# ---------------------------------------------------------------------------
validate_firewall_access() {
    _backend="$1"

    case "${_backend}" in
        nftables)
            if ! nft list tables >/dev/null 2>&1; then
                echo "ERROR: Cannot execute 'nft list tables'." >&2
                echo "  Ensure NET_ADMIN capability is granted and network_mode is 'host'." >&2
                return 1
            fi
            echo "Validated: nftables kernel access OK (NET_ADMIN + host network)"
            ;;
        iptables)
            if ! iptables -L -n >/dev/null 2>&1; then
                echo "ERROR: Cannot execute 'iptables -L -n'." >&2
                echo "  Ensure NET_ADMIN capability is granted and network_mode is 'host'." >&2
                return 1
            fi
            echo "Validated: iptables kernel access OK (NET_ADMIN + host network)"
            ;;
    esac
    return 0
}

list_nft_sets_with_prefix() {
    _family="$1"
    _table="$2"
    _prefix="$3"

    nft -t list table "${_family}" "${_table}" 2>/dev/null | \
        awk -v prefix="${_prefix}" '$1 == "set" && index($2, prefix) == 1 { print $2 }'
}

wait_for_nft_sets() {
    _family="$1"
    _table="$2"
    _prefix="$3"
    _sets=""
    _attempts=0
    _max_attempts=30

    while [ "${_attempts}" -lt "${_max_attempts}" ]; do
        _sets="$(list_nft_sets_with_prefix "${_family}" "${_table}" "${_prefix}")"
        if [ -n "${_sets}" ]; then
            printf '%s\n' "${_sets}"
            return 0
        fi
        _attempts=$((_attempts + 1))
        sleep 1
    done

    return 1
}

ensure_nft_forward_chain() {
    _family="$1"
    _table="$2"
    _chain="$3"
    _sets="$4"

    if nft list chain "${_family}" "${_table}" "${_chain}" >/dev/null 2>&1; then
        nft flush chain "${_family}" "${_table}" "${_chain}"
    else
        nft add chain "${_family}" "${_table}" "${_chain}" \
            '{ type filter hook forward priority -10 ; policy accept ; }'
    fi

    for _set in ${_sets}; do
        case "${_family}" in
            ip)
                nft add rule "${_family}" "${_table}" "${_chain}" \
                    ip saddr "@${_set}" drop
                ;;
            ip6)
                nft add rule "${_family}" "${_table}" "${_chain}" \
                    ip6 saddr "@${_set}" drop
                ;;
        esac
    done
}

count_lines() {
    awk 'NF { count++ } END { print count + 0 }'
}

# ---------------------------------------------------------------------------
# Generate bouncer configuration for the detected firewall backend
# ---------------------------------------------------------------------------
# Arguments:
#   $1 — API key (raw string from 'cscli bouncers add ... -o raw')
#   $2 — firewall backend ("nftables" or "iptables")
# ---------------------------------------------------------------------------
generate_bouncer_config() {
    _api_key="$1"
    _backend="$2"
    _config_path="/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml"

    mkdir -p "$(dirname "${_config_path}")"

    case "${_backend}" in
        nftables)
            echo "Generating firewall bouncer config: mode=nftables"
            # The bouncer creates its own nftables table ('crowdsec' for IPv4,
            # 'crowdsec6' for IPv6) with an INPUT-hook chain at priority -10.
            # This processes packets BEFORE the default filter table (priority 0),
            # ensuring bans take effect before any other firewall rules.
            #
            # FORWARD-hook protection for Docker containers is added separately
            # by add_nftables_forward_chains() after the bouncer starts.
            cat > "${_config_path}" <<NFTCFG
mode: nftables
pid_dir: /var/run/
update_frequency: 10s
daemonize: false
log_mode: stdout
log_level: info
api_url: http://127.0.0.1:8080/
api_key: ${_api_key}
disable_ipv6: false
nftables:
  ipv4:
    enabled: true
    set-only: false
    table: crowdsec
    chain: crowdsec-chain
    priority: -10
  ipv6:
    enabled: true
    set-only: false
    table: crowdsec6
    chain: crowdsec6-chain
    priority: -10
NFTCFG
            ;;
        *)
            echo "Generating firewall bouncer config: mode=iptables (legacy fallback)"
            # iptables mode: the bouncer inserts jump rules into each specified
            # chain pointing to its own CROWDSEC chain which contains the drop
            # rules for banned IPs.
            #
            # INPUT  — protects services running directly on the host.
            # DOCKER-USER — processed before Docker's own FORWARD rules,
            #               protecting containers behind bridge networking.
            cat > "${_config_path}" <<IPTCFG
mode: iptables
pid_dir: /var/run/
update_frequency: 10s
daemonize: false
log_mode: stdout
log_level: info
api_url: http://127.0.0.1:8080/
api_key: ${_api_key}
disable_ipv6: false
iptables_chains:
  - INPUT
  - DOCKER-USER
IPTCFG
            ;;
    esac

    echo "Bouncer config written to ${_config_path}"
}

# ---------------------------------------------------------------------------
# Add supplementary nftables FORWARD-hook chains for Docker traffic protection
# ---------------------------------------------------------------------------
# The bouncer's built-in nftables mode creates chains on the INPUT hook only,
# which protects services running directly on the host.  Docker containers
# behind bridge networking receive traffic via the FORWARD hook (after DNAT
# in prerouting), so we add parallel chains that reference the same banned-IP
# sets the bouncer already manages.
#
# This function waits for the bouncer to create its nftables structures
# (tables + sets), then discovers the set names and adds FORWARD-hook chains
# in each table.
# ---------------------------------------------------------------------------
add_nftables_forward_chains() {
    echo "Adding nftables FORWARD-hook chains for Docker traffic protection..."

    # --- Wait for the bouncer to create its nftables structures. -----------
    _attempts=0
    _max_attempts=30
    while [ "${_attempts}" -lt "${_max_attempts}" ]; do
        if nft list table ip crowdsec >/dev/null 2>&1; then
            break
        fi
        _attempts=$((_attempts + 1))
        sleep 1
    done

    if ! nft list table ip crowdsec >/dev/null 2>&1; then
        echo "WARNING: Timed out waiting for bouncer nftables table 'ip crowdsec'." >&2
        echo "  FORWARD-hook chains NOT added. Docker containers will not be" >&2
        echo "  protected by CrowdSec bans (host INPUT is still protected)." >&2
        return 1
    fi

    # --- IPv4 FORWARD chain ------------------------------------------------
    _ipv4_sets="$(wait_for_nft_sets ip crowdsec crowdsec-blacklists || true)"

    if [ -n "${_ipv4_sets}" ]; then
        # Create a FORWARD-hook chain at the same priority as the INPUT chain
        # so that forwarded packets (Docker bridge traffic) are also checked
        # against every banned-IP set managed by the bouncer.  Bouncer 0.0.31
        # creates one set per decision origin, so a single hard-coded set name
        # is not sufficient.
        ensure_nft_forward_chain ip crowdsec crowdsec-chain-forward "${_ipv4_sets}"
        _ipv4_set_count="$(printf '%s\n' "${_ipv4_sets}" | count_lines)"
        echo "Added IPv4 FORWARD chain in table 'ip crowdsec' (sets=${_ipv4_set_count})"
    else
        echo "WARNING: Timed out waiting for IPv4 blacklist sets in table 'ip crowdsec'." >&2
        echo "  IPv4 FORWARD-hook chain NOT added." >&2
    fi

    # --- IPv6 FORWARD chain ------------------------------------------------
    if nft list table ip6 crowdsec6 >/dev/null 2>&1; then
        _ipv6_sets="$(wait_for_nft_sets ip6 crowdsec6 crowdsec6-blacklists || true)"

        if [ -n "${_ipv6_sets}" ]; then
            ensure_nft_forward_chain ip6 crowdsec6 crowdsec6-chain-forward "${_ipv6_sets}"
            _ipv6_set_count="$(printf '%s\n' "${_ipv6_sets}" | count_lines)"
            echo "Added IPv6 FORWARD chain in table 'ip6 crowdsec6' (sets=${_ipv6_set_count})"
        else
            echo "WARNING: Timed out waiting for IPv6 blacklist sets in table 'ip6 crowdsec6'." >&2
            echo "  IPv6 FORWARD-hook chain NOT added." >&2
        fi
    fi

    return 0
}

# ===========================================================================
# Main
# ===========================================================================

FIREWALL_BACKEND=$(detect_firewall_backend)
echo "Detected host firewall backend: ${FIREWALL_BACKEND}"

# --- Validate bouncer availability ----------------------------------------
BOUNCER_AVAILABLE=false
if validate_bouncer_binary; then
    BOUNCER_AVAILABLE=true
fi

# --- Validate firewall access before starting anything --------------------
if [ "${BOUNCER_AVAILABLE}" = "true" ]; then
    if ! validate_firewall_access "${FIREWALL_BACKEND}"; then
        if is_true "${CROWDSEC_REQUIRE_BOUNCERS}"; then
            echo "ERROR: CROWDSEC_REQUIRE_BOUNCERS=true but firewall access validation failed." >&2
            exit 1
        fi
        echo "WARNING: Firewall access validation failed; bouncer will start but may not function correctly." >&2
    fi
fi

# ---------------------------------------------------------------------------
# Bootstrap bind-mounted /etc/crowdsec/ from the upstream image's staging directory.
#
# CROWDSEC_CONFIG_PATH is mounted onto /etc/crowdsec/ and shadows every file
# and directory. The upstream docker_start.sh only repopulates this if config.yaml
# is completely missing. If config.yaml exists but sub-directories like patterns/
# or hub/ are missing (e.g., deleted by admin, or from a partial restore), crowdsec
# dies on startup.
#
# We use the official image's /staging/etc/crowdsec/ as the fallback source,
# so no custom .bak file is strictly required. This is 100% robust.
# ---------------------------------------------------------------------------
_CS_DIR="/etc/crowdsec"
# Use the official image's staging directory as the source of truth,
# or fallback to our custom backup if it exists. This ensures 100% robustness
# even if the custom .bak is never created.
if [ -d "/staging/etc/crowdsec" ]; then
    _CS_BAK="/staging/etc/crowdsec"
elif [ -d "/etc/crowdsec.bak" ]; then
    _CS_BAK="/etc/crowdsec.bak"
else
    _CS_BAK=""
fi

if [ -n "${_CS_BAK}" ]; then
    echo "Bootstrap: syncing missing items from ${_CS_BAK} into ${_CS_DIR}"
    for _bak_item in "${_CS_BAK}"/*; do
        [ -e "${_bak_item}" ] || continue
        _name=$(basename "${_bak_item}")
        if [ ! -e "${_CS_DIR}/${_name}" ]; then
            cp -a "${_bak_item}" "${_CS_DIR}/${_name}"
            echo "Bootstrap: restored ${_CS_DIR}/${_name}"
        fi
    done
else
    echo "WARNING: No backup directory found; skipping full restore." >&2
fi

# Belt-and-suspenders: ensure critical directories always exist.
mkdir -p "${_CS_DIR}/hub"
mkdir -p "${_CS_DIR}/patterns"

# --- Start CrowdSec daemon in background ----------------------------------
/docker_start.sh &
CROWDSEC_PID=$!

echo "Waiting for CrowdSec LAPI to become ready..."
until cscli lapi status >/dev/null 2>&1; do
    sleep 2
done
echo "CrowdSec LAPI is ready."

# --- Configure and start the firewall bouncer -----------------------------
if [ "${BOUNCER_AVAILABLE}" = "true" ]; then
    echo "Configuring crowdsec-firewall-bouncer (backend=${FIREWALL_BACKEND})..."

    # Remove stale bouncer registration from a previous run, then register.
    # The API key is generated LOCALLY by the LAPI — it is a random string
    # stored in the local CrowdSec SQLite database.  No cloud API, no paid
    # subscription, and no CROWDSEC_ENROLL_KEY is required for this step.
    # The bouncer uses this key to authenticate with the local LAPI at
    # http://127.0.0.1:8080/ inside this same container.
    if cscli bouncers list 2>/dev/null | grep -q "firewall-bouncer"; then
        cscli bouncers delete firewall-bouncer || true
    fi

    if API_KEY=$(cscli bouncers add firewall-bouncer -o raw 2>/dev/null) && [ -n "${API_KEY}" ]; then
        generate_bouncer_config "${API_KEY}" "${FIREWALL_BACKEND}"

        echo "Starting crowdsec-firewall-bouncer in background..."
        crowdsec-firewall-bouncer \
            -c /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml &

        # For nftables mode, add supplementary FORWARD-hook chains so that
        # Docker-bridged containers are also covered by CrowdSec bans.
        if [ "${FIREWALL_BACKEND}" = "nftables" ]; then
            add_nftables_forward_chains || true
        fi
    else
        echo "WARNING: Failed to register firewall bouncer with local LAPI." >&2
        echo "  'cscli bouncers add firewall-bouncer -o raw' returned empty or failed." >&2
        if is_true "${CROWDSEC_REQUIRE_BOUNCERS}"; then
            exit 1
        fi
        echo "  Continuing without firewall bouncer (CrowdSec detection still active)." >&2
    fi
fi

# --- Console enrollment (optional, free tier) -----------------------------
crowdsec_install_enrollment_done_marker_path() {
    printf '%s' "${CROWDSEC_INSTALL_BOOTSTRAP_STATE_DIR%/}/.console-enrollment-install.done"
}

crowdsec_has_install_enrollment_done_marker() {
    [ -f "$(crowdsec_install_enrollment_done_marker_path)" ]
}

mark_crowdsec_install_enrollment_done() {
    local marker_path=""

    marker_path="$(crowdsec_install_enrollment_done_marker_path)"
    mkdir -p "$(dirname "${marker_path}")"
    : > "${marker_path}"
    chmod 0600 "${marker_path}" 2>/dev/null || true
}

configure_console_enrollment() {
    local enroll_key="${CROWDSEC_ENROLL_KEY:-}"
    local engine_name="${CROWDSEC_ENGINE_NAME:-}"
    local clean_token=""

    if [ -z "${enroll_key}" ] || is_placeholder_value "${enroll_key}"; then
        echo "CROWDSEC_ENROLL_KEY is empty or a placeholder."
        echo "Ensuring console enrollment is disabled to reflect current environment state..."
        cscli console disable >/dev/null 2>&1 || true
        return 0
    fi

    if ! is_true "${CROWDSEC_INSTALL_BOOTSTRAP_ENROLL}"; then
        echo "CrowdSec install-only enrollment is not armed for this startup. Skipping console enrollment."
        return 0
    fi

    if crowdsec_has_install_enrollment_done_marker; then
        echo "CrowdSec install enrollment request was already created earlier. Skipping console enrollment."
        return 0
    fi

    clean_token="$(echo "${enroll_key}" | awk '{print $NF}')"
    if [ -z "${clean_token}" ]; then
        echo "WARNING: CrowdSec enrollment token resolved to an empty value." >&2
        return 1
    fi

    echo "Enrolling to CrowdSec Console for this installation run..."
    if [ -n "${engine_name}" ] && ! is_placeholder_value "${engine_name}"; then
        if cscli console enroll "${clean_token}" --overwrite --name "${engine_name}"; then
            mark_crowdsec_install_enrollment_done
        else
            echo "WARNING: Failed to enroll to CrowdSec Console."
        fi
        return 0
    fi

    if cscli console enroll "${clean_token}" --overwrite; then
        mark_crowdsec_install_enrollment_done
    else
        echo "WARNING: Failed to enroll to CrowdSec Console."
    fi
    return 0
}

configure_console_enrollment

# --- Wait for CrowdSec daemon to exit (container lifecycle) ----------------
wait $CROWDSEC_PID
