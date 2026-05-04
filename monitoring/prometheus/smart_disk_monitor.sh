#!/bin/sh
set -eu

OUT_FILE="${SMART_DISK_MONITOR_OUT_FILE:-/out/omero_disks.prom}"
OUT_DIR=$(dirname "$OUT_FILE")
TMP_FILE="${OUT_DIR}/.${OUT_FILE##*/}.tmp"
INTERVAL="${SMART_DISK_MONITOR_INTERVAL_SECONDS:-30}"
OMERO_DATA_PATH="${SMART_DISK_MONITOR_OMERO_DATA_PATH:-/data/omero}"
DATABASE_PATH="${SMART_DISK_MONITOR_DATABASE_PATH:-/data/db}"
PLUGIN_DATABASE_PATH="${SMART_DISK_MONITOR_PLUGIN_DATABASE_PATH:-/data/db-plugin}"

echo "Starting smart disk monitor..."

mkdir -p "$OUT_DIR"
trap 'rm -f "$TMP_FILE"' EXIT

# Return whether uint. Inputs: shell arguments and environment. Output: success or failure status.
is_uint() {
    case "$1" in
        "" | *[!0-9]*)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

if ! is_uint "$INTERVAL" || [ "$INTERVAL" -lt 1 ]; then
    INTERVAL=30
fi

# Check path. Inputs: shell arguments and environment. Output: command status and side effects.
check_path() {
    name=$1
    target_path=$2

    if [ ! -d "$target_path" ]; then
        echo "Warning: Path $target_path does not exist, skipping." >&2
        return
    fi

    if ! df_output=$(df -kP "$target_path" 2>/dev/null); then
        echo "Warning: df failed for $target_path, skipping." >&2
        return
    fi

    df_fields=$(
        printf '%s\n' "$df_output" \
            | awk 'NF { total = $2; used = $3; avail = $4 } END { if (total != "") print total, used, avail }'
    )
    if [ -z "$df_fields" ]; then
        echo "Warning: Unexpected df output for $target_path, skipping." >&2
        return
    fi
    read -r total_kb used_kb avail_kb extra <<EOF
$df_fields
EOF
    if [ -n "${extra:-}" ]; then
        echo "Warning: Unexpected df output for $target_path, skipping." >&2
        return
    fi

    if ! is_uint "$total_kb" || ! is_uint "$used_kb" || ! is_uint "$avail_kb"; then
        echo "Warning: Non-numeric df output for $target_path, skipping." >&2
        return
    fi

    total_bytes=$((total_kb * 1024))
    used_bytes=$((used_kb * 1024))
    avail_bytes=$((avail_kb * 1024))

    {
        echo "omero_volume_bytes_total{name=\"$name\"} $total_bytes"
        echo "omero_volume_bytes_free{name=\"$name\"} $avail_bytes"
        echo "omero_volume_bytes_used{name=\"$name\"} $used_bytes"
    } >> "$TMP_FILE"
}

while true; do
    {
        echo "# HELP omero_volume_bytes_total Total size of the storage volume in bytes"
        echo "# TYPE omero_volume_bytes_total gauge"
        echo "# HELP omero_volume_bytes_free Free space of the storage volume in bytes"
        echo "# TYPE omero_volume_bytes_free gauge"
        echo "# HELP omero_volume_bytes_used Used space of the storage volume in bytes"
        echo "# TYPE omero_volume_bytes_used gauge"
    } > "$TMP_FILE"

    check_path "omero_data" "$OMERO_DATA_PATH"
    check_path "database" "$DATABASE_PATH"
    check_path "plugin_database" "$PLUGIN_DATABASE_PATH"

    mv -f "$TMP_FILE" "$OUT_FILE"

    sleep "$INTERVAL"
done
