#!/usr/bin/env bash
# =============================================================================
# omero-tmp-cleaner.sh — Host-side cleanup for OMERO_TMP_PATH
#
# Deletes temporary artifacts older than a given age from the OMERO_TMP_PATH tree.
# This is designed to be invoked by systemd (timer) on Ubuntu 24.04+ and Debian 13+.
#
# Safety properties:
#   - Requires an explicit --tmp-dir argument (no defaults).
#   - Refuses to operate on / or very short/unsafe paths.
#   - Never follows symlinks.
#   - Uses -xdev to avoid crossing filesystem boundaries.
#
# NOTE:
#   Immediate deletion of large artifacts after a successful job is handled in-plugin.
#   This host-side cleaner is the default 24h sweep, but it also honors per-path
#   deferred-cleanup markers written by plugins for longer retention when needed.
# =============================================================================
set -euo pipefail

TMP_DIR=""
MAX_AGE_SECONDS="86400"
RETENTION_DIR_MARKER_NAME=".omero-retain-until"
RETENTION_FILE_MARKER_SUFFIX=".retain-until"
declare -a RETAINED_DIRS=()
declare -a RETAINED_FILES=()
declare -a RETAINED_MARKERS=()

usage() {
    echo "Usage: $0 --tmp-dir <DIR> [--max-age-seconds <SECONDS>]" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tmp-dir)
            TMP_DIR="${2:-}"
            shift 2
            ;;
        --max-age-seconds)
            MAX_AGE_SECONDS="${2:-}"
            shift 2
            ;;
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
done

if [[ -z "${TMP_DIR}" ]]; then
    echo "ERROR: --tmp-dir is required." >&2
    usage
    exit 2
fi

TMP_DIR="$(readlink -f "${TMP_DIR}")"

# Very defensive safety checks
if [[ "${TMP_DIR}" = "/" ]]; then
    echo "ERROR: Refusing to operate on /" >&2
    exit 3
fi
if [[ ! -d "${TMP_DIR}" ]]; then
    echo "ERROR: Not a directory: ${TMP_DIR}" >&2
    exit 3
fi
# Refuse paths that are suspiciously short (e.g. /tmp) unless they contain 'omero'
if [[ ${#TMP_DIR} -lt 10 && "${TMP_DIR}" != *omero* ]]; then
    echo "ERROR: Refusing to operate on unsafe tmp-dir path: ${TMP_DIR}" >&2
    exit 3
fi

if ! [[ "${MAX_AGE_SECONDS}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --max-age-seconds must be an integer." >&2
    exit 2
fi

MAX_AGE_MINUTES=$(( MAX_AGE_SECONDS / 60 ))
if [[ "${MAX_AGE_MINUTES}" -lt 1 ]]; then
    MAX_AGE_MINUTES=1
fi

read_retention_expiry() {
    local marker="$1"
    local expiry=""

    if [[ ! -f "${marker}" || -L "${marker}" ]]; then
        return 1
    fi
    IFS= read -r expiry < "${marker}" || true
    expiry="${expiry//[$' \t\r\n']/}"
    if [[ ! "${expiry}" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    printf '%s\n' "${expiry}"
}

path_is_within() {
    local path="$1"
    local root="$2"
    [[ "${path}" = "${root}" || "${path}" = "${root}"/* ]]
}

load_active_retention_markers() {
    local now_epoch marker expiry marker_name target_name target_path
    now_epoch="$(date +%s)"

    while IFS= read -r -d '' marker; do
        expiry="$(read_retention_expiry "${marker}" || true)"
        if [[ -z "${expiry}" || "${expiry}" -le "${now_epoch}" ]]; then
            continue
        fi

        marker_name="$(basename "${marker}")"
        if [[ "${marker_name}" = "${RETENTION_DIR_MARKER_NAME}" ]]; then
            RETAINED_DIRS+=("$(dirname "${marker}")")
            RETAINED_MARKERS+=("${marker}")
            continue
        fi

        if [[ "${marker_name}" = .*"${RETENTION_FILE_MARKER_SUFFIX}" ]]; then
            target_name="${marker_name#.}"
            target_name="${target_name%"${RETENTION_FILE_MARKER_SUFFIX}"}"
            target_path="$(dirname "${marker}")/${target_name}"
            RETAINED_FILES+=("${target_path}")
            RETAINED_MARKERS+=("${marker}")
        fi
    done < <(
        find -P "${TMP_DIR}" -xdev -type f \
            \( -name "${RETENTION_DIR_MARKER_NAME}" -o -name ".*${RETENTION_FILE_MARKER_SUFFIX}" \) \
            -print0
    )
}

path_is_structural() {
    # Protect namespace directories (depth 1) and their tmp/ subdirectories
    # (depth 2) from deletion.  These are the TMPDIR targets that running
    # containers rely on; removing them breaks session storage and temp file
    # creation until the next container restart.
    local path="$1"
    local relative="${path#"${TMP_DIR}"/}"

    [[ "${relative}" = "${path}" ]] && return 1

    case "${relative}" in
        # depth-1 namespace dir  (e.g. omero-web, omero-server, omeroweb-import)
        */*) ;;
        *)   return 0 ;;
    esac

    case "${relative}" in
        # depth-2 tmp dir  (e.g. omero-web/tmp, omero-server/tmp)
        */tmp) return 0 ;;
    esac

    return 1
}

path_is_retained() {
    local path="$1"
    local retained_dir retained_file retained_marker

    if path_is_structural "${path}"; then
        return 0
    fi

    for retained_dir in "${RETAINED_DIRS[@]}"; do
        if path_is_within "${path}" "${retained_dir}"; then
            return 0
        fi
    done

    for retained_file in "${RETAINED_FILES[@]}"; do
        if [[ "${path}" = "${retained_file}" ]]; then
            return 0
        fi
    done

    for retained_marker in "${RETAINED_MARKERS[@]}"; do
        if [[ "${path}" = "${retained_marker}" ]]; then
            return 0
        fi
    done

    return 1
}

load_active_retention_markers

echo "[omero-tmp-cleaner] tmp_dir=${TMP_DIR} max_age_seconds=${MAX_AGE_SECONDS}"
echo "[omero-tmp-cleaner] retained_dirs=${#RETAINED_DIRS[@]} retained_files=${#RETAINED_FILES[@]}"

# ---------------------------------------------------------------------------
# Delete old files (and symlinks) first.
# ---------------------------------------------------------------------------
# -xdev: do not cross filesystem boundaries
# -mindepth 1: never target the root itself
# -mmin +N: older than N minutes
# -P: never follow symlinks (default for find, explicit for clarity)
while IFS= read -r -d '' candidate; do
    if path_is_retained "${candidate}"; then
        continue
    fi
    rm -f -- "${candidate}"
done < <(
    find -P "${TMP_DIR}" -xdev -mindepth 1 \( -type f -o -type l \) -mmin "+${MAX_AGE_MINUTES}" -print0
)

# ---------------------------------------------------------------------------
# Then prune empty directories (repeat twice to catch nested empties).
# ---------------------------------------------------------------------------
for _ in 1 2; do
    while IFS= read -r -d '' candidate; do
        if path_is_retained "${candidate}"; then
            continue
        fi
        rmdir --ignore-fail-on-non-empty -- "${candidate}"
    done < <(
        find -P "${TMP_DIR}" -xdev -mindepth 1 -type d -empty -mmin "+${MAX_AGE_MINUTES}" -print0
    )
done

echo "[omero-tmp-cleaner] done"
