#!/usr/bin/env bash
# Common installer helpers for OMERO host-side systemd services.
#
# This file is installer-only. Runtime service scripts remain standalone after
# Perform OMERO die. Inputs: shell arguments and environment. Output: command status and side effects.

omero_die() {
    echo "ERROR: $*" >&2
    exit 1
}

# Perform OMERO require root. Inputs: shell arguments and environment. Output: command status and side effects.
omero_require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        omero_die "This script must run as root (use sudo)."
    fi
}

# Perform OMERO canonical existing directory. Inputs: shell arguments and environment. Output: command status and side effects.
omero_canonical_existing_dir() {
    local raw_path="$1"
    local label="$2"
    local resolved_path

    [[ -n "${raw_path}" ]] || omero_die "${label} is required."
    resolved_path="$(readlink -f -- "${raw_path}")" || {
        omero_die "Unable to resolve ${label}: ${raw_path}"
    }
    [[ -d "${resolved_path}" ]] || {
        omero_die "${label} does not exist or is not a directory: ${resolved_path}"
    }
    printf '%s\n' "${resolved_path}"
}

# Perform OMERO systemd escape. Inputs: shell arguments and environment. Output: command status and side effects.
omero_systemd_escape() {
    local LC_ALL=C
    local value="$1"
    local escaped=""
    local char hex index

    for ((index = 0; index < ${#value}; index++)); do
        char="${value:index:1}"
        case "${char}" in
            [A-Za-z0-9/._:@+-])
                escaped+="${char}"
                ;;
            *)
                printf -v hex '%02x' "'${char}"
                escaped+="\\x${hex}"
                ;;
        esac
    done

    printf '%s' "${escaped}"
}

# Perform OMERO environment quote. Inputs: shell arguments and environment. Output: command status and side effects.
omero_environment_quote() {
    local LC_ALL=C
    local value="$1"
    local quoted=""
    local char index

    for ((index = 0; index < ${#value}; index++)); do
        char="${value:index:1}"
        case "${char}" in
            $'\n' | $'\r')
                omero_die "Environment values must not contain newlines."
                ;;
            \\)
                quoted+="\\\\"
                ;;
            '"')
                quoted+="\\\""
                ;;
            '$')
                quoted+="\\$"
                ;;
            '`')
                quoted+="\\\`"
                ;;
            *)
                quoted+="${char}"
                ;;
        esac
    done

    printf '"%s"' "${quoted}"
}

