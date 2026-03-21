#!/usr/bin/env bash
################################################################################
# OMERO.web Bootstrap Script
################################################################################
#
# PURPOSE:
#   Ensures OMERO.web log directory is writable before OMERO.web starts.
#   This prevents zarr/numcodecs logging failures during Python module imports.
#
# CRITICAL CHANGE:
#   CONFIG_omero_web_logdir now points directly to the mounted volume:
#   /opt/omero/web/OMERO.web/var/log (not /tmp/omero-web-logs)
#   
#   This matches the volume mount in docker-compose.yml and ensures logs
#   persist on the host filesystem.
#
# WHAT IT DOES:
#   1. Verifies log directory (from CONFIG_omero_web_logdir) is writable
#   2. If directory is a mountpoint, confirms it's accessible
#   3. If directory doesn't exist, creates it
#   4. Exits with error if log directory cannot be made writable
#
# WHY THIS IS CRITICAL:
#   - zarr library logs during import (before OMERO.web is fully initialized)
#   - If log directory isn't writable, concurrent_log_handler fails
#   - This causes OMERO.web startup to crash with emit(record) errors
#
# DEPENDENCIES:
#   - omero-data-init must run first to set host directory permissions
#   - Volume must be mounted at CONFIG_omero_web_logdir path
#
################################################################################
set -euo pipefail

log_dir="${CONFIG_omero_web_logdir:-/opt/omero/web/OMERO.web/var/log}"

echo "[web-bootstrap] Checking OMERO.web log directory: ${log_dir}"


configure_docker_socket_access() {
    local docker_socket="${ADMIN_TOOLS_DOCKER_SOCKET:-/var/run/docker.sock}"
    local target_user="${OMERO_WEB_RUNTIME_USER:-omero-web}"

    if [[ ! -S "${docker_socket}" ]]; then
        echo "[web-bootstrap] Docker socket not present at ${docker_socket}; skipping socket group bootstrap"
        return
    fi

    if [[ "$(id -u)" -ne 0 ]]; then
        echo "[web-bootstrap] Running unprivileged; cannot adjust docker socket group membership"
        return
    fi

    local socket_gid
    socket_gid="$(stat -c '%g' "${docker_socket}")"
    if [[ -z "${socket_gid}" ]]; then
        echo "[web-bootstrap] ERROR: Failed to resolve docker socket gid from ${docker_socket}" >&2
        exit 1
    fi

    local socket_group
    socket_group="$(getent group "${socket_gid}" | cut -d: -f1 || true)"
    if [[ -z "${socket_group}" ]]; then
        socket_group="docker-host"
        if getent group "${socket_group}" >/dev/null 2>&1; then
            socket_group="docker-host-${socket_gid}"
        fi
        groupadd -g "${socket_gid}" "${socket_group}"
        echo "[web-bootstrap] Created group ${socket_group} with gid ${socket_gid} for docker socket access"
    fi

    if ! id -nG "${target_user}" | tr ' ' '\012' | grep -qx "${socket_group}"; then
        usermod -aG "${socket_group}" "${target_user}"
        echo "[web-bootstrap] Added ${target_user} to group ${socket_group} (gid ${socket_gid})"
    else
        echo "[web-bootstrap] ${target_user} already in docker socket group ${socket_group}"
    fi
}

