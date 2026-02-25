from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pwd import getpwuid
from grp import getgrgid
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "/OMERO/.admin-tools/group-quotas.json"
DEFAULT_ENFORCER_MARKER_PATH = "/OMERO/.admin-tools/quota-enforcer-installed"
DEFAULT_OMERO_DATA_DIR = "/OMERO"
DEFAULT_MANAGED_REPOSITORY_SUBDIR = "ManagedRepository"
DEFAULT_LOG_LIMIT = 200
EXPECTED_MANAGED_REPOSITORY_PREFIX = "%group%/%user%/"
STATE_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION_KEY = "state_schema_version"
AUTO_GROUP_QUOTA_ENV = "ADMIN_TOOLS_AUTO_SET_DEFAULT_GROUP_QUOTA"
DEFAULT_GROUP_QUOTA_ENV = "ADMIN_TOOLS_DEFAULT_GROUP_QUOTA_GB"
MIN_GROUP_QUOTA_ENV = "ADMIN_TOOLS_MIN_QUOTA_GB"
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


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise QuotaError(f"Missing required environment variable: {name}")
    return value


def _parse_bool_env(name: str) -> bool:
    raw_value = _required_env(name).lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise QuotaError(
        f"Invalid {name} value {raw_value!r}; expected one of: true/false, 1/0, yes/no, on/off."
    )


def _parse_quota_env(name: str) -> float:
    raw_value = _required_env(name)
    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise QuotaError(
            f"Invalid {name} value; expected a numeric value in GB."
        ) from exc
    if parsed <= 0:
        raise QuotaError(f"{name} must be greater than 0.")
    return round(parsed, 3)


def min_quota_gb() -> float:
    """Return minimum allowed quota in GB from environment."""
    return _parse_quota_env(MIN_GROUP_QUOTA_ENV)


def default_group_quota_gb() -> float:
    """Return default quota in GB for newly created groups from environment."""
    return _parse_quota_env(DEFAULT_GROUP_QUOTA_ENV)


def auto_set_default_group_quota_enabled() -> bool:
    """Return whether new OMERO groups should automatically receive default quotas."""
    return _parse_bool_env(AUTO_GROUP_QUOTA_ENV)


def is_quota_enforcement_available() -> bool:
    """Return True when the host-side quota enforcer is installed.

    The installer writes a marker file on the shared /OMERO volume when
    ext4 project quota support is confirmed and the systemd timer is
    installed.  The absence of this file means the host filesystem does
    not support quotas or the enforcer was never installed.
    """
    marker_path = quota_enforcer_marker_path()
    return marker_path.is_file()


def quota_enforcer_marker_path() -> Path:
    """Return host-side quota enforcer marker path from environment."""
    return Path(
        os.environ.get(
            "ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH",
            DEFAULT_ENFORCER_MARKER_PATH,
        )
    )


def _safe_username(uid: int) -> str:
    try:
        return getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _safe_groupname(gid: int) -> str:
    try:
        return getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _path_access_summary(path: Path) -> Dict[str, object]:
    """Return deterministic access diagnostics for an on-disk path."""
    uid = os.geteuid()
    gid = os.getegid()
    summary: Dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "is_directory": path.is_dir(),
        "writable": os.access(path, os.W_OK),
        "executable": os.access(path, os.X_OK),
        "effective_uid": uid,
        "effective_user": _safe_username(uid),
        "effective_gid": gid,
        "effective_group": _safe_groupname(gid),
    }
    if path.exists():
        stat_result = path.stat()
        summary.update(
            {
                "owner_uid": stat_result.st_uid,
                "owner_user": _safe_username(stat_result.st_uid),
                "owner_gid": stat_result.st_gid,
                "owner_group": _safe_groupname(stat_result.st_gid),
                "mode_octal": f"{stat_result.st_mode & 0o7777:04o}",
            }
        )
    return summary


