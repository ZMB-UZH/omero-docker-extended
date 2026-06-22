from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from omeroweb_admin_tools.services.storage_quotas import (
    AUTO_GROUP_QUOTA_ENV,
    DEFAULT_GROUP_QUOTA_ENV,
    MIN_GROUP_QUOTA_ENV,
    _write_state,
    detect_filesystem,
    managed_group_root,
    managed_repository_compatibility,
    import_quotas_csv,
    get_state,
    QuotaError,
    quota_csv_template,
    reconcile_quotas,
    STATE_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION_KEY,
    upsert_quotas,
)
from omeroweb_admin_tools.views.index_view import (
    storage_data,
    storage_quota_data,
    storage_quota_import,
    storage_quota_template,
    storage_quota_update,
)

import pytest


@pytest.fixture(autouse=True)
def _set_required_quota_env(monkeypatch) -> None:
    """Set the required quota environment.

    Inputs: `monkeypatch` pytest monkeypatch fixture. Output: None.
    """
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(DEFAULT_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(AUTO_GROUP_QUOTA_ENV, "false")


def test_quota_csv_template_headers() -> None:
    """Check quota csv template headers renders the expected surface.

    Inputs: admin-tool fixtures. Output: fails on regressions in quota csv template headers.
    """
    assert quota_csv_template() == "Group,Quota [GB]\n"


def test_upsert_and_import_quotas_roundtrip(tmp_path, monkeypatch) -> None:
    """Verify upsert and import quotas roundtrip.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert and import quotas roundtrip.
    """
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])
    import_quotas_csv("Group,Quota [GB]\ngroup-b,22.5\n")

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 10.0
    assert payload["quotas_gb"]["group-b"] == 22.5
    assert payload["logs"]


def test_upsert_writes_schema_version(tmp_path, monkeypatch) -> None:
    """Verify upsert writes schema version.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert writes schema version.
    """
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload[STATE_SCHEMA_VERSION_KEY] == STATE_SCHEMA_VERSION


def test_write_state_temp_file_is_not_world_writable(tmp_path) -> None:
    """Verify write state temp file is not world writable.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in write state temp file is not world writable.
    """
    if os.name == "nt":
        pytest.skip("Windows chmod does not preserve POSIX 0600 semantics")

    state_path = tmp_path / "quotas.json"
    seen_modes = []

    real_replace = os.replace

    def _capturing_replace(src: Path, dst: Path) -> None:
        """Record the capturing replace call on the test double for later assertions.

        Inputs: `src` (Path), `dst` (Path). Output: None.
        """
        seen_modes.append(stat.S_IMODE(Path(src).stat().st_mode))
        real_replace(src, dst)

    with patch(
        "omeroweb_admin_tools.services.storage_quotas.os.replace",
        _capturing_replace,
    ):
        _write_state(state_path, {"quotas_gb": {}, "logs": []})

    assert seen_modes
    assert seen_modes[0] == 0o600


def test_quota_state_file_must_not_be_world_writable(tmp_path, monkeypatch) -> None:
    """Verify world-writable quota state is rejected before use.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions
    in quota state path mode validation.
    """
    if os.name == "nt":
        pytest.skip("Windows mode bits do not model POSIX world-write safety")

    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps(
            {
                STATE_SCHEMA_VERSION_KEY: STATE_SCHEMA_VERSION,
                "quotas_gb": {},
                "logs": [],
            }
        ),
        encoding="utf-8",
    )
    state_path.chmod(0o666)
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    with pytest.raises(QuotaError, match="world-writable"):
        get_state()


