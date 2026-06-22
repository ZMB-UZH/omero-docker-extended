#!/usr/bin/env bash
# shellcheck shell=bash
################################################################################
# OMERO.web Bootstrap Script
################################################################################
#
# Prepares the mounted OMERO.web runtime tree before the container drops from
# root to the application user. This includes:
#   - validating the OMERO.web var/ layout,
#   - repairing the runtime-user write path for OMERO.web and supervisord logs,
#   - synchronizing static assets,
#   - installing a generated login-logo fallback when explicitly enabled.
#
# The runtime-user checks matter because startup runs as root, but supervisord
# and the OMERO.web process run as the non-root application user afterward. A
# bind mount that is only writable by root can therefore pass a naive check and
# still crash the service immediately.
#
################################################################################
set -euo pipefail

runtime_user="${OMERO_WEB_RUNTIME_USER:-${OMERO_WEB_RUN_USER:-omero-web}}"
runtime_group="${OMERO_WEB_RUNTIME_GROUP:-${OMERO_WEB_RUN_GROUP:-${runtime_user}}}"
log_dir="${CONFIG_omero_web_logdir:-/opt/omero/web/OMERO.web/var/log}"
supervisord_config_path="${OMERO_WEB_SUPERVISORD_CONFIG:-/etc/supervisord.conf}"

declare -A prepared_runtime_directories=()
declare -A prepared_runtime_files=()

echo "[web-bootstrap] Checking OMERO.web log directory: ${log_dir}"

# Perform runtime user exists. Inputs: shell arguments and environment. Output: command status and side effects.
runtime_user_exists() {
    id -u "${runtime_user}" >/dev/null 2>&1
}

# Ensure runtime identity. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_runtime_identity() {
    if ! runtime_user_exists; then
        echo "[web-bootstrap] ERROR: Runtime user does not exist: ${runtime_user}" >&2
        exit 1
    fi

    if ! getent group "${runtime_group}" >/dev/null 2>&1; then
        echo "[web-bootstrap] WARNING: Runtime group does not exist: ${runtime_group}; falling back to $(id -gn "${runtime_user}")" >&2
        runtime_group="$(id -gn "${runtime_user}")"
    fi
}

# Trim whitespace. Inputs: shell arguments and environment. Output: command status and side effects.
trim_whitespace() {
    local value="${1:-}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "${value}"
}

# Log mount status. Inputs: shell arguments and environment. Output: command status and side effects.
log_mount_status() {
    local path="${1:?BUG: log_mount_status requires a path}"
    local label="${2:?BUG: log_mount_status requires a label}"

    if mountpoint -q "${path}"; then
        echo "[web-bootstrap] ${label} is a mounted filesystem: ${path}"
    else
        echo "[web-bootstrap] ${label} is local (not mounted): ${path}"
    fi
}

# Ensure runtime directory. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_runtime_directory() {
    local path="${1:?BUG: ensure_runtime_directory requires a path}"
    local label="${2:?BUG: ensure_runtime_directory requires a label}"
    local mode="${3:-0755}"
    local probe_path=""

    if [[ -n "${prepared_runtime_directories[${path}]:-}" ]]; then
        return 0
    fi
    prepared_runtime_directories["${path}"]=1

    mkdir -p "${path}"

    if runtime_user_exists; then
        chown -R "${runtime_user}:${runtime_group}" "${path}" 2>/dev/null || true
    fi
    chmod "${mode}" "${path}" 2>/dev/null || true

    if [[ ! -d "${path}" ]]; then
        echo "[web-bootstrap] ERROR: ${label} does not exist and could not be created: ${path}" >&2
        exit 1
    fi

    if runtime_user_exists; then
        probe_path="${path}/.runtime-write-test.$$"
        if ! runuser -u "${runtime_user}" -- touch "${probe_path}" 2>/dev/null; then
            echo "[web-bootstrap] ERROR: ${label} is not writable for ${runtime_user}: ${path}" >&2
            ls -ld "${path}" >&2 || true
            exit 1
        fi
        rm -f "${probe_path}" || true
    elif [[ ! -w "${path}" ]]; then
        echo "[web-bootstrap] ERROR: ${label} is not writable: ${path}" >&2
        ls -ld "${path}" >&2 || true
        exit 1
    fi

    log_mount_status "${path}" "${label}"
    echo "[web-bootstrap] ✓ ${label} is ready and writable for ${runtime_user}: ${path}"
}

