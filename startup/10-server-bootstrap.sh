#!/usr/bin/env bash
set -euo pipefail

log() {
    echo "[server-bootstrap] $*"
}

OMERO_DIR="${OMERO_DIR:-/OMERO}"
CERTS_DIR="${CERTS_DIR:-${OMERO_DIR}/certs}"
SERVER_HOME="/opt/omero/server/OMERO.server"
SERVER_VAR_DIR="${SERVER_VAR_DIR:-${SERVER_HOME}/var}"
SERVER_LOG_DIR="${SERVER_LOG_DIR:-${SERVER_VAR_DIR}/log}"
OMERO_BIN="${SERVER_HOME}/bin/omero"
OMERO_CLI_USER="${OMERO_CLI_USER:-omero-server}"

run_omero() {
    if [[ "$(id -u)" -ne 0 ]]; then
        "${OMERO_BIN}" "$@"
        return
    fi

    if ! id -u "${OMERO_CLI_USER}" >/dev/null 2>&1; then
        echo "FATAL: user '${OMERO_CLI_USER}' not found; cannot run OMERO CLI safely." >&2
        exit 1
    fi

    runuser -u "${OMERO_CLI_USER}" -- "${OMERO_BIN}" "$@"
}

validate_ldap_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_user_filter="${CONFIG_omero_ldap_user__filter:-}"

    local required_non_empty=(
        "CONFIG_omero_ldap_urls"
        "CONFIG_omero_ldap_username"
        "CONFIG_omero_ldap_password"
    )

    local var_name
    for var_name in "${required_non_empty[@]}"; do
        if [[ -z "${!var_name:-}" ]]; then
            echo "ERROR: LDAP is enabled but ${var_name} is not set in env/omero_secrets.env" >&2
            exit 1
        fi
    done

    if [[ -z "${CONFIG_omero_ldap_base+x}" ]]; then
        echo "ERROR: LDAP is enabled but CONFIG_omero_ldap_base is not declared in env/omero_secrets.env (empty is allowed, missing is not)." >&2
        exit 1
    fi

    log "LDAP enabled; required secret-backed LDAP settings are present"
}

validate_ldap_new_user_group_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    if [[ -z "${ldap_group_setting}" ]]; then
        log "LDAP enabled without CONFIG_omero_ldap_new__user__group; OMERO will use its built-in default new-user group behavior"
        return
    fi

    if [[ "${ldap_group_setting}" == :* ]]; then
        log "LDAP new-user group uses dynamic mapping expression (${ldap_group_setting}); runtime group auto-bootstrap is skipped"
        return
    fi

    if ! [[ "${ldap_group_setting}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
        echo "ERROR: CONFIG_omero_ldap_new__user__group contains invalid OMERO group name '${ldap_group_setting}'. Allowed pattern: [A-Za-z0-9_.-]+" >&2
        exit 1
    fi
}


apply_ldap_runtime_configuration() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_user_filter="${CONFIG_omero_ldap_user__filter:-}"
    local ldap_new_user_group="${CONFIG_omero_ldap_new__user__group:-}"

    # Explicitly set LDAP properties at runtime so settings that include underscores
    # (for example omero.ldap.new_user_group) are never lost due to env-name
    # translation ambiguities in upstream entrypoints.
    run_omero config set omero.ldap.config true
    run_omero config set omero.ldap.urls "${CONFIG_omero_ldap_urls}"
    run_omero config set omero.ldap.username "${CONFIG_omero_ldap_username}"
    run_omero config set omero.ldap.password "${CONFIG_omero_ldap_password}"
    run_omero config set omero.ldap.base "${CONFIG_omero_ldap_base}"
    if [[ -n "${CONFIG_omero_ldap_user__filter+x}" ]]; then
        run_omero config set omero.ldap.user_filter "${ldap_user_filter}"
    else
        log "LDAP user filter not declared; leaving omero.ldap.user_filter unchanged"
    fi

    if [[ -n "${ldap_new_user_group}" ]]; then
        run_omero config set omero.ldap.new_user_group "${ldap_new_user_group}"
        local configured_group=""
        configured_group="$(run_omero config get omero.ldap.new_user_group 2>/dev/null || true)"
        if [[ "${configured_group}" != "${ldap_new_user_group}" ]]; then
            echo "ERROR: Failed to persist LDAP new-user group. Expected '${ldap_new_user_group}', got '${configured_group}'." >&2
            exit 1
        fi
    fi

    log "Applied LDAP runtime configuration from environment"
}
check_writable_dir() {
    local path="$1"
    local label="$2"

    if [[ ! -d "${path}" ]]; then
        echo "ERROR: ${label} directory missing: ${path}" >&2
        exit 1
    fi

    if touch "${path}/.permission_test" 2>/dev/null; then
        rm -f "${path}/.permission_test"
        log "${label} writable: ${path}"
        return
    fi

    if chown -R "$(id -u):$(id -g)" "${path}" 2>/dev/null; then
        chmod -R u+rwX "${path}" 2>/dev/null || true
    fi

    if ! touch "${path}/.permission_test" 2>/dev/null; then
        echo "ERROR: ${label} is not writable: ${path}" >&2
        exit 1
    fi

    rm -f "${path}/.permission_test"
    log "${label} writable after ownership fix: ${path}"
}