def test_reconcile_rejects_unknown_schema_version(tmp_path, monkeypatch) -> None:
    """Confirm reconcile rejects unknown schema version is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile rejects unknown schema version.
    """
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
    """Verify upsert falls back when atomic replace is not permitted.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None. Raises: PermissionError when validation or the called operation fails.
    """
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
        """Record the deny replace call on the test double for later assertions.

        Inputs: `_src` (Path), `_dst` (Path). Output: None. Raises: PermissionError when validation or the called operation fails.
        """
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
    """Confirm upsert raises clear error when replace and write are not permitted exposes the expected failure.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None. Raises: PermissionError when validation or the called operation fails.
    """
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
        """Record the deny replace call on the test double for later assertions.

        Inputs: `_src` (Path), `_dst` (Path). Output: None. Raises: PermissionError when validation or the called operation fails.
        """
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
    """Check upsert deletes quota for null or empty value cleanup behavior.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert deletes quota for null or empty value.
    """
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
    """Check upsert skips delete log when quota not set cleanup behavior.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert skips delete log when quota not set.
    """
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", None)])

    assert not state_path.exists()


def test_upsert_does_not_repeat_log_for_unchanged_quota(tmp_path, monkeypatch) -> None:
    """Verify upsert does not repeat log for unchanged quota.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert does not repeat log for unchanged quota.
    """
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
    """Confirm upsert rejects quota below minimum is rejected at the boundary.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None. Raises: AssertionError when validation or the called operation fails.
    """
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    try:
        upsert_quotas([("group-a", 0.09)])
    except QuotaError as exc:
        assert "at least 0.10 GB" in str(exc)
    else:
        raise AssertionError("Expected quota validation error for value below 0.10 GB")


def test_upsert_respects_minimum_quota_from_environment(tmp_path, monkeypatch) -> None:
    """Verify upsert respects minimum quota from environment.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert respects minimum quota from environment.
    """
    state_path = tmp_path / "quotas.json"
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    monkeypatch.setenv(MIN_GROUP_QUOTA_ENV, "0.10")

    upsert_quotas([("group-a", 0.10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 0.1


def test_upsert_rejects_invalid_environment_minimum_quota(
    tmp_path, monkeypatch
) -> None:
    """Confirm upsert rejects invalid environment minimum quota is rejected at the boundary.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None. Raises: AssertionError when validation or the called operation fails.
    """
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
    """Verify reconcile marks pending when group directory missing.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile marks pending when group directory missing.
    """
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
    """Verify detect filesystem returns metadata for existing path result shape.

    Inputs: admin-tool fixtures. Output: fails on regressions when detect filesystem returns metadata for existing path accepts unsafe input.
    """
    fs = detect_filesystem(Path(tempfile.gettempdir()))

    assert isinstance(fs.fs_type, str)
    assert isinstance(fs.mount_point, str)


def test_managed_group_root_uses_environment_configuration(monkeypatch) -> None:
    """Verify managed group root uses environment configuration.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in managed group root uses environment configuration.
    """
    monkeypatch.delenv("ADMIN_TOOLS_MANAGED_GROUP_ROOT", raising=False)
    monkeypatch.delenv("CONFIG_omero_managed_dir", raising=False)
    monkeypatch.setenv("OMERO_DATA_DIR", "/custom-omero")

    assert managed_group_root() == Path("/custom-omero/ManagedRepository")


def test_reconcile_does_not_attempt_mkdir_when_root_is_not_writable(
    tmp_path, monkeypatch
) -> None:
    """Verify reconcile does not attempt mkdir when root is not writable.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile does not attempt mkdir when root is not writable.
    """
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
    """Verify reconcile auto sets default quota for new group.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile auto sets default quota for new group.
    """
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
    """Confirm reconcile rejects default quota below minimum is rejected at the boundary.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None. Raises: AssertionError when validation or the called operation fails.
    """
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
    """Verify get state requires minimum quota env.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get state requires minimum quota env.
    AssertionError when validation or the called operation fails.
    """
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
    """Verify storage quota update endpoint.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update endpoint.
    """
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data=json.dumps({"updates": [{"group": "demo", "quota_gb": 15}]}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
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
    """Verify storage quota update endpoint accepts empty body.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update endpoint accepts empty body.
    """
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data="",
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
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


def test_storage_quota_update_endpoint_accepts_form_encoded_updates(
    monkeypatch,
) -> None:
    """Verify storage quota update endpoint accepts form encoded updates.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update endpoint accepts form encoded updates.
    """
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"updates": json.dumps([{"group": "demo", "quota_gb": 0.5}])},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
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


def test_storage_quota_update_endpoint_treats_missing_form_updates_as_noop(
    monkeypatch,
) -> None:
    """Verify storage quota update endpoint treats missing form updates as noop.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update endpoint treats missing form updates as noop.
    """
    captured = {}
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"other": "value"},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    def _upsert(updates, source):
        """Return the upsert.

        Inputs: `updates`, `source`. Output: `dict`.
        """
        captured["updates"] = updates
        captured["source"] = source
        return {"quotas_gb": {}}

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.upsert_quotas",
        _upsert,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda groups: {"logs": []},
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 200
    assert captured == {"updates": [], "source": "ui-edit"}


def test_upsert_recovers_from_empty_state_file(tmp_path, monkeypatch) -> None:
    """Verify upsert recovers from empty state file.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert recovers from empty state file.
    """
    state_path = tmp_path / "quotas.json"
    state_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 10)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 10.0


def test_upsert_recovers_from_corrupted_state_file(tmp_path, monkeypatch) -> None:
    """Verify upsert recovers from corrupted state file.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert recovers from corrupted state file.
    """
    state_path = tmp_path / "quotas.json"
    state_path.write_text("{corrupt", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 5)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 5.0


def test_upsert_recovers_from_non_object_state_file(tmp_path, monkeypatch) -> None:
    """Verify upsert recovers from non object state file.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in upsert recovers from non object state file.
    """
    state_path = tmp_path / "quotas.json"
    state_path.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))

    upsert_quotas([("group-a", 5)])

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["quotas_gb"]["group-a"] == 5.0


