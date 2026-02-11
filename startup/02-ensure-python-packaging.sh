#!/usr/bin/env bash
set -euo pipefail

OMERO_SERVER_ROOT="/opt/omero/server"
SETUPTOOLS_VERSION="${SETUPTOOLS_VERSION:-80.9.0}"

if [[ ! -d "${OMERO_SERVER_ROOT}" ]]; then
    echo "ERROR: OMERO server root not found at ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

mapfile -t VENV_DIRS < <(find -L "${OMERO_SERVER_ROOT}" -maxdepth 1 -mindepth 1 \( -type d -o -type l \) -name 'venv*' | sort -u -V)

if [[ "${#VENV_DIRS[@]}" -eq 0 ]]; then
    echo "ERROR: No OMERO virtual environments found under ${OMERO_SERVER_ROOT}" >&2
    exit 1
fi

for venv_dir in "${VENV_DIRS[@]}"; do
    python_bin="${venv_dir}/bin/python"
    if [[ ! -x "${python_bin}" ]]; then
        echo "ERROR: Invalid OMERO virtual environment (missing python): ${venv_dir}" >&2
        exit 1
    fi

    echo "Validating Python packaging tooling in ${venv_dir}"
    if ! "${python_bin}" - <<'PY'
import importlib.metadata as metadata
import setuptools
import pkg_resources

for package_name in ("pip", "setuptools", "wheel"):
    print(f"{package_name}={metadata.version(package_name)}")

# setuptools is imported explicitly so this check continues to validate
# the package is importable even if deprecated helper modules are removed.
print(f"setuptools_import={setuptools.__name__}")
print(f"pkg_resources_import={pkg_resources.__name__}")
PY
    then
        echo "Packaging tools missing in ${venv_dir}; attempting recovery with pip" >&2
        "${python_bin}" -m pip install --no-cache-dir --upgrade \
            pip \
            "setuptools==${SETUPTOOLS_VERSION}" \
            wheel

        "${python_bin}" - <<'PY'
import importlib.metadata as metadata
import setuptools
import pkg_resources

for package_name in ("pip", "setuptools", "wheel"):
    print(f"Recovered {package_name}={metadata.version(package_name)}")

# setuptools is imported explicitly so this check continues to validate
# the package is importable even if deprecated helper modules are removed.
print(f"Recovered setuptools_import={setuptools.__name__}")
print(f"Recovered pkg_resources_import={pkg_resources.__name__}")
PY
    fi
done