reset_runtime_if_requested() {
    if [[ "${RESET_OMERO_RUNTIME:-0}" != "1" ]]; then
        return
    fi

    local grid_dir="${SERVER_HOME}/var/master"
    if [[ -d "${grid_dir}" ]]; then
        rm -rf "${grid_dir}"
        log "Removed IceGrid runtime directory: ${grid_dir}"
    fi
}

configure_script_python() {
    local venv_py
    venv_py="$(find /opt/omero/server -maxdepth 1 -type d -name 'venv*' | sort -V | tail -n 1)/bin/python"
    if [[ ! -x "${venv_py}" ]]; then
        echo "ERROR: OMERO venv python not found at ${venv_py}" >&2
        exit 1
    fi

    run_omero config set omero.scripts.python "${venv_py}"
    log "Configured omero.scripts.python=${venv_py}"
}

ensure_certificate_sans() {
    local cert_pem="${CERTS_DIR}/server.pem"
    local san_value="DNS:localhost,DNS:omeroserver"

    mkdir -p "${CERTS_DIR}"
    if [[ "$(id -u)" -eq 0 ]]; then
        chown "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${CERTS_DIR}"
    fi
    chmod 0750 "${CERTS_DIR}"

    if [[ ! -f "${cert_pem}" ]] || ! openssl x509 -in "${cert_pem}" -noout -text | grep -q "DNS:omeroserver"; then
        run_omero config set omero.certificates.commonname localhost
        run_omero config set omero.certificates.subjectAltName "${san_value}"
        rm -f "${CERTS_DIR}/server."* || true
        run_omero certificates
        log "Regenerated server certificate with SANs: ${san_value}"
    else
        log "Existing certificate already includes DNS:omeroserver"
    fi
}

schedule_job_service_bootstrap() {
    local root_pass="${ROOTPASS:-}"
    local job_user="${OMERO_JOB_SERVICE_USERNAME:-job-service}"
    local job_pass="${OMERO_JOB_SERVICE_PASS:-}"

    if [[ -z "${root_pass}" || -z "${job_pass}" ]]; then
        log "Skipping job-service bootstrap (ROOTPASS or OMERO_JOB_SERVICE_PASS missing)."
        return
    fi

    (
        set -euo pipefail
        sleep 5
        for _ in $(seq 1 180); do
            if run_omero -s localhost -p 4064 -u root -w "${root_pass}" user list >/dev/null 2>&1; then
                break
            fi
            sleep 2
        done

        if ! run_omero -s localhost -p 4064 -u root -w "${root_pass}" user info --user-name "${job_user}" >/dev/null 2>&1; then
            run_omero -s localhost -p 4064 -u root -w "${root_pass}" \
                user add "${job_user}" Job Service --group-name user -P "${job_pass}"
        fi
    ) >>"${SERVER_LOG_DIR}/job-service-bootstrap.log" 2>&1 &

    log "Scheduled background job-service bootstrap"
}

