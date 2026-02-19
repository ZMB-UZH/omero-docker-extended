from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from omeroweb_admin_tools.services.storage_quotas import (
    reconcile_quotas,
    resolve_managed_group_root,
    upsert_quotas,
)


def test_resolve_managed_group_root_uses_fixed_path_when_present(
    tmp_path, monkeypatch
) -> None:
    managed_root = tmp_path / "OMERO" / "ManagedRepository"
    managed_root.mkdir(parents=True)

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.MANAGED_GROUP_ROOT",
        managed_root,
    )

    root, reason = resolve_managed_group_root(["group-a", "group-b"])

    assert root == managed_root
    assert reason == "using fixed managed repository root"


def test_resolve_managed_group_root_reports_missing_fixed_path(
    tmp_path, monkeypatch
) -> None:
    missing_root = tmp_path / "OMERO" / "ManagedRepository"

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.MANAGED_GROUP_ROOT",
        missing_root,
    )

    root, reason = resolve_managed_group_root(["unknown-group"])

    assert root == missing_root
    assert reason == "fixed managed repository root does not exist"


def test_reconcile_blocks_enforcement_for_unsafe_root(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    unsafe_root = tmp_path / "not-omero"
    unsafe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print('should-not-run')\"",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (unsafe_root, "test-unsafe-root"),
    )

    upsert_quotas([("group-a", 5)])
    result = reconcile_quotas(["group-a"])

    assert result["applied_groups"] == []
    assert "group-a" in result["pending_groups"]
    assert any(
        "ManagedRepository root is unsafe for quota enforcement" in entry["message"]
        for entry in result["logs"]
    )


def test_reconcile_includes_detection_reason_in_response(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    (safe_root / "group-a").mkdir()

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print('ok')\"",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "unit-test-detected"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("group-a", 5)])
    result = reconcile_quotas(["group-a"])

    assert result["managed_group_root_reason"] == "unit-test-detected"


def test_reconcile_creates_missing_group_directory(tmp_path, monkeypatch) -> None:
    """Reconcile auto-creates group directory when root is safe and template compatible."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print('ok')\"",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("new-group", 5)])
    group_dir = safe_root / "new-group"
    assert not group_dir.exists()

    result = reconcile_quotas(["new-group"])

    assert group_dir.exists() and group_dir.is_dir()
    assert "new-group" in result["applied_groups"]
    assert "new-group" not in result["pending_groups"]
    assert any(
        "Created group directory for quota enforcement" in entry["message"]
        for entry in result["logs"]
    )


def test_reconcile_creates_directory_without_known_groups(tmp_path, monkeypatch) -> None:
    """Reconcile auto-creates directory even when known_groups is empty (UI path)."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print('ok')\"",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("users", 1)])
    group_dir = safe_root / "users"
    assert not group_dir.exists()

    result = reconcile_quotas([])

    assert group_dir.exists() and group_dir.is_dir()
    assert "users" in result["applied_groups"]
    assert "users" not in result["pending_groups"]


def test_reconcile_logs_warning_when_directory_creation_fails(
    tmp_path, monkeypatch
) -> None:
    """Reconcile logs a warning when directory creation fails (e.g. permissions)."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print('ok')\"",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("fail-group", 5)])

    original_mkdir = Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if self.name == "fail-group":
            raise OSError("Permission denied")
        return original_mkdir(self, *args, **kwargs)

    with patch.object(Path, "mkdir", failing_mkdir):
        result = reconcile_quotas([])

    assert "fail-group" in result["pending_groups"]
    assert "fail-group" not in result["applied_groups"]
    assert any(
        "could not create directory" in entry["message"]
        and "fail-group" in entry["message"]
        for entry in result["logs"]
    )


def test_reconcile_skips_directory_creation_when_root_unsafe(
    tmp_path, monkeypatch
) -> None:
    """Directory is NOT created when managed repository root is unsafe."""
    state_path = tmp_path / "quotas.json"
    unsafe_root = tmp_path / "unsafe"
    unsafe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (unsafe_root, "test-unsafe"),
    )

    upsert_quotas([("some-group", 5)])
    result = reconcile_quotas([])

    assert not (unsafe_root / "some-group").exists()
    assert "some-group" in result["pending_groups"]


def test_reconcile_skips_directory_creation_when_template_incompatible(
    tmp_path, monkeypatch
) -> None:
    """Directory is NOT created when repository template is incompatible."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%user%/%group%/%time%")
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("some-group", 5)])
    result = reconcile_quotas([])

    assert not (safe_root / "some-group").exists()
    assert "some-group" in result["pending_groups"]


def test_reconcile_does_not_recreate_existing_directory(tmp_path, monkeypatch) -> None:
    """No creation log when group directory already exists."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    (safe_root / "existing-group").mkdir()

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print('ok')\"",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("existing-group", 5)])
    result = reconcile_quotas(["existing-group"])

    assert "existing-group" in result["applied_groups"]
    assert not any(
        "Created group directory" in entry["message"]
        for entry in result["logs"]
    )
