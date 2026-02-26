#!/usr/bin/env bash
# =============================================================================
# omero-quota-enforcer.sh — Host-side ext4 project-quota enforcement
#
# Reads the quota state JSON written by the omeroweb container and applies
# ext4 project quotas on the host filesystem using chattr + setquota.
#
# Must run as root on the Docker host (via systemd timer or cron).
# Compatible with Ubuntu 24.04+ and Debian 13 (Trixie)+.
#
# Required host packages: e2fsprogs, quota
# Required filesystem:    ext4 mounted with prjquota, project feature enabled
# Note: group directories are created by OMERO.server; this script never creates them.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment or /etc/default/omero-quota-enforcer)
# ---------------------------------------------------------------------------
DEFAULTS_FILE="/etc/default/omero-quota-enforcer"
if [[ -f "$DEFAULTS_FILE" ]]; then
    # shellcheck source=/dev/null
    . "$DEFAULTS_FILE"
fi

# Path to the OMERO data directory (same as OMERO_USER_DATA_PATH from
# installation_paths.env, e.g. /data/OMERO or /srv/OMERO).
OMERO_DATA_DIR="${OMERO_DATA_DIR:-}"

# Quota state JSON written by the omeroweb container.
QUOTA_STATE_FILE="${QUOTA_STATE_FILE:-${OMERO_DATA_DIR}/.admin-tools/group-quotas.json}"

# Managed repository root inside the OMERO data directory.
MANAGED_REPO_ROOT="${MANAGED_REPO_ROOT:-${OMERO_DATA_DIR}/ManagedRepository}"

# Project-ID mapping files (host-side copies).
PROJECTS_FILE="${PROJECTS_FILE:-${OMERO_DATA_DIR}/.admin-tools/quota/projects}"
PROJID_FILE="${PROJID_FILE:-${OMERO_DATA_DIR}/.admin-tools/quota/projid}"

# First project ID to allocate.
PROJECT_ID_MIN="${PROJECT_ID_MIN:-200000}"

# Minimum quota in GB (reject anything below this).
MIN_QUOTA_GB="${MIN_QUOTA_GB:-0.10}"

# Lock file for serialised access.
LOCK_PATH="${LOCK_PATH:-/run/omero-quota-enforcer.lock}"

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must run as root." >&2
    exit 1
fi

if [[ -z "$OMERO_DATA_DIR" ]]; then
    echo "ERROR: OMERO_DATA_DIR is not set." >&2
    echo "Set it in $DEFAULTS_FILE or export it before running this script." >&2
    exit 1
fi

if [[ ! -d "$OMERO_DATA_DIR" ]]; then
    echo "ERROR: OMERO_DATA_DIR does not exist: $OMERO_DATA_DIR" >&2
    exit 1
fi

for cmd in chattr setquota python3 flock; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: Required command '$cmd' is not available." >&2
        echo "Install packages: e2fsprogs quota python3" >&2
        exit 1
    fi
done

if [[ ! -f "$QUOTA_STATE_FILE" ]]; then
    # No quota state yet — nothing to enforce.
    exit 0
fi

# Detect the filesystem type and mount point for the OMERO data directory.
fs_info="$(python3 -c "
import os, pathlib
p = pathlib.Path('${OMERO_DATA_DIR}').resolve()
best = None
for line in pathlib.Path('/proc/mounts').read_text().splitlines():
    parts = line.split()
    if len(parts) < 3:
        continue
    source, mp, fstype = parts[0], parts[1], parts[2]
    try:
        p.relative_to(mp)
    except ValueError:
        continue
    if best is None or len(mp) > len(best[1]):
        best = (source, mp, fstype)
if best is None:
    print('unknown||')
else:
    print(f'{best[2]}|{best[1]}|{best[0]}')
")"

FS_TYPE="${fs_info%%|*}"
remainder="${fs_info#*|}"
MOUNT_POINT="${remainder%%|*}"
FS_SOURCE="${remainder#*|}"

if [[ "$FS_TYPE" != "ext4" ]]; then
    echo "WARNING: Filesystem at $OMERO_DATA_DIR is '$FS_TYPE', not ext4. Skipping enforcement." >&2
    exit 0
fi

if [[ -z "$MOUNT_POINT" ]]; then
    echo "ERROR: Could not determine mount point for $OMERO_DATA_DIR." >&2
    exit 1
fi

