#!/bin/sh

# Set output file
OUT_FILE="/out/omero_disks.prom"
TMP_FILE="/out/omero_disks.prom.tmp"

# Check interval
INTERVAL=30

echo "Starting smart disk monitor..."

while true; do
    # Clear temp file and write headers
    echo "# HELP omero_volume_bytes_total Total size of the storage volume in bytes" > "$TMP_FILE"
    echo "# TYPE omero_volume_bytes_total gauge" >> "$TMP_FILE"
    echo "# HELP omero_volume_bytes_free Free space of the storage volume in bytes" >> "$TMP_FILE"
    echo "# TYPE omero_volume_bytes_free gauge" >> "$TMP_FILE"
    echo "# HELP omero_volume_bytes_used Used space of the storage volume in bytes" >> "$TMP_FILE"
    echo "# TYPE omero_volume_bytes_used gauge" >> "$TMP_FILE"

    # Function to check a path
    check_path() {
        NAME=$1
        TARGET_PATH=$2

        if [ ! -d "$TARGET_PATH" ]; then
            echo "Warning: Path $TARGET_PATH does not exist, skipping."
            return
        fi

        # Run df -k (1K blocks) on the path. 
        # -P forces POSIX output (portability).
        # tail -n1 gets the data line.
        # Output format: Filesystem 1024-blocks Used Available Capacity Mounted on
        LINE=$(df -kP "$TARGET_PATH" | tail -n1)
        
        # Extract values
        TOTAL_KB=$(echo "$LINE" | awk '{print $2}')
        USED_KB=$(echo "$LINE" | awk '{print $3}')
        AVAIL_KB=$(echo "$LINE" | awk '{print $4}')

        # Convert to bytes
        TOTAL_BYTES=$(($TOTAL_KB * 1024))
        USED_BYTES=$(($USED_KB * 1024))
        AVAIL_BYTES=$(($AVAIL_KB * 1024))

        # Write metrics
        echo "omero_volume_bytes_total{name=\"$NAME\"} $TOTAL_BYTES" >> "$TMP_FILE"
        echo "omero_volume_bytes_free{name=\"$NAME\"} $AVAIL_BYTES" >> "$TMP_FILE"
        echo "omero_volume_bytes_used{name=\"$NAME\"} $USED_BYTES" >> "$TMP_FILE"
    }

    # Check the three critical paths mounted into this container
    check_path "omero_data" "/data/omero"
    check_path "database" "/data/db"
    check_path "plugin_database" "/data/db-plugin"

    # Atomic move
    mv "$TMP_FILE" "$OUT_FILE"

    sleep "$INTERVAL"
done
