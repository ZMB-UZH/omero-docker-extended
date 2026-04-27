#!/bin/sh
set -eu

# Auto-mirror host top-level mountpoints into the container so paths like /disks/..., /data/..., /srv/...
# exist inside the container root (without hardcoding any of them).
#
# We intentionally refuse to touch core OS dirs that already exist in the container.
deny='^(dev|proc|sys|run|etc|usr|var|bin|sbin|lib|lib64|root|tmp|rootfs|boot)$'

if [ -d /rootfs ]; then
  for rootfs_entry in /rootfs/*; do
    [ -e "$rootfs_entry" ] || continue
    d=${rootfs_entry#/rootfs/}
    echo "$d" | grep -Eq "$deny" && continue
    [ -e "/$d" ] && continue

    mkdir -p "/$d" || continue
    mount --rbind "$rootfs_entry" "/$d" 2>/dev/null || true
    mount -o remount,ro,bind "/$d" 2>/dev/null || true
  done
fi

if command -v cadvisor >/dev/null 2>&1; then
  exec cadvisor "$@"
elif [ -x /usr/bin/cadvisor ]; then
  exec /usr/bin/cadvisor "$@"
elif [ -x /cadvisor ]; then
  exec /cadvisor "$@"
else
  echo "ERROR: cadvisor binary not found" >&2
  exit 1
fi
