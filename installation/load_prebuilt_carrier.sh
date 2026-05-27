#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

PREBUILT_IMAGE_REPOSITORY="${PREBUILT_IMAGE_REPOSITORY:-strmt7/omero-docker-extended}"
PREBUILT_IMAGE_RELEASE="${PREBUILT_IMAGE_RELEASE:-}"
PREBUILT_IMAGE_REF="${PREBUILT_IMAGE_REF:-}"
OMERO_TMP_PATH="${OMERO_TMP_PATH:-}"
MANIFEST_CONTAINER_PATH="/omero-prebuilt/prebuilt-manifest.json"
BUNDLE_CONTAINER_PATH="/omero-prebuilt/runtime-images.tar.gz"

# Exit with an installer error. Inputs: shell arguments and environment. Output: process termination.
fail() {
    echo "ERROR: $*" >&2
    exit 1
}

# Validate a docker image reference component. Inputs: shell arguments and environment. Output: command status or process termination.
validate_image_component() {
    local label="$1"
    local value="$2"

    [ -n "${value}" ] || fail "${label} cannot be empty."
    case "${value}" in
        *[!A-Za-z0-9._:/@-]*)
            fail "${label} contains unsupported characters: ${value}"
            ;;
    esac
    case "${value}" in
        latest|*:latest|*:latest@*)
            fail "${label} must not use the floating latest tag."
            ;;
    esac
}

# Resolve the carrier image reference. Inputs: shell arguments and environment. Output: stdout image reference or process termination.
resolve_carrier_image_ref() {
    if [ -n "${PREBUILT_IMAGE_REF}" ]; then
        validate_image_component "PREBUILT_IMAGE_REF" "${PREBUILT_IMAGE_REF}"
        printf '%s' "${PREBUILT_IMAGE_REF}"
        return 0
    fi

    validate_image_component "PREBUILT_IMAGE_REPOSITORY" "${PREBUILT_IMAGE_REPOSITORY}"
    validate_image_component "PREBUILT_IMAGE_RELEASE" "${PREBUILT_IMAGE_RELEASE}"
    printf '%s:%s' "${PREBUILT_IMAGE_REPOSITORY}" "${PREBUILT_IMAGE_RELEASE}"
}

[ -n "${OMERO_TMP_PATH}" ] || fail "OMERO_TMP_PATH is required."
[ -d "${OMERO_TMP_PATH}" ] || fail "OMERO_TMP_PATH does not exist: ${OMERO_TMP_PATH}"

carrier_ref="$(resolve_carrier_image_ref)"
work_dir="$(mktemp -d "${OMERO_TMP_PATH%/}/prebuilt-carrier.XXXXXX")"
container_name="omero-prebuilt-carrier-$$-$(date -u +%s)"
required_images_file="${work_dir}/required-images.txt"
bundle_bytes_file="${work_dir}/runtime-images.bytes"
bundle_uncompressed_bytes_file="${work_dir}/runtime-images-uncompressed.bytes"
manifest_path="${work_dir}/prebuilt-manifest.json"

# Remove temporary carrier resources. Inputs: shell arguments and environment. Output: best-effort cleanup side effects.
cleanup() {
    docker rm -f "${container_name}" >/dev/null 2>&1 || true
    rm -rf "${work_dir}"
}
trap cleanup EXIT

# Stream the compressed runtime image archive out of the carrier container.
# Inputs: environment. Output: archive bytes on stdout.
stream_carrier_bundle() {
    docker cp "${container_name}:${BUNDLE_CONTAINER_PATH}" - | tar -xO
}

echo "Pulling prebuilt carrier image: ${carrier_ref}"
docker pull "${carrier_ref}"

docker create --name "${container_name}" "${carrier_ref}" >/dev/null
docker cp "${container_name}:${MANIFEST_CONTAINER_PATH}" "${manifest_path}"

[ -s "${manifest_path}" ] || fail "Carrier manifest is empty."

python3 - \
    "${manifest_path}" \
    "${PREBUILT_IMAGE_RELEASE}" \
    "${bundle_bytes_file}" \
    "${bundle_uncompressed_bytes_file}" > "${required_images_file}" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
expected_release = sys.argv[2]
bundle_bytes_path = Path(sys.argv[3])
bundle_uncompressed_bytes_path = Path(sys.argv[4])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("schema_version") != 1:
    raise SystemExit("Carrier manifest schema_version must be 1.")

release = manifest.get("release")
if expected_release and release != expected_release:
    raise SystemExit(
        f"Carrier manifest release mismatch: expected {expected_release}, got {release}"
    )

