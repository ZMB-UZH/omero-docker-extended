from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "/OMERO/.admin-tools/group-quotas.json"
DEFAULT_ENFORCER_MARKER_PATH = "/OMERO/.admin-tools/quota-enforcer-installed"
DEFAULT_LOG_LIMIT = 200
EXPECTED_MANAGED_REPOSITORY_PREFIX = "%group%/%user%/"
DEFAULT_MIN_QUOTA_GB = 0.10
_RECONCILE_LOCK = threading.Lock()


@dataclass(frozen=True)
class FilesystemInfo:
    """Filesystem metadata for the managed repository root."""

    fs_type: str
    mount_point: str
    source: str


class QuotaError(RuntimeError):
    """Raised for invalid quota input."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def quota_state_path() -> Path:
    """Return quota state path from environment."""
    return Path(
        os.environ.get("ADMIN_TOOLS_QUOTA_STATE_PATH", DEFAULT_STATE_PATH)
    ).expanduser()


def min_quota_gb() -> float:
    """Return minimum allowed quota in GB from environment."""
    raw_value = os.environ.get("ADMIN_TOOLS_MIN_QUOTA_GB", "").strip()
    if not raw_value:
        return DEFAULT_MIN_QUOTA_GB
    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise QuotaError(
            "Invalid ADMIN_TOOLS_MIN_QUOTA_GB value; expected a numeric value in GB."
        ) from exc
    if parsed <= 0:
        raise QuotaError("ADMIN_TOOLS_MIN_QUOTA_GB must be greater than 0.")
    return round(parsed, 3)


def is_quota_enforcement_available() -> bool:
    """Return True when the host-side quota enforcer is installed.

    The installer writes a marker file on the shared /OMERO volume when
    ext4 project quota support is confirmed and the systemd timer is
    installed.  The absence of this file means the host filesystem does
    not support quotas or the enforcer was never installed.
    """
    marker_path = Path(
        os.environ.get(
            "ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH",
            DEFAULT_ENFORCER_MARKER_PATH,
        )
    )
    return marker_path.is_file()


MANAGED_GROUP_ROOT = Path("/OMERO/ManagedRepository")


def managed_group_root() -> Path:
    """Return the fixed OMERO managed repository group root."""
    return MANAGED_GROUP_ROOT



def resolve_managed_group_root(known_groups: Sequence[str]) -> Tuple[Path, str]:
    """Return the fixed managed repository root without fallback resolution."""
    del known_groups
    if MANAGED_GROUP_ROOT.exists() and MANAGED_GROUP_ROOT.is_dir():
        return MANAGED_GROUP_ROOT, "using fixed managed repository root"
    return MANAGED_GROUP_ROOT, "fixed managed repository root does not exist"


def _is_safe_managed_repository_root(path: Path) -> Tuple[bool, str]:
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path

    if not path.exists() or not path.is_dir():
        return False, "path does not exist or is not a directory"

    omero_root = Path("/OMERO").resolve()
    try:
        resolved.relative_to(omero_root)
    except ValueError:
        if resolved != omero_root:
            return False, "path must be within /OMERO mount"

    return True, ""


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_state(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"quotas_gb": {}, "logs": []}
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise QuotaError("Quota state file must contain a JSON object")
    data.setdefault("quotas_gb", {})
    data.setdefault("logs", [])
    return data


def _write_state(path: Path, state: Dict[str, object]) -> None:
    _ensure_parent(path)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, path)


def _append_log(state: Dict[str, object], level: str, message: str) -> None:
    logs = state.setdefault("logs", [])
    assert isinstance(logs, list)
    if (
        level == "info"
        and logs
        and isinstance(logs[-1], dict)
        and logs[-1].get("level") == "info"
        and logs[-1].get("message") == message
    ):
        return
    logs.append({"timestamp": _now_iso(), "level": level, "message": message})
    if len(logs) > DEFAULT_LOG_LIMIT:
        del logs[: len(logs) - DEFAULT_LOG_LIMIT]


def _reconcile_event_cache(state: Dict[str, object]) -> Dict[str, str]:
    cache = state.setdefault("_reconcile_event_cache", {})
    if not isinstance(cache, dict):
        cache = {}
        state["_reconcile_event_cache"] = cache
    normalized: Dict[str, str] = {}
    for key, value in cache.items():
        normalized[str(key)] = str(value)
    state["_reconcile_event_cache"] = normalized
    return normalized


def _append_reconcile_event(
    state: Dict[str, object],
    *,
    event_key: str,
    level: str,
    message: str,
) -> None:
    cache = _reconcile_event_cache(state)
    cache_value = f"{level}|{message}"
    if level != "warning" and cache.get(event_key) == cache_value:
        return
    cache[event_key] = cache_value
    _append_log(state, level, message)


def _prune_reconcile_event_cache(
    state: Dict[str, object], valid_keys: Sequence[str]
) -> None:
    cache = _reconcile_event_cache(state)
    valid = {str(key) for key in valid_keys}
    stale_keys = [key for key in cache if key not in valid]
    for key in stale_keys:
        del cache[key]


def _normalize_group(value: str) -> str:
    group_name = value.strip()
    if not group_name:
        raise QuotaError("Group name must not be empty")
    return group_name


def _normalize_quota_gb(value: object) -> Optional[float]:
    minimum_quota_gb = min_quota_gb()
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QuotaError(f"Invalid quota value: {value!r}") from exc
    if number < minimum_quota_gb:
        raise QuotaError(f"Quota value must be at least {minimum_quota_gb:.2f} GB")
    return round(number, 3)


def managed_repository_template() -> str:
    """Return OMERO managed repository template for compatibility checks."""
    return os.environ.get("CONFIG_omero_fs_repo_path", "").strip()


def managed_repository_compatibility() -> Dict[str, object]:
    """Validate managed repository template prefix for group-quota safety."""
    template = managed_repository_template()
    compatible = template.startswith(EXPECTED_MANAGED_REPOSITORY_PREFIX)
    return {
        "template": template,
        "expected_prefix": EXPECTED_MANAGED_REPOSITORY_PREFIX,
        "is_compatible": compatible,
    }


def detect_filesystem(path: Path) -> FilesystemInfo:
    """Detect Linux filesystem type and mountpoint for a path."""
    mounts_path = Path("/proc/mounts")
    resolved = path.resolve()
    if not mounts_path.exists():
        return FilesystemInfo(fs_type="unknown", mount_point="", source="")

    best_match: Optional[Tuple[str, str, str]] = None
    for line in mounts_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        source, mount_point, fs_type = parts[0], parts[1], parts[2]
        mount_path = Path(mount_point)
        try:
            resolved.relative_to(mount_path)
        except ValueError:
            continue
        if best_match is None or len(mount_point) > len(best_match[1]):
            best_match = (source, mount_point, fs_type)

    if best_match is None:
        return FilesystemInfo(fs_type="unknown", mount_point="", source="")
    return FilesystemInfo(
        source=best_match[0],
        mount_point=best_match[1],
        fs_type=best_match[2],
    )


def _is_group_folder_available(group_path: Path) -> bool:
    return group_path.exists() and group_path.is_dir()


def upsert_quotas(
    updates: Sequence[Tuple[str, object]], source: str = "ui"
) -> Dict[str, object]:
    """Update quotas in GB and return the latest full state."""
    path = quota_state_path()
    state = _load_state(path)
    quotas = state.setdefault("quotas_gb", {})
    assert isinstance(quotas, dict)
    changed = False

    for raw_group, raw_quota in updates:
        group_name = _normalize_group(raw_group)
        quota_gb = _normalize_quota_gb(raw_quota)
        if quota_gb is None:
            if group_name in quotas:
                del quotas[group_name]
                changed = True
                _append_log(
                    state,
                    "info",
                    f"Deleted quota for group '{group_name}' (source={source}).",
                )
            continue

        existing_quota = quotas.get(group_name)
        if existing_quota == quota_gb:
            continue

        quotas[group_name] = quota_gb
        changed = True
        _append_log(
            state,
            "info",
            f"Updated quota for group '{group_name}' to {quota_gb:.3f} GB (source={source}).",
        )

    if changed:
        _write_state(path, state)
    return state


def import_quotas_csv(content: str) -> Dict[str, object]:
    """Import quotas from CSV content containing Group,Quota [GB]."""
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise QuotaError("CSV file is empty")

    data_rows = rows[1:] if rows else []
    updates: List[Tuple[str, object]] = []
    for index, row in enumerate(data_rows, start=2):
        if not row or all(not str(cell).strip() for cell in row):
            continue
        if len(row) < 2:
            raise QuotaError(f"CSV row {index} must contain at least 2 columns")
        updates.append((row[0], row[1]))

    if not updates:
        raise QuotaError("CSV contains no quota rows")
    return upsert_quotas(updates, source="csv-import")


def quota_csv_template() -> str:
    """Return CSV template text for quota imports."""
    return "Group,Quota [GB]\n"


def list_group_directories(group_root: Path) -> List[str]:
    """List group directory names from managed repository root."""
    if not group_root.exists() or not group_root.is_dir():
        return []
    names = [entry.name for entry in group_root.iterdir() if entry.is_dir()]
    return sorted(names)


def get_state() -> Dict[str, object]:
    """Return quota state; does not mutate filesystem."""
    path = quota_state_path()
    state = _load_state(path)
    quotas = state.get("quotas_gb", {})
    if not isinstance(quotas, dict):
        quotas = {}
    logs = state.get("logs", [])
    if not isinstance(logs, list):
        logs = []

    return {
        "quotas_gb": quotas,
        "logs": logs,
        "min_quota_gb": min_quota_gb(),
        "quota_enforcement_available": is_quota_enforcement_available(),
    }


def reconcile_quotas(known_groups: Sequence[str]) -> Dict[str, object]:
    """Reconcile quota definitions with existing directories.

    This function manages the quota state file and ensures group directories
    exist.  Actual filesystem-level enforcement (chattr, setquota) is
    performed by the host-side systemd timer (omero-quota-enforcer) which
    reads the same state file with root privileges.
    """
    with _RECONCILE_LOCK:
        path = quota_state_path()
        state = _load_state(path)
        quotas = state.setdefault("quotas_gb", {})
        assert isinstance(quotas, dict)

        group_root, root_reason = resolve_managed_group_root(known_groups)
        root_is_safe, root_safety_reason = _is_safe_managed_repository_root(group_root)
        available_groups = (
            set(list_group_directories(group_root)) if root_is_safe else set()
        )
        available_groups.update(set(known_groups))

        filesystem = detect_filesystem(group_root)
        repository_compatibility = managed_repository_compatibility()

        configured = []
        pending = []
        reconcile_event_keys: List[str] = []

        if not root_is_safe:
            event_key = "global:managed_group_root_unsafe"
            reconcile_event_keys.append(event_key)
            _append_reconcile_event(
                state,
                event_key=event_key,
                level="error",
                message=(
                    "ManagedRepository root is unsafe for quota enforcement: "
                    f"{group_root} ({root_safety_reason}; detection={root_reason})."
                ),
            )

        if not repository_compatibility["is_compatible"]:
            event_key = "global:repository_incompatible"
            reconcile_event_keys.append(event_key)
            _append_reconcile_event(
                state,
                event_key=event_key,
                level="error",
                message=(
                    "ManagedRepository template is incompatible with group quota enforcement. "
                    "Required prefix: %group%/%user%/."
                ),
            )

        for group_name, raw_quota in sorted(quotas.items()):
            group_key = f"group:{group_name}"
            reconcile_event_keys.append(group_key)
            try:
                quota_gb = _normalize_quota_gb(raw_quota)
            except QuotaError as exc:
                _append_reconcile_event(
                    state,
                    event_key=group_key,
                    level="error",
                    message=f"Invalid stored quota for group '{group_name}': {exc}",
                )
                continue

            group_path = group_root / group_name
            if not root_is_safe:
                pending.append(group_name)
                continue
            if not repository_compatibility["is_compatible"]:
                pending.append(group_name)
                continue
            if not _is_group_folder_available(group_path):
                try:
                    group_path.mkdir(parents=False, exist_ok=True)
                    _append_reconcile_event(
                        state,
                        event_key=group_key,
                        level="info",
                        message=f"Created group directory for quota enforcement: {group_path}.",
                    )
                except OSError as exc:
                    pending.append(group_name)
                    _append_reconcile_event(
                        state,
                        event_key=group_key,
                        level="warning",
                        message=f"Quota pending for group '{group_name}': could not create directory {group_path}: {exc}.",
                    )
                    continue
            if not _is_group_folder_available(group_path):
                pending.append(group_name)
                _append_reconcile_event(
                    state,
                    event_key=group_key,
                    level="warning",
                    message=f"Quota pending for group '{group_name}': directory not present at {group_path}.",
                )
                continue

            configured.append(group_name)
            _append_reconcile_event(
                state,
                event_key=group_key,
                level="info",
                message=(
                    f"Quota for group '{group_name}' is configured at {quota_gb:.3f} GB. "
                    "Host-side enforcer will apply ext4 project quota."
                ),
            )

        _prune_reconcile_event_cache(state, reconcile_event_keys)
        _write_state(path, state)
        return {
            "filesystem": {
                "type": filesystem.fs_type,
                "mount_point": filesystem.mount_point,
                "source": filesystem.source,
            },
            "managed_group_root": str(group_root),
            "managed_group_root_reason": root_reason,
            "managed_repository": repository_compatibility,
            "available_groups": sorted(available_groups),
            "applied_groups": sorted(set(configured)),
            "pending_groups": sorted(set(pending)),
            "quotas_gb": state.get("quotas_gb", {}),
            "logs": state.get("logs", []),
            "min_quota_gb": min_quota_gb(),
            "quota_enforcement_available": is_quota_enforcement_available(),
        }
