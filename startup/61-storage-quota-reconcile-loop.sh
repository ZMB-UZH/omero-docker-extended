#!/usr/bin/env bash
set -euo pipefail

interval_seconds="${ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS:-60}"

is_non_negative_integer() {
  case "${1:-}" in
    ""|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

if ! is_non_negative_integer "$interval_seconds" || [ "$interval_seconds" -lt 10 ]; then
  echo "[quota-reconcile-loop] ADMIN_TOOLS_QUOTA_RECONCILE_INTERVAL_SECONDS must be an integer >= 10" >&2
  exit 1
fi

while true; do
  python3 - <<'PY' || echo "[quota-reconcile-loop] reconciliation failed (will retry in ${interval_seconds}s)" >&2
import traceback
try:
    from omeroweb_admin_tools.services.storage_quotas import list_group_directories, managed_group_root, reconcile_quotas
    root = managed_group_root()
    known_groups = list_group_directories(root)
    reconcile_quotas(known_groups)
except Exception:
    traceback.print_exc()
    raise
PY
  sleep "$interval_seconds"
done