# Check that ext4 has prjquota support.
if ! mount | grep -qE "on ${MOUNT_POINT} .*prjquota"; then
    echo "ERROR: Filesystem at $MOUNT_POINT is not mounted with prjquota." >&2
    echo "Add 'prjquota' to the mount options in /etc/fstab and remount." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Acquire exclusive lock
# ---------------------------------------------------------------------------
mkdir -p "$(dirname "$LOCK_PATH")"
exec 9>"$LOCK_PATH"
if ! flock -n -x 9; then
    echo "Another instance is already running (lock: $LOCK_PATH). Exiting." >&2
    exit 0
fi

# ---------------------------------------------------------------------------
# Ensure mapping file directories exist
# ---------------------------------------------------------------------------
mkdir -p "$(dirname "$PROJECTS_FILE")" "$(dirname "$PROJID_FILE")"
touch "$PROJECTS_FILE" "$PROJID_FILE"

# ---------------------------------------------------------------------------
# Read quotas from the state JSON
# ---------------------------------------------------------------------------
quotas_json="$(python3 -c "
import json, sys
state = json.loads(open('${QUOTA_STATE_FILE}').read())
quotas = state.get('quotas_gb', {})
for group, gb in sorted(quotas.items()):
    print(f'{group}\t{gb}')
")"

desired_groups="$(python3 -c "
import json
state = json.loads(open('${QUOTA_STATE_FILE}').read())
quotas = state.get('quotas_gb', {})
for group in sorted(quotas):
    print(group)
")"

applied=0
failed=0
SETQUOTA_ERR=""

is_desired_group() {
    local lookup_group="$1"
    if [[ -z "$desired_groups" ]]; then
        return 1
    fi
    while IFS= read -r desired_group; do
        [[ "$lookup_group" == "$desired_group" ]] && return 0
    done <<< "$desired_groups"
    return 1
}

clear_project_quota() {
    local project_id="$1"
    local setquota_err=""
    quota_target="$MOUNT_POINT"
    if [[ -z "$quota_target" ]]; then
        quota_target="/"
    fi
    if ! setquota_err="$(setquota -P "$project_id" 0 0 0 0 "$quota_target" 2>&1)"; then
        if [[ -n "${FS_SOURCE:-}" ]]; then
            if ! setquota_err="$(setquota -P "$project_id" 0 0 0 0 "$FS_SOURCE" 2>&1)"; then
                SETQUOTA_ERR="$setquota_err"
                return 1
            fi
            return 0
        fi
        SETQUOTA_ERR="$setquota_err"
        return 1
    fi
    return 0
}

apply_project_quota() {
    local project_id="$1"
    local quota_blocks="$2"
    local quota_target="$3"
    local setquota_err=""

    # BUGFIX: Do NOT call clear_project_quota before applying limits. 
    # Calling setquota with 0 limits drops the boundaries entirely. If a user is
    # already over the new requested limit when we try to apply it, setting to 0 
    # first causes the subsequent application of the new block boundaries to fail 
    # silently (or break ext4 tracking state). Direct overwrite is the safe path.

    if ! setquota_err="$(setquota -P "$project_id" "$quota_blocks" "$quota_blocks" 0 0 "$quota_target" 2>&1)"; then
        SETQUOTA_ERR="$setquota_err"
        return 1
    fi

    return 0
}

clear_group_project_attributes() {
    local group_path="$1"
    local chattr_err=""

    if [[ ! -d "$group_path" ]]; then
        return 0
    fi

    if ! chattr_err="$(chattr -R -p 0 "$group_path" 2>&1)"; then
        echo "FAIL: chattr -R -p 0 $group_path: $chattr_err" >&2
        return 1
    fi

    while IFS= read -r -d '' d; do
        chattr_err=""
        if ! chattr_err="$(chattr -p 0 "$d" 2>&1)"; then
            echo "FAIL: chattr -p 0 $d: $chattr_err" >&2
            return 1
        fi
    done < <(find "$group_path" -xdev -type d -print0)

    return 0
}

