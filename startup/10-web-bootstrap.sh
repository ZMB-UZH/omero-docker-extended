#!/usr/bin/env bash
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

runtime_user_exists() {
    id -u "${runtime_user}" >/dev/null 2>&1
}

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

trim_whitespace() {
    local value="${1:-}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "${value}"
}

log_mount_status() {
    local path="${1:?BUG: log_mount_status requires a path}"
    local label="${2:?BUG: log_mount_status requires a label}"

    if mountpoint -q "${path}"; then
        echo "[web-bootstrap] ${label} is a mounted filesystem: ${path}"
    else
        echo "[web-bootstrap] ${label} is local (not mounted): ${path}"
    fi
}

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
    mkdir -p "${static_dir}"
    cp -a "${static_backup_dir}/." "${static_dir}/"

    if id -u "${effective_runtime_user}" >/dev/null 2>&1; then
        chown -R "${effective_runtime_user}:${effective_runtime_group}" "${static_dir}" || true
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
}

sync_static_assets

# ── Upgrade OMEZarrReader + JZarr in OMERO CLI JAR cache ──────────────────────
# The OMERO CLI downloads OMERO.java JARs into the bind-mounted var/ directory
# on first use.  The bundled OMEZarrReader and JZarr are outdated; replace them
# with the versions staged by the Dockerfile at /opt/omero/web/zarr-jar-upgrade/.
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
