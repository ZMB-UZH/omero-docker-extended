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
    """Set the required quota environment.

    Inputs: `monkeypatch` pytest monkeypatch fixture. Output: None.
    """
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(DEFAULT_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(AUTO_GROUP_QUOTA_ENV, "false")


def test_resolve_managed_group_root_uses_fixed_path_when_present(
    tmp_path, monkeypatch
) -> None:
    """Verify the resolve managed group root uses fixed path when present safety boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions when resolve managed group root uses fixed path when present accepts unsafe input.
    """
    managed_root = tmp_path / "OMERO" / "ManagedRepository"
    managed_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(managed_root))

    root, reason = resolve_managed_group_root(["group-a", "group-b"])

    assert root == managed_root
    assert reason == "using configured managed repository root"


def test_resolve_managed_group_root_reports_missing_fixed_path(
    tmp_path, monkeypatch
) -> None:
    """Verify the resolve managed group root reports missing fixed path safety boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions when resolve managed group root reports missing fixed path accepts unsafe input.
    """
    missing_root = tmp_path / "OMERO" / "ManagedRepository"

    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(missing_root))

    root, reason = resolve_managed_group_root(["unknown-group"])

    assert root == missing_root
    assert reason == "configured managed repository root does not exist"


def test_resolve_managed_group_root_uses_absolute_server_setting(
    tmp_path, monkeypatch
) -> None:
    """Verify resolve managed group root uses absolute server setting.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in resolve managed group root uses absolute server setting.
    """
    managed_root = tmp_path / "OMERO" / "ManagedRepository"
    managed_root.mkdir(parents=True)

    monkeypatch.delenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", raising=False)
    monkeypatch.setenv("CONFIG_omero_managed_dir", str(managed_root))
    monkeypatch.setenv("OMERO_DATA_DIR", str(tmp_path / "OTHER"))

    root, reason = resolve_managed_group_root(["group-a"])

    assert root == managed_root
    assert reason == "using configured managed repository root"


def test_reconcile_blocks_enforcement_for_unsafe_root(tmp_path, monkeypatch) -> None:
    """Confirm reconcile blocks enforcement for unsafe root is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile blocks enforcement for unsafe root.
    """
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
    """Verify reconcile includes detection reason in response result shape.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile includes detection reason in response.
    """
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
    """Check that reconcile keeps missing group directory pending remains stable.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile keeps missing group directory pending.
    """
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
    """Check that reconcile keeps pending without known groups remains stable.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile keeps pending without known groups.
    """
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
    """Verify reconcile skips directory creation when root unsafe.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile skips directory creation when root unsafe.
    """
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
    """Check reconcile skips directory creation when template incompatible renders the expected surface.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile skips directory creation when template incompatible.
    """
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


def test_reconcile_reports_configured_when_directory_already_exists(
    tmp_path, monkeypatch
) -> None:
    """Verify reconcile reports configured when directory already exists.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile reports configured when directory already exists.
    """
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
    """Verify reconcile reports configured status for ready groups.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile reports configured status for ready groups.
    """
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
        "Host-side enforcer will apply" in entry["message"] for entry in result["logs"]
    )


def test_is_quota_enforcement_available_returns_true_when_marker_exists(
    tmp_path, monkeypatch
) -> None:
    """Verify is quota enforcement available returns true when marker exists result shape.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in is quota enforcement available returns true when marker exists.
    """
    marker = tmp_path / ".admin-tools" / "quota-enforcer-installed"
    marker.parent.mkdir(parents=True)
    marker.write_text("installed\n")

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(marker))

    assert is_quota_enforcement_available() is True


def test_is_quota_enforcement_available_returns_false_when_marker_missing(
    tmp_path, monkeypatch
) -> None:
    """Verify is quota enforcement available returns false when marker missing result shape.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in is quota enforcement available returns false when marker missing.
    """
    missing_marker = tmp_path / ".admin-tools" / "quota-enforcer-installed"

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(missing_marker))

    assert is_quota_enforcement_available() is False


def test_is_quota_enforcement_available_returns_false_when_marker_is_directory(
    tmp_path, monkeypatch
) -> None:
    """Verify is quota enforcement available returns false when marker is directory result shape.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in is quota enforcement available returns false when marker is directory.
    """
    marker_dir = tmp_path / ".admin-tools" / "quota-enforcer-installed"
    marker_dir.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(marker_dir))

    assert is_quota_enforcement_available() is False


def test_reconcile_includes_enforcement_available_flag(tmp_path, monkeypatch) -> None:
    """Verify reconcile includes enforcement available flag.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile includes enforcement available flag.
    """
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
    """Verify reconcile reports enforcement unavailable when marker missing.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile reports enforcement unavailable when marker missing.
    """
    state_path = tmp_path / "quotas.json"
    safe_root = tmp_path / "safe" / "group-root"
    safe_root.mkdir(parents=True)
    missing_marker = tmp_path / "nonexistent-marker"

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_ENFORCER_MARKER_PATH", str(missing_marker))
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
