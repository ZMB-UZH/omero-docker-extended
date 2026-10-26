#!/usr/bin/env bash
# Build OMERO's supported Ice binding with upstream CPython compatibility patches.
set -euo pipefail

if [ "$#" -ne 1 ] || [ ! -x "$1" ]; then
    echo "Usage: install-ice-python.sh /absolute/venv/bin/python" >&2
    exit 2
fi
python="$1"
"$python" -c 'import sys; assert sys.version_info[:2] in {(3, 11), (3, 12)}, "Unqualified Ice build interpreter"'

readonly ICE_SOURCE_SHA256='4235ffeb605bcd4e22e716577f7d61e4aa1bc82f65276bb542701a81b7933356' # DevSkim: ignore DS173237 -- public PyPI source SHA-256, not a credential
readonly PYTHON311_PATCH_SHA256='228d972347a89870994235edf0b7bef23eac69b9ec46ebf13ac5c9bc03774371' # DevSkim: ignore DS173237 -- public upstream patch SHA-256, not a credential
readonly PYTHON312_PATCH_SHA256='97c577d010690c66d2be37530985d4fba14b1564211a057257c52e7f2bfb469b' # DevSkim: ignore DS173237 -- public upstream patch SHA-256, not a credential

work="$(mktemp -d "${TMPDIR:-/tmp}/omero-ice-build.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT

# Inputs: HTTPS URL, checksum, destination. Output: verified file or fatal failure.
download() {
    local url="$1" checksum="$2" destination="$3"
    curl --proto '=https' --proto-redir '=https' \
        --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
        --output "$destination" "$url" --tlsv1.2 # DevSkim: ignore DS440001,DS440016 -- minimum only; TLS 1.3 negotiation remains enabled
    printf '%s  %s\n' "$checksum" "$destination" | sha256sum --check --strict
}

# Source identity comes from PyPI; both patches are used by OMERO's wheel supplier.
# The unrelated NumPy-distutils parallel-compiler patch is not required here.
download \
    'https://files.pythonhosted.org/packages/1e/65/43c3ad2412467c731ee3c23bce03fad7e2b79df31301e27cc7b1b454554b/zeroc-ice-3.6.5.tar.gz' \
    "$ICE_SOURCE_SHA256" \
    "$work/source.tar.gz"
download \
    'https://raw.githubusercontent.com/glencoesoftware/zeroc-ice-py-patches/fedb23b9029b525e2e5a6396a970f5f1fa5bb3aa/0002-python-311-support.patch' \
    "$PYTHON311_PATCH_SHA256" \
    "$work/python311.patch"
download \
    'https://raw.githubusercontent.com/glencoesoftware/zeroc-ice-py-patches/fedb23b9029b525e2e5a6396a970f5f1fa5bb3aa/0003-python-312-support.patch' \
    "$PYTHON312_PATCH_SHA256" \
    "$work/python312.patch"

"$python" - "$work/source.tar.gz" "$work" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as archive:
    archive.extractall(sys.argv[2], filter="data")
PY
for name in python311 python312; do
    patch --batch --forward --fuzz=0 --no-backup-if-mismatch \
        --directory "$work" -p0 < "$work/$name.patch"
done

CFLAGS="${CFLAGS:-} -std=gnu17 -D_DEFAULT_SOURCE" \
    "$python" -m pip wheel --no-deps --no-build-isolation \
    --wheel-dir "$work/wheels" "$work/zeroc-ice-3.6.5"
mapfile -t wheels < <(find "$work/wheels" -maxdepth 1 -type f -name 'zeroc_ice-3.6.5-*.whl')
if [ "${#wheels[@]}" -ne 1 ]; then
    echo "Expected exactly one native Ice wheel" >&2
    exit 1
fi
"$python" -m pip install --no-deps --force-reinstall "${wheels[0]}"
extension="$("$python" -c 'import importlib.metadata as m; import Ice, IcePy; assert m.version("zeroc-ice") == "3.6.5"; print(IcePy.__file__)')"
dependencies="$(ldd "$extension")"
printf '%s\n' "$dependencies" | grep -Eq 'libssl\.so\.3[[:space:]]+=>'
printf '%s\n' "$dependencies" | grep -Eq 'libcrypto\.so\.3[[:space:]]+=>'
if printf '%s\n' "$dependencies" | grep -Eq 'lib(ssl|crypto)[^ ]*\.so\.1|not found'; then
    echo "Ice must not retain legacy or missing TLS libraries" >&2
    exit 1
fi
echo "Ice 3.6.5 uses the maintained system OpenSSL 3 libraries."