# ---------------------------------------------------------------------------
# Remove stale mappings for groups that no longer have configured quotas
# ---------------------------------------------------------------------------
while IFS=: read -r mapped_group mapped_project_id; do
    if [[ -z "$mapped_group" || -z "$mapped_project_id" ]]; then
        continue
    fi
    if is_desired_group "$mapped_group"; then
        continue
    fi
    if [[ ! "$mapped_project_id" =~ ^[0-9]+$ ]]; then
        echo "SKIP: Invalid project ID '$mapped_project_id' for stale group '$mapped_group'." >&2
        continue
    fi

    group_path="${MANAGED_REPO_ROOT}/${mapped_group}"
    if ! clear_project_quota "$mapped_project_id"; then
        echo "FAIL: Unable to clear quota for stale group '$mapped_group' (project_id=$mapped_project_id)." >&2
        ((failed++)) || true
        continue
    fi

    if ! clear_group_project_attributes "$group_path"; then
        echo "FAIL: Unable to clear project attributes for stale group '$mapped_group' (path=$group_path)." >&2
        ((failed++)) || true
        continue
    fi

    sed -i "/^${mapped_group}:[0-9][0-9]*$/d" "$PROJID_FILE"
    sed -i "/^${mapped_project_id}:/d" "$PROJECTS_FILE"
    find "$(dirname "$PROJECTS_FILE")" -maxdepth 1 -type f -name ".retag_done_${mapped_group}_*" -delete || true

    echo "OK: cleared stale quota mapping for group '$mapped_group' (project_id=$mapped_project_id)."
done < "$PROJID_FILE"

if [[ -z "$quotas_json" ]]; then
    echo "No active group quotas configured; stale mappings (if any) have been reconciled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Process each group quota
