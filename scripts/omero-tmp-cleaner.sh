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
#   This host-side cleaner is the "sweep" that removes remnants older than 24h.
# =============================================================================
set -euo pipefail

TMP_DIR=""
MAX_AGE_SECONDS="86400"

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
if [[ "${TMP_DIR}" == "/" ]]; then
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

echo "[omero-tmp-cleaner] tmp_dir=${TMP_DIR} max_age_seconds=${MAX_AGE_SECONDS}"

# ---------------------------------------------------------------------------
# Delete old files (and symlinks) first.
# ---------------------------------------------------------------------------
# -xdev: do not cross filesystem boundaries
# -mindepth 1: never target the root itself
# -mmin +N: older than N minutes
# -P: never follow symlinks (default for find, explicit for clarity)
find -P "${TMP_DIR}" -xdev -mindepth 1 \( -type f -o -type l \) -mmin "+${MAX_AGE_MINUTES}" -print0 \
  | xargs -0r rm -f --

# ---------------------------------------------------------------------------
# Then prune empty directories (repeat twice to catch nested empties).
# ---------------------------------------------------------------------------
for _ in 1 2; do
    find -P "${TMP_DIR}" -xdev -mindepth 1 -type d -empty -mmin "+${MAX_AGE_MINUTES}" -print0 \
      | xargs -0r rmdir --ignore-fail-on-non-empty --
done

echo "[omero-tmp-cleaner] done"