def managed_group_root() -> Path:
    """Return OMERO managed repository group root from environment."""
    configured = os.environ.get("ADMIN_TOOLS_MANAGED_GROUP_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    omero_data_dir = os.environ.get("OMERO_DATA_DIR", DEFAULT_OMERO_DATA_DIR).strip()
    if not omero_data_dir:
        omero_data_dir = DEFAULT_OMERO_DATA_DIR
    return Path(omero_data_dir).expanduser() / DEFAULT_MANAGED_REPOSITORY_SUBDIR


def resolve_managed_group_root(known_groups: Sequence[str]) -> Tuple[Path, str]:
    """Return configured managed repository root without fallback resolution."""
    del known_groups
    group_root = managed_group_root()
    if group_root.exists() and group_root.is_dir():
        return group_root, "using configured managed repository root"
    return group_root, "configured managed repository root does not exist"


def _is_safe_managed_repository_root(path: Path) -> Tuple[bool, str]:
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path

    if not path.exists() or not path.is_dir():
        return False, "path does not exist or is not a directory"

    omero_data_root = Path(
        os.environ.get("OMERO_DATA_DIR", DEFAULT_OMERO_DATA_DIR).strip()
        or DEFAULT_OMERO_DATA_DIR
    ).expanduser()
    omero_root = omero_data_root.resolve()
    try:
        resolved.relative_to(omero_root)
    except ValueError:
        if resolved != omero_root:
            return False, f"path must be within {omero_root} mount"

    return True, ""


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _fresh_state() -> Dict[str, object]:
    """Return a blank quota state dict."""
    return {
        STATE_SCHEMA_VERSION_KEY: STATE_SCHEMA_VERSION,
        "quotas_gb": {},
        "logs": [],
    }


def _load_state(path: Path) -> Dict[str, object]:
    if not path.exists():
        return _fresh_state()
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        logger.warning(
            "Quota state file %s is empty; initialising fresh state", path
        )
        return _fresh_state()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Quota state file %s contains invalid JSON; initialising fresh state",
            path,
        )
        return _fresh_state()
    if not isinstance(data, dict):
        logger.warning(
            "Quota state file %s does not contain a JSON object; "
            "initialising fresh state",
            path,
        )
        return _fresh_state()
    schema_version = data.get(STATE_SCHEMA_VERSION_KEY)
    if schema_version is None:
        data[STATE_SCHEMA_VERSION_KEY] = STATE_SCHEMA_VERSION
    elif schema_version != STATE_SCHEMA_VERSION:
        raise QuotaError(
            "Unsupported quota state schema version "
            f"{schema_version!r}; expected {STATE_SCHEMA_VERSION}."
        )
    data.setdefault("quotas_gb", {})
    data.setdefault("logs", [])
    return data


def _write_state(path: Path, state: Dict[str, object]) -> None:
    state[STATE_SCHEMA_VERSION_KEY] = STATE_SCHEMA_VERSION
    _ensure_parent(path)
    serialized = json.dumps(state, indent=2, sort_keys=True)
    
    # We use a unique randomized suffix instead of a fixed .tmp to avoid ANY
    # chance of colliding with a locked or root-owned file from a previous 
    # process or host-side tool.
    random_suffix = uuid.uuid4().hex[:8]
    temp_path = path.with_suffix(f"{path.suffix}.tmp_{random_suffix}")
    
    try:
        temp_path.write_text(serialized, encoding="utf-8")
        
        # Ensure the final file maintains readability for the host enforcer (root)
        os.chmod(temp_path, 0o666)
        
        # os.replace is atomic on POSIX
        os.replace(temp_path, path)
    except PermissionError as exc:
        # Fallback if replacing fails (e.g., sticky bit preventing rename)
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
            
        if not path.exists() or not os.access(path, os.W_OK):
            raise QuotaError(
                f"Quota state path is not replaceable/writable: {path}. "
                "Ensure /OMERO/.admin-tools is mode 0777 without sticky-bit "
                "and writable by the omeroweb UID."
            ) from exc

        # Last resort fallback: direct write to existing file
        path.write_text(serialized, encoding="utf-8")
    finally:
        # Clean up any unique random tmp files we created if something went terribly wrong
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
            
        # Optional: Attempt to clean up the legacy fixed .tmp file to prevent future confusion
        legacy_tmp = path.with_suffix(f"{path.suffix}.tmp")
        try:
            legacy_tmp.unlink(missing_ok=True)
        except OSError:
            pass


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


