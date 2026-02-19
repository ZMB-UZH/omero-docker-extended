from __future__ import annotations

import csv
import io
import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "/tmp/omero-admin-tools/group-quotas.json"
DEFAULT_LOG_LIMIT = 200
EXPECTED_MANAGED_REPOSITORY_PREFIX = "%group%/%user%/"
MIN_QUOTA_GB = 1.0


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


def managed_group_root() -> Path:
    """Return the configured OMERO managed repository group root directory."""
    configured = os.environ.get("ADMIN_TOOLS_MANAGED_GROUP_ROOT", "")
    if configured.strip():
        return Path(configured).expanduser()

    omero_data = Path(os.environ.get("OMERO_DATA_DIR", "/OMERO")).expanduser()
    return omero_data / "omero_user_data" / "ManagedRepository"


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
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QuotaError(f"Invalid quota value: {value!r}") from exc
    if number < MIN_QUOTA_GB:
        raise QuotaError(f"Quota value must be at least {MIN_QUOTA_GB:.2f} GB")
    return round(number, 3)


def _bytes_from_gb(quota_gb: float) -> int:
    return int(quota_gb * 1024 * 1024 * 1024)


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


def _run_quota_apply_command(
    *,
    command_template: str,
    filesystem: FilesystemInfo,
    group_name: str,
    group_path: Path,
    quota_bytes: int,
    quota_gb: float,
) -> Tuple[bool, str]:
    context = {
        "fs_type": filesystem.fs_type,
        "mount_point": filesystem.mount_point,
        "source": filesystem.source,
        "group": group_name,
        "group_path": str(group_path),
        "quota_bytes": str(quota_bytes),
        "quota_gb": f"{quota_gb:.3f}",
    }
    try:
        expanded = command_template.format(**context)
    except KeyError as exc:
        return False, f"Invalid quota command template placeholder: {exc}"

    command = shlex.split(expanded)
    if not command:
        return False, "Quota command template produced an empty command"

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        return (
            False,
            f"Quota apply command failed (code {completed.returncode}): {stderr}",
        )
    stdout = completed.stdout.strip()
    return True, stdout or "quota applied"


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

    for raw_group, raw_quota in updates:
        group_name = _normalize_group(raw_group)
        quota_gb = _normalize_quota_gb(raw_quota)
        if quota_gb is None:
            if group_name in quotas:
                del quotas[group_name]
            _append_log(
                state,
                "info",
                f"Deleted quota for group '{group_name}' (source={source}).",
            )
            continue

        quotas[group_name] = quota_gb
        _append_log(
            state,
            "info",
            f"Updated quota for group '{group_name}' to {quota_gb:.3f} GB (source={source}).",
        )

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

    return {"quotas_gb": quotas, "logs": logs}


def reconcile_quotas(known_groups: Sequence[str]) -> Dict[str, object]:
    """Reconcile quota definitions with existing directories and attempt enforcement.

    Enforcement is performed using an optional external command template from
    ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE. The command receives placeholders:
    {fs_type}, {mount_point}, {source}, {group}, {group_path}, {quota_bytes}, {quota_gb}.
    """
    path = quota_state_path()
    state = _load_state(path)
    quotas = state.setdefault("quotas_gb", {})
    assert isinstance(quotas, dict)

    group_root = managed_group_root()
    available_groups = set(list_group_directories(group_root))
    available_groups.update(set(known_groups))

    filesystem = detect_filesystem(group_root)
    command_template = os.environ.get(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE", ""
    ).strip()
    repository_compatibility = managed_repository_compatibility()

    pending = []
    applied = []
    reconcile_event_keys: List[str] = []

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
        if not repository_compatibility["is_compatible"]:
            pending.append(group_name)
            continue
        if group_name not in available_groups or not _is_group_folder_available(
            group_path
        ):
            pending.append(group_name)
            _append_reconcile_event(
                state,
                event_key=group_key,
                level="warning",
                message=f"Quota pending for group '{group_name}': directory not present at {group_path}.",
            )
            continue

        if not command_template:
            pending.append(group_name)
            _append_reconcile_event(
                state,
                event_key=group_key,
                level="warning",
                message=(
                    f"Quota for group '{group_name}' is configured but no apply command is set. "
                    "Set ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE to enforce at filesystem level."
                ),
            )
            continue

        ok, message = _run_quota_apply_command(
            command_template=command_template,
            filesystem=filesystem,
            group_name=group_name,
            group_path=group_path,
            quota_bytes=_bytes_from_gb(quota_gb),
            quota_gb=quota_gb,
        )
        if ok:
            applied.append(group_name)
            _append_reconcile_event(
                state,
                event_key=group_key,
                level="info",
                message=f"Applied quota for group '{group_name}': {message}",
            )
        else:
            pending.append(group_name)
            _append_reconcile_event(
                state,
                event_key=group_key,
                level="error",
                message=f"Failed to apply quota for group '{group_name}': {message}",
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
        "managed_repository": repository_compatibility,
        "available_groups": sorted(available_groups),
        "applied_groups": sorted(set(applied)),
        "pending_groups": sorted(set(pending)),
        "quotas_gb": state.get("quotas_gb", {}),
        "logs": state.get("logs", []),
    }
