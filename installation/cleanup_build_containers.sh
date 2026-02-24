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

remove_containers_by_name_regex() {
    local name_regex="$1"
    local label="$2"
    local found_any=false
    local cid=""
    local cname=""
    local running=""

    while IFS=' ' read -r cid cname; do
        [ -n "${cid}" ] || continue
        [ -n "${cname}" ] || continue

        found_any=true
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
    done < <(docker ps -a --format '{{.ID}} {{.Names}}' 2>/dev/null | awk -v r="${name_regex}" '$2 ~ r { print $1 " " $2 }')

    if [[ "${found_any}" != "true" ]]; then
        echo "  No containers found for ${label} - skipping."
    fi
}

remove_containers_by_name_prefix() {
    local prefix="$1"
    remove_containers_by_name_regex "^${prefix}" "prefix '${prefix}'"
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
remove_containers_by_name_regex "(^|[-_.])redis-sysctl-init($|[-_.][0-9]+$)" "redis-sysctl-init"
remove_image "redis-sysctl-init:custom"
echo

echo "=== buildx buildkit ==="
remove_containers_by_name_prefix "buildx_buildkit_"

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