def _can_manage_group_directories(group_root: Path) -> bool:
    return os.access(group_root, os.W_OK | os.X_OK)


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

    This function manages the quota state file and reports quota readiness.
    It never creates ManagedRepository group directories because OMERO.server
    owns repository registration. Actual filesystem-level enforcement (chattr, setquota) is
    performed by the host-side systemd timer (omero-quota-enforcer) which
    reads the same state file with root privileges.
    """
    with _RECONCILE_LOCK:
        path = quota_state_path()
        state = _load_state(path)
        quotas = state.setdefault("quotas_gb", {})
        assert isinstance(quotas, dict)

        auto_set_default_quota = auto_set_default_group_quota_enabled()
        default_quota_gb = default_group_quota_gb()
        minimum_quota_gb = min_quota_gb()
        if default_quota_gb < minimum_quota_gb:
            raise QuotaError(
                f"{DEFAULT_GROUP_QUOTA_ENV} ({default_quota_gb:.3f}) must be >= "
                f"{MIN_GROUP_QUOTA_ENV} ({minimum_quota_gb:.3f})."
            )

        for known_group_name in sorted(set(known_groups)):
            normalized_known_group_name = _normalize_group(str(known_group_name))
            if auto_set_default_quota and normalized_known_group_name not in quotas:
                quotas[normalized_known_group_name] = default_quota_gb
                _append_log(
                    state,
                    "info",
                    (
                        f"Auto-created quota for new group '{normalized_known_group_name}' at "
                        f"{default_quota_gb:.3f} GB (source=auto-group-create)."
                    ),
                )

        group_root, root_reason = resolve_managed_group_root(known_groups)
        root_is_safe, root_safety_reason = _is_safe_managed_repository_root(group_root)
        available_groups = (
            set(list_group_directories(group_root)) if root_is_safe else set()
        )
        available_groups.update(set(known_groups))

        filesystem = detect_filesystem(group_root)
        repository_compatibility = managed_repository_compatibility()
        group_root_access = _path_access_summary(group_root)
        enforcer_marker = quota_enforcer_marker_path()
        enforcer_available = is_quota_enforcement_available()

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
                pending.append(group_name)
                if not _can_manage_group_directories(group_root):
                    _append_reconcile_event(
                        state,
                        event_key=group_key,
                        level="info",
                        message=(
                            f"Quota pending for group '{group_name}': managed root "
                            f"{group_root} is not writable by the omeroweb process "
                            f"(uid={group_root_access['effective_uid']}:{group_root_access['effective_gid']} "
                            f"{group_root_access['effective_user']}:{group_root_access['effective_group']}; "
                            f"mode={group_root_access.get('mode_octal', 'unknown')}; "
                            f"owner={group_root_access.get('owner_user', 'unknown')}:{group_root_access.get('owner_group', 'unknown')}). "
                            "Waiting for OMERO.server to create/register the directory during normal import/group operations. "
                            f"enforcer_available={enforcer_available} marker={enforcer_marker}"
                        ),
                    )
                else:
                    _append_reconcile_event(
                        state,
                        event_key=group_key,
                        level="info",
                        message=(
                            f"Quota pending for group '{group_name}': directory not present at {group_path}. "
                            "Waiting for OMERO.server to create/register the directory during normal import/group operations. "
                            f"enforcer_available={enforcer_available} marker={enforcer_marker}"
                        ),
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
        try:
            _write_state(path, state)
        except OSError:
            logger.warning(
                "Could not persist quota state to %s; "
                "reconciliation result is still valid but changes will not "
                "be saved until the directory is writable",
                path,
                exc_info=True,
            )
        return {
            "filesystem": {
                "type": filesystem.fs_type,
                "mount_point": filesystem.mount_point,
                "source": filesystem.source,
            },
            "managed_group_root": str(group_root),
            "managed_group_root_reason": root_reason,
            "managed_group_root_access": group_root_access,
            "managed_repository": repository_compatibility,
            "available_groups": sorted(available_groups),
            "applied_groups": sorted(set(configured)),
            "pending_groups": sorted(set(pending)),
            "quotas_gb": state.get("quotas_gb", {}),
            "logs": state.get("logs", []),
            "min_quota_gb": min_quota_gb(),
            "quota_enforcement_available": enforcer_available,
            "quota_enforcer_marker_path": str(enforcer_marker),
        }