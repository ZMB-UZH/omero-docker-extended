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


def test_upsert_rejects_quota_below_minimum(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    try:
        upsert_quotas([("group-a", 0.99)])
    except QuotaError as exc:
        assert "at least 1.00 GB" in str(exc)
    else:
        raise AssertionError("Expected quota validation error for value below 1.00 GB")

def test_reconcile_marks_pending_when_group_directory_missing(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    group_root.mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(group_root))

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
    monkeypatch.setenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", str(group_root))
    monkeypatch.setenv(
        "CONFIG_omero_fs_repo_path", "%user%/%group%/%time%"
    )

    upsert_quotas([("group-a", 5)])
    result = reconcile_quotas([])

    assert "group-a" in result["pending_groups"]
    assert result["managed_repository"]["is_compatible"] is False