ensure_web_var_layout() {
    local var_dir="${OMERO_WEB_VAR_DIR:-/opt/omero/web/OMERO.web/var}"
    local runtime_user="${OMERO_WEB_RUNTIME_USER:-omero-web}"
    local run_dir="${var_dir}/run"

    echo "[web-bootstrap] Checking OMERO.web var directory: ${var_dir}"
    mkdir -p "${var_dir}" "${var_dir}/omero/tmp" "${var_dir}/static" "${run_dir}"

    if id -u "${runtime_user}" >/dev/null 2>&1; then
        chown -R "${runtime_user}:${runtime_user}" "${var_dir}" || true
    else
        echo "[web-bootstrap] WARNING: Runtime user ${runtime_user} does not exist; skipping chown for ${var_dir}" >&2
    fi

    chmod 0755 "${var_dir}" "${var_dir}/omero" "${run_dir}" || true
    chmod 1777 "${var_dir}/omero/tmp" || true

    if [[ ! -w "${var_dir}" ]]; then
        echo "[web-bootstrap] ERROR: OMERO.web var directory is not writable: ${var_dir}" >&2
        ls -ld "${var_dir}" >&2 || true
        exit 1
    fi

    if [[ ! -w "${var_dir}/omero" ]]; then
        echo "[web-bootstrap] ERROR: OMERO.web runtime directory is not writable: ${var_dir}/omero" >&2
        ls -ld "${var_dir}/omero" >&2 || true
        exit 1
    fi

    if [[ ! -w "${var_dir}/omero/tmp" ]]; then
        echo "[web-bootstrap] ERROR: OMERO.web tmp directory is not writable: ${var_dir}/omero/tmp" >&2
        ls -ld "${var_dir}/omero/tmp" >&2 || true
        exit 1
    fi

    if [[ ! -w "${run_dir}" ]]; then
        echo "[web-bootstrap] ERROR: OMERO.web runtime directory is not writable: ${run_dir}" >&2
        ls -ld "${run_dir}" >&2 || true
        exit 1
    fi

    if [[ ! -f "${var_dir}/django_secret_key" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            umask 077
            openssl rand -base64 64 > "${var_dir}/django_secret_key"
        else
            echo "[web-bootstrap] ERROR: Missing ${var_dir}/django_secret_key and openssl is unavailable to generate one" >&2
            exit 1
        fi
        if id -u "${runtime_user}" >/dev/null 2>&1; then
            chown "${runtime_user}:${runtime_user}" "${var_dir}/django_secret_key" || true
        fi
        chmod 0600 "${var_dir}/django_secret_key" || true
        echo "[web-bootstrap] Generated ${var_dir}/django_secret_key"
    fi
}

ensure_web_var_layout

# Create log directory if it doesn't exist
mkdir -p "${log_dir}"

# Verify directory is writable
if [[ ! -d "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: Log directory does not exist and could not be created: ${log_dir}" >&2
    exit 1
fi

if [[ ! -w "${log_dir}" ]]; then
    echo "[web-bootstrap] ERROR: Log directory is not writable: ${log_dir}" >&2
    echo "[web-bootstrap] This will cause zarr import to fail during OMERO.web startup" >&2
    echo "[web-bootstrap] Ensure omero-data-init has set correct permissions (UID:GID 1000:1000)" >&2
    ls -ld "${log_dir}" >&2 || true
    exit 1
fi

# Test write access
if ! touch "${log_dir}/.permission_test" 2>/dev/null; then
    echo "[web-bootstrap] ERROR: Cannot write to log directory: ${log_dir}" >&2
    ls -ld "${log_dir}" >&2 || true
    exit 1
fi

rm -f "${log_dir}/.permission_test"

if mountpoint -q "${log_dir}"; then
    echo "[web-bootstrap] Log directory is a mounted filesystem: ${log_dir}"
else
    echo "[web-bootstrap] Log directory is local (not mounted): ${log_dir}"
fi

echo "[web-bootstrap] ✓ OMERO.web log directory is ready and writable: ${log_dir}"

# ── Ensure .admin-tools directory is writable for quota state persistence ──
omero_data_dir="${OMERO_DATA_DIR:-/OMERO}"
admin_tools_dir="${omero_data_dir}/.admin-tools"
quota_state_path="${ADMIN_TOOLS_QUOTA_STATE_PATH:-${admin_tools_dir}/group-quotas.json}"
quota_projects_file="${ADMIN_TOOLS_QUOTA_PROJECTS_FILE:-${admin_tools_dir}/quota/projects}"
quota_projid_file="${ADMIN_TOOLS_QUOTA_PROJID_FILE:-${admin_tools_dir}/quota/projid}"
quota_marker_path="${ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH:-${admin_tools_dir}/quota-enforcer-installed}"
quota_runtime_user="${OMERO_WEB_RUN_USER:-omero-web}"
quota_runtime_group="${OMERO_WEB_RUN_GROUP:-omero-web}"

normalize_quota_path() {
    local target_path="$1"
    local target_dir
    target_dir="$(dirname "${target_path}")"

    mkdir -p "${target_dir}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not create quota metadata directory ${target_dir}" >&2

    if [[ -d "${target_dir}" && ! -w "${target_dir}" ]]; then
        echo "[web-bootstrap] WARNING: ${target_dir} is not writable; attempting chmod 0777"
        chmod 0777 "${target_dir}" 2>/dev/null || \
            echo "[web-bootstrap] WARNING: Could not fix permissions on ${target_dir}. Quota state persistence may fail." >&2
    fi

    if [[ ! -e "${target_path}" ]]; then
        return 0
    fi

    if id "${quota_runtime_user}" >/dev/null 2>&1; then
        chown "${quota_runtime_user}:${quota_runtime_group}" "${target_path}" 2>/dev/null || \
            echo "[web-bootstrap] WARNING: Could not chown quota metadata file ${target_path} to ${quota_runtime_user}:${quota_runtime_group}" >&2
    fi

    if [[ ! -r "${target_path}" || ! -w "${target_path}" ]]; then
        chmod 0664 "${target_path}" 2>/dev/null || \
            chmod 0666 "${target_path}" 2>/dev/null || \
            echo "[web-bootstrap] WARNING: Could not fix permissions on quota metadata file ${target_path}" >&2
    fi
}

normalize_quota_path "${quota_state_path}"
normalize_quota_path "${quota_projects_file}"
normalize_quota_path "${quota_projid_file}"
normalize_quota_path "${quota_marker_path}"

configure_docker_socket_access

repair_branding_logo_permissions() {
    local logo_path="${1:?BUG: repair_branding_logo_permissions requires a logo path}"
    local runtime_user="${2:-omero-web}"
    local runtime_group="${3:-${runtime_user}}"
    local branding_dir

    if [[ ! -f "${logo_path}" ]]; then
        return 1
    fi

    branding_dir="$(dirname "${logo_path}")"
    chmod 0755 "${branding_dir}" 2>/dev/null || true

    if id -u "${runtime_user}" >/dev/null 2>&1; then
        chown "${runtime_user}:${runtime_group}" "${logo_path}" 2>/dev/null || true
    fi

    if [[ ! -r "${logo_path}" ]]; then
        echo "[web-bootstrap] WARNING: Branding logo exists but is not readable; repairing permissions: ${logo_path}" >&2
    fi

    chmod 0444 "${logo_path}" 2>/dev/null || chmod a+r "${logo_path}" 2>/dev/null || true
    return 0
}

branding_logo_uses_generated_fallback() {
    local logo_path="${1:?BUG: branding_logo_uses_generated_fallback requires a logo path}"
    local marker_path="${2:?BUG: branding_logo_uses_generated_fallback requires a marker path}"
    local fallback_writer_path="/opt/omero/tools/write_branding_logo_fallback.py"
    local generated_fallback_path=""

    if [[ ! -f "${marker_path}" || ! -f "${logo_path}" || ! -f "${fallback_writer_path}" ]]; then
        return 1
    fi

    generated_fallback_path="$(mktemp "${TMPDIR:-/tmp}/omero-web-branding-logo-fallback.XXXXXX.png")"
    if python3 "${fallback_writer_path}" "${generated_fallback_path}" && cmp -s "${generated_fallback_path}" "${logo_path}"; then
        rm -f "${generated_fallback_path}" || true
        return 0
    fi

    rm -f "${generated_fallback_path}" || true
    echo "[web-bootstrap] WARNING: Branding fallback marker is stale; preserving non-generated logo at ${logo_path}" >&2
    rm -f "${marker_path}" || true
    return 1
}

branding_logo_fallback_enabled() {
    local configured_login_logo="${CONFIG_omero_web_login__logo:-}"
    [[ "${configured_login_logo}" == "/static/branding/logo.png" ]]
}

install_branding_logo_fallback() {
    local logo_path="${1:?BUG: install_branding_logo_fallback requires a logo path}"
    local marker_path="${2:?BUG: install_branding_logo_fallback requires a marker path}"
    local runtime_user="${3:-omero-web}"
    local runtime_group="${4:-${runtime_user}}"
    local fallback_writer_path="/opt/omero/tools/write_branding_logo_fallback.py"

    mkdir -p "$(dirname "${logo_path}")"

    if [[ ! -f "${fallback_writer_path}" ]]; then
        echo "[web-bootstrap] WARNING: Branding fallback writer missing: ${fallback_writer_path}" >&2
        return 1
    fi

    if ! python3 "${fallback_writer_path}" "${logo_path}"; then
        echo "[web-bootstrap] WARNING: Failed to generate branding fallback icon: ${logo_path}" >&2
        return 1
    fi

    printf '%s\n' "generated-fallback" > "${marker_path}"
    repair_branding_logo_permissions "${logo_path}" "${runtime_user}" "${runtime_group}" || true

    if id -u "${runtime_user}" >/dev/null 2>&1; then
        chown "${runtime_user}:${runtime_group}" "${marker_path}" 2>/dev/null || true
    fi
    chmod 0644 "${marker_path}" 2>/dev/null || true

    echo "[web-bootstrap] Installed generated branding fallback icon: ${logo_path}"
    return 0
}

sync_static_assets() {
    local var_dir="${OMERO_WEB_VAR_DIR:-/opt/omero/web/OMERO.web/var}"
    local static_dir="${var_dir}/static"
    local static_backup_dir="/opt/omero/web/static_backup"
    local runtime_user="${OMERO_WEB_RUNTIME_USER:-omero-web}"
    local runtime_group="${OMERO_WEB_RUNTIME_GROUP:-${runtime_user}}"
    local branding_logo_path="${static_dir}/branding/logo.png"
    local branding_fallback_marker_path="${static_dir}/branding/.generated-logo-fallback"
    local repo_logo_path="/opt/omero/logo/logo.png"
    local preserved_logo_path=""

    if [[ ! -d "${static_backup_dir}" ]]; then
        echo "[web-bootstrap] ERROR: Static backup directory missing: ${static_backup_dir}" >&2
        exit 1
    fi

    # A generated fallback should never block a newly provided repository logo
    # or a manually replaced site-local logo on later restarts.
    if branding_logo_uses_generated_fallback "${branding_logo_path}" "${branding_fallback_marker_path}"; then
        rm -f "${branding_logo_path}" "${branding_fallback_marker_path}" || true
    fi

    if [[ -f "${branding_logo_path}" ]]; then
        preserved_logo_path="$(mktemp "${TMPDIR:-/tmp}/omero-web-branding-logo.XXXXXX")"
        if cp -p "${branding_logo_path}" "${preserved_logo_path}"; then
            echo "[web-bootstrap] Preserving existing branding logo across static sync: ${branding_logo_path}"
        else
            echo "[web-bootstrap] WARNING: Failed to preserve existing branding logo before static sync: ${branding_logo_path}" >&2
            rm -f "${preserved_logo_path}" || true
            preserved_logo_path=""
        fi
    fi

    echo "[web-bootstrap] Synchronizing OMERO.web static assets into ${static_dir}"
    mkdir -p "${static_dir}"
    cp -a "${static_backup_dir}/." "${static_dir}/"

    if id -u "${runtime_user}" >/dev/null 2>&1; then
        chown -R "${runtime_user}:${runtime_group}" "${static_dir}" || true
    fi

    if ! branding_logo_fallback_enabled; then
        return 0
    fi

    if [[ -n "${preserved_logo_path}" && -f "${preserved_logo_path}" ]]; then
        mkdir -p "${static_dir}/branding"
        if cp -f "${preserved_logo_path}" "${branding_logo_path}"; then
            echo "[web-bootstrap] Restored pre-existing branding logo after static sync: ${branding_logo_path}"
            rm -f "${branding_fallback_marker_path}" || true
        else
            echo "[web-bootstrap] WARNING: Failed to restore preserved branding logo after static sync: ${branding_logo_path}" >&2
        fi
        rm -f "${preserved_logo_path}" || true
    fi

    if [[ ! -f "${branding_logo_path}" && -f "${repo_logo_path}" ]]; then
        mkdir -p "${static_dir}/branding"
        if cp -f "${repo_logo_path}" "${branding_logo_path}"; then
            echo "[web-bootstrap] Restored branding logo from repository logo path: ${repo_logo_path}"
            rm -f "${branding_fallback_marker_path}" || true
        else
            echo "[web-bootstrap] WARNING: Failed to restore branding logo from repository logo path: ${repo_logo_path}" >&2
        fi
    fi

    if [[ -f "${branding_logo_path}" ]]; then
        rm -f "${branding_fallback_marker_path}" || true
        repair_branding_logo_permissions "${branding_logo_path}" "${runtime_user}" "${runtime_group}" || true
    else
        echo "[web-bootstrap] WARNING: Branding logo missing after static sync: ${branding_logo_path}. Installing generated fallback icon." >&2
        install_branding_logo_fallback "${branding_logo_path}" "${branding_fallback_marker_path}" "${runtime_user}" "${runtime_group}" || true
    fi

    if [[ ! -f "${static_dir}/omero_web_zarr/openwith.js" ]]; then
        echo "[web-bootstrap] ERROR: Vizarr static asset missing after static sync: ${static_dir}/omero_web_zarr/openwith.js" >&2
        exit 1
    fi
}

sync_static_assets

# ── Upgrade OMEZarrReader + JZarr in OMERO CLI JAR cache ──────────────────────
# The OMERO CLI downloads OMERO.java JARs into the bind-mounted var/ directory
# on first use.  The bundled OMEZarrReader and JZarr are outdated; replace them
# with the versions staged by the Dockerfile at /opt/omero/web/zarr-jar-upgrade/.
upgrade_zarr_jars() {
    local staged_dir="/opt/omero/web/zarr-jar-upgrade"
    local var_dir="${OMERO_WEB_VAR_DIR:-/opt/omero/web/OMERO.web/var}"
    local runtime_user="${OMERO_WEB_RUNTIME_USER:-omero-web}"

    if [[ ! -d "${staged_dir}" ]]; then
        return 0
    fi

    local jar_cache
    jar_cache="$(find "${var_dir}/.cache" -maxdepth 7 -type d -name "libs" -path "*/OMERO.java-*/libs" 2>/dev/null | head -n 1)"

    if [[ -z "${jar_cache}" || ! -d "${jar_cache}" ]]; then
        echo "[web-bootstrap] OMERO CLI JAR cache not yet created; zarr JAR upgrade will apply on next container restart"
        return 0
    fi

    local updated=0
    for jar_name in OMEZarrReader.jar jzarr.jar; do
        local staged="${staged_dir}/${jar_name}"
        local target="${jar_cache}/${jar_name}"
        if [[ ! -f "${staged}" ]]; then
            continue
        fi
        if [[ -f "${target}" ]] && cmp -s "${staged}" "${target}"; then
            continue
        fi
        cp -f "${staged}" "${target}"
        if id -u "${runtime_user}" >/dev/null 2>&1; then
            chown "${runtime_user}:${runtime_user}" "${target}" 2>/dev/null || true
        fi
        echo "[web-bootstrap] Upgraded ${jar_name} in OMERO CLI JAR cache"
        updated=$((updated + 1))
    done

    if [[ "${updated}" -gt 0 ]]; then
        echo "[web-bootstrap] ✓ Zarr JAR upgrade complete (${updated} file(s) updated)"
    fi
}

upgrade_zarr_jars

# ── Ensure OME-Zarr permanent storage directory exists ─────────────────────────
omero_zarr_store="${OMERO_ZARR_STORE_ROOT:-/OMERO/OME-Zarr}"
if [[ ! -d "${omero_zarr_store}" ]]; then
    mkdir -p "${omero_zarr_store}"
    echo "[web-bootstrap] Created OME-Zarr store: ${omero_zarr_store}"
fi
chmod 1777 "${omero_zarr_store}" 2>/dev/null || true
