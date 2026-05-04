#!/usr/bin/env bash
set -euo pipefail

# Print usage text. Inputs: shell arguments and environment. Output: command status and side effects.
usage() {
  cat <<'USAGE'
Usage: enforce-ext4-project-quota.sh --group <name> --group-path <path> --quota-gb <gb> --mount-point <path>
USAGE
}

group_name=""
group_path=""
quota_gb=""
mount_point=""
projects_file="${ADMIN_TOOLS_QUOTA_PROJECTS_FILE:-/tmp/omero-admin-tools/quota/projects}"
projid_file="${ADMIN_TOOLS_QUOTA_PROJID_FILE:-/tmp/omero-admin-tools/quota/projid}"
project_id_min="${ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN:-200000}"
minimum_quota_gb="${ADMIN_TOOLS_MIN_QUOTA_GB:-0.10}"
lock_path="${ADMIN_TOOLS_QUOTA_LOCK_PATH:-/tmp/omero-ext4-quota.lock}"

# Return whether non negative integer. Inputs: shell arguments and environment. Output: success or failure status.
is_non_negative_integer() {
  case "${1:-}" in
    ""|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

# Return whether safe group name. Inputs: shell arguments and environment. Output: success or failure status.
is_safe_group_name() {
  case "${1:-}" in
    ""|*[!A-Za-z0-9._-]*) return 1 ;;
    *) return 0 ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --group) group_name="${2:-}"; shift 2 ;;
    --group-path) group_path="${2:-}"; shift 2 ;;
    --quota-gb) quota_gb="${2:-}"; shift 2 ;;
    --mount-point) mount_point="${2:-}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$group_name" || -z "$group_path" || -z "$quota_gb" || -z "$mount_point" ]]; then
  usage >&2
  exit 2
fi

if ! is_safe_group_name "$group_name"; then
  echo "Unsafe group name '$group_name'. Allowed pattern: [A-Za-z0-9._-]+" >&2
  exit 1
fi

if ! is_non_negative_integer "$project_id_min"; then
  echo "ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN must be a non-negative integer. Got: $project_id_min" >&2
  exit 1
fi

for cmd in chattr setquota awk flock; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Required command '$cmd' is not available" >&2
    exit 1
  fi
done

if [[ ! -d "$group_path" ]]; then
  echo "Group path does not exist or is not a directory: $group_path" >&2
  exit 1
fi

if [[ ! -d "$mount_point" ]]; then
  echo "Mount point does not exist or is not a directory: $mount_point" >&2
  exit 1
fi

resolved_group_path="$(readlink -f "$group_path")"
resolved_mount_point="$(readlink -f "$mount_point")"
# Strip trailing slash so that root mount "/" becomes "" and the
# pattern "/*" correctly matches any absolute path.
mount_prefix="${resolved_mount_point%/}"
case "$resolved_group_path" in
  "$mount_prefix"/*) ;;
  *)
    echo "Group path '$resolved_group_path' is not under mount point '$resolved_mount_point'" >&2
    exit 1
    ;;
esac

mkdir -p "$(dirname "$lock_path")"
mkdir -p "$(dirname "$projects_file")"
mkdir -p "$(dirname "$projid_file")"
exec 9>"$lock_path"
flock -x 9

touch "$projects_file" "$projid_file"

project_id="$(
  awk -F: -v group="$group_name" '
    $1 == group && $2 ~ /^[0-9]+$/ { value=$2 }
    END { print value }
  ' "$projid_file"
)"

if [ -z "$project_id" ]; then
  project_id="$(
    awk -v target_path="$resolved_group_path" '
      {
        separator_index = index($0, ":")
        project_id = (separator_index > 1) ? substr($0, 1, separator_index - 1) : ""
        current_path = (separator_index > 0) ? substr($0, separator_index + 1) : ""
        if (project_id ~ /^[0-9]+$/ && current_path == target_path) {
          value = project_id
        }
      }
      END { print value }
    ' "$projects_file"
  )"
fi

if [[ -z "$project_id" ]]; then
  max_existing="$(
    awk -F: '
      NF >= 2 && $1 ~ /^[0-9]+$/ { candidate = $1 }
      NF >= 2 && $1 !~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { candidate = $2 }
      candidate != "" {
        if (candidate > max) {
          max = candidate
        }
        candidate = ""
      }
      END { print max + 0 }
    ' "$projects_file" "$projid_file"
  )"
  if [[ "$max_existing" -lt "$project_id_min" ]]; then
    project_id="$project_id_min"
  else
    project_id="$((max_existing + 1))"
  fi
fi

if ! awk -v expected_id="$project_id" -v expected_path="$resolved_group_path" '
    {
      separator_index = index($0, ":")
      project_id = (separator_index > 1) ? substr($0, 1, separator_index - 1) : ""
      current_path = (separator_index > 0) ? substr($0, separator_index + 1) : ""
      if (project_id == expected_id && current_path == expected_path) {
        found = 1
      }
    }
    END { exit found ? 0 : 1 }
  ' "$projects_file"; then
  awk -F: -v path="$resolved_group_path" '
    {
      separator_index = index($0, ":")
      current_path = (separator_index > 0) ? substr($0, separator_index + 1) : ""
      if (current_path != path) {
        print $0
      }
    }
  ' "$projects_file" > "${projects_file}.tmp"
  mv "${projects_file}.tmp" "$projects_file"
  printf '%s:%s\n' "$project_id" "$resolved_group_path" >> "$projects_file"
fi

if ! awk -F: -v group="$group_name" -v expected_id="$project_id" '
    $1 == group && $2 == expected_id { found = 1 }
    END { exit found ? 0 : 1 }
  ' "$projid_file"; then
  awk -F: -v group="$group_name" '$1 != group { print $0 }' "$projid_file" > "${projid_file}.tmp"
  mv "${projid_file}.tmp" "$projid_file"
  printf '%s:%s\n' "$group_name" "$project_id" >> "$projid_file"
fi

quota_blocks="$(python3 - <<PY
quota_gb = float(${quota_gb@Q})
minimum_quota_gb = float(${minimum_quota_gb@Q})
if minimum_quota_gb <= 0:
    raise SystemExit("ADMIN_TOOLS_MIN_QUOTA_GB must be > 0")
if quota_gb < minimum_quota_gb:
    raise SystemExit(f"quota_gb must be >= {minimum_quota_gb:.2f}")
print(int(quota_gb * 1024 * 1024))
PY
)"

chattr -p "$project_id" "$resolved_group_path"
chattr +P "$resolved_group_path"
setquota -P "$project_id" 0 "$quota_blocks" 0 0 "$resolved_mount_point"

echo "project_id=$project_id quota_blocks=$quota_blocks path=$resolved_group_path"
