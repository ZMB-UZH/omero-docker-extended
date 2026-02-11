#!/usr/bin/env bash
set -euo pipefail

OMERO_SERVER_ROOT="/opt/omero/server"
SETUPTOOLS_VERSION="${SETUPTOOLS_VERSION:-80.9.0}"
TARGET_VENV_PATH="${TARGET_VENV_PATH:-}"

if [[ ! -d "${OMERO_SERVER_ROOT}" ]]; then
    echo "ERROR: OMERO server root not found at ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

mapfile -t VENV_DIRS < <(find -L "${OMERO_SERVER_ROOT}" -maxdepth 1 -mindepth 1 \( -type d -o -type l \) -name 'venv*' | sort -u -V)

if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then
    echo "ERROR: No OMERO virtual environments found under ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

if [[ -z "${TARGET_VENV_PATH}" ]]; then
    TARGET_VENV_PATH="${VENV_DIRS[-1]}"
fi

if [[ ! -e "${TARGET_VENV_PATH}" ]]; then
    echo "ERROR: TARGET_VENV_PATH does not exist: ${TARGET_VENV_PATH}" >&2
    exit 1
fi

TARGET_VENV_PATH="$(realpath "${TARGET_VENV_PATH}")"

selected_venv=""
for venv_dir in "${VENV_DIRS[@]}"; do
    resolved_venv_dir="$(realpath "${venv_dir}")"
    if [[ "${resolved_venv_dir}" == "${TARGET_VENV_PATH}" ]]; then
        selected_venv="${venv_dir}"
        break
    fi
done

if [[ -z "${selected_venv}" ]]; then
    echo "ERROR: TARGET_VENV_PATH (${TARGET_VENV_PATH}) is not a discovered venv under ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

if [[ "${#VENV_DIRS[@]}" -gt 1 ]]; then
    echo "Found multiple OMERO virtual environments; validating selected venv only: ${selected_venv}"
fi

for venv_dir in "${selected_venv}"; do
    python_bin="${venv_dir}/bin/python"
    if [[ ! -x "${python_bin}" ]]; then
        echo "ERROR: Invalid OMERO virtual environment (missing python): ${venv_dir}" >&2
        exit 1
    fi

    echo "Validating Python packaging tooling in ${venv_dir}"

    missing_packages="$(${python_bin} - <<'PY'
import importlib.metadata as metadata
from importlib.metadata import PackageNotFoundError

required_packages = ("pip", "setuptools", "wheel")
missing = []

for package_name in required_packages:
    try:
        metadata.version(package_name)
    except PackageNotFoundError:
        missing.append(package_name)

print(",".join(missing))
PY
)"

    missing_packages="$(echo "${missing_packages}" | tail -n 1)"
    if [[ -n "${missing_packages}" ]]; then
        target_site_packages="$(${python_bin} - <<'PY'
import sysconfig
print(sysconfig.get_path("purelib"))
PY
)"

        echo "Packaging tools missing in ${venv_dir}: ${missing_packages}" >&2
        echo "Attempting recovery in ${target_site_packages}" >&2

        if [[ ! -d "${target_site_packages}" || ! -w "${target_site_packages}" ]]; then
            echo "ERROR: Cannot repair Python tooling in ${venv_dir}. ${target_site_packages} is not writable by user $(id -un)." >&2
            echo "ERROR: Fix ownership/permissions for ${target_site_packages}, or pre-install missing packages during image build." >&2
            exit 1
        fi

        IFS=',' read -r -a missing_array <<< "${missing_packages}"
        install_args=()
        for package_name in "${missing_array[@]}"; do
            if [[ "${package_name}" == "setuptools" ]]; then
                install_args+=("setuptools==${SETUPTOOLS_VERSION}")
            else
                install_args+=("${package_name}")
            fi
        done

        "${python_bin}" -m pip install --no-cache-dir --upgrade --target "${target_site_packages}" "${install_args[@]}"

        remaining_missing="$(${python_bin} - <<'PY'
import importlib.metadata as metadata
from importlib.metadata import PackageNotFoundError

required_packages = ("pip", "setuptools", "wheel")
missing = []

for package_name in required_packages:
    try:
        metadata.version(package_name)
    except PackageNotFoundError:
        missing.append(package_name)

print(",".join(missing))
PY
)"
        remaining_missing="$(echo "${remaining_missing}" | tail -n 1)"

        if [[ -n "${remaining_missing}" ]]; then
            echo "ERROR: Python packaging recovery failed in ${venv_dir}; still missing: ${remaining_missing}" >&2
            exit 1
        fi
    fi
done