# Ensure runtime file. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_runtime_file() {
    local path="${1:?BUG: ensure_runtime_file requires a path}"
    local label="${2:?BUG: ensure_runtime_file requires a label}"
    local mode="${3:-0664}"

    if [[ -n "${prepared_runtime_files[${path}]:-}" ]]; then
        return 0
    fi
    prepared_runtime_files["${path}"]=1

    ensure_runtime_directory "$(dirname "${path}")" "${label} parent directory" 0755
    if [[ ! -e "${path}" ]]; then
        : > "${path}"
    fi

    if runtime_user_exists; then
        chown "${runtime_user}:${runtime_group}" "${path}" 2>/dev/null || true
    fi
    chmod "${mode}" "${path}" 2>/dev/null || true

    if [[ ! -f "${path}" ]]; then
        echo "[web-bootstrap] ERROR: ${label} does not exist and could not be created: ${path}" >&2
        exit 1
    fi

    if runtime_user_exists; then
        if ! runuser -u "${runtime_user}" -- test -w "${path}" 2>/dev/null; then
            echo "[web-bootstrap] ERROR: ${label} is not writable for ${runtime_user}: ${path}" >&2
            ls -l "${path}" >&2 || true
            exit 1
        fi
    elif [[ ! -w "${path}" ]]; then
        echo "[web-bootstrap] ERROR: ${label} is not writable: ${path}" >&2
        ls -l "${path}" >&2 || true
        exit 1
    fi
}

# Prepare supervisor logs from config. Inputs: shell arguments and environment. Output: command status and side effects.
prepare_supervisor_logs_from_config() {
    local config_path="${1:?BUG: prepare_supervisor_logs_from_config requires a config path}"
    local raw_line=""
    local line=""
    local key=""
    local log_path=""
    local label=""

    if [[ ! -f "${config_path}" ]]; then
        echo "[web-bootstrap] WARNING: supervisord config missing; skipping logfile preparation: ${config_path}" >&2
        return 0
    fi

    echo "[web-bootstrap] Checking supervisord log targets from ${config_path}"

    while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
        line="${raw_line%%#*}"
        line="$(trim_whitespace "${line}")"

        case "${line}" in
            logfile=*|stdout_logfile=*|stderr_logfile=*)
                key="${line%%=*}"
                log_path="$(trim_whitespace "${line#*=}")"
                [[ -n "${log_path}" ]] || continue

                case "${key}" in
                    logfile)
                        label="supervisord log file"
                        ;;
                    stdout_logfile)
                        label="supervisor-managed stdout log file"
                        ;;
                    stderr_logfile)
                        label="supervisor-managed stderr log file"
                        ;;
                esac

                ensure_runtime_file "${log_path}" "${label}" 0664
                ;;
        esac
    done < "${config_path}"
}

ensure_runtime_identity

# Repair plugin temporary layout. Inputs: shell arguments and environment. Output: command status and side effects.
repair_plugin_tmp_layout() {
    local tmp_root="${OMERO_TMP_PATH:-}"
    local server_runtime_user="${OMERO_SERVER_RUNTIME_USER:-omero-server}"
    local top_level_entry=""
    local entry_name=""
    local probe_path=""

    if [[ -z "${tmp_root}" ]]; then
        return 0
    fi

    mkdir -p "${tmp_root}"
    chown "${runtime_user}:${runtime_group}" "${tmp_root}" 2>/dev/null || true
    chmod 0755 "${tmp_root}" 2>/dev/null || true

    while IFS= read -r -d '' top_level_entry; do
        entry_name="$(basename "${top_level_entry}")"
        case "${entry_name}" in
            "${server_runtime_user}")
                continue
                ;;
            "${runtime_user}"|omeroweb-*)
                chown -R "${runtime_user}:${runtime_group}" "${top_level_entry}" 2>/dev/null || true
                chmod -R u+rwX "${top_level_entry}" 2>/dev/null || true
                if runtime_user_exists; then
                    probe_path="${top_level_entry}/.runtime-write-test.$$"
                    if ! runuser -u "${runtime_user}" -- touch "${probe_path}" 2>/dev/null; then
                        echo "[web-bootstrap] ERROR: Plugin temp subtree is not writable for ${runtime_user}: ${top_level_entry}" >&2
                        ls -ld "${top_level_entry}" >&2 || true
                        exit 1
                    fi
                    rm -f "${probe_path}" || true
                elif [[ ! -w "${top_level_entry}" ]]; then
                    echo "[web-bootstrap] ERROR: Plugin temp subtree is not writable: ${top_level_entry}" >&2
                    ls -ld "${top_level_entry}" >&2 || true
                    exit 1
                fi
                ;;
        esac
    done < <(find "${tmp_root}" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
}