def test_storage_quota_update_returns_500_on_state_file_error(monkeypatch) -> None:
    """Confirm storage quota update returns 500 on state file error exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when storage quota update returns 500 on state file error stops reporting the expected error.
    """
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data=json.dumps({"updates": [{"group": "demo", "quota_gb": 10}]}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
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
    assert body["error"] == "Quota update failed."


def test_storage_quota_update_hides_payload_parse_details(monkeypatch) -> None:
    """Verify storage quota update hides payload parse details result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update hides payload parse details.
    """
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data=json.dumps({"updates": "not-a-list"}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    response = storage_quota_update(request, conn=None)

    assert response.status_code == 400
    body = json.loads(response.content)
    assert body["error"] == "Invalid quota update payload."


def _raises(exc):
    """Return a callable that raises the given exception.

    Inputs: `exc`. Output: `_fn`. Raises: exc when validation or external operations
    fail.
    """

    def _fn(*_a, **_kw):
        """Record the fn call on the test double for later assertions.

        Inputs: `*_a`, `**_kw`. Output: None. Raises: exc for the exercised failure path.
        """
        raise exc

    return _fn


def test_storage_quota_update_endpoint_multipart_form(monkeypatch) -> None:
    """Verify storage quota update endpoint multipart form.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update endpoint multipart form.
    """
    multipart_request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"updates": json.dumps([{"group": "demo", "quota_gb": 0.5}])},
        content_type="multipart/form-data; boundary=BoUnDaRyStRiNg",
    )
    assert multipart_request.content_type.startswith("multipart/form-data")
    # Django RequestFactory with multipart sends data differently.
    # Use the standard form POST approach.
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data={"updates": json.dumps([{"group": "demo", "quota_gb": 0.5}])},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
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
    """Check storage quota import and template endpoints renders the expected surface.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota import and template endpoints.
    """
    file_payload = b"Group,Quota [GB]\ndemo,12\n"
    upload = SimpleUploadedFile("quotas.csv", file_payload, content_type="text/csv")
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/import/",
        data={"file": upload},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
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