schedule_ldap_group_bootstrap() {
    if [[ "${CONFIG_omero_ldap_config:-false}" != "true" ]]; then
        return
    fi

    local ldap_group_setting="${CONFIG_omero_ldap_new__user__group:-}"
    if [[ -z "${ldap_group_setting}" || "${ldap_group_setting}" == :* ]]; then
        return
    fi

    if [[ "${ldap_group_setting}" == "default" ]]; then
        log "LDAP new-user group is set to built-in default; explicit group bootstrap is skipped"
        return
    fi

    local root_pass="${ROOTPASS:-}"
    if [[ -z "${root_pass}" ]]; then
        echo "ERROR: LDAP group bootstrap requires ROOTPASS when CONFIG_omero_ldap_new__user__group is a static non-default group name." >&2
        exit 1
    fi

    (
        set -euo pipefail
        local add_output=""
        local add_exit_code=1
        local retry_limit="${OMERO_LDAP_GROUP_BOOTSTRAP_RETRIES:-180}"
        local retry_delay_seconds="${OMERO_LDAP_GROUP_BOOTSTRAP_RETRY_DELAY_SECONDS:-2}"
        local attempt=1

        for attempt in $(seq 1 "${retry_limit}"); do
            if run_omero admin status -s localhost -p 4064 -u root -w "${root_pass}" --wait >/dev/null 2>&1; then
                break
            fi
            sleep "${retry_delay_seconds}"
        done

        for attempt in $(seq 1 "${retry_limit}"); do
            set +e
            add_output="$(run_omero -s localhost -p 4064 -u root -w "${root_pass}" group add "${ldap_group_setting}" --type=private 2>&1)"
            add_exit_code=$?
            set -e

            if [[ "${add_exit_code}" -eq 0 ]] || printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|exists"; then
                break
            fi

            sleep "${retry_delay_seconds}"
        done

        if [[ "${add_exit_code}" -eq 0 ]]; then
            log "Ensured LDAP new-user target group exists: ${ldap_group_setting}"
            exit 0
        fi

        if printf '%s' "${add_output}" | grep -qiE "already exists|duplicate|exists"; then
            log "LDAP new-user target group already exists: ${ldap_group_setting}"
            exit 0
        fi

        echo "ERROR: Failed ensuring LDAP new-user target group '${ldap_group_setting}'." >&2
        echo "ERROR: omero output: ${add_output}" >&2
        exit 1
    ) >>"${SERVER_LOG_DIR}/ldap-group-bootstrap.log" 2>&1 &

    log "Scheduled background LDAP group bootstrap for static group '${ldap_group_setting}'"
}


