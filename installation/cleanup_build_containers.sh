#!/usr/bin/env bash

# Cleanup helper for build-time-only containers/images.
# Must be run as root on the host.

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

# For backward compatibility; we remove this builder if it exists.
DOCKER_BUILDX_BUILDER_NAME="${DOCKER_BUILDX_BUILDER_NAME:-omero-builder}"

# Containers we want completely gone after installation finishes.
FIXED_CONTAINERS=(
  "redis-sysctl-init"
)

# Images to remove after installation, even if the container is already gone.
# These are one-shot images that serve no purpose after the init phase.
FIXED_IMAGES=(
  "redis-sysctl-init:custom"
)

# Require root. Inputs: shell arguments and environment. Output: command status and side effects.
require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR (${SCRIPT_NAME}): Must run as root." >&2
    exit 1
  fi
}

# Perform container exists. Inputs: shell arguments and environment. Output: command status and side effects.
container_exists() {
  local name="$1"
  docker container inspect "${name}" >/dev/null 2>&1
}

# Perform container state. Inputs: shell arguments and environment. Output: command status and side effects.
container_state() {
  local name="$1"
  docker container inspect -f '{{.State.Status}}' "${name}" 2>/dev/null || true
}

# Stop container best effort. Inputs: shell arguments and environment. Output: command status and side effects.
stop_container_best_effort() {
  local name="$1"
  container_exists "${name}" || return 0
  docker stop -t 20 "${name}" >/dev/null 2>&1 || true
}

# Wait container stopped. Inputs: shell arguments and environment. Output: command status and side effects.
wait_container_stopped() {
  local name="$1"
  local timeout_seconds="${2:-30}"
  local waited=0

  while container_exists "${name}"; do
    local st
    st="$(container_state "${name}")"
    case "${st}" in
      exited|dead|created|"")
        return 0
        ;;
      running|restarting|paused)
        ;;
      *)
        ;;
    esac

    if [ "${waited}" -ge "${timeout_seconds}" ]; then
      echo "WARNING (${SCRIPT_NAME}): Timeout waiting for ${name} to stop (state=${st})." >&2
      return 1
    fi

    sleep 1
    waited=$((waited + 1))
  done

  return 0
}

# Remove container force. Inputs: shell arguments and environment. Output: command status and side effects.
remove_container_force() {
  local name="$1"
  container_exists "${name}" || return 0
  docker rm -f "${name}" >/dev/null 2>&1 || true
}

# Discover container image ID. Inputs: shell arguments and environment. Output: command status and side effects.
discover_container_image_id() {
  local name="$1"
  docker container inspect -f '{{.Image}}' "${name}" 2>/dev/null || true
}

# Discover container volume names. Inputs: shell arguments and environment. Output: command status and side effects.
discover_container_volume_names() {
  local name="$1"
  docker container inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{"\n"}}{{end}}{{end}}' "${name}" 2>/dev/null || true
}

# Remove image force. Inputs: shell arguments and environment. Output: command status and side effects.
remove_image_force() {
  local image_ref="$1"
  [ -z "${image_ref}" ] && return 0
  docker rmi -f "${image_ref}" >/dev/null 2>&1 || true
}

# Remove volume force. Inputs: shell arguments and environment. Output: command status and side effects.
remove_volume_force() {
  local volume_name="$1"
  [ -z "${volume_name}" ] && return 0
  docker volume rm -f "${volume_name}" >/dev/null 2>&1 || true
}

# Cleanup one container. Inputs: shell arguments and environment. Output: command status and side effects.
cleanup_one_container() {
  local name="$1"

  container_exists "${name}" || return 0

  local image_id=""
  image_id="$(discover_container_image_id "${name}")"

  local volumes
  volumes="$(discover_container_volume_names "${name}")"

  echo "Cleaning container: ${name}"
  stop_container_best_effort "${name}"
  wait_container_stopped "${name}" 30 || true
  remove_container_force "${name}"

  if [ -n "${volumes}" ]; then
    while IFS= read -r v; do
      [ -z "${v}" ] && continue
      echo "Removing docker volume: ${v} (from ${name})"
      remove_volume_force "${v}"
    done <<< "${volumes}"
  fi

  if [ -n "${image_id}" ]; then
    echo "Removing docker image id: ${image_id} (from ${name})"
    remove_image_force "${image_id}"
  fi
}