def test_storage_quota_update_invalid_payload_is_sanitized(monkeypatch) -> None:
    """Verify storage quota update invalid payload is sanitized result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota update invalid payload is sanitized.
    """
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/update/",
        data=json.dumps({"updates": {"group": "demo"}}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    response = storage_quota_update(request, conn=None)
    body = json.loads(response.content)

    assert response.status_code == 400
    assert body["error"] == "Invalid quota update payload."


def test_storage_quota_import_invalid_errors_are_sanitized(monkeypatch) -> None:
    """Verify storage quota import invalid errors are sanitized.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota import invalid errors are sanitized.
    """
    file_payload = b"Group,Quota [GB]\ndemo,broken\n"
    upload = SimpleUploadedFile("quotas.csv", file_payload, content_type="text/csv")
    request = RequestFactory().post(
        "/omeroweb_admin_tools/storage/quota/import/",
        data={"file": upload},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.import_quotas_csv",
        _raises(QuotaError("line 2 leaked details")),
    )

    response = storage_quota_import(request, conn=None)
    body = json.loads(response.content)

    assert response.status_code == 400
    assert body["error"] == "Invalid CSV import."


def test_storage_data_failure_is_sanitized(monkeypatch) -> None:
    """Verify storage data failure is sanitized.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage data failure is sanitized.
    """
    request = RequestFactory().get("/omeroweb_admin_tools/storage/data/")
    conn = SimpleNamespace(
        c=None,
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=lambda value: None),
        getQueryService=lambda: SimpleNamespace(
            projection=lambda query, params, opts: (_ for _ in ()).throw(
                RuntimeError("storage backend leaked details")
            )
        ),
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    response = storage_data(request, conn=conn)
    body = json.loads(response.content)

    assert response.status_code == 500
    assert body["error"] == "Storage query failed."


def test_storage_data_merges_known_users_groups_and_quota_fallback(
    monkeypatch,
) -> None:
    """Verify storage data merges known users groups and quota fallback.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage data merges known users groups and quota fallback.
    """

    class _Value:
        """Test double for value behavior in this module."""

        def __init__(self, value):
            """Create `_Value` with `value`.

            Inputs: `value`. Output: None.
            """
            self.val = value

        def getValue(self):
            """Return `_Value`'s fake OMERO value.

            Inputs: none. Output: `self.val`.
            """
            return self.val

    rows = [
        [None, _Value("alice"), None, _Value("users_private"), _Value(10)],
        [None, _Value("alice"), None, _Value("users_collaboration"), _Value(5)],
    ]
    group_calls = []
    conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=group_calls.append),
        getQueryService=lambda: SimpleNamespace(
            projection=lambda query, params, opts: rows
        ),
    )

    monkeypatch.setenv("OMERO_DATA_DIR", "/srv/omero")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._list_all_users_and_groups",
        lambda conn: (
            {"alice": "Alice Admin", "bob": "Bob Builder"},
            {"users_private", "users_collaboration", "users_read"},
            {
                "users_private": "Private",
                "users_collaboration": "Read-annotate",
            },
            {
                "alice": {"users_private", "users_collaboration"},
                "bob": {"users_read"},
            },
            {
                "users_private": {"alice"},
                "users_collaboration": {"alice"},
                "users_read": {"bob"},
            },
        ),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.shutil.disk_usage",
        lambda path: (100, 60, 40),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda known_groups: (_ for _ in ()).throw(
            RuntimeError("quota backend offline")
        ),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.is_quota_enforcement_available",
        lambda: True,
    )

    response = storage_data(
        RequestFactory().get("/omeroweb_admin_tools/storage/data/"),
        conn=conn,
    )
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert group_calls == [-1]
    assert payload["totals"] == {
        "omero_binary_bytes": 15,
        "data_root": "/srv/omero",
        "data_root_total_bytes": 100,
        "data_root_used_bytes": 60,
        "data_root_free_bytes": 40,
    }
    assert payload["by_user"] == [
        {
            "username": "alice",
            "full_name": "Alice Admin",
            "groups": ["users_collaboration", "users_private"],
            "bytes": 15,
        },
        {
            "username": "bob",
            "full_name": "Bob Builder",
            "groups": ["users_read"],
            "bytes": 0,
        },
    ]
    assert payload["by_group"] == [
        {
            "group": "users_private",
            "users": ["alice"],
            "permissions": "Private",
            "bytes": 10,
        },
        {
            "group": "users_collaboration",
            "users": ["alice"],
            "permissions": "Read-annotate",
            "bytes": 5,
        },
        {
            "group": "users_read",
            "users": ["bob"],
            "permissions": "Private",
            "bytes": 0,
        },
    ]
    assert payload["by_user_group"] == [
        {"username": "alice", "group": "users_private", "bytes": 10},
        {"username": "alice", "group": "users_collaboration", "bytes": 5},
    ]
    assert payload["quotas"] == {
        "quotas_gb": {},
        "logs": [],
        "quota_enforcement_available": True,
    }


