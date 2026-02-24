#!/usr/bin/env bash
# Removes buildx and redis-init containers/images.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

echo "Cleaning up build and init containers..."

# Define targets
CONTAINERS="omero-buildkitd redis-sysctl-init"
IMAGES="redis-sysctl-init:custom moby/buildkit:latest"
BUILDER_NAME="omero-builder"

# Stop and remove containers
for container in $CONTAINERS; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "Stopping and removing container: ${container}"
        docker stop "${container}" >/dev/null 2>&1 || true
        # Wait for stop just in case, though docker stop blocks
        docker rm -f "${container}" >/dev/null 2>&1 || true
    fi
done

# Remove buildx builder
if docker buildx ls | grep -q "^${BUILDER_NAME}"; then
    echo "Removing buildx builder: ${BUILDER_NAME}"
    docker buildx rm "${BUILDER_NAME}" >/dev/null 2>&1 || true
fi

# Remove images
for image in $IMAGES; do
    if docker images -q "${image}" >/dev/null 2>&1; then
         echo "Removing image: ${image}"
         docker rmi -f "${image}" >/dev/null 2>&1 || true
    fi
done

echo "Cleanup complete."
