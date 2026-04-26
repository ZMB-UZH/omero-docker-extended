#!/usr/bin/env bash
# =============================================================================
# omero-quota-enforcer.sh — Host-side ext4 project-quota enforcement
#
# Reads the quota state JSON written by the omeroweb container and applies
# ext4 project quotas on the host filesystem using chattr and setquota.
#
# Must run as root on the Docker host through systemd.
# Compatible with Ubuntu 24.04+ and Debian 13 (Trixie)+.
#
# Required host packages: e2fsprogs, quota, python3, util-linux
# Required filesystem:    ext4 mounted with prjquota, project feature enabled
# =============================================================================
set -euo pipefail

DEFAULTS_FILE="${OMERO_QUOTA_DEFAULTS_FILE:-/etc/default/omero-quota-enforcer}"
if [[ -f "${DEFAULTS_FILE}" ]]; then
    # shellcheck source=/dev/null
    . "${DEFAULTS_FILE}"
fi

OMERO_DATA_DIR="${OMERO_DATA_DIR:-}"
QUOTA_STATE_FILE="${QUOTA_STATE_FILE:-${OMERO_DATA_DIR}/.admin-tools/group-quotas.json}"
MANAGED_REPO_ROOT="${MANAGED_REPO_ROOT:-${OMERO_DATA_DIR}/ManagedRepository}"
PROJECTS_FILE="${PROJECTS_FILE:-${OMERO_DATA_DIR}/.admin-tools/quota/projects}"
PROJID_FILE="${PROJID_FILE:-${OMERO_DATA_DIR}/.admin-tools/quota/projid}"
PROJECT_ID_MIN="${PROJECT_ID_MIN:-200000}"
MIN_QUOTA_GB="${MIN_QUOTA_GB:-0.10}"
LOCK_PATH="${LOCK_PATH:-/run/omero-quota-enforcer.lock}"

declare -A DESIRED_GROUPS=()
declare -a QUOTA_GROUPS=()
declare -a QUOTA_GB_VALUES=()
declare -a QUOTA_BLOCK_VALUES=()
applied=0
failed=0
SETQUOTA_ERR=""

die() {
    echo "ERROR: $*" >&2
    exit 1
}

warn() {
    echo "WARNING: $*" >&2
}

usage() {
    echo "Usage: $0" >&2
    echo "Runs one OMERO project-quota reconciliation pass using environment/defaults configuration." >&2
}

parse_args() {
    if [[ "$#" -eq 0 ]]; then
        return 0
    fi

    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage
            exit 2
            ;;
    esac
}

require_root() {
    [[ "$(id -u)" -eq 0 ]] || die "This script must run as root."
}

require_command() {
    local command_name="$1"
    command -v "${command_name}" >/dev/null 2>&1 || {
        die "Required command '${command_name}' is not available. Install packages: e2fsprogs quota python3 util-linux"
    }
}

is_unsigned_integer() {
    case "${1:-}" in
        "" | *[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

is_safe_group_name() {
    case "${1:-}" in
        "" | *[!A-Za-z0-9._-]*) return 1 ;;
        *) return 0 ;;
    esac
}

canonical_existing_dir() {
    local raw_path="$1"
    local label="$2"
    local resolved_path

    [[ -n "${raw_path}" ]] || die "${label} is not set."
    resolved_path="$(readlink -f -- "${raw_path}")" || {
        die "Unable to resolve ${label}: ${raw_path}"
    }
    [[ -d "${resolved_path}" ]] || die "${label} does not exist: ${resolved_path}"
    printf '%s\n' "${resolved_path}"
}

canonical_existing_file() {
    local raw_path="$1"
    local label="$2"
    local resolved_path

    [[ -n "${raw_path}" ]] || die "${label} is not set."
    resolved_path="$(readlink -f -- "${raw_path}")" || {
        die "Unable to resolve ${label}: ${raw_path}"
    }
    [[ -f "${resolved_path}" ]] || die "${label} is not a regular file: ${resolved_path}"
    printf '%s\n' "${resolved_path}"
}

