#!/usr/bin/env bash
set -euo pipefail

interval_seconds="${ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS:-60}"

if ! [[ "$interval_seconds" =~ ^[0-9]+$ ]] || [[ "$interval_seconds" -lt 10 ]]; then
  echo "[quota-reconcile-loop] ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS must be an integer >= 10" >&2
  exit 1
fi

while true; do
  python3 - <<'PY'
from omeroweb_admin_tools.services.storage_quotas import list_group_directories, managed_group_root, reconcile_quotas

root = managed_group_root()
known_groups = list_group_directories(root)
reconcile_quotas(known_groups)
PY
  sleep "$interval_seconds"
done