# Configure docker socket access. Inputs: shell arguments and environment. Output: command status and side effects.
configure_docker_socket_access() {
    local docker_socket="${ADMIN_TOOLS_DOCKER_SOCKET:-/var/run/docker.sock}"
    local target_user="${runtime_user}"

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

# Ensure web variable layout. Inputs: shell arguments and environment. Output: command status and side effects.
ensure_web_var_layout() {
    local var_dir="${OMERO_WEB_VAR_DIR:-/opt/omero/web/OMERO.web/var}"
    local run_dir="${var_dir}/run"
    local static_dir="${var_dir}/static"

    echo "[web-bootstrap] Checking OMERO.web var directory: ${var_dir}"
    ensure_runtime_directory "${var_dir}" "OMERO.web var directory" 0755
    ensure_runtime_directory "${var_dir}/omero" "OMERO.web runtime directory" 0755
    ensure_runtime_directory "${var_dir}/omero/tmp" "OMERO.web tmp directory" 1777
    ensure_runtime_directory "${run_dir}" "OMERO.web runtime directory" 0755
    ensure_runtime_directory "${static_dir}" "OMERO.web static directory" 0755

    if [[ ! -f "${var_dir}/django_secret_key" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            umask 077
            openssl rand -base64 64 > "${var_dir}/django_secret_key"
        else
            echo "[web-bootstrap] ERROR: Missing ${var_dir}/django_secret_key and openssl is unavailable to generate one" >&2
            exit 1
        fi
        if runtime_user_exists; then
            chown "${runtime_user}:${runtime_group}" "${var_dir}/django_secret_key" || true
        fi
        chmod 0600 "${var_dir}/django_secret_key" || true
        echo "[web-bootstrap] Generated ${var_dir}/django_secret_key"
    else
        if runtime_user_exists; then
            chown "${runtime_user}:${runtime_group}" "${var_dir}/django_secret_key" 2>/dev/null || true
        fi
        chmod 0600 "${var_dir}/django_secret_key" 2>/dev/null || true
    fi

    if runtime_user_exists && ! runuser -u "${runtime_user}" -- test -r "${var_dir}/django_secret_key" 2>/dev/null; then
        echo "[web-bootstrap] ERROR: Django secret key is not readable for ${runtime_user}: ${var_dir}/django_secret_key" >&2
        ls -l "${var_dir}/django_secret_key" >&2 || true
        exit 1
    fi
}

ensure_web_var_layout

ensure_runtime_directory "${log_dir}" "OMERO.web log directory" 0755
prepare_supervisor_logs_from_config "${supervisord_config_path}"

# ── Ensure TMPDIR exists and is writable (Django file-based session storage) ──
# docker-compose.yml sets TMPDIR to a bind-mounted host path.  If this directory
# does not exist or is not owned by the runtime user, Django's file session
# backend silently fails to persist sessions and login breaks (the authenticated
# session evaporates on redirect).
if [[ -n "${TMPDIR:-}" && "${TMPDIR}" != "/tmp" ]]; then
    ensure_runtime_directory "${TMPDIR}" "OMERO.web TMPDIR (session storage)" 0700
fi
repair_plugin_tmp_layout

# ── Ensure .admin-tools directory is writable for quota state persistence ──
omero_data_dir="${OMERO_DATA_DIR:-}"
if [[ -z "${omero_data_dir}" ]]; then
    echo "[web-bootstrap] ERROR: OMERO_DATA_DIR is required for quota state paths." >&2
    exit 1
fi
admin_tools_dir="${omero_data_dir}/.admin-tools"
quota_state_path="${ADMIN_TOOLS_QUOTA_STATE_PATH:-${admin_tools_dir}/group-quotas.json}"
quota_projects_file="${ADMIN_TOOLS_QUOTA_PROJECTS_FILE:-${admin_tools_dir}/quota/projects}"
quota_projid_file="${ADMIN_TOOLS_QUOTA_PROJID_FILE:-${admin_tools_dir}/quota/projid}"
quota_marker_path="${ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH:-${admin_tools_dir}/quota-enforcer-installed}"
quota_runtime_user="${runtime_user}"
quota_runtime_group="${runtime_group}"
quota_runtime_gid="$(id -g "${quota_runtime_user}" 2>/dev/null || printf '%s' "${quota_runtime_group}")"

# Return whether a path is unsafe for quota metadata. Inputs: path. Output: status.
quota_path_is_symlink() {
    local target_path="$1"
    [[ -L "${target_path}" ]]
}

# Repair the quota metadata root. Inputs: none. Output: command status and side effects.
prepare_quota_metadata_root() {
    mkdir -p "${admin_tools_dir}/quota" 2>/dev/null || {
        echo "[web-bootstrap] WARNING: Could not create quota metadata directories under ${admin_tools_dir}" >&2
        return 0
    }

    if quota_path_is_symlink "${admin_tools_dir}" || quota_path_is_symlink "${admin_tools_dir}/quota"; then
        echo "[web-bootstrap] WARNING: Refusing to repair symlinked quota metadata path under ${admin_tools_dir}" >&2
        return 0
    fi

    chown "root:${quota_runtime_gid}" "${admin_tools_dir}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not chown ${admin_tools_dir} to root:${quota_runtime_gid}" >&2
    chmod 1770 "${admin_tools_dir}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not set secure mode 1770 on ${admin_tools_dir}" >&2

    chown root:root "${admin_tools_dir}/quota" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not chown ${admin_tools_dir}/quota to root:root" >&2
    chmod 0700 "${admin_tools_dir}/quota" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not set secure mode 0700 on ${admin_tools_dir}/quota" >&2
}

# Normalize quota state path. Inputs: shell arguments and environment. Output: command status and side effects.
normalize_quota_state_path() {
    local target_path="$1"
    local target_dir
    target_dir="$(dirname "${target_path}")"

    if quota_path_is_symlink "${target_dir}" || quota_path_is_symlink "${target_path}"; then
        echo "[web-bootstrap] WARNING: Refusing to repair symlinked quota state path ${target_path}" >&2
        return 0
    fi

    mkdir -p "${target_dir}" 2>/dev/null || {
        echo "[web-bootstrap] WARNING: Could not create quota state directory ${target_dir}" >&2
        return 0
    }

    chown "root:${quota_runtime_gid}" "${target_dir}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not chown quota state directory ${target_dir} to root:${quota_runtime_gid}" >&2
    chmod 1770 "${target_dir}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not set secure mode 1770 on quota state directory ${target_dir}" >&2

    if [[ ! -e "${target_path}" ]]; then
        install -m 0600 -o "${quota_runtime_user}" -g "${quota_runtime_group}" /dev/null "${target_path}" 2>/dev/null || \
            touch "${target_path}" 2>/dev/null || true
    fi

    if [[ -e "${target_path}" ]]; then
        chown "${quota_runtime_user}:${quota_runtime_group}" "${target_path}" 2>/dev/null || \
            echo "[web-bootstrap] WARNING: Could not chown quota state file ${target_path} to ${quota_runtime_user}:${quota_runtime_group}" >&2
        chmod 0600 "${target_path}" 2>/dev/null || \
            echo "[web-bootstrap] WARNING: Could not set secure mode 0600 on quota state file ${target_path}" >&2
    fi
}

# Normalize host-owned quota metadata path. Inputs: shell arguments and environment. Output: command status and side effects.
normalize_host_quota_metadata_path() {
    local target_path="$1"
    if [[ ! -e "${target_path}" ]]; then
        return 0
    fi
    if quota_path_is_symlink "${target_path}"; then
        echo "[web-bootstrap] WARNING: Refusing to repair symlinked host quota metadata file ${target_path}" >&2
        return 0
    fi
    chown root:root "${target_path}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not chown host quota metadata file ${target_path} to root:root" >&2
    chmod 0600 "${target_path}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not set secure mode 0600 on host quota metadata file ${target_path}" >&2
}

prepare_quota_metadata_root
normalize_quota_state_path "${quota_state_path}"
normalize_host_quota_metadata_path "${quota_projects_file}"
normalize_host_quota_metadata_path "${quota_projid_file}"
if [[ -e "${quota_marker_path}" && ! -L "${quota_marker_path}" ]]; then
    chown "root:${quota_runtime_gid}" "${quota_marker_path}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not chown quota marker ${quota_marker_path} to root:${quota_runtime_gid}" >&2
    chmod 0640 "${quota_marker_path}" 2>/dev/null || \
        echo "[web-bootstrap] WARNING: Could not set secure mode 0640 on quota marker ${quota_marker_path}" >&2
fi

configure_docker_socket_access

# Repair branding logo permissions. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Perform branding logo is known generated fallback. Inputs: shell arguments and environment. Output: command status and side effects.
branding_logo_is_known_generated_fallback() {
    local logo_path="${1:?BUG: branding_logo_is_known_generated_fallback requires a logo path}"
    local logo_sha=""

    if [[ ! -f "${logo_path}" ]]; then
        return 1
    fi

    logo_sha="$(sha256sum "${logo_path}" | awk '{print $1}')"
    case "${logo_sha}" in
        4962acc5fbf52f8ef72721990487fdc9a1e76c862e8e0676acd4aa0dad867286|\
        fed3805fd27203cb1d2d80df346d625ee5b9fa127e7f5408c0ede31eeb148bc7|\
        a755d0d82d51c3292bb7047b7bdfbb92c6f430b6d99cd91c463510b43b462e84)
            return 0
            ;;
    esac

    return 1
}

# Perform branding logo uses generated fallback. Inputs: shell arguments and environment. Output: command status and side effects.
branding_logo_uses_generated_fallback() {
    local logo_path="${1:?BUG: branding_logo_uses_generated_fallback requires a logo path}"
    local marker_path="${2:?BUG: branding_logo_uses_generated_fallback requires a marker path}"
    local fallback_writer_path="/opt/omero/tools/write_branding_logo_fallback.py"
    local generated_fallback_path=""

    if [[ ! -f "${logo_path}" || ! -f "${fallback_writer_path}" ]]; then
        return 1
    fi

    generated_fallback_path="$(mktemp "${TMPDIR:-/tmp}/omero-web-branding-logo-fallback.XXXXXX.png")"
    if python3 "${fallback_writer_path}" "${generated_fallback_path}" && cmp -s "${generated_fallback_path}" "${logo_path}"; then
        rm -f "${generated_fallback_path}" || true
        return 0
    fi

    rm -f "${generated_fallback_path}" || true

    if branding_logo_is_known_generated_fallback "${logo_path}"; then
        echo "[web-bootstrap] Refreshing legacy generated branding fallback icon: ${logo_path}" >&2
        return 0
    fi

    if [[ -f "${marker_path}" ]]; then
        echo "[web-bootstrap] WARNING: Branding fallback marker is stale; preserving non-generated logo at ${logo_path}" >&2
        rm -f "${marker_path}" || true
    fi
    return 1
}

# Perform branding logo fallback enabled. Inputs: shell arguments and environment. Output: command status and side effects.
branding_logo_fallback_enabled() {
    local configured_login_logo="${CONFIG_omero_web_login__logo:-}"
    [[ "${configured_login_logo}" = "/static/branding/logo.png" ]]
}

# Install branding logo fallback. Inputs: shell arguments and environment. Output: command status and side effects.
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

# Clear generated static assets before restoring backup. Inputs: target static directory. Output: command status and side effects.
clear_static_directory_for_backup_sync() {
    local target_dir="${1:-}"

    case "${target_dir}" in
        "" | "/" | "/static" | [!/]*)
            echo "[web-bootstrap] ERROR: Refusing unsafe static directory cleanup target: ${target_dir:-<empty>}" >&2
            exit 1
            ;;
    esac

    if [[ -L "${target_dir}" ]]; then
        echo "[web-bootstrap] ERROR: Refusing to clean symlinked static directory: ${target_dir}" >&2
        exit 1
    fi

    mkdir -p "${target_dir}"
    if [[ ! -d "${target_dir}" ]]; then
        echo "[web-bootstrap] ERROR: Static directory is not a directory after creation: ${target_dir}" >&2
        exit 1
    fi

    find "${target_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
}

# Sync static assets. Inputs: shell arguments and environment. Output: command status and side effects.
sync_static_assets() {
    local var_dir="${OMERO_WEB_VAR_DIR:-/opt/omero/web/OMERO.web/var}"
    local static_dir="${var_dir}/static"
    local static_backup_dir="/opt/omero/web/static_backup"
    local effective_runtime_user="${runtime_user}"
    local effective_runtime_group="${runtime_group}"
    local branding_logo_path="${static_dir}/branding/logo.png"
    local branding_fallback_marker_path="${static_dir}/branding/.generated-logo-fallback"
    local local_logo_path="/opt/omero/logo/logo.png"
    local preserved_logo_path=""

    if [[ ! -d "${static_backup_dir}" ]]; then
        echo "[web-bootstrap] ERROR: Static backup directory missing: ${static_backup_dir}" >&2
        exit 1
    fi

    # A generated fallback should never block a newly provided site-local logo
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
    clear_static_directory_for_backup_sync "${static_dir}"
    cp -a "${static_backup_dir}/." "${static_dir}/"

    if id -u "${effective_runtime_user}" >/dev/null 2>&1; then
        chown -R "${effective_runtime_user}:${effective_runtime_group}" "${static_dir}" || true
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

    if ! branding_logo_fallback_enabled; then
        return 0
    fi

    if [[ ! -f "${branding_logo_path}" && -f "${local_logo_path}" ]]; then
        mkdir -p "${static_dir}/branding"
        if cp -f "${local_logo_path}" "${branding_logo_path}"; then
            echo "[web-bootstrap] Restored branding logo from site-local logo path: ${local_logo_path}"
            rm -f "${branding_fallback_marker_path}" || true
        else
            echo "[web-bootstrap] WARNING: Failed to restore branding logo from site-local logo path: ${local_logo_path}" >&2
        fi
    fi

    if [[ -f "${branding_logo_path}" ]]; then
        rm -f "${branding_fallback_marker_path}" || true
        repair_branding_logo_permissions "${branding_logo_path}" "${effective_runtime_user}" "${effective_runtime_group}" || true
    else
        echo "[web-bootstrap] WARNING: Branding logo missing after static sync: ${branding_logo_path}. Installing generated fallback icon." >&2
        install_branding_logo_fallback "${branding_logo_path}" "${branding_fallback_marker_path}" "${effective_runtime_user}" "${effective_runtime_group}" || true
    fi

    if [[ ! -f "${static_dir}/omero_web_zarr/openwith.js" ]]; then
        echo "[web-bootstrap] ERROR: Vizarr static asset missing after static sync: ${static_dir}/omero_web_zarr/openwith.js" >&2
        exit 1
    fi

    vizarr_vendor_dir="${static_dir}/omero_web_zarr/vendor/vizarr"
    vizarr_index_count="$(
        find "${vizarr_vendor_dir}" -mindepth 2 -maxdepth 2 -type f -name index.html 2>/dev/null | wc -l
    )"
    if [[ "${vizarr_index_count}" -ne 1 ]]; then
        echo "[web-bootstrap] ERROR: expected exactly one pinned Vizarr static app under ${vizarr_vendor_dir}, found ${vizarr_index_count}" >&2
        exit 1
    fi
}