def test_storage_quota_data_returns_current_state_and_reconcile_summary(
    monkeypatch,
) -> None:
    """Verify storage quota data returns current state and reconcile summary result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in storage quota data returns current state and reconcile summary.
    """
    request = RequestFactory().get("/omeroweb_admin_tools/storage/quota/data/")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.get_quota_state",
        lambda: {
            "quotas_gb": {"users_private": 12.5},
            "logs": [{"level": "info", "message": "ok"}],
        },
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._list_omero_group_names",
        lambda conn: ["users_private"],
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda known_groups: {
            "quotas_gb": {"users_private": 12.5},
            "logs": [{"level": "info", "message": "reconciled"}],
            "quota_enforcement_available": False,
        },
    )

    response = storage_quota_data(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload == {
        "quotas_gb": {"users_private": 12.5},
        "logs": [{"level": "info", "message": "ok"}],
        "reconcile": {
            "quotas_gb": {"users_private": 12.5},
            "logs": [{"level": "info", "message": "reconciled"}],
            "quota_enforcement_available": False,
        },
    }


def test_storage_quota_data_uses_safe_fallbacks_when_state_or_reconcile_fail(
    monkeypatch,
) -> None:
    """Confirm storage quota data uses safe fallbacks when state or reconcile fail exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when storage quota data uses safe fallbacks when state or reconcile fail stops reporting the expected error.
    """
    request = RequestFactory().get("/omeroweb_admin_tools/storage/quota/data/")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.get_quota_state",
        lambda: (_ for _ in ()).throw(RuntimeError("state file unreadable")),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._list_omero_group_names",
        lambda conn: ["users_private"],
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.reconcile_quotas",
        lambda known_groups: (_ for _ in ()).throw(RuntimeError("reconcile failed")),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.is_quota_enforcement_available",
        lambda: True,
    )

    response = storage_quota_data(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload == {
        "quotas_gb": {},
        "logs": [],
        "reconcile": {
            "quotas_gb": {},
            "logs": [],
            "quota_enforcement_available": True,
        },
    }


def test_managed_repository_compatibility_requires_group_user_prefix(
    monkeypatch,
) -> None:
    """Verify managed repository compatibility requires group user prefix.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in managed repository compatibility requires group user prefix.
    """
    monkeypatch.setenv(
        "CONFIG_omero_fs_repo_path",
        "%user%/%group%/%year%-%month%-%day%/%time%",
    )

    compatibility = managed_repository_compatibility()

    assert compatibility["is_compatible"] is False


def test_reconcile_marks_all_pending_when_template_incompatible(
    tmp_path, monkeypatch
) -> None:
    """Check reconcile marks all pending when template incompatible renders the expected surface.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile marks all pending when template incompatible.
    """
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
    """Verify reconcile deduplicates non warning logs.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile deduplicates non warning logs.
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
    """Check reconcile repeats warnings and cleans event cache after quota delete cleanup behavior.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None. Raises: OSError when validation or the called operation fails.
    """
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
        """Return the failing mkdir.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `original_mkdir` result. Raises: OSError when validation or external operations
        fail.
        """
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
    """Verify reconcile marks group as applied when directory exists.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in reconcile marks group as applied when directory exists.

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
