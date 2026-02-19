from __future__ import annotations

import json
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from omeroweb_admin_tools.services.storage_quotas import (
    detect_filesystem,
    managed_repository_compatibility,
    import_quotas_csv,
    QuotaError,
    quota_csv_template,
    reconcile_quotas,
    upsert_quotas,
)
from omeroweb_admin_tools.views.index_view import (
    storage_quota_import,
    storage_quota_template,
    storage_quota_update,
)


def test_quota_csv_template_headers() -> None:
    assert quota_csv_template() == "Group,Quota [GB]\n"


def test_upsert_and_import_quotas_roundtrip(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])
    import_quotas_csv("Group,Quota [GB]\ngroup-b,22.5\n")

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 10.0
    assert payload["quotas_gb"]["group-b"] == 22.5
    assert payload["logs"]


def test_upsert_deletes_quota_for_null_or_empty_value(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])
    upsert_quotas([("group-a", None)])
    upsert_quotas([("group-b", 12)])
    upsert_quotas([("group-b", "")])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert "group-a" not in payload["quotas_gb"]
    assert "group-b" not in payload["quotas_gb"]


def test_upsert_skips_delete_log_when_quota_not_set(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", None)])

    assert not state_path.exists()


def test_upsert_does_not_repeat_log_for_unchanged_quota(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])
    upsert_quotas([("group-a", 10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    info_messages = [
        entry["message"] for entry in payload["logs"] if entry["level"] == "info"
    ]
    assert info_messages == [
        "Updated quota for group 'group-a' to 10.000 GB (source=ui)."
    ]


def test_upsert_rejects_quota_below_minimum(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    try:
        upsert_quotas([("group-a", 0.09)])
    except QuotaError as exc:
        assert "at least 0.10 GB" in str(exc)
    else:
        raise AssertionError("Expected quota validation error for value below 0.10 GB")


def test_upsert_respects_minimum_quota_from_environment(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("ADMIN_TOOLS_MIN_QUOTA_GB", "0.10")

    upsert_quotas([("group-a", 0.10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 0.1


def test_upsert_rejects_invalid_environment_minimum_quota(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("ADMIN_TOOLS_MIN_QUOTA_GB", "invalid")

    try:
        upsert_quotas([("group-a", 1.0)])
    except QuotaError as exc:
        assert "Invalid ADMIN_TOOLS_MIN_QUOTA_GB value" in str(exc)
    else:
        raise AssertionError("Expected quota validation error for invalid environment minimum")


def test_reconcile_marks_pending_when_group_directory_missing(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    group_root.mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )

    upsert_quotas([("new-group", 3)])
    result = reconcile_quotas([])

    assert "new-group" in result["pending_groups"]
    assert result["managed_group_root"] == str(group_root)


def test_detect_filesystem_returns_metadata_for_existing_path() -> None:
    fs = detect_filesystem(Path("/tmp"))

    assert isinstance(fs.fs_type, str)
    assert isinstance(fs.mount_point, str)


def test_storage_quota_update_endpoint(monkeypatch) -> None:
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data=json.dumps({"updates": [{"group": "demo", "quota_gb": 15}]}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.upsert_quotas",
        lambda updates, source: {"quotas_gb": {"demo": 15.0}},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda groups: {"logs": []},
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 200


def test_storage_quota_import_and_template_endpoints(monkeypatch) -> None:
    file_payload = b"Group,Quota [GB]\ndemo,12\n"
    upload = SimpleUploadedFile("quotas.csv", file_payload, content_type="text/csv")
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/import/",
        data={"file": upload},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.import_quotas_csv",
        lambda content: {"quotas_gb": {"demo": 12.0}},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda groups: {"logs": []},
    )

    response = storage_quota_import(request, conn=None)
    template_response = storage_quota_template(RequestFactory().get("/"), conn=None)

    assert response.status_code == 200
    assert template_response.status_code == 200
    assert b"Group,Quota [GB]" in template_response.content


def test_managed_repository_compatibility_requires_group_user_prefix(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "CONFIG_omero_fs_repo_path",
        "%user%/%group%/%year%-%month%-%day%/%time%",
    )

    compatibility = managed_repository_compatibility()

    assert compatibility["is_compatible"] is False


def test_reconcile_marks_all_pending_when_template_incompatible(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    (group_root / "group-a").mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%user%/%group%/%time%")

    upsert_quotas([("group-a", 5)])
    result = reconcile_quotas([])

    assert "group-a" in result["pending_groups"]
    assert result["managed_repository"]["is_compatible"] is False


def test_reconcile_deduplicates_non_warning_logs(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    (group_root / "group-a").mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setenv(
        "ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE",
        "python3 -c \"print(\\'ok\\')\"",
    )

    upsert_quotas([("group-a", 5)])
    reconcile_quotas(["group-a"])
    reconcile_quotas(["group-a"])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    applied_messages = [
        entry["message"]
        for entry in payload["logs"]
        if entry["message"].startswith("Applied quota for group 'group-a'")
    ]
    assert len(applied_messages) == 1


def test_reconcile_repeats_warnings_and_cleans_event_cache_after_quota_delete(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    group_root.mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")

    upsert_quotas([("group-a", 5)])
    reconcile_quotas([])
    reconcile_quotas([])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    warning_messages = [
        entry["message"]
        for entry in payload["logs"]
        if entry["message"].startswith("Quota pending for group 'group-a'")
    ]
    assert len(warning_messages) == 2

    upsert_quotas([("group-a", None)])
    reconcile_quotas([])

    updated_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated_payload["_reconcile_event_cache"] == {}


def test_reconcile_uses_default_ext4_enforcer_when_command_template_unset(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    (group_root / "group-a").mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.delenv("ADMIN_TOOLS_QUOTA_APPLY_COMMAND_TEMPLATE", raising=False)

    upsert_quotas([("group-a", 5)])

    seen = {}

    def _fake_run(
        *, command_template, filesystem, group_name, group_path, quota_bytes, quota_gb
    ):
        seen["command_template"] = command_template
        return True, "ok"

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.detect_filesystem",
        lambda path: type(
            "Fs",
            (),
            {"fs_type": "ext4", "mount_point": "/OMERO", "source": "/dev/demo"},
        )(),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._run_quota_apply_command",
        _fake_run,
    )

    result = reconcile_quotas(["group-a"])

    assert "group-a" in result["applied_groups"]
    assert "enforce-ext4-project-quota.sh" in seen["command_template"]
