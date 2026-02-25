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

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR (${SCRIPT_NAME}): Must run as root." >&2
    exit 1
  fi
}

container_exists() {
  local name="$1"
  docker container inspect "${name}" >/dev/null 2>&1
}

container_state() {
  local name="$1"
  docker container inspect -f '{{.State.Status}}' "${name}" 2>/dev/null || true
}

stop_container_best_effort() {
  local name="$1"
  container_exists "${name}" || return 0
  docker stop -t 20 "${name}" >/dev/null 2>&1 || true
}

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

remove_container_force() {
  local name="$1"
  container_exists "${name}" || return 0
  docker rm -f "${name}" >/dev/null 2>&1 || true
}

discover_container_image_id() {
  local name="$1"
  docker container inspect -f '{{.Image}}' "${name}" 2>/dev/null || true
}

discover_container_volume_names() {
  local name="$1"
  docker container inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}}{{"\n"}}{{end}}{{end}}' "${name}" 2>/dev/null || true
}

remove_image_force() {
  local image_ref="$1"
  [ -z "${image_ref}" ] && return 0
  docker rmi -f "${image_ref}" >/dev/null 2>&1 || true
}

remove_volume_force() {
  local volume_name="$1"
  [ -z "${volume_name}" ] && return 0
  docker volume rm -f "${volume_name}" >/dev/null 2>&1 || true
}

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

cleanup_buildx_builder() {
  local builder_name="$1"

  # Remove the named builder if present.
  if docker buildx inspect "${builder_name}" >/dev/null 2>&1; then
    echo "Removing buildx builder: ${builder_name}"
    docker buildx rm "${builder_name}" >/dev/null 2>&1 || true
  fi

  # Remove ANY buildx buildkit container (covers default builder, old builders,
  # and containers that created anonymous volumes).
  local c
  while IFS= read -r c; do
    [ -z "${c}" ] && continue
    cleanup_one_container "${c}"
  done < <(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^buildx_buildkit_.*' || true)

  # Remove any remaining buildx volumes by name (best effort).
  local v
  while IFS= read -r v; do
    [ -z "${v}" ] && continue
    echo "Removing buildx volume: ${v}"
    remove_volume_force "${v}"
  done < <(docker volume ls -q 2>/dev/null | grep -E '^buildx_buildkit_.*' || true)

  # Remove buildkit image if present (best effort).
  remove_image_force "moby/buildkit:latest"
}

main() {
  require_root

  cleanup_buildx_builder "${DOCKER_BUILDX_BUILDER_NAME}"

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