path_is_within() {
    local child="$1"
    local parent="$2"
    local parent_prefix="${parent%/}"

    if [[ "${parent_prefix}" = "" ]]; then
        parent_prefix="/"
    fi

    case "${parent_prefix}" in
        /) [[ "${child}" = /* ]] ;;
        *) [[ "${child}" = "${parent_prefix}" || "${child}" = "${parent_prefix}"/* ]] ;;
    esac
}

path_is_strict_child() {
    local child="$1"
    local parent="$2"
    local parent_prefix="${parent%/}"

    [[ "${child}" != "${parent_prefix}" ]] || return 1
    path_is_within "${child}" "${parent_prefix}"
}

ensure_regular_or_absent() {
    local path="$1"
    if [[ -L "${path}" || ( -e "${path}" && ! -f "${path}" ) ]]; then
        die "Refusing to use non-regular file: ${path}"
    fi
}

mount_context() {
    local target_path="$1"
    python3 - "${target_path}" <<'PY'
import os
import pathlib
import re
import sys


def unescape_mount_field(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


target = pathlib.Path(sys.argv[1]).resolve()
best: tuple[int, str, str, str, str] | None = None

for line in pathlib.Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
    if " - " not in line:
        continue
    left, right = line.split(" - ", 1)
    left_parts = left.split()
    right_parts = right.split()
    if len(left_parts) < 6 or len(right_parts) < 3:
        continue

    mount_point = pathlib.Path(unescape_mount_field(left_parts[4])).resolve()
    try:
        common_path = os.path.commonpath((str(target), str(mount_point)))
    except ValueError:
        continue
    if common_path != str(mount_point):
        continue

    fs_type = right_parts[0]
    source = unescape_mount_field(right_parts[1])
    mount_options = left_parts[5]
    super_options = right_parts[2]
    options = ",".join(option for option in (mount_options, super_options) if option)
    candidate = (len(str(mount_point)), fs_type, str(mount_point), source, options)
    if best is None or candidate[0] > best[0]:
        best = candidate

if best is None:
    print("unknown\t\t\t")
else:
    _, fs_type, mount_point, source, options = best
    print("\t".join((fs_type, mount_point, source, options)))
PY
}

mount_options_include() {
    local options="$1"
    local wanted="$2"
    case ",${options}," in
        *",${wanted},"*) return 0 ;;
        *) return 1 ;;
    esac
}

load_quota_records() {
    local records_file="$1"
    python3 - "${QUOTA_STATE_FILE}" "${MIN_QUOTA_GB}" > "${records_file}" <<'PY'
import decimal
import json
import pathlib
import re
import sys

state_path = pathlib.Path(sys.argv[1])
try:
    min_gb = decimal.Decimal(str(sys.argv[2]))
except decimal.InvalidOperation as exc:
    raise SystemExit(f"MIN_QUOTA_GB is invalid: {sys.argv[2]!r}") from exc
if min_gb <= 0:
    raise SystemExit("MIN_QUOTA_GB must be greater than 0")

try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"Unable to read quota state JSON: {exc}") from exc

quotas = state.get("quotas_gb", {})
if not isinstance(quotas, dict):
    raise SystemExit("quota state field 'quotas_gb' must be an object")

safe_name = re.compile(r"^[A-Za-z0-9._-]+$")
for group_name in sorted(str(group) for group in quotas):
    if not safe_name.fullmatch(group_name):
        print(f"SKIP\t{group_name!r}\tunsafe group name")
        continue

    raw_value = quotas[group_name]
    try:
        quota_gb = decimal.Decimal(str(raw_value))
    except decimal.InvalidOperation:
        print(f"ERR\t{group_name}\tinvalid quota value: {raw_value!r}")
        continue

    if not quota_gb.is_finite() or quota_gb < min_gb:
        print(f"ERR\t{group_name}\tquota_gb ({quota_gb}) must be >= {min_gb}")
        continue

    quota_blocks = int(quota_gb * decimal.Decimal(1024 * 1024))
    print(f"OK\t{group_name}\t{quota_gb}\t{quota_blocks}")
PY
}

read_quota_records() {
    local records_file="$1"
    local status group_name quota_gb quota_blocks _message

    while IFS=$'\t' read -r status group_name quota_gb quota_blocks _message; do
        [[ -n "${status}" ]] || continue
        case "${status}" in
            OK)
                DESIRED_GROUPS["${group_name}"]=1
                QUOTA_GROUPS+=("${group_name}")
                QUOTA_GB_VALUES+=("${quota_gb}")
                QUOTA_BLOCK_VALUES+=("${quota_blocks}")
                ;;
            ERR)
                DESIRED_GROUPS["${group_name}"]=1
                echo "FAIL: Invalid quota for group '${group_name}': ${quota_gb}" >&2
                ((failed++)) || true
                ;;
            SKIP)
                echo "SKIP: ${group_name} (${quota_gb})." >&2
                ;;
            *)
                echo "FAIL: Unknown quota parser status '${status}'." >&2
                ((failed++)) || true
                ;;
        esac
    done < "${records_file}"
}

is_desired_group() {
    local group_name="$1"
    [[ -n "${DESIRED_GROUPS[${group_name}]:-}" ]]
}

project_id_for_group() {
    local group_name="$1"
    awk -F: -v group="${group_name}" '
        $1 == group && $2 ~ /^[0-9]+$/ { project_id = $2 }
        END { if (project_id != "") print project_id }
    ' "${PROJID_FILE}"
}

project_id_for_path() {
    local group_path="$1"
    awk -F: -v path="${group_path}" '
        {
            separator_index = index($0, ":")
            project_id = (separator_index > 0) ? substr($0, 1, separator_index - 1) : ""
            current_path = (separator_index > 0) ? substr($0, separator_index + 1) : ""
            if (project_id ~ /^[0-9]+$/ && current_path == path) {
                found_project_id = project_id
            }
        }
        END { if (found_project_id != "") print found_project_id }
    ' "${PROJECTS_FILE}"
}

next_project_id() {
    local max_existing
    max_existing="$(
        awk -F: 'NF >= 2 && $1 ~ /^[0-9]+$/ { if ($1 > max) max = $1 }
                 NF >= 2 && $2 ~ /^[0-9]+$/ { if ($2 > max) max = $2 }
                 END { print max + 0 }' \
            "${PROJECTS_FILE}" "${PROJID_FILE}"
    )"
    if [[ "${max_existing}" -lt "${PROJECT_ID_MIN}" ]]; then
        printf '%s\n' "${PROJECT_ID_MIN}"
    else
        printf '%s\n' "$((max_existing + 1))"
    fi
}

rewrite_without_group() {
    local file_path="$1"
    local group_name="$2"
    local tmp_file

    tmp_file="$(mktemp "$(dirname -- "${file_path}")/.rewrite.XXXXXX")"
    awk -F: -v group="${group_name}" '$1 != group { print }' "${file_path}" > "${tmp_file}"
    mv "${tmp_file}" "${file_path}"
}

rewrite_without_project_path() {
    local file_path="$1"
    local group_path="$2"
    local tmp_file

    tmp_file="$(mktemp "$(dirname -- "${file_path}")/.rewrite.XXXXXX")"
    awk -F: -v path="${group_path}" '
        {
            separator_index = index($0, ":")
            current_path = (separator_index > 0) ? substr($0, separator_index + 1) : ""
            if (current_path != path) print
        }
    ' "${file_path}" > "${tmp_file}"
    mv "${tmp_file}" "${file_path}"
}

rewrite_without_project_id() {
    local file_path="$1"
    local project_id="$2"
    local tmp_file

    tmp_file="$(mktemp "$(dirname -- "${file_path}")/.rewrite.XXXXXX")"
    awk -F: -v project_id="${project_id}" '$1 != project_id { print }' "${file_path}" > "${tmp_file}"
    mv "${tmp_file}" "${file_path}"
}

write_project_mappings() {
    local group_name="$1"
    local project_id="$2"
    local group_path="$3"

    rewrite_without_project_path "${PROJECTS_FILE}" "${group_path}"
    rewrite_without_group "${PROJID_FILE}" "${group_name}"
    printf '%s:%s\n' "${project_id}" "${group_path}" >> "${PROJECTS_FILE}"
    printf '%s:%s\n' "${group_name}" "${project_id}" >> "${PROJID_FILE}"
}

clear_project_quota() {
    local project_id="$1"
    local setquota_err=""

    if ! setquota_err="$(setquota -P "${project_id}" 0 0 0 0 "${MOUNT_POINT}" 2>&1)"; then
        SETQUOTA_ERR="${setquota_err}"
        return 1
    fi
}

apply_project_quota() {
    local project_id="$1"
    local quota_blocks="$2"
    local setquota_err=""

    if ! setquota_err="$(setquota -P "${project_id}" "${quota_blocks}" "${quota_blocks}" 0 0 "${MOUNT_POINT}" 2>&1)"; then
        SETQUOTA_ERR="${setquota_err}"
        return 1
    fi
}

clear_group_project_attributes() {
    local group_path="$1"
    local chattr_err=""

    [[ -d "${group_path}" ]] || return 0

    while IFS= read -r -d '' directory_path; do
        chattr_err=""
        if ! chattr_err="$(chattr -P "${directory_path}" 2>&1)"; then
            echo "FAIL: chattr -P ${directory_path}: ${chattr_err}" >&2
            return 1
        fi
        chattr_err=""
        if ! chattr_err="$(chattr -p 0 "${directory_path}" 2>&1)"; then
            echo "FAIL: chattr -p 0 ${directory_path}: ${chattr_err}" >&2
            return 1
        fi
    done < <(find -P "${group_path}" -xdev -type d -print0)
}

retag_group_tree_once() {
    local group_name="$1"
    local project_id="$2"
    local group_path="$3"
    local retag_marker_dir retag_marker_file chattr_err retag_failed directory_path

    retag_marker_dir="$(dirname -- "${PROJECTS_FILE}")"
    retag_marker_file="${retag_marker_dir}/.retag_done_${group_name}_${project_id}"
    [[ ! -f "${retag_marker_file}" ]] || return 0

    echo "INFO: One-time retag for group '${group_name}' project_id=${project_id} under: ${group_path}"
    if ! chattr_err="$(chattr -R -p "${project_id}" "${group_path}" 2>&1)"; then
        echo "FAIL: chattr -R -p ${project_id} ${group_path}: ${chattr_err}" >&2
        return 1
    fi

    retag_failed=0
    while IFS= read -r -d '' directory_path; do
        chattr_err=""
        if ! chattr_err="$(chattr +P "${directory_path}" 2>&1)"; then
            echo "FAIL: chattr +P ${directory_path}: ${chattr_err}" >&2
            retag_failed=1
            break
        fi
    done < <(find -P "${group_path}" -xdev -type d -print0)

    [[ "${retag_failed}" -eq 0 ]] || return 1
    touch "${retag_marker_file}"
}

reconcile_stale_mappings() {
    local existing_project_mapping mapped_group mapped_project_id extra
    local group_path resolved_group_path marker_dir
    local -a existing_project_mappings=()

    marker_dir="$(dirname -- "${PROJECTS_FILE}")"
    mapfile -t existing_project_mappings < "${PROJID_FILE}"

    for existing_project_mapping in "${existing_project_mappings[@]}"; do
        IFS=: read -r mapped_group mapped_project_id extra <<< "${existing_project_mapping}"
        [[ -z "${extra:-}" ]] || continue
        [[ -n "${mapped_group}" && -n "${mapped_project_id}" ]] || continue
        if ! is_safe_group_name "${mapped_group}"; then
            echo "SKIP: Unsafe stale group name '${mapped_group}'." >&2
            continue
        fi
        is_desired_group "${mapped_group}" && continue
        if ! is_unsigned_integer "${mapped_project_id}"; then
            echo "SKIP: Invalid project ID '${mapped_project_id}' for stale group '${mapped_group}'." >&2
            continue
        fi

        group_path="${MANAGED_REPO_ROOT}/${mapped_group}"
        if [[ -d "${group_path}" ]]; then
            resolved_group_path="$(readlink -f -- "${group_path}")"
            if path_is_strict_child "${resolved_group_path}" "${MANAGED_REPO_ROOT}"; then
                if ! clear_group_project_attributes "${resolved_group_path}"; then
                    echo "FAIL: Unable to clear project attributes for stale group '${mapped_group}' (path=${resolved_group_path})." >&2
                    ((failed++)) || true
                    continue
                fi
            else
                echo "SKIP: Stale group path escapes managed root: ${resolved_group_path}" >&2
            fi
        fi

        if ! clear_project_quota "${mapped_project_id}"; then
            echo "FAIL: Unable to clear quota for stale group '${mapped_group}' (project_id=${mapped_project_id}): ${SETQUOTA_ERR}" >&2
            ((failed++)) || true
            continue
        fi

        rewrite_without_group "${PROJID_FILE}" "${mapped_group}"
        rewrite_without_project_id "${PROJECTS_FILE}" "${mapped_project_id}"
        find -P "${marker_dir}" -maxdepth 1 -type f \
            -name ".retag_done_${mapped_group}_*" -delete
        echo "OK: cleared stale quota mapping for group '${mapped_group}' (project_id=${mapped_project_id})."
    done
}

process_group_quota() {
    local group_name="$1"
    local quota_gb="$2"
    local quota_blocks="$3"
    local group_path resolved_group_path resolved_mount_point project_id chattr_err

    group_path="${MANAGED_REPO_ROOT}/${group_name}"
    if [[ ! -d "${group_path}" ]]; then
        echo "SKIP: Group directory is missing and must be created by OMERO.server: ${group_path}" >&2
        return 0
    fi

    resolved_group_path="$(readlink -f -- "${group_path}")"
    if ! path_is_strict_child "${resolved_group_path}" "${MANAGED_REPO_ROOT}"; then
        echo "SKIP: Group path '${resolved_group_path}' is not under managed root '${MANAGED_REPO_ROOT}'." >&2
        return 0
    fi

    resolved_mount_point="$(readlink -f -- "${MOUNT_POINT}")"
    if ! path_is_within "${resolved_group_path}" "${resolved_mount_point}"; then
        echo "SKIP: Group path '${resolved_group_path}' is not under mount '${resolved_mount_point}'." >&2
        return 0
    fi

    project_id="$(project_id_for_group "${group_name}")"
    if [[ -z "${project_id}" ]]; then
        project_id="$(project_id_for_path "${resolved_group_path}")"
    fi
    if [[ -z "${project_id}" ]]; then
        project_id="$(next_project_id)"
    fi

    if ! is_unsigned_integer "${project_id}"; then
        echo "FAIL: Invalid project ID '${project_id}' for group '${group_name}'." >&2
        ((failed++)) || true
        return 0
    fi

    write_project_mappings "${group_name}" "${project_id}" "${resolved_group_path}"

    if ! chattr_err="$(chattr -p "${project_id}" "${resolved_group_path}" 2>&1)"; then
        echo "FAIL: chattr -p ${project_id} ${resolved_group_path}: ${chattr_err}" >&2
        ((failed++)) || true
        return 0
    fi
    if ! chattr_err="$(chattr +P "${resolved_group_path}" 2>&1)"; then
        echo "FAIL: chattr +P ${resolved_group_path}: ${chattr_err}" >&2
        ((failed++)) || true
        return 0
    fi

    if ! retag_group_tree_once "${group_name}" "${project_id}" "${resolved_group_path}"; then
        ((failed++)) || true
        return 0
    fi

    if ! apply_project_quota "${project_id}" "${quota_blocks}"; then
        echo "FAIL: setquota -P ${project_id} ${quota_blocks} ${quota_blocks} 0 0 ${MOUNT_POINT}: ${SETQUOTA_ERR}" >&2
        ((failed++)) || true
        return 0
    fi

    echo "OK: group='${group_name}' project_id=${project_id} quota=${quota_gb}GB (${quota_blocks} blocks) path=${resolved_group_path}"
    ((applied++)) || true
}

main() {
    parse_args "$@"
    require_root
    for cmd in chattr setquota python3 flock find awk readlink mktemp; do
        require_command "${cmd}"
    done
    is_unsigned_integer "${PROJECT_ID_MIN}" || die "PROJECT_ID_MIN must be an unsigned integer."

    OMERO_DATA_DIR="$(canonical_existing_dir "${OMERO_DATA_DIR}" "OMERO_DATA_DIR")"
    if [[ ! -f "${QUOTA_STATE_FILE}" ]]; then
        exit 0
    fi
    QUOTA_STATE_FILE="$(canonical_existing_file "${QUOTA_STATE_FILE}" "QUOTA_STATE_FILE")"
    MANAGED_REPO_ROOT="$(canonical_existing_dir "${MANAGED_REPO_ROOT}" "MANAGED_REPO_ROOT")"

    IFS=$'\t' read -r FS_TYPE MOUNT_POINT _mount_source MOUNT_OPTIONS \
        < <(mount_context "${OMERO_DATA_DIR}")
    if [[ "${FS_TYPE}" != "ext4" ]]; then
        warn "Filesystem at ${OMERO_DATA_DIR} is '${FS_TYPE}', not ext4. Skipping enforcement."
        exit 0
    fi
    [[ -n "${MOUNT_POINT}" ]] || die "Could not determine mount point for ${OMERO_DATA_DIR}."
    if ! mount_options_include "${MOUNT_OPTIONS}" prjquota \
        && ! mount_options_include "${MOUNT_OPTIONS}" project; then
        die "Filesystem at ${MOUNT_POINT} is not mounted with prjquota."
    fi

    ensure_regular_or_absent "${PROJECTS_FILE}"
    ensure_regular_or_absent "${PROJID_FILE}"

    mkdir -p "$(dirname -- "${LOCK_PATH}")"
    exec 9>"${LOCK_PATH}"
    if ! flock -n -x 9; then
        echo "Another instance is already running (lock: ${LOCK_PATH}). Exiting." >&2
        exit 0
    fi

    mkdir -p "$(dirname -- "${PROJECTS_FILE}")" "$(dirname -- "${PROJID_FILE}")"
    touch "${PROJECTS_FILE}" "${PROJID_FILE}"

    records_file="$(mktemp)"
    trap 'rm -f -- "${records_file}"' EXIT
    if ! load_quota_records "${records_file}"; then
        die "Unable to parse quota state from ${QUOTA_STATE_FILE}."
    fi
    read_quota_records "${records_file}"

    reconcile_stale_mappings

    if [[ ${#QUOTA_GROUPS[@]} -eq 0 ]]; then
        echo "No active group quotas configured; stale mappings (if any) have been reconciled."
        [[ "${failed}" -eq 0 ]] || exit 1
        exit 0
    fi

    for index in "${!QUOTA_GROUPS[@]}"; do
        process_group_quota \
            "${QUOTA_GROUPS[${index}]}" \
            "${QUOTA_GB_VALUES[${index}]}" \
            "${QUOTA_BLOCK_VALUES[${index}]}"
    done

    echo "Enforcement complete: ${applied} applied, ${failed} failed."
    [[ "${failed}" -eq 0 ]] || exit 1
}

if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
    main "$@"
fi