# Perform OMERO render systemd unit. Inputs: shell arguments and environment. Output: command status and side effects.
omero_render_systemd_unit() {
    local source_file="$1"
    local dest_file="$2"
    shift 2

    local dest_dir tmp_file text placeholder value
    dest_dir="$(dirname -- "${dest_file}")"
    install -d -m 0755 "${dest_dir}"

    text="$(< "${source_file}")"
    while [[ $# -gt 0 ]]; do
        [[ $# -ge 2 ]] || omero_die "Internal error: unmatched unit placeholder."
        placeholder="$1"
        value="$2"
        shift 2
        text="${text//__${placeholder}__/$(omero_systemd_escape "${value}")}"
    done

    if printf '%s\n' "${text}" | grep -Eq '__[A-Z0-9_]+__'; then
        omero_die "Unresolved placeholder while rendering ${source_file}."
    fi

    tmp_file="$(mktemp "${dest_dir}/.$(basename -- "${dest_file}").XXXXXX")"
    printf '%s\n' "${text}" > "${tmp_file}"
    rm -f -- "${dest_file}"
    install -D -T -m 0644 "${tmp_file}" "${dest_file}"
    rm -f -- "${tmp_file}"
}

# Perform OMERO replace systemd units. Inputs: shell arguments and environment. Output: command status and side effects.
omero_replace_systemd_units() {
    local systemctl_bin="$1"
    local systemd_system_dir="$2"
    shift 2

    "${systemctl_bin}" disable --now "$@" >/dev/null 2>&1 || true
    "${systemctl_bin}" reset-failed "$@" >/dev/null 2>&1 || true

    local unit_name
    for unit_name in "$@"; do
        omero_remove_systemd_unit_artifacts "${systemd_system_dir}" "${unit_name}"
    done
}

# Perform OMERO validate systemd unit name. Inputs: shell arguments and environment. Output: command status and side effects.
omero_validate_systemd_unit_name() {
    local unit_name="$1"

    case "${unit_name}" in
        "" | */* | .* | *[!A-Za-z0-9_.@:-]*)
            omero_die "Unsafe systemd unit name: ${unit_name}"
            ;;
    esac
    case "${unit_name}" in
        *.service | *.timer | *.path) ;;
        *) omero_die "Unsupported systemd unit type: ${unit_name}" ;;
    esac
}

# Perform OMERO remove systemd unit artifacts. Inputs: shell arguments and environment. Output: command status and side effects.
omero_remove_systemd_unit_artifacts() {
    local systemd_system_dir="$1"
    local unit_name="$2"
    local dependency_dir
    local nullglob_was_set=0

    [[ -n "${systemd_system_dir}" ]] || omero_die "Systemd directory is required."
    [[ "${systemd_system_dir}" != "/" ]] || omero_die "Refusing to clean root directory."
    omero_validate_systemd_unit_name "${unit_name}"

    install -d -m 0755 "${systemd_system_dir}"
    rm -f -- "${systemd_system_dir%/}/${unit_name}"
    rm -rf -- "${systemd_system_dir:?}/${unit_name:?}.d"

    if shopt -q nullglob; then
        nullglob_was_set=1
    fi
    shopt -s nullglob
    for dependency_dir in \
        "${systemd_system_dir%/}"/*.requires \
        "${systemd_system_dir%/}"/*.wants; do
        [[ -d "${dependency_dir}" ]] || continue
        rm -rf -- "${dependency_dir:?}/${unit_name:?}"
    done
    if [[ "${nullglob_was_set}" -eq 0 ]]; then
        shopt -u nullglob
    fi
}

# Perform OMERO install verified. Inputs: shell arguments and environment. Output: command status and side effects.
omero_install_verified() {
    local source_file="$1"
    local dest_file="$2"
    local mode="$3"
    local source_real dest_real source_sha dest_sha

    source_real="$(readlink -f -- "${source_file}")"
    if [[ -e "${dest_file}" ]]; then
        dest_real="$(readlink -f -- "${dest_file}")"
    else
        dest_real=""
    fi

    if [[ -n "${dest_real}" && "${source_real}" = "${dest_real}" ]]; then
        chmod "${mode}" "${dest_file}"
    else
        rm -f -- "${dest_file}"
        install -D -T -m "${mode}" "${source_file}" "${dest_file}"
    fi

    source_sha="$(sha256sum "${source_file}" | awk '{print $1}')"
    dest_sha="$(sha256sum "${dest_file}" | awk '{print $1}')"
    if [[ "${source_sha}" != "${dest_sha}" ]]; then
        echo "ERROR: Integrity check failed for ${dest_file}." >&2
        echo "ERROR: expected_sha256=${source_sha} actual_sha256=${dest_sha}" >&2
        exit 1
    fi
    printf '%s\n' "${source_sha}"
}

# Perform OMERO install missing deb packages. Inputs: shell arguments and environment. Output: command status and side effects.
omero_install_missing_deb_packages() {
    local missing_packages=()
    local package_name

    command -v dpkg-query >/dev/null 2>&1 || {
        omero_die "dpkg-query is required; this installer supports Debian and Ubuntu hosts."
    }
    command -v apt-get >/dev/null 2>&1 || {
        omero_die "apt-get is required; this installer supports Debian and Ubuntu hosts."
    }

    for package_name in "$@"; do
        if ! dpkg-query -W -f='${Status}' "${package_name}" 2>/dev/null \
            | grep -qx 'install ok installed'; then
            missing_packages+=("${package_name}")
        fi
    done

    if [[ ${#missing_packages[@]} -eq 0 ]]; then
        echo "  All required packages are installed."
        return 0
    fi

    echo "  Installing missing packages: ${missing_packages[*]}"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install \
        --no-install-recommends -y -qq "${missing_packages[@]}"
}

# Perform OMERO mount context. Inputs: shell arguments and environment. Output: command status and side effects.
omero_mount_context() {
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

# Perform OMERO mount options include. Inputs: shell arguments and environment. Output: command status and side effects.
omero_mount_options_include() {
    local options="$1"
    local wanted="$2"
    case ",${options}," in
        *",${wanted},"*) return 0 ;;
        *) return 1 ;;
    esac
}