install_figure_script() {
    # Ensure OMERO.Figure PDF export script exists under OMERO.server scripts tree so it can be uploaded.
    # The script is NOT part of the official OMERO scripts bundle.
    local figure_version="${OMERO_FIGURE_VERSION:-}"
    if [[ -z "${figure_version}" ]]; then
        # Default chosen to match env/omeroserver.env, but keep this robust if unset.
        figure_version="7.3.0"
    fi

    local script_dir="${SERVER_HOME}/lib/scripts/omero/figure_scripts"
    local script_path="${script_dir}/Figure_To_Pdf.py"
    local tmp_dir="/tmp/omero-figure-${figure_version}"

    mkdir -p "${script_dir}"

    # If script exists, keep it if version matches.
    if [[ -f "${script_path}" ]]; then
        local current_version="unknown"
        current_version="$(grep -Eo "__version__\s*=\s*'[^']+'" "${script_path}" 2>/dev/null | head -n 1 | sed -E "s/.*'([^']+)'.*/\1/" || true)"
        if [[ "${current_version}" == "${figure_version}" ]]; then
            log "OMERO.Figure script already present (version ${current_version})"
            return
        fi
        log "OMERO.Figure script version mismatch (${current_version} != ${figure_version}); reinstalling"
        rm -f "${script_path}"
    fi

    rm -rf "${tmp_dir}"
    mkdir -p "${tmp_dir}"

    log "Installing OMERO.Figure Figure_To_Pdf.py (version ${figure_version})"
    # Use git if available (installed in Dockerfile). Fall back to tarball if needed.
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch "v${figure_version}" https://github.com/ome/omero-figure.git "${tmp_dir}/repo" >/dev/null 2>&1 \
            || git clone --depth 1 --branch "${figure_version}" https://github.com/ome/omero-figure.git "${tmp_dir}/repo" >/dev/null 2>&1 \
            || true
    fi

    if [[ -f "${tmp_dir}/repo/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" ]]; then
        cp "${tmp_dir}/repo/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" "${script_path}"
    else
        # Tarball fallback (works even if git clone is blocked)
        local url="https://github.com/ome/omero-figure/archive/refs/tags/v${figure_version}.tar.gz"
        curl -fsSL "${url}" -o "${tmp_dir}/figure.tar.gz"
        tar -xzf "${tmp_dir}/figure.tar.gz" -C "${tmp_dir}"
        local extracted
        extracted="$(find "${tmp_dir}" -maxdepth 1 -type d -name "omero-figure-*${figure_version}*" | head -n 1 || true)"
        if [[ -z "${extracted}" || ! -f "${extracted}/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" ]]; then
            echo "ERROR: Failed to obtain Figure_To_Pdf.py for OMERO.Figure ${figure_version}" >&2
            exit 1
        fi
        cp "${extracted}/omero_figure/scripts/omero/figure_scripts/Figure_To_Pdf.py" "${script_path}"
    fi

    rm -rf "${tmp_dir}"

    # Ensure ownership/permissions suitable for script upload
    if [[ "$(id -u)" -eq 0 ]]; then
        chown -R "$(id -u "${OMERO_CLI_USER}")":"$(id -g "${OMERO_CLI_USER}")" "${SERVER_HOME}/lib/scripts" 2>/dev/null || true
    fi
    chmod -R a+rX "${SERVER_HOME}/lib/scripts" 2>/dev/null || true

    log "Installed OMERO.Figure script at ${script_path}"
}

schedule_script_registration() {
    if [[ "${REGISTER_OFFICIAL_SCRIPTS:-0}" != "1" ]]; then
        return
    fi

    local root_pass="${ROOTPASS:-}"
    if [[ -z "${root_pass}" ]]; then
        echo "ERROR: REGISTER_OFFICIAL_SCRIPTS=1 requires ROOTPASS" >&2
        exit 1
    fi

    (
        set -euo pipefail
        local scripts_dir="${SERVER_HOME}/lib/scripts/omero"

        until run_omero admin status -s localhost -p 4064 -u root -w "${root_pass}" --wait >/dev/null 2>&1; do
            sleep 2
        done

        until run_omero script list -s localhost -p 4064 -u root -w "${root_pass}" --sudo root >/dev/null 2>&1; do
            sleep 2
        done

        while IFS= read -r script; do
            run_omero script upload --official --sudo root \
                -s localhost -p 4064 -u root -w "${root_pass}" "${script}" >/dev/null 2>&1 || true
        done < <(find "${scripts_dir}" -type f -name '*.py' | sort)
    ) >>"${SERVER_LOG_DIR}/register-official-scripts.log" 2>&1 &

    log "Scheduled background official script registration"
}

main() {
    log "Starting consolidated startup flow"

    mkdir -p "${CERTS_DIR}" "${SERVER_LOG_DIR}"

    check_writable_dir "${OMERO_DIR}" "OMERO data"
    check_writable_dir "${CERTS_DIR}" "OMERO certificates"
    check_writable_dir "${SERVER_VAR_DIR}" "OMERO var"
    check_writable_dir "${SERVER_LOG_DIR}" "OMERO logs"

    validate_ldap_configuration
    validate_ldap_new_user_group_configuration
    apply_ldap_runtime_configuration
    reset_runtime_if_requested
    configure_script_python
    ensure_certificate_sans
    install_figure_script
    schedule_script_registration
    schedule_job_service_bootstrap
    schedule_ldap_group_bootstrap

    log "Startup flow finished"
}

main "$@"
