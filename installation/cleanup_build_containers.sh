#!/usr/bin/env bash
# Removes leftover post-build containers/images if present.
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[dry-run] No containers or images will be removed."
    echo
fi

removed_containers=0
removed_images=0

remove_container() {
    local name="$1"
    local cid

    cid="$(docker ps -aq --filter "name=^/${name}$" 2>/dev/null || true)"
    if [[ -z "${cid}" ]]; then
        echo "  Container '${name}' not found - skipping."
        return
    fi

    local running
    running="$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || true)"
    if [[ "${running}" == "true" ]]; then
        if ${DRY_RUN}; then
            echo "  [dry-run] Would stop container '${name}' (${cid})"
        else
            echo "  Stopping container '${name}' (${cid}) ..."
            docker stop "${cid}" >/dev/null
        fi
    fi

    if ${DRY_RUN}; then
        echo "  [dry-run] Would remove container '${name}' (${cid})"
    else
        echo "  Removing container '${name}' (${cid}) ..."
        docker rm "${cid}" >/dev/null
    fi
    removed_containers=$((removed_containers + 1))
}

remove_image() {
    local image_ref="$1"
    local iid

    iid="$(docker images -q "${image_ref}" 2>/dev/null || true)"
    if [[ -z "${iid}" ]]; then
        echo "  Image '${image_ref}' not found - skipping."
        return
    fi

    if ${DRY_RUN}; then
        echo "  [dry-run] Would remove image '${image_ref}' (${iid})"
    else
        echo "  Removing image '${image_ref}' (${iid}) ..."
        docker rmi "${iid}" >/dev/null
    fi
    removed_images=$((removed_images + 1))
}

echo "=== redis-sysctl-init ==="
remove_container "redis-sysctl-init"
remove_image "redis-sysctl-init:custom"
echo

echo "=== buildx buildkit ==="
buildx_ids="$(docker ps -aq --filter "name=^buildx_buildkit_" 2>/dev/null || true)"
if [[ -z "${buildx_ids}" ]]; then
    echo "  No buildx_buildkit containers found - skipping."
else
    for cid in ${buildx_ids}; do
        cname="$(docker inspect -f '{{.Name}}' "${cid}" 2>/dev/null | sed 's|^/||')"
        cname="${cname:-${cid}}"

        running="$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || true)"
        if [[ "${running}" == "true" ]]; then
            if ${DRY_RUN}; then
                echo "  [dry-run] Would stop container '${cname}' (${cid})"
            else
                echo "  Stopping container '${cname}' (${cid}) ..."
                docker stop "${cid}" >/dev/null
            fi
        fi

        if ${DRY_RUN}; then
            echo "  [dry-run] Would remove container '${cname}' (${cid})"
        else
            echo "  Removing container '${cname}' (${cid}) ..."
            docker rm "${cid}" >/dev/null
        fi
        removed_containers=$((removed_containers + 1))
    done
fi

buildkit_images="$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep '^moby/buildkit:' || true)"
if [[ -z "${buildkit_images}" ]]; then
    echo "  No moby/buildkit images found - skipping."
else
    for img in ${buildkit_images}; do
        remove_image "${img}"
    done
fi

echo
if ${DRY_RUN}; then
    echo "[dry-run] Would have removed ${removed_containers} container(s) and ${removed_images} image(s)."
else
    echo "Removed ${removed_containers} container(s) and ${removed_images} image(s)."
fi