sync_static_assets

# ── Upgrade OMEZarrReader + JZarr in OMERO CLI JAR cache ──────────────────────
# The OMERO CLI downloads OMERO.java JARs into the bind-mounted var/ directory
# on first use.  The bundled OMEZarrReader and JZarr are outdated; replace them
# Perform upgrade Zarr jars. Inputs: shell arguments and environment. Output: command status and side effects.
upgrade_zarr_jars() {
    local staged_dir="/opt/omero/web/zarr-jar-upgrade"
    local var_dir="${OMERO_WEB_VAR_DIR:-/opt/omero/web/OMERO.web/var}"
    local effective_runtime_user="${runtime_user}"
    local effective_runtime_group="${runtime_group}"
    local cache_root="${var_dir}/.cache"

    if [[ ! -d "${staged_dir}" ]]; then
        return 0
    fi

    if [[ ! -d "${cache_root}" ]]; then
        echo "[web-bootstrap] OMERO CLI cache directory not yet created; zarr JAR upgrade will apply on next container restart"
        return 0
    fi

    local jar_cache
    jar_cache="$(find "${cache_root}" -maxdepth 7 -type d -name "libs" -path "*/OMERO.java-*/libs" 2>/dev/null | head -n 1)"

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
        if id -u "${effective_runtime_user}" >/dev/null 2>&1; then
            chown "${effective_runtime_user}:${effective_runtime_group}" "${target}" 2>/dev/null || true
        fi
        echo "[web-bootstrap] Upgraded ${jar_name} in OMERO CLI JAR cache"
        updated=$((updated + 1))
    done

    if [[ "${updated}" -gt 0 ]]; then
        echo "[web-bootstrap] ✓ Zarr JAR upgrade complete (${updated} file(s) updated)"
    fi
}

upgrade_zarr_jars