# Cleanup buildx builder. Inputs: shell arguments and environment. Output: command status and side effects.
cleanup_buildx_builder() {
  local builder_name="$1"

  # Reset to default builder context before manipulating our specific builder
  docker buildx use default >/dev/null 2>&1 || true

  # Stop the builder container gracefully before attempting removal
  docker buildx stop "${builder_name}" >/dev/null 2>&1 || true

  # Discover buildkit images BEFORE removing the builder container
  # (Since docker buildx rm destroys the container, we'd lose the image reference otherwise)
  local buildkit_images=""
  buildkit_images="$(docker ps -a --filter "name=buildx_buildkit_${builder_name}" --format '{{.Image}}' 2>/dev/null || true)"

  # Discover anonymous volumes attached to the builder container BEFORE removing it
  local buildkit_volumes=""
  buildkit_volumes="$(docker ps -a --filter "name=buildx_buildkit_${builder_name}" --format '{{.Names}}' 2>/dev/null | awk 'NF' | xargs -I {} docker container inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{"\n"}}{{end}}{{end}}' {} 2>/dev/null || true)"

  # Remove the named builder if present. Use -f to force removal even if it is busy.
  if docker buildx inspect "${builder_name}" >/dev/null 2>&1; then
    echo "Removing buildx builder: ${builder_name}"
    docker buildx rm -f "${builder_name}" >/dev/null 2>&1 || true
  fi

  # Remove ONLY the remaining buildkit containers that belonged to OUR builder.
  # BUGFIX: We cannot use '^buildx_buildkit_.*' because it will match the system's
  # default buildx builder (e.g. buildx_buildkit_default). If we kill the system's
  # default builder container but do not remove the builder itself, Docker daemon
  # will instantly recreate it (restart=always), leaving you with a fresh "running"
  # buildx container immediately after the script finishes.
  local c
  while IFS= read -r c; do
    [ -z "${c}" ] && continue
    cleanup_one_container "${c}"
  done < <(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E "^buildx_buildkit_${builder_name}.*" || true)

  # Remove any remaining buildx volumes by name that specifically belonged to OUR builder.
  local v
  while IFS= read -r v; do
    [ -z "${v}" ] && continue
    echo "Removing buildx named volume: ${v}"
    remove_volume_force "${v}"
  done < <(docker volume ls -q 2>/dev/null | grep -E "^buildx_buildkit_${builder_name}.*" || true)

  # Remove discovered anonymous volumes from the named builder
  if [ -n "${buildkit_volumes}" ]; then
    while IFS= read -r v; do
      [ -z "${v}" ] && continue
      echo "Removing buildx anonymous volume: ${v}"
      remove_volume_force "${v}"
    done <<< "${buildkit_volumes}"
  fi

  # Remove discovered buildkit images from the named builder
  if [ -n "${buildkit_images}" ]; then
    local img
    while IFS= read -r img; do
      [ -z "${img}" ] && continue
      echo "Removing buildx image: ${img}"
      remove_image_force "${img}"
    done <<< "${buildkit_images}"
  fi

  # Fallback: aggressively remove moby/buildkit images ONLY IF THEY ARE DANGLING.
  # Do not forcefully remove tagged buildkit images because other global builders
  # on the host system may be using them!
  local dangling_buildkit
  dangling_buildkit="$(docker images --filter "reference=moby/buildkit" --filter "dangling=true" --format '{{.ID}}' 2>/dev/null || true)"
  if [ -n "${dangling_buildkit}" ]; then
    local img
    while IFS= read -r img; do
      [ -z "${img}" ] && continue
      echo "Removing dangling buildx image: ${img}"
      remove_image_force "${img}"
    done <<< "${dangling_buildkit}"
  fi
}

# Cleanup probe containers. Inputs: shell arguments and environment. Output: command status and side effects.
cleanup_probe_containers() {
  echo "Cleaning up probe containers..."
  local c
  while IFS= read -r c; do
    [ -z "${c}" ] && continue
    echo "Removing stuck probe container: ${c}"
    remove_container_force "${c}"
  done < <(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^omero-install-probe-' || true)
}

# Execute the command entrypoint. Inputs: shell arguments and environment. Output: command status and side effects.
main() {
  require_root

  cleanup_buildx_builder "${DOCKER_BUILDX_BUILDER_NAME}"
  cleanup_probe_containers

  local name
  for name in "${FIXED_CONTAINERS[@]}"; do
    cleanup_one_container "${name}"
  done

  # Remove one-shot images that may linger after the container is already gone.
  local image_name
  for image_name in "${FIXED_IMAGES[@]}"; do
    if docker image inspect "${image_name}" >/dev/null 2>&1; then
      echo "Removing one-shot image: ${image_name}"
      remove_image_force "${image_name}"
    fi
  done

  # Remove dangling image objects left behind by interrupted/replaced builds.
  # This prevents <none>:<none> images from persisting in container UIs.
  docker image prune -f >/dev/null 2>&1 || true

  echo "Cleanup complete."
}

main "$@"
