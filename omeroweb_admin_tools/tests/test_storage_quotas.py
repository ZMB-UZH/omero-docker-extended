from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from omeroweb_admin_tools.services.storage_quotas import (
    AUTO_GROUP_QUOTA_ENV,
    DEFAULT_GROUP_QUOTA_ENV,
    MIN_GROUP_QUOTA_ENV,
    detect_filesystem,
    managed_group_root,
    managed_repository_compatibility,
    import_quotas_csv,
    QuotaError,
    quota_csv_template,
    reconcile_quotas,
    STATE_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION_KEY,
    upsert_quotas,
)
from omeroweb_admin_tools.views.index_view import (
    storage_quota_import,
    storage_quota_template,
    storage_quota_update,
)

import pytest


@pytest.fixture(autouse=True)
def _set_required_quota_env(monkeypatch) -> None:
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(DEFAULT_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(AUTO_GROUP_QUOTA_ENV, "false")


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


def test_upsert_writes_schema_version(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload[STATE_SCHEMA_VERSION_KEY] == STATE_SCHEMA_VERSION


def test_reconcile_rejects_unknown_schema_version(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps(
            {
                STATE_SCHEMA_VERSION_KEY: STATE_SCHEMA_VERSION + 1,
                "quotas_gb": {"group-a": 1.0},
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    with pytest.raises(QuotaError, match="Unsupported quota state schema version"):
        reconcile_quotas(["group-a"])


def test_upsert_falls_back_when_atomic_replace_is_not_permitted(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps(
            {
                STATE_SCHEMA_VERSION_KEY: STATE_SCHEMA_VERSION,
                "quotas_gb": {"group-a": 1.0},
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    def _deny_replace(_src: Path, _dst: Path) -> None:
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.os.replace", _deny_replace
    )

    upsert_quotas([("group-b", 2.0)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 1.0
    assert payload["quotas_gb"]["group-b"] == 2.0


def test_upsert_raises_clear_error_when_replace_and_write_are_not_permitted(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps(
            {
                STATE_SCHEMA_VERSION_KEY: STATE_SCHEMA_VERSION,
                "quotas_gb": {"group-a": 1.0},
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    def _deny_replace(_src: Path, _dst: Path) -> None:
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.os.replace", _deny_replace
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.os.access",
        lambda _path, _mode: False,
    )

    with pytest.raises(QuotaError, match="not replaceable/writable"):
        upsert_quotas([("group-b", 2.0)])


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
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")

    upsert_quotas([("group-a", 0.10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 0.1


def test_upsert_rejects_invalid_environment_minimum_quota(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "invalid")

    try:
        upsert_quotas([("group-a", 1.0)])
    except QuotaError as exc:
        assert f"Invalid {MIN_GROUP_QUOTA_ENV} value" in str(exc)
    else:
        raise AssertionError(
            "Expected quota validation error for invalid environment minimum"
        )


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


def test_managed_group_root_uses_environment_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OMERO_DATA_DIR", "/custom-omero")

    assert managed_group_root() == Path("/custom-omero/ManagedRepository")


def test_reconcile_does_not_attempt_mkdir_when_root_is_not_writable(
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
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._can_manage_group_directories",
        lambda path: False,
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")

    upsert_quotas([("group-a", 5)])
    result = reconcile_quotas([])

    assert "group-a" in result["pending_groups"]
    assert any("managed root" in entry["message"] for entry in result["logs"])


def test_reconcile_auto_sets_default_quota_for_new_group(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    group_root.mkdir(parents=True)

    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv(AUTO_GROUP_QUOTA_ENV, "true")
    monkeypatch.setenv(DEFAULT_GROUP_QUOTA_ENV, "0.25")
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )

    result = reconcile_quotas(["group-a"])

    assert result["quotas_gb"]["group-a"] == 0.25
    assert "group-a" in result["pending_groups"]


def test_reconcile_rejects_default_quota_below_minimum(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv(AUTO_GROUP_QUOTA_ENV, "true")
    monkeypatch.setenv(DEFAULT_GROUP_QUOTA_ENV, "0.09")
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")

    try:
        reconcile_quotas(["group-a"])
    except QuotaError as exc:
        assert DEFAULT_GROUP_QUOTA_ENV in str(exc)
    else:
        raise AssertionError(
            "Expected default quota lower-than-minimum validation error"
        )


def test_get_state_requires_minimum_quota_env(monkeypatch) -> None:
    monkeypatch.delenv(MIN_GROUP_QUOTA_ENV, raising=False)

    try:
        from omeroweb_admin_tools.services.storage_quotas import get_state

        get_state()
    except QuotaError as exc:
        assert "Missing required environment variable" in str(exc)
    else:
        raise AssertionError(
            "Expected get_state to fail when minimum quota env is missing"
        )


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




def test_storage_quota_update_endpoint_accepts_empty_body(monkeypatch) -> None:
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data="",
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.upsert_quotas",
        lambda updates, source: {"quotas_gb": {}},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda groups: {"logs": []},
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 200



def test_storage_quota_update_endpoint_accepts_form_encoded_updates(monkeypatch) -> None:
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"updates": json.dumps([{"group": "demo", "quota_gb": 0.5}])},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.upsert_quotas",
        lambda updates, source: {"quotas_gb": {"demo": 0.5}},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda groups: {"logs": []},
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 200

def test_upsert_recovers_from_empty_state_file(tmp_path, monkeypatch) -> None:
    """When the state file exists but is empty, upsert should start fresh."""
    state_path = tmp_path / "quotas.json"
    state_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 10.0


def test_upsert_recovers_from_corrupted_state_file(tmp_path, monkeypatch) -> None:
    """When the state file contains invalid JSON, upsert should start fresh."""
    state_path = tmp_path / "quotas.json"
    state_path.write_text("{corrupt", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 5)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 5.0


def test_upsert_recovers_from_non_object_state_file(tmp_path, monkeypatch) -> None:
    """When the state file contains a JSON array instead of an object, start fresh."""
    state_path = tmp_path / "quotas.json"
    state_path.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 5)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 5.0


def test_storage_quota_update_returns_500_on_state_file_error(monkeypatch) -> None:
    """When upsert_quotas raises, the view should return 500 not 400."""
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data=json.dumps({"updates": [{"group": "demo", "quota_gb": 10}]}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.upsert_quotas",
        _raises(OSError("Permission denied: /OMERO/.admin-tools/group-quotas.json")),
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 500
    body = json.loads(response.content)
    assert "Quota update failed" in body["error"]


def _raises(exc):
    """Return a callable that raises the given exception."""
    def _fn(*_a, **_kw):
        raise exc
    return _fn


def test_storage_quota_update_endpoint_multipart_form(monkeypatch) -> None:
    """Multipart form-encoded request with updates field should be accepted."""
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"updates": json.dumps([{"group": "demo", "quota_gb": 0.5}])},
        content_type="multipart/form-data; boundary=BoUnDaRyStRiNg",
    )
    # Django RequestFactory with multipart sends data differently.
    # Use the standard form POST approach.
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"updates": json.dumps([{"group": "demo", "quota_gb": 0.5}])},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.upsert_quotas",
        lambda updates, source: {"quotas_gb": {"demo": 0.5}},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda groups: {"logs": []},
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["quotas_gb"]["demo"] == 0.5


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
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")

    upsert_quotas([("group-a", 5)])
    reconcile_quotas(["group-a"])
    reconcile_quotas(["group-a"])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    configured_messages = [
        entry["message"]
        for entry in payload["logs"]
        if entry["message"].startswith("Quota for group 'group-a' is configured")
    ]
    assert len(configured_messages) == 1


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
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")

    upsert_quotas([("group-a", 5)])

    # Make directory creation fail so the warning (pending) path is exercised.
    original_mkdir = Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if self.name == "group-a":
            raise OSError("Permission denied")
        return original_mkdir(self, *args, **kwargs)

    with patch.object(Path, "mkdir", failing_mkdir):
        reconcile_quotas([])
        reconcile_quotas([])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    warning_messages = [
        entry["message"]
        for entry in payload["logs"]
        if entry["message"].startswith("Quota pending for group 'group-a'")
    ]
    assert len(warning_messages) == 1

    upsert_quotas([("group-a", None)])
    reconcile_quotas([])

    updated_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated_payload["_reconcile_event_cache"] == {}


def test_reconcile_marks_group_as_applied_when_directory_exists(
    tmp_path, monkeypatch
) -> None:
    """Reconcile marks groups as applied when directory exists and conditions are met.

    The host-side systemd timer (omero-quota-enforcer) reads the state file
    and applies ext4 project quotas.  reconcile_quotas is responsible for
    writing the state file and reporting which groups are ready for enforcement.
    """
    state_path = tmp_path / "quotas.json"
    group_root = tmp_path / "ManagedRepository"
    (group_root / "group-a").mkdir(parents=True)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas.resolve_managed_group_root",
        lambda known_groups: (group_root, "test-override"),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.services.storage_quotas._is_safe_managed_repository_root",
        lambda path: (True, ""),
    )
    monkeypatch.setenv("CONFIG_omero_fs_repo_path", "%group%/%user%/%time%")

    upsert_quotas([("group-a", 5)])
    result = reconcile_quotas(["group-a"])

    assert "group-a" in result["applied_groups"]
    assert any(
        "Host-side enforcer will apply" in entry["message"] for entry in result["logs"]
    )
