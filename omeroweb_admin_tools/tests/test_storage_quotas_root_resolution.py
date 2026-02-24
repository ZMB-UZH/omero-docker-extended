from __future__ import annotations

import pytest

from omeroweb_admin_tools.services.storage_quotas import (
    AUTO_GROUP_QUOTA_ENV,
    DEFAULT_GROUP_QUOTA_ENV,
    MIN_GROUP_QUOTA_ENV,
    is_quota_enforcement_available,
    reconcile_quotas,
    resolve_managed_group_root,
    upsert_quotas,
)


@pytest.fixture(autouse=True)
def _set_required_quota_env(monkeypatch) -> None:
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(DEFAULT_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(AUTO_GROUP_QUOTA_ENV, "false")


def test_resolve_managed_group_root_uses_fixed_path_when_present(
    tmp_path, monkeypatch
) -> None:
    managed_root = tmp_path / "OMERO" / "ManagedRepository"
    managed_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(managed_root))

    root, reason = resolve_managed_group_root(["group-a", "group-b"])

    assert root == managed_root
    assert reason == "using configured managed repository root"


def test_resolve_managed_group_root_reports_missing_fixed_path(
    tmp_path, monkeypatch
) -> None:
    missing_root = tmp_path / "OMERO" / "ManagedRepository"

    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(missing_root))

    root, reason = resolve_managed_group_root(["unknown-group"])

    assert root == missing_root
    assert reason == "configured managed repository root does not exist"


def test_reconcile_blocks_enforcement_for_unsafe_root(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    unsafe_root = tmp_path / "not-omero"
    unsafe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
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


def test_reconcile_keeps_missing_group_directory_pending(tmp_path, monkeypatch) -> None:
    """Reconcile never creates missing group directories; it reports pending status."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
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

    assert not group_dir.exists()
    assert "new-group" not in result["applied_groups"]
    assert "new-group" in result["pending_groups"]
    assert any(
        "Waiting for OMERO.server to create/register the directory" in entry["message"]
        for entry in result["logs"]
    )


def test_reconcile_keeps_pending_without_known_groups(tmp_path, monkeypatch) -> None:
    """Reconcile keeps quotas pending when known_groups is empty and directory is absent."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
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

    assert not group_dir.exists()
    assert "users" not in result["applied_groups"]
    assert "users" in result["pending_groups"]


def test_reconcile_skips_directory_creation_when_root_unsafe(
    tmp_path, monkeypatch
) -> None:
    """Directory is never created when managed repository root is unsafe."""
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
    """Directory is never created when repository template is incompatible."""
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


def test_reconcile_reports_configured_when_directory_already_exists(tmp_path, monkeypatch) -> None:
    """Existing directory is reported as configured."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    (safe_root / "existing-group").mkdir()

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
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


def test_reconcile_reports_configured_status_for_ready_groups(
    tmp_path, monkeypatch
) -> None:
    """Groups with quota + existing directory are reported as configured (applied)."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    (safe_root / "group-a").mkdir()
    (safe_root / "group-b").mkdir()

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    upsert_quotas([("group-a", 5), ("group-b", 10)])
    result = reconcile_quotas(["group-a", "group-b"])

    assert sorted(result["applied_groups"]) == ["group-a", "group-b"]
    assert result["pending_groups"] == []
    assert any(
        "Host-side enforcer will apply" in entry["message"]
        for entry in result["logs"]
    )


def test_is_quota_enforcement_available_returns_true_when_marker_exists(
    tmp_path, monkeypatch
) -> None:
    """Enforcement is available when marker file exists."""
    marker = tmp_path / ".admin-tools" / "quota-enforcer-installed"
    marker.parent.mkdir(parents=True)
    marker.write_text("installed\n")

    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(marker)
    )

    assert is_quota_enforcement_available() is True


def test_is_quota_enforcement_available_returns_false_when_marker_missing(
    tmp_path, monkeypatch
) -> None:
    """Enforcement is NOT available when marker file is absent."""
    missing_marker = tmp_path / ".admin-tools" / "quota-enforcer-installed"

    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(missing_marker)
    )

    assert is_quota_enforcement_available() is False


def test_is_quota_enforcement_available_returns_false_when_marker_is_directory(
    tmp_path, monkeypatch
) -> None:
    """Enforcement is NOT available when marker path is a directory (not a file)."""
    marker_dir = tmp_path / ".admin-tools" / "quota-enforcer-installed"
    marker_dir.mkdir(parents=True)

    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(marker_dir)
    )

    assert is_quota_enforcement_available() is False


def test_reconcile_includes_enforcement_available_flag(
    tmp_path, monkeypatch
) -> None:
    """reconcile_quotas includes quota_enforcement_available in response."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    marker = tmp_path / "marker"
    marker.write_text("installed\n")

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(marker))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    result = reconcile_quotas([])

    assert "quota_enforcement_available" in result
    assert result["quota_enforcement_available"] is True


def test_reconcile_reports_enforcement_unavailable_when_marker_missing(
    tmp_path, monkeypatch
) -> None:
    """reconcile_quotas reports enforcement unavailable when marker is missing."""
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    missing_marker = tmp_path / "nonexistent-marker"

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(missing_marker)
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (safe_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    result = reconcile_quotas([])

    assert result["quota_enforcement_available"] is False
