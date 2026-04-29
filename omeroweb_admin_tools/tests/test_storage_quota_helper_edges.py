from __future__ import annotations

import json
from pathlib import Path

import pytest

from omeroweb_admin_tools.services import storage_quotas


@pytest.fixture(autouse=True)
def _quota_env(monkeypatch):
    """Handle quota env."""
    monkeypatch.setenv(storage_quotas.MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(storage_quotas.DEFAULT_GROUP_QUOTA_ENV, "0.25")
    monkeypatch.setenv(storage_quotas.AUTO_GROUP_QUOTA_ENV, "false")


def test_storage_quota_env_and_root_helpers_cover_validation_edges(
    monkeypatch,
    tmp_path,
):
    """Verify test storage quota env and root helpers cover behavior."""
    monkeypatch.setenv(storage_quotas.AUTO_GROUP_QUOTA_ENV, "maybe")
    with pytest.raises(storage_quotas.QuotaError, match="expected one of"):
        storage_quotas.auto_set_default_group_quota_enabled()

    monkeypatch.setenv(storage_quotas.MIN_GROUP_QUOTA_ENV, "0")
    with pytest.raises(storage_quotas.QuotaError, match="greater than 0"):
        storage_quotas.min_quota_gb()

    monkeypatch.setattr(
        storage_quotas, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid))
    )
    monkeypatch.setattr(
        storage_quotas, "getgrgid", lambda gid: (_ for _ in ()).throw(KeyError(gid))
    )
    assert storage_quotas._safe_username(7) == "7"
    assert storage_quotas._safe_groupname(8) == "8"

    monkeypatch.delenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", raising=False)
    monkeypatch.setenv("CONFIG_omero_managed_dir", "ManagedRepository")
    monkeypatch.setenv("OMERO_DATA_DIR", "")
    assert storage_quotas.managed_group_root() == Path("/OMERO/ManagedRepository")

    missing_root = tmp_path / "missing"
    assert storage_quotas._is_safe_managed_repository_root(missing_root) == (
        False,
        "path does not exist or is not a directory",
    )

    managed_root = tmp_path / "ManagedRepository"
    managed_root.mkdir()
    monkeypatch.setenv("OMERO_DATA_DIR", str(tmp_path))
    real_resolve = Path.resolve

    def _resolve(self, *args, **kwargs):
        """Handle resolve."""
        if self == managed_root:
            raise FileNotFoundError("deferred mount metadata")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _resolve)
    assert storage_quotas._is_safe_managed_repository_root(managed_root) == (True, "")


def test_storage_quota_state_and_log_helpers_cover_normalization_paths(
    monkeypatch,
    tmp_path,
):
    """Verify test storage quota state and log helpers cove behavior."""
    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps({"quotas_gb": {}, "logs": []}),
        encoding="utf-8",
    )
    loaded = storage_quotas._load_state(state_path)
    assert loaded[storage_quotas.STATE_SCHEMA_VERSION_KEY] == (
        storage_quotas.STATE_SCHEMA_VERSION
    )

    with pytest.raises(TypeError, match="Expected 'logs' to be a list"):
        storage_quotas._append_log({"logs": "bad"}, "info", "message")

    monkeypatch.setattr(storage_quotas, "DEFAULT_LOG_LIMIT", 2)
    state = {"logs": []}
    storage_quotas._append_log(state, "info", "first")
    storage_quotas._append_log(state, "info", "first")
    storage_quotas._append_log(state, "info", "second")
    storage_quotas._append_log(state, "warning", "third")
    assert [entry["message"] for entry in state["logs"]] == ["second", "third"]

    cache = storage_quotas._reconcile_event_cache({"_reconcile_event_cache": "bad"})
    assert cache == {}

    with pytest.raises(storage_quotas.QuotaError, match="must not be empty"):
        storage_quotas._normalize_group("   ")

    with pytest.raises(storage_quotas.QuotaError, match="Invalid quota value"):
        storage_quotas._normalize_quota_gb("not-a-number")

    with pytest.raises(storage_quotas.QuotaError, match="Invalid quota value"):
        storage_quotas._normalize_quota_gb(["not", "a", "scalar"])


def test_storage_quota_csv_filesystem_and_state_helpers_cover_edge_cases(
    monkeypatch,
    tmp_path,
):
    """Verify test storage quota CSV filesystem and state h behavior."""
    with pytest.raises(storage_quotas.QuotaError, match="CSV file is empty"):
        storage_quotas.import_quotas_csv("")

    with pytest.raises(storage_quotas.QuotaError, match="at least 2 columns"):
        storage_quotas.import_quotas_csv("Group,Quota [GB]\nonly-group\n")

    with pytest.raises(storage_quotas.QuotaError, match="no quota rows"):
        storage_quotas.import_quotas_csv("Group,Quota [GB]\n,\n")

    assert storage_quotas.list_group_directories(tmp_path / "missing") == []

    real_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: False if str(self) == "/proc/mounts" else real_exists(self),
    )
    assert storage_quotas.detect_filesystem(tmp_path) == storage_quotas.FilesystemInfo(
        fs_type="unknown",
        mount_point="",
        source="",
    )

    monkeypatch.setattr(Path, "exists", real_exists)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, encoding="utf-8": "badline\n/dev/sda1 /other ext4 rw 0 0\n",
    )
    assert storage_quotas.detect_filesystem(tmp_path) == storage_quotas.FilesystemInfo(
        fs_type="unknown",
        mount_point="",
        source="",
    )

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": [],
                "logs": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    state = storage_quotas.get_state()
    assert state["quotas_gb"] == {}
    assert state["logs"] == []


def test_reconcile_quotas_covers_invalid_state_entries_and_persist_warnings(
    monkeypatch,
    tmp_path,
):
    """Verify test reconcile quotas covers invalid state en behavior."""
    invalid_state_path = tmp_path / "invalid-state.json"
    invalid_state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": [],
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(invalid_state_path))
    with pytest.raises(TypeError, match="Expected 'quotas_gb' to be a dict"):
        storage_quotas.reconcile_quotas([])

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": {"group-a": "bad"},
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    managed_root = tmp_path / "ManagedRepository"
    managed_root.mkdir()
    monkeypatch.setattr(
        storage_quotas,
        "resolve_managed_group_root",
        lambda known_groups: (managed_root, "configured"),
    )
    monkeypatch.setattr(
        storage_quotas,
        "_is_safe_managed_repository_root",
        lambda path: (True, ""),
    )
    monkeypatch.setattr(
        storage_quotas,
        "detect_filesystem",
        lambda path: storage_quotas.FilesystemInfo("ext4", "/", "/dev/sda1"),
    )
    monkeypatch.setattr(
        storage_quotas,
        "managed_repository_compatibility",
        lambda: {
            "template": storage_quotas.EXPECTED_MANAGED_REPOSITORY_PREFIX,
            "expected_prefix": storage_quotas.EXPECTED_MANAGED_REPOSITORY_PREFIX,
            "is_compatible": True,
        },
    )
    monkeypatch.setattr(
        storage_quotas, "_path_access_summary", lambda path: {"mode_octal": "0770"}
    )
    monkeypatch.setattr(storage_quotas, "is_quota_enforcement_available", lambda: True)
    monkeypatch.setattr(
        storage_quotas,
        "_write_state",
        lambda path, state: (_ for _ in ()).throw(OSError("readonly")),
    )

    result = storage_quotas.reconcile_quotas([])

    assert result["applied_groups"] == []
    assert result["pending_groups"] == []
    assert any(
        "Invalid stored quota for group 'group-a'" in entry["message"]
        for entry in result["logs"]
    )