# ---------------------------------------------------------------------------
while IFS=$'\t' read -r group_name quota_gb; do
    # Validate group name
    if [[ ! "$group_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
        echo "SKIP: Unsafe group name '$group_name'." >&2
        continue
    fi

    group_path="${MANAGED_REPO_ROOT}/${group_name}"

    if [[ ! -d "$group_path" ]]; then
        echo "SKIP: Group directory is missing and must be created by OMERO.server: $group_path" >&2
        continue
    fi

    resolved_group_path="$(readlink -f "$group_path")"
    resolved_mount_point="$(readlink -f "$MOUNT_POINT")"

    # Safety: group path must be under the mount point.
    # Strip trailing slash so that root mount "/" becomes "" and the
    # pattern "/*" correctly matches any absolute path.
    mount_prefix="${resolved_mount_point%/}"
    case "$resolved_group_path" in
        "$mount_prefix"/*) ;;
        *)
            echo "SKIP: Group path '$resolved_group_path' is not under mount '$resolved_mount_point'." >&2
            continue
            ;;
    esac

    # -----------------------------------------------------------------------
    # Allocate or look up project ID
    # -----------------------------------------------------------------------
    project_id=""
    escaped_group_path_regex="$(printf '%s' "$resolved_group_path" | sed 's/[.[\*^$()+?{}|]/\\&/g')"
    escaped_group_path_sed="$(printf '%s' "$resolved_group_path" | sed 's/[\\/&]/\\\\&/g')"

    if grep -Eq "^${group_name}:" "$PROJID_FILE"; then
        project_id="$(sed -n "s/^${group_name}:\([0-9][0-9]*\)$/\1/p" "$PROJID_FILE" | tail -n1)"
    fi

    if [[ -z "$project_id" ]] && grep -Eq "^[0-9]+:${escaped_group_path_regex}$" "$PROJECTS_FILE"; then
        project_id="$(sed -n "s/^\([0-9][0-9]*\):${escaped_group_path_sed}$/\1/p" "$PROJECTS_FILE" | tail -n1)"
    fi

    if [[ -z "$project_id" ]]; then
        max_existing="$(
            awk -F: 'NF>=2 && $1 ~ /^[0-9]+$/ { if ($1 > max) max=$1 } END { print max+0 }' \
                "$PROJECTS_FILE" "$PROJID_FILE"
        )"
        if [[ "$max_existing" -lt "$PROJECT_ID_MIN" ]]; then
            project_id="$PROJECT_ID_MIN"
        else
            project_id="$((max_existing + 1))"
        fi
    fi

    # Update mapping files
    if ! grep -Eq "^${project_id}:${escaped_group_path_regex}$" "$PROJECTS_FILE"; then
        awk -F: -v path="$resolved_group_path" '
            {
                separator_index = index($0, ":")
                current_path = (separator_index > 0) ? substr($0, separator_index + 1) : ""
                if (current_path != path) print $0
            }
        ' "$PROJECTS_FILE" > "${PROJECTS_FILE}.tmp"
        mv "${PROJECTS_FILE}.tmp" "$PROJECTS_FILE"
        printf '%s:%s\n' "$project_id" "$resolved_group_path" >> "$PROJECTS_FILE"
    fi

    if ! grep -Eq "^${group_name}:${project_id}$" "$PROJID_FILE"; then
        sed -i "/^${group_name}:[0-9][0-9]*$/d" "$PROJID_FILE"
        printf '%s:%s\n' "$group_name" "$project_id" >> "$PROJID_FILE"
    fi

    # -----------------------------------------------------------------------
    # Compute quota in 1K blocks
    # -----------------------------------------------------------------------
    quota_blocks="$(python3 -c "
quota_gb = float(${quota_gb})
min_gb = float(${MIN_QUOTA_GB})
if min_gb <= 0:
    raise SystemExit('MIN_QUOTA_GB must be > 0')
if quota_gb < min_gb:
    raise SystemExit(f'quota_gb ({quota_gb}) must be >= {min_gb:.2f}')
print(int(quota_gb * 1024 * 1024))
")" || {
        echo "FAIL: Invalid quota value for group '$group_name': ${quota_gb} GB." >&2
        ((failed++)) || true
        continue
    }

    # -----------------------------------------------------------------------
    # Apply ext4 project attributes and quota
    # -----------------------------------------------------------------------
    chattr_err=""
    if ! chattr_err="$(chattr -p "$project_id" "$resolved_group_path" 2>&1)"; then
        echo "FAIL: chattr -p $project_id $resolved_group_path: $chattr_err" >&2
        ((failed++)) || true
        continue
    fi

    if ! chattr_err="$(chattr +P "$resolved_group_path" 2>&1)"; then
        echo "FAIL: chattr +P $resolved_group_path: $chattr_err" >&2
        ((failed++)) || true
        continue
    fi

    # -----------------------------------------------------------------------
    # IMPORTANT: One-time recursive retag of existing content
    #
    # Setting +P on the group directory only affects NEW inodes created after.
    # Existing subdirectories (e.g. users/<username>) may still have project 0,
    # meaning quota enforcement won't apply to OMERO writes under them.
    #
    # We retag the entire tree ONCE per (group_name, project_id), and drop a
    # marker file so we don't rescan every minute.
    # -----------------------------------------------------------------------
    retag_marker_dir="$(dirname "$PROJECTS_FILE")"
    retag_marker_file="${retag_marker_dir}/.retag_done_${group_name}_${project_id}"

    if [[ ! -f "$retag_marker_file" ]]; then
        echo "INFO: One-time retag for group '$group_name' project_id=$project_id under: $resolved_group_path"

        chattr_err=""
        if ! chattr_err="$(chattr -R -p "$project_id" "$resolved_group_path" 2>&1)"; then
            echo "FAIL: chattr -R -p $project_id $resolved_group_path: $chattr_err" >&2
            ((failed++)) || true
            continue
        fi

        retag_failed=0
        while IFS= read -r -d '' d; do
            chattr_err=""
            if ! chattr_err="$(chattr +P "$d" 2>&1)"; then
                echo "FAIL: chattr +P $d: $chattr_err" >&2
                retag_failed=1
                break
            fi
        done < <(find "$resolved_group_path" -xdev -type d -print0)

        if [[ "$retag_failed" -ne 0 ]]; then
            ((failed++)) || true
            continue
        fi

        touch "$retag_marker_file"
    fi


    # setquota MUST target a real filesystem mountpoint (or device).
    # If OMERO_DATA_DIR is under /, the mountpoint is "/" (not OMERO_DATA_DIR).
    quota_target="$MOUNT_POINT"
    if [[ -z "$quota_target" ]]; then
        quota_target="/"
    fi

    if ! apply_project_quota "$project_id" "$quota_blocks" "$quota_target"; then
        # Fallback: some quota toolchains behave better with the block device.
        if [[ -n "${FS_SOURCE:-}" ]]; then
            if ! apply_project_quota "$project_id" "$quota_blocks" "$FS_SOURCE"; then
                echo "FAIL: setquota -P $project_id $quota_blocks $quota_blocks 0 0 $quota_target (fallback $FS_SOURCE): $SETQUOTA_ERR" >&2
                ((failed++)) || true
                continue
            fi
        else
            echo "FAIL: setquota -P $project_id $quota_blocks $quota_blocks 0 0 $quota_target: $SETQUOTA_ERR" >&2
            ((failed++)) || true
            continue
        fi
    fi

    echo "OK: group='$group_name' project_id=$project_id quota=${quota_gb}GB (${quota_blocks} blocks) path=$resolved_group_path"
    ((applied++)) || true

done <<< "$quotas_json"

echo "Enforcement complete: $applied applied, $failed failed."
if [[ "$failed" -gt 0 ]]; then
    exit 1
fi
