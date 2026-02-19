from __future__ import annotations

from pathlib import Path

from omeroweb_admin_tools.services.storage_quotas import (
    reconcile_quotas,
    resolve_managed_group_root,
    upsert_quotas,
)


def test_resolve_managed_group_root_prefers_candidate_with_group_matches(
    tmp_path, monkeypatch
) -> None:
    c1 = tmp_path / "candidate-1"
    c2 = tmp_path / "candidate-2"
    c1.mkdir(parents=True)
    c2.mkdir(parents=True)
    (c2 / "group-a").mkdir()

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._candidate_managed_group_roots",
        lambda: [c1, c2],
    )

    root, reason = resolve_managed_group_root(["group-a", "group-b"])

    assert root == c2
    assert "matched 1" in reason


def test_resolve_managed_group_root_falls_back_to_first_existing_candidate(
    tmp_path, monkeypatch
) -> None:
    c1 = tmp_path / "candidate-1"
    c2 = tmp_path / "candidate-2"
    c1.mkdir(parents=True)
    c2.mkdir(parents=True)

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._candidate_managed_group_roots",
        lambda: [c1, c2],
    )

    root, reason = resolve_managed_group_root(["unknown-group"])

    assert root == c1
    assert "no candidate matched known groups" in reason


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
