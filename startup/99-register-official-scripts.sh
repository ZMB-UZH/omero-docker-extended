#!/usr/bin/env bash

(
    set -euo pipefail

    REGISTER_OFFICIAL_SCRIPTS="${REGISTER_OFFICIAL_SCRIPTS:-0}"
    if [[ "${REGISTER_OFFICIAL_SCRIPTS}" != "1" ]]; then
        echo "[OMERO scripts] REGISTER_OFFICIAL_SCRIPTS != 1 -> skipping script registration."
        echo "[OMERO scripts] (This does NOT affect whether scripts can RUN; it only re-uploads them.)"
        exit 0
    fi

    OMERO_BIN="/opt/omero/server/OMERO.server/bin/omero"

    source /startup/omero-cli-safe.sh

    OMERO_HOST="localhost"
    OMERO_PORT="4064"
    SCRIPTS_DIR="/opt/omero/server/OMERO.server/lib/scripts/omero"
    MAX_PARALLEL=4

    : "${ROOTPASS:?ROOTPASS must be set}"

    echo "[OMERO scripts] Background script registration started"
    echo "[OMERO scripts] Waiting for OMERO.server JVM to start..."

    until pgrep -f "java .*omero.server.Server\$" >/dev/null 2>&1
    do
        sleep 2
    done

    echo "[OMERO scripts] OMERO.server JVM detected"
    echo "[OMERO scripts] Waiting for OMERO.server to be fully ready..."

    run_omero admin status \
        -s "${OMERO_HOST}" \
        -p "${OMERO_PORT}" \
        -u root \
        -w "${ROOTPASS}" \
        --wait \
        </dev/null \
        >/dev/null 2>&1

    echo "[OMERO scripts] Waiting for Script service to be available..."

    until run_omero script list \
        -s "${OMERO_HOST}" \
        -p "${OMERO_PORT}" \
        -u root \
        -w "${ROOTPASS}" \
        --sudo root \
        </dev/null \
        >/dev/null 2>&1
    do
        sleep 2
    done

    echo "[OMERO scripts] Script service ready"
    echo "[OMERO scripts] Glacier2 is ready"

    export OMERO_BIN
    export OMERO_HOST
    export OMERO_PORT
    export ROOTPASS
    export -f run_omero

    upload_one() {
        script="$1"
        base="$(basename "${script}" .py)"

        existing_id=$(run_omero script list \
                -s "${OMERO_HOST}" \
                -p "${OMERO_PORT}" \
                -u root \
                -w "${ROOTPASS}" \
                --sudo root \
                </dev/null 2>/dev/null \
                | grep -E "^\s*[0-9]+" \
                | while IFS='|' read -r id name rest; do
                    clean_name=$(echo "$name" | sed 's/^ *//;s/ *$//;s/\.py$//')
                    if [ "$clean_name" = "$base" ]; then
                        echo "$id" | sed 's/^ *//;s/ *$//'
                        break
                    fi
                done)

        if [ -n "$existing_id" ]; then
            echo "[OMERO scripts] Replacing existing script: ${base} (ID: ${existing_id})"

            if run_omero script replace "${existing_id}" "${script}" \
                    -s "${OMERO_HOST}" \
                    -p "${OMERO_PORT}" \
                    -u root \
                    -w "${ROOTPASS}" \
                    --sudo root \
                    </dev/null 2>&1; then
                echo "[OMERO scripts] Replaced: ${base}"
            else
                echo "[OMERO scripts] Replace failed for ${base}, trying delete+upload"

                run_omero script delete "${existing_id}" \
                    -s "${OMERO_HOST}" \
                    -p "${OMERO_PORT}" \
                    -u root \
                    -w "${ROOTPASS}" \
                    --sudo root \
                    </dev/null 2>/dev/null || true

                run_omero script upload \
                    --official \
                    --sudo root \
                    -s "${OMERO_HOST}" \
                    -p "${OMERO_PORT}" \
                    -u root \
                    -w "${ROOTPASS}" \
                    "${script}" \
                    </dev/null
            fi
            return 0
        fi

        echo "[OMERO scripts] Uploading new: ${base}"

        run_omero script upload \
            --official \
            --sudo root \
            -s "${OMERO_HOST}" \
            -p "${OMERO_PORT}" \
            -u root \
            -w "${ROOTPASS}" \
            "${script}" \
            </dev/null
    }

    export -f upload_one

    echo "[OMERO scripts] Parallel upload (max ${MAX_PARALLEL})"

    find "${SCRIPTS_DIR}" -type f -name "*.py" \
        | sort \
        | xargs -n 1 -P "${MAX_PARALLEL}" -I {} \
            bash -c 'upload_one "$@"' _ {}

    echo "[OMERO scripts] Registration finished"
) >> /opt/omero/server/OMERO.server/var/log/register-official-scripts.log 2>&1 &
