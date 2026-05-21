#!/usr/bin/env bash
# shellcheck shell=bash
# =============================================================================
# enable-storage-quotas.sh - Enable host ext4 project quotas for OMERO data.
#
# This script is intentionally fail-closed. It verifies the operating system,
# package/tool surface, kernel/filesystem quota behavior, target filesystem
# type, fstab entry, and mount state before mutating the OMERO data filesystem.
# =============================================================================
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "${SCRIPT_PATH}" in
    */*) SCRIPT_DIR_PART="${SCRIPT_PATH%/*}" ;;
    *) SCRIPT_DIR_PART="." ;;
esac
SCRIPT_DIR="$(cd -P -- "${SCRIPT_DIR_PART}" && pwd -P)"
REPO_ROOT="$(cd -P -- "${SCRIPT_DIR%/}/.." && pwd -P)"
INSTALLATION_PATHS_ENV="${OMERO_QUOTA_INSTALLATION_PATHS_ENV:-${REPO_ROOT}/installation_paths.env}"
CONFIRMATION_FLAG="--yes-i-have-a-backup"
COMPOSE_STOPPED=0
FSTAB_BACKUP_PATH=""
FSTAB_CHANGED=0
REMOUNT_NEEDED=0
QUOTA_TARGET=""
OMERO_QUOTA_CREATE_DATA_DIR="${OMERO_QUOTA_CREATE_DATA_DIR:-0}"
OMERO_QUOTA_SKIP_COMPOSE="${OMERO_QUOTA_SKIP_COMPOSE:-0}"

if [[ "${EUID}" -eq 0 ]]; then
    SUDO=()
else
    SUDO=(sudo)
fi

# Print usage text. Inputs: none. Output: stderr usage and command status.
usage() {
    printf '%s\n' \
"Usage: $0 ${CONFIRMATION_FLAG}" \
"" \
"Enables ext4 project quotas for OMERO_USER_DATA_PATH from installation_paths.env." \
"The command may stop the Compose stack and unmount a non-root OMERO data" \
"filesystem. It never force-unmounts, lazy-unmounts, or enables the ext4" \
"'project' feature on a running root filesystem." >&2
}

# Print an error and exit. Inputs: message text. Output: stderr and exit.
die() {
    echo "ERROR: $*" >&2
    exit 1
}

# Print an informational message. Inputs: message text. Output: stdout.
info() {
    echo "$*"
}

# Require an executable command. Inputs: command name. Output: command status.
require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Parse CLI arguments. Inputs: shell arguments. Output: command status.
parse_args() {
    if [ "$#" -eq 1 ] && [ "$1" = "--help" ]; then
        usage
        exit 0
    fi
    if [[ $# -ne 1 || "$1" != "${CONFIRMATION_FLAG}" ]]; then
        usage
        die "Refusing to continue without ${CONFIRMATION_FLAG}."
    fi
}

# Verify supported host OS. Inputs: /etc/os-release. Output: command status.
check_supported_os() {
    local os_id="" version_id="" line name value

    [[ -r /etc/os-release ]] || die "/etc/os-release is not readable."
    while IFS= read -r line; do
        case "${line}" in
            ID=* | VERSION_ID=*)
                name="${line%%=*}"
                value="${line#*=}"
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                case "${name}" in
                    ID) os_id="${value}" ;;
                    VERSION_ID) version_id="${value}" ;;
                esac
                ;;
        esac
    done </etc/os-release

    case "${os_id}:${version_id}" in
        debian:13 | ubuntu:26.04) ;;
        *)
            die "This quota enablement command supports Debian 13 and Ubuntu 26.04 LTS only."
            ;;
    esac
}

# Install required Debian packages. Inputs: apt repository state. Output: side effects.
install_required_packages() {
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none apt-get update
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none apt-get install -y \
        coreutils \
        e2fsprogs \
        grep \
        mount \
        python3 \
        quota \
        sed \
        util-linux
}

# Run Docker Compose with this repository's env-file contract. Inputs: args. Output: command status.
compose() {
    if [[ "${OMERO_QUOTA_SKIP_COMPOSE}" -eq 1 ]]; then
        return 0
    fi

    docker compose \
        --env-file "${REPO_ROOT}/.env" \
        --env-file "${INSTALLATION_PATHS_ENV}" \
        --env-file "${REPO_ROOT}/env/omero_secrets.env" \
        --env-file "${REPO_ROOT}/env/omeroserver.env" \
        --env-file "${REPO_ROOT}/env/omeroweb.env" \
        --env-file "${REPO_ROOT}/env/omero-celery.env" \
        --env-file "${REPO_ROOT}/env/grafana.env" \
        "$@"
}

# Verify Compose can manage this installation before filesystem changes. Inputs: none. Output: command status.
preflight_compose_if_needed() {
    if [[ "${OMERO_QUOTA_SKIP_COMPOSE}" -eq 1 ]]; then
        return 0
    fi
    require_command docker
    docker compose version >/dev/null
    compose config --quiet
}

# Verify systemd is usable before filesystem changes. Inputs: systemctl. Output: command status.
preflight_systemd() {
    systemctl list-unit-files --no-pager >/dev/null \
        || die "systemctl is not operational; refusing to change storage quota settings."
}

# Show service status without changing success/failure of quota enablement. Inputs: systemctl. Output: stdout/stderr.
show_unit_status() {
    systemctl status omero-quota-enforcer.path --no-pager || true
    systemctl status omero-quota-enforcer.timer --no-pager || true
}

# Run a destructive-operation self-test on a disposable ext4 image. Inputs: host kernel/tools. Output: command status.
quota_self_test() (
    set -euo pipefail

    local workdir image mountpoint mounted
    workdir="$(mktemp -d)"
    image="${workdir}/fs.img"
    mountpoint="${workdir}/mnt"
    mounted=0
    chmod 0755 "${workdir}"

    trap 'if [[ "${mounted}" -eq 1 ]]; then
        "${SUDO[@]}" umount "${mountpoint}" >/dev/null 2>&1 || true
    fi
    rm -rf -- "${workdir}"' EXIT

    mkdir -p "${mountpoint}"
    truncate -s 128M "${image}"
    "${SUDO[@]}" mkfs.ext4 -q "${image}"
    "${SUDO[@]}" tune2fs -O project "${image}" >/dev/null
    "${SUDO[@]}" mount -o loop,prjquota "${image}" "${mountpoint}"
    mounted=1
    findmnt -M "${mountpoint}" -no OPTIONS | tr ',' '\n' | grep -qx prjquota

    "${SUDO[@]}" mkdir "${mountpoint}/quota-test"
    "${SUDO[@]}" chattr -p 200000 "${mountpoint}/quota-test"
    "${SUDO[@]}" chattr +P "${mountpoint}/quota-test"
    "${SUDO[@]}" chmod 0777 "${mountpoint}/quota-test"
    "${SUDO[@]}" setquota -P 200000 1024 1024 0 0 "${mountpoint}"
    if "${SUDO[@]}" setpriv --reuid 65534 --regid 65534 --clear-groups \
        dd if=/dev/zero of="${mountpoint}/quota-test/too-large.bin" \
        bs=1M count=2 status=none 2>"${workdir}/dd.err"; then
        die "Project-quota self-test failed: a write over the test quota succeeded."
    fi
    if ! grep -Eqi "quota|Disk quota exceeded|No space left" "${workdir}/dd.err"; then
        cat "${workdir}/dd.err" >&2
        die "Project-quota self-test failed for an unexpected reason."
    fi
)

# Discover the fstab entry that owns a path. Inputs: data path. Output: env assignments.
discover_fstab_entry() {
    python3 - "$1" <<'PY'
import os
import sys
from pathlib import Path

data_dir = os.path.normpath(sys.argv[1])


def fstab_unescape(value: str) -> str:
    result = ""
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 3 < len(value):
            maybe_octal = value[index + 1 : index + 4]
            if all(char in "01234567" for char in maybe_octal):
                result += chr(int(maybe_octal, 8))
                index += 4
                continue
        result += value[index]
        index += 1
    return result


def contains_path(parent: str, child: str) -> bool:
    parent = os.path.normpath(parent)
    child = os.path.normpath(child)
    return parent == "/" or child == parent or child.startswith(parent.rstrip("/") + "/")


best = None
for raw_line in Path("/etc/fstab").read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    fields = line.split()
    if len(fields) < 4:
        continue
    source, target, fs_type, options = fields[:4]
    target = os.path.normpath(fstab_unescape(target))
    if contains_path(target, data_dir) and (best is None or len(target) > len(best[1])):
        best = (source, target, fs_type, options)

if best:
    for value in best:
        print(value)
PY
}

# Resolve an fstab source to a block device. Inputs: source spec. Output: stdout path.
resolve_block_device() {
    case "$1" in
        /dev/*)
            readlink -f -- "$1"
            ;;
        UUID=* | LABEL=* | PARTUUID=* | PARTLABEL=*)
            findfs "$1"
            ;;
        *)
            die "Unsupported OMERO data source reference: $1"
            ;;
    esac
}

# Ensure a project-quota option exists on exactly one active fstab entry. Inputs: QUOTA_TARGET. Output: side effects.
ensure_fstab_prjquota() {
    local backup_path=""

    backup_path="$("${SUDO[@]}" env QUOTA_TARGET="${QUOTA_TARGET}" python3 - <<'PY'
from pathlib import Path
import datetime
import os
import re
import shutil

target = os.environ["QUOTA_TARGET"]
fstab = Path("/etc/fstab")
lines = fstab.read_text(encoding="utf-8").splitlines()
updated = []
matches = 0
changed = False


def fstab_unescape(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        updated.append(line)
        continue
    fields = list(re.finditer(r"\S+", line))
    if len(fields) < 4 or fstab_unescape(fields[1].group(0)) != target:
        updated.append(line)
        continue
    matches += 1
    options_token = fields[3].group(0)  # skipcq: SCT-A000
    options = options_token.split(",")
    if "prjquota" not in options and "project" not in options:
        replacement = ",".join([*options, "prjquota"])
        line = f"{line[: fields[3].start()]}{replacement}{line[fields[3].end() :]}"
        changed = True
    updated.append(line)

if matches == 0:
    raise SystemExit(
        f"/etc/fstab has no active entry for {target}; add prjquota manually, then rerun."
    )
if matches > 1:
    raise SystemExit(f"/etc/fstab has {matches} active entries for {target}; fix it manually.")
if changed:
    backup = Path(
        f"/etc/fstab.omero-quota."
        f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S%f')}.bak"
    )
    shutil.copy2(fstab, backup)
    temp_path = fstab.with_name(f".{fstab.name}.omero-quota.tmp")
    temp_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    shutil.copystat(fstab, temp_path)
    os.replace(temp_path, fstab)
    print(backup)
PY
)"
    if [[ -n "${backup_path}" ]]; then
        FSTAB_BACKUP_PATH="${backup_path}"
        FSTAB_CHANGED=1
    fi
}

# Restore services/mounts after a failing mutation. Inputs: shell exit status. Output: side effects.
cleanup_on_error() { # skipcq: SH-2329 - invoked through the EXIT trap in enable_project_quotas.
    local status=$?
    if [[ "${FSTAB_CHANGED}" -eq 1 && -n "${FSTAB_BACKUP_PATH}" && -f "${FSTAB_BACKUP_PATH}" ]]; then
        "${SUDO[@]}" cp -a -- "${FSTAB_BACKUP_PATH}" /etc/fstab || true
    fi
    if [[ "${REMOUNT_NEEDED}" -eq 1 && -n "${QUOTA_TARGET}" ]]; then
        if ! findmnt -M "${QUOTA_TARGET}" >/dev/null; then
            "${SUDO[@]}" mount "${QUOTA_TARGET}" || true
        fi
    fi
    if [[ "${COMPOSE_STOPPED}" -eq 1 ]]; then
        compose up -d || true
    fi
    exit "${status}"
}

# Load and validate OMERO_USER_DATA_PATH. Inputs: installation_paths.env. Output: OMERO_DATA_DIR.
load_omero_data_dir() {
    [[ -f "${REPO_ROOT}/docker-compose.yml" ]] || die "docker-compose.yml was not found in ${REPO_ROOT}."
    [[ -f "${INSTALLATION_PATHS_ENV}" ]] || {
        die "installation paths env file was not found: ${INSTALLATION_PATHS_ENV}"
    }

    python3 - "${INSTALLATION_PATHS_ENV}" <<'PY'
import os
import re
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
values: dict[str, str] = {}
name_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
var_re = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        continue
    name, value = line.split("=", 1)
    name = name.strip()
    if not name_re.fullmatch(name):
        raise SystemExit(f"invalid variable name in {env_path}: {name!r}")
    values[name] = strip_optional_quotes(value.strip())


def expand(value: str, stack: tuple[str, ...] = ()) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in stack:
            raise SystemExit(f"cyclic variable reference in {env_path}: {' -> '.join((*stack, name))}")
        if name not in values:
            raise SystemExit(f"undefined variable reference in {env_path}: {name}")
        return expand(values[name], (*stack, name))

    return var_re.sub(replace, value)


if "OMERO_USER_DATA_PATH" not in values:
    raise SystemExit("OMERO_USER_DATA_PATH must be set in installation_paths.env.")
omero_user_data_path = expand(values["OMERO_USER_DATA_PATH"])
if not os.path.isabs(omero_user_data_path):
    raise SystemExit("OMERO_USER_DATA_PATH must resolve to an absolute path.")
print(os.path.normpath(omero_user_data_path))
PY
}

# Discover the OMERO data filesystem. Inputs: OMERO_DATA_DIR. Output: global variables.
discover_quota_target() {
    local active_fstype
    local -a discovery_fields

    FSTAB_SOURCE=""
    FSTAB_TARGET=""
    FSTAB_FSTYPE=""
    mapfile -t discovery_fields < <(discover_fstab_entry "${OMERO_DATA_DIR}")
    if [[ "${#discovery_fields[@]}" -eq 4 ]]; then
        FSTAB_SOURCE="${discovery_fields[0]}"
        FSTAB_TARGET="${discovery_fields[1]}"
        FSTAB_FSTYPE="${discovery_fields[2]}"
    elif [[ "${#discovery_fields[@]}" -ne 0 ]]; then
        die "Unable to parse the /etc/fstab entry that owns OMERO_USER_DATA_PATH."
    fi

    if [[ -n "${FSTAB_FSTYPE:-}" && "${FSTAB_FSTYPE}" != "ext4" && "${FSTAB_FSTYPE}" != "auto" ]]; then
        die "/etc/fstab selects filesystem type '${FSTAB_FSTYPE}', not ext4."
    fi

    if [[ -n "${FSTAB_TARGET:-}" && ! -d "${FSTAB_TARGET}" ]]; then
        die "/etc/fstab mount point does not exist: ${FSTAB_TARGET}"
    fi

    if [[ -n "${FSTAB_TARGET:-}" ]] && ! findmnt -M "${FSTAB_TARGET}" >/dev/null; then
        QUOTA_SOURCE_SPEC="${FSTAB_SOURCE}"
        QUOTA_TARGET="${FSTAB_TARGET}"
        QUOTA_WAS_MOUNTED=0
    else
        if [[ ! -d "${OMERO_DATA_DIR}" && "${OMERO_QUOTA_CREATE_DATA_DIR}" -eq 1 ]]; then
            mkdir -p -- "${OMERO_DATA_DIR}"
        fi
        [[ -d "${OMERO_DATA_DIR}" ]] || die "OMERO_USER_DATA_PATH does not exist: ${OMERO_DATA_DIR}"
        QUOTA_SOURCE_SPEC="$(findmnt -T "${OMERO_DATA_DIR}" -no SOURCE)"
        QUOTA_TARGET="$(findmnt -T "${OMERO_DATA_DIR}" -no TARGET)"
        QUOTA_WAS_MOUNTED=1
        if [[ -n "${FSTAB_TARGET:-}" && "${FSTAB_TARGET}" != "${QUOTA_TARGET}" ]]; then
            die "OMERO data is on '${QUOTA_TARGET}', but /etc/fstab selects '${FSTAB_TARGET}'."
        fi
    fi

    QUOTA_DEVICE="$(resolve_block_device "${QUOTA_SOURCE_SPEC}")"
    [[ -b "${QUOTA_DEVICE}" ]] || die "Resolved OMERO data device is not a block device: ${QUOTA_DEVICE}"

    QUOTA_FSTYPE="$("${SUDO[@]}" blkid -o value -s TYPE "${QUOTA_DEVICE}")"
    [ "${QUOTA_FSTYPE}" = "ext4" ] || {
        die "The OMERO data filesystem must be ext4 before quotas can be enabled."
    }

    if [[ "${QUOTA_WAS_MOUNTED}" -eq 1 ]]; then
        active_fstype="$(findmnt -M "${QUOTA_TARGET}" -no FSTYPE)"
        [ "${active_fstype}" = "ext4" ] || die "The active OMERO data mount is '${active_fstype}', not ext4."
    fi

    info "OMERO data: ${OMERO_DATA_DIR}"
    info "Device: ${QUOTA_DEVICE}"
    info "Mount point: ${QUOTA_TARGET}"
    info "Filesystem: ${QUOTA_FSTYPE}"
}

# Return whether the ext4 project feature is enabled. Inputs: QUOTA_DEVICE. Output: command status.
project_feature_enabled() {
    "${SUDO[@]}" tune2fs -l "${QUOTA_DEVICE}" \
        | grep -Eq "Filesystem features:.*(^| )project( |$)"
}

# Return whether the OMERO data mount exposes project quotas. Inputs: OMERO_DATA_DIR. Output: command status.
mount_has_project_quota() {
    findmnt -T "${OMERO_DATA_DIR}" -no OPTIONS | tr "," "\n" | grep -Eqx "prjquota|project"
}

# Validate before unmounting a mounted data filesystem. Inputs: QUOTA_TARGET. Output: command status.
validate_unmount_preconditions() {
    if findmnt -R -M "${QUOTA_TARGET}" -n -r -o TARGET | sed "1d" | grep -q .; then
        die "Refusing to unmount '${QUOTA_TARGET}' because it has nested mounts."
    fi
}

# Enable ext4 project quotas and install the enforcer. Inputs: discovered target state. Output: side effects.
enable_project_quotas() {
    local mount_project_present project_feature_present

    project_feature_present=0
    if project_feature_enabled; then
        project_feature_present=1
    fi
    mount_project_present=0
    if [[ "${QUOTA_WAS_MOUNTED}" -eq 1 ]] && mount_has_project_quota; then
        mount_project_present=1
    fi

    if [ "${project_feature_present}" -eq 0 ] && [ "${QUOTA_TARGET}" = "/" ]; then
        die "Root is ext4, but its 'project' feature is not enabled. Run from rescue media or use a separate ext4 data filesystem."
    fi

    if [[ "${project_feature_present}" -eq 0 && "${QUOTA_WAS_MOUNTED}" -eq 1 ]]; then
        validate_unmount_preconditions
    fi
    if [[ "${QUOTA_WAS_MOUNTED}" -eq 1 ]] \
        && [[ "${project_feature_present}" -eq 0 || "${mount_project_present}" -eq 0 ]]; then
        preflight_compose_if_needed
    fi

    ensure_fstab_prjquota
    if [[ "${project_feature_present}" -eq 1 && "${QUOTA_WAS_MOUNTED}" -eq 1 ]] \
        && [[ "${mount_project_present}" -eq 1 ]]; then
        info "ext4 project quotas are already enabled on the OMERO data filesystem."
        "${SUDO[@]}" "${SCRIPT_DIR}/install-quota-enforcer.sh" "${OMERO_DATA_DIR}"
        show_unit_status
        return 0
    fi

    trap cleanup_on_error EXIT

    if [[ "${QUOTA_WAS_MOUNTED}" -eq 1 && "${OMERO_QUOTA_SKIP_COMPOSE}" -eq 0 ]]; then
        compose down
        COMPOSE_STOPPED=1
    fi

    if [[ "${project_feature_present}" -eq 0 ]]; then
        if [[ "${QUOTA_WAS_MOUNTED}" -eq 1 ]]; then
            "${SUDO[@]}" umount "${QUOTA_TARGET}"
        fi
        REMOUNT_NEEDED=1
        "${SUDO[@]}" tune2fs -O project "${QUOTA_DEVICE}"
        "${SUDO[@]}" mount "${QUOTA_TARGET}"
        REMOUNT_NEEDED=0
    elif [[ "${QUOTA_WAS_MOUNTED}" -eq 1 ]]; then
        "${SUDO[@]}" mount -o remount,prjquota "${QUOTA_TARGET}"
    else
        "${SUDO[@]}" mount "${QUOTA_TARGET}"
    fi

    project_feature_enabled || die "ext4 'project' feature verification failed after enablement."
    if [[ ! -d "${OMERO_DATA_DIR}" && "${OMERO_QUOTA_CREATE_DATA_DIR}" -eq 1 ]]; then
        mkdir -p -- "${OMERO_DATA_DIR}"
    fi
    if ! mount_has_project_quota; then
        die "Mounted OMERO data filesystem does not expose prjquota or project."
    fi
    [[ -d "${OMERO_DATA_DIR}" ]] || die "OMERO_USER_DATA_PATH is not present after mounting: ${OMERO_DATA_DIR}"

    "${SUDO[@]}" "${SCRIPT_DIR}/install-quota-enforcer.sh" "${OMERO_DATA_DIR}"
    if [[ "${COMPOSE_STOPPED}" -eq 1 ]]; then
        compose up -d
        COMPOSE_STOPPED=0
    fi
    trap - EXIT

    show_unit_status
}

# Execute the command entrypoint. Inputs: shell arguments. Output: side effects.
main() {
    parse_args "$@"
    case "${OMERO_QUOTA_CREATE_DATA_DIR}:${OMERO_QUOTA_SKIP_COMPOSE}" in
        0:0 | 0:1 | 1:0 | 1:1) ;;
        *) die "OMERO_QUOTA_CREATE_DATA_DIR and OMERO_QUOTA_SKIP_COMPOSE must be 0 or 1." ;;
    esac
    check_supported_os
    if [[ "${#SUDO[@]}" -gt 0 ]]; then
        require_command sudo
    fi
    require_command apt-get
    require_command env
    install_required_packages
    for cmd in blkid chattr cp date dd findfs findmnt grep mapfile mkfs.ext4 mkdir mount \
        python3 readlink rm sed setpriv setquota systemctl tr truncate tune2fs umount; do
        require_command "${cmd}"
    done
    preflight_systemd

    info "Running disposable ext4 project-quota self-test..."
    quota_self_test
    info "Self-test passed."

    OMERO_DATA_DIR="$(load_omero_data_dir)"
    discover_quota_target
    enable_project_quotas
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