required_images = manifest.get("required_images")
if not isinstance(required_images, list) or not required_images:
    raise SystemExit("Carrier manifest required_images must be a non-empty list.")

safe_ref = re.compile(r"^[A-Za-z0-9._:/@-]+$")
for image in required_images:
    if not isinstance(image, str) or not image:
        raise SystemExit("Carrier manifest contains an invalid image reference.")
    if not safe_ref.fullmatch(image):
        raise SystemExit(f"Unsupported image reference in manifest: {image}")
    if image == "latest" or image.endswith(":latest") or ":latest@" in image:
        raise SystemExit(f"Floating latest tag is not allowed: {image}")

runtime_images_archive = manifest.get("runtime_images_archive")
if runtime_images_archive != "runtime-images.tar.gz":
    raise SystemExit("Carrier manifest runtime_images_archive must be runtime-images.tar.gz.")

expected_sha256 = manifest.get("image_archive_sha256")
if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
    raise SystemExit("Carrier manifest must include image_archive_sha256.")

runtime_images_archive_bytes = manifest.get("runtime_images_archive_bytes")
if (
    not isinstance(runtime_images_archive_bytes, int)
    or runtime_images_archive_bytes <= 0
):
    raise SystemExit("Carrier manifest must include positive runtime_images_archive_bytes.")

runtime_images_uncompressed_bytes = manifest.get("runtime_images_uncompressed_bytes")
if (
    not isinstance(runtime_images_uncompressed_bytes, int)
    or runtime_images_uncompressed_bytes <= 0
):
    raise SystemExit(
        "Carrier manifest must include positive runtime_images_uncompressed_bytes."
    )

bundle_bytes_path.write_text(str(runtime_images_archive_bytes), encoding="utf-8")
bundle_uncompressed_bytes_path.write_text(
    str(runtime_images_uncompressed_bytes),
    encoding="utf-8",
)
print("\n".join(required_images))
PY

expected_bundle_bytes="$(cat "${bundle_bytes_file}")"
expected_uncompressed_bytes="$(cat "${bundle_uncompressed_bytes_file}")"
docker_root_dir="$(docker info -f '{{.DockerRootDir}}')"
[ -n "${docker_root_dir}" ] || fail "docker root directory could not be discovered."
[ -d "${docker_root_dir}" ] || fail "docker root directory does not exist: ${docker_root_dir}"
docker_available_kb="$(df -Pk "${docker_root_dir}" | awk 'NR == 2 { print $4 }')"
docker_required_kb="$(((expected_uncompressed_bytes + 1023) / 1024))"
if [ "${docker_available_kb}" -lt "${docker_required_kb}" ]; then
    fail "Not enough free space under docker root ${docker_root_dir}. Need at least ${docker_required_kb} KiB for docker load; available ${docker_available_kb} KiB."
fi

bundle_verification="$(
    stream_carrier_bundle | python3 -c '
from __future__ import annotations

import hashlib
import sys

expected_bytes = int(sys.argv[1])
digest = hashlib.sha256()
actual_bytes = 0
for chunk in iter(lambda: sys.stdin.buffer.read(1024 * 1024), b""):
    actual_bytes += len(chunk)
    digest.update(chunk)
if actual_bytes <= 0:
    raise SystemExit("Carrier runtime image bundle is empty.")
if actual_bytes != expected_bytes:
    raise SystemExit(
        "Carrier runtime image bundle size mismatch: "
        f"expected {expected_bytes}, got {actual_bytes}"
    )
print(f"{actual_bytes} {digest.hexdigest()}")
' "${expected_bundle_bytes}"
)"

actual_bundle_bytes="${bundle_verification%% *}"
actual_sha256="${bundle_verification#* }"
expected_sha256="$(
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["image_archive_sha256"])' \
        "${manifest_path}"
)"
if [ "${actual_sha256}" != "${expected_sha256}" ]; then
    fail "Carrier runtime image bundle checksum mismatch: expected ${expected_sha256}, got ${actual_sha256}"
fi
echo "Verified carrier runtime image bundle: ${actual_bundle_bytes} bytes, sha256=${actual_sha256}"

echo "Loading runtime images from verified carrier bundle..."
if ! stream_carrier_bundle | docker load; then
    fail "docker load failed while importing the verified carrier runtime image bundle."
fi

while IFS= read -r image_ref; do
    [ -n "${image_ref}" ] || continue
    if ! docker image inspect "${image_ref}" >/dev/null 2>&1; then
        fail "Required runtime image was not loaded: ${image_ref}"
    fi
    echo "Verified runtime image: ${image_ref}"
done < "${required_images_file}"

echo "Prebuilt runtime image load completed."
