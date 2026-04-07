from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

from omeroweb_import.views import core_functions


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


def _raise(exc):
    raise exc


def test_identity_owner_and_permission_helpers_cover_edge_failures(monkeypatch) -> None:
    assert (
        core_functions._get_id(
            SimpleNamespace(
                getId=lambda: _raise(RuntimeError("missing id")),
            )
        )
        is None
    )
    assert core_functions._get_owner_id(None) is None

    fallback_owner = SimpleNamespace(getId=lambda: _Value(9))
    fallback_owner_obj = SimpleNamespace(
        getDetails=lambda: _raise(RuntimeError("details exploded")),
        getOwner=lambda: fallback_owner,
    )
    assert core_functions._get_owner_id(fallback_owner_obj) == 9

    failing_owner_obj = SimpleNamespace(
        getDetails=lambda: _raise(RuntimeError("details exploded")),
        getOwner=lambda: _raise(RuntimeError("owner exploded")),
    )
    assert core_functions._get_owner_id(failing_owner_obj) is None

    assert (
        core_functions._current_user_id(
            SimpleNamespace(getUser=lambda: _raise(RuntimeError("user exploded")))
        )
        is None
    )
    assert (
        core_functions._current_user_id(SimpleNamespace(getUser=lambda: None)) is None
    )

    assert core_functions._is_owned_by_user(None, 5) is False
    assert (
        core_functions._is_owned_by_user(
            SimpleNamespace(
                getDetails=lambda: SimpleNamespace(
                    getOwner=lambda: SimpleNamespace(getId=lambda: "owner-5")
                )
            ),
            5,
        )
        is False
    )

    assert core_functions._get_owner_username(None) == ""
    assert (
        core_functions._get_owner_username(
            SimpleNamespace(
                getDetails=lambda: _raise(RuntimeError("details exploded")),
                getOwner=lambda: _raise(RuntimeError("owner exploded")),
            )
        )
        == ""
    )

    class _FallbackOwner:
        def getOmeName(self):
            raise RuntimeError("ome name exploded")

        def getName(self):
            return SimpleNamespace(val="")

        def getFirstName(self):
            return SimpleNamespace(val="")

    monkeypatch.setattr(core_functions, "_get_id", lambda owner: 42)
    assert (
        core_functions._get_owner_username(
            SimpleNamespace(
                getDetails=lambda: SimpleNamespace(getOwner=lambda: _FallbackOwner())
            )
        )
        == "42"
    )

    assert core_functions._has_read_write_permissions(None) is False
    assert (
        core_functions._has_read_write_permissions(
            SimpleNamespace(
                canEdit=lambda: _raise(RuntimeError("edit exploded")),
                canWrite=lambda: True,
            )
        )
        is True
    )
    assert (
        core_functions._has_read_write_permissions(
            SimpleNamespace(
                canEdit=lambda: _raise(RuntimeError("edit exploded")),
                canWrite=lambda: False,
                getDetails=lambda: _raise(RuntimeError("details exploded")),
            )
        )
        is False
    )


def test_project_listing_and_payload_helpers_cover_restore_and_failure_paths(
    monkeypatch,
) -> None:
    assert list(core_functions._iter_accessible_projects(None)) == []

    class _ServiceOpts:
        def __init__(self, *, group="5", fail_get=False, fail_restore=False):
            self.group = group
            self.fail_get = fail_get
            self.fail_restore = fail_restore
            self.set_calls = []

        def getOmeroGroup(self):
            if self.fail_get:
                raise RuntimeError("group read exploded")
            return self.group

        def setOmeroGroup(self, value):
            self.set_calls.append(value)
            self.group = value
            if self.fail_restore and value == "5":
                raise RuntimeError("restore exploded")

    restore_opts = _ServiceOpts(fail_restore=True)

    def _restore_get_objects(model, opts=None):
        assert model == "Project"
        if restore_opts.group == "-1":
            raise RuntimeError("cross-group exploded")
        if opts == {"group": "-1"}:
            raise RuntimeError("opts exploded")
        return iter(["project-a"])

    restore_conn = SimpleNamespace(
        SERVICE_OPTS=restore_opts,
        getObjects=_restore_get_objects,
        listProjects=lambda: ["project-list"],
    )
    assert list(core_functions._iter_accessible_projects(restore_conn)) == ["project-a"]
    assert restore_opts.set_calls == ["-1", "5"]

    failing_opts = _ServiceOpts(fail_get=True)
    failing_conn = SimpleNamespace(
        SERVICE_OPTS=failing_opts,
        getObjects=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("query exploded")
        ),
        listProjects=lambda: (_ for _ in ()).throw(RuntimeError("list exploded")),
    )
    assert list(core_functions._iter_accessible_projects(failing_conn)) == []

    monkeypatch.setattr(
        core_functions,
        "_iter_accessible_projects",
        lambda conn: (_ for _ in ()).throw(RuntimeError("payload exploded")),
    )
    assert core_functions._collect_project_payload(object(), user_id=7) == {
        "owned": [],
        "collab": [],
    }


def test_dataset_and_native_zarr_helpers_cover_unhappy_paths(
    monkeypatch, tmp_path
) -> None:
    class _LengthWithRawFallback:
        val = "2.5"

        def getValue(self):
            raise RuntimeError("value exploded")

        def getUnit(self):
            raise RuntimeError("unit exploded")

    class _BadLength:
        val = "not-a-number"

        def getValue(self):
            raise RuntimeError("value exploded")

    assert core_functions._native_zarr_length_signature(_LengthWithRawFallback()) == (
        2.5,
        "",
    )
    assert core_functions._native_zarr_length_signature(_BadLength()) is None

    inspection = SimpleNamespace(
        recognized=False,
        support_error=None,
        physical_sizes={},
    )
    monkeypatch.setattr(
        core_functions,
        "inspect_ome_zarr_image",
        lambda target_path: inspection,
    )
    zarr_store_path = tmp_path / "store"
    normalized_sizes, error = core_functions._runtime_native_zarr_physical_sizes(
        zarr_store_path,
        None,
    )
    assert normalized_sizes == {}
    assert "did not recognize" in (error or "")

    inspection.recognized = True
    inspection.support_error = "unsupported layout"
    normalized_sizes, error = core_functions._runtime_native_zarr_physical_sizes(
        zarr_store_path,
        "0",
    )
    assert normalized_sizes == {}
    assert error == "unsupported layout"

    inspection.support_error = None
    inspection.physical_sizes = {"x": ("2.5", "nm")}
    monkeypatch.setattr(
        core_functions,
        "_native_zarr_length_from_value_unit",
        lambda raw_value: _raise(RuntimeError("normalization exploded")),
    )
    normalized_sizes, error = core_functions._runtime_native_zarr_physical_sizes(
        zarr_store_path,
        "0",
    )
    assert normalized_sizes == {}
    assert "axis x" in (error or "")
    assert "normalization exploded" in (error or "")

    assert core_functions._directory_package_root_for_relative_path("") is None
    assert (
        core_functions._logical_unit_is_directory_package_root(
            {
                "relative_path": "bundle/data.bin",
                "dataset_relative_path": "other/data.bin",
                "covered_relative_paths": ["bundle/data.bin", "bundle/meta.json"],
            }
        )
        is False
    )
    assert (
        core_functions._logical_unit_is_directory_package_root(
            {
                "relative_path": "bundle.zarr",
                "dataset_relative_path": "bundle.zarr",
                "covered_relative_paths": ["bundle.zarr"],
            }
        )
        is False
    )

    assert core_functions._find_project_dataset(object(), 0, "Target") is None
    assert core_functions._find_project_dataset(object(), 3, "") is None
    assert (
        core_functions._find_project_dataset(
            SimpleNamespace(
                getObject=lambda model, project_id: _raise(
                    RuntimeError("project exploded")
                )
            ),
            3,
            "Target",
        )
        is None
    )
    assert (
        core_functions._find_project_dataset(
            SimpleNamespace(
                getObject=lambda model, project_id: SimpleNamespace(
                    listChildren=lambda: _raise(RuntimeError("children exploded"))
                )
            ),
            3,
            "Target",
        )
        is None
    )


def test_background_import_session_covers_missing_error_and_cleanup_paths(
    monkeypatch,
) -> None:
    monkeypatch.setattr(core_functions, "_open_admin_connection", lambda *args: None)
    with core_functions._background_import_session("alice", "omeroserver", 4064) as key:
        assert key is None

    monkeypatch.setattr(
        core_functions.omero.sys,
        "Principal",
        lambda username, group_name, role: (username, group_name, role),
    )
    monkeypatch.setattr(
        core_functions,
        "_get_background_import_session_timeout_seconds",
        lambda timeout_hint_seconds: 12,
    )

    created = []
    closed = []

    class _SessionService:
        def createSessionWithTimeouts(
            self, principal, user_timeout_ms, group_timeout_ms
        ):
            created.append((principal, user_timeout_ms, group_timeout_ms))
            return SimpleNamespace(getUuid=lambda: _Value("background-session"))

        def closeSession(self, session):
            closed.append(session)
            raise RuntimeError("close exploded")

    service = _SessionService()
    admin_conn = SimpleNamespace(
        c=SimpleNamespace(sf=SimpleNamespace(getSessionService=lambda: service)),
        close=lambda: _raise(RuntimeError("admin close exploded")),
    )
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: admin_conn,
    )

    with core_functions._background_import_session(
        "alice",
        "omeroserver",
        4064,
        group_name="users_private",
        timeout_hint_seconds=20,
    ) as key:
        assert key == "background-session"

    assert created == [(("alice", "users_private", "User"), 12000, 12000)]
    assert len(closed) == 1

    failing_service = SimpleNamespace(
        createSessionWithTimeouts=lambda *args: _raise(RuntimeError("session exploded"))
    )
    failing_admin = SimpleNamespace(
        c=SimpleNamespace(
            sf=SimpleNamespace(getSessionService=lambda: failing_service)
        ),
        close=lambda: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: failing_admin,
    )
    with core_functions._background_import_session(
        "alice", "omeroserver", 4064, group_name="users_private"
    ) as key:
        assert key is None


def test_shared_transfer_helpers_cover_symlink_and_cleanup_error_paths(
    monkeypatch, tmp_path: Path
) -> None:
    core_functions._normalize_shared_zarr_permissions(tmp_path / "missing")

    tree_root = tmp_path / "tree"
    real_dir = tree_root / "real"
    real_dir.mkdir(parents=True)
    real_file = tree_root / "payload.txt"
    real_file.write_text("payload", encoding="utf-8")
    link_dir = tree_root / "link-dir"
    link_file = tree_root / "link-file"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    link_file.symlink_to(real_file)

    core_functions._normalize_shared_zarr_permissions(tree_root)

    assert stat.S_IMODE(tree_root.stat().st_mode) == (
        core_functions.ZARR_SHARED_TRANSFER_DIR_MODE
    )
    assert stat.S_IMODE(real_dir.stat().st_mode) == (
        core_functions.ZARR_SHARED_TRANSFER_DIR_MODE
    )
    assert stat.S_IMODE(real_file.stat().st_mode) == (
        core_functions.ZARR_SHARED_TRANSFER_FILE_MODE
    )
    assert link_dir.is_symlink()
    assert link_file.is_symlink()

    transfer_root = tmp_path / "shared-transfer"
    transfer_root.mkdir()
    monkeypatch.setattr(
        core_functions,
        "get_plugin_tmp_dir",
        lambda name: transfer_root,
    )

    missing_source, missing_parent, missing_error = (
        core_functions._prepare_server_readable_zarr_source(
            tmp_path / "absent.ome.zarr"
        )
    )
    assert missing_source is None
    assert missing_parent is None
    assert "Failed to resolve staged Zarr source" in (missing_error or "")

    file_source = tmp_path / "source.txt"
    file_source.write_text("payload", encoding="utf-8")
    staged_source, staged_parent, staged_error = (
        core_functions._prepare_server_readable_zarr_source(file_source)
    )
    assert staged_source is None
    assert staged_parent is None
    assert "not a directory" in (staged_error or "")

    valid_source = tmp_path / "store.ome.zarr"
    (valid_source / "0").mkdir(parents=True)
    (valid_source / "0" / ".zarray").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        core_functions,
        "_prepare_native_zarr_copy",
        lambda path: "native normalization exploded",
    )
    monkeypatch.setattr(
        core_functions.shutil,
        "rmtree",
        lambda path: _raise(RuntimeError("cleanup exploded")),
    )
    _, _, failed_error = core_functions._prepare_server_readable_zarr_source(
        valid_source
    )
    assert "Failed to prepare server-readable Zarr staging copy" in (failed_error or "")

    core_functions._cleanup_shared_zarr_transfer(None)
    cleanup_target = transfer_root / "token"
    cleanup_target.mkdir()
    core_functions._cleanup_shared_zarr_transfer(cleanup_target)
    assert cleanup_target.exists()


def test_script_service_helpers_cover_deduping_and_selection() -> None:
    assert list(core_functions._iter_script_services(None)) == []
    assert core_functions._find_script_id_by_name(None, "demo.py") is None
    assert core_functions._find_script_id_by_name(object(), "") is None

    shared_service = object()
    duplicate_conn = SimpleNamespace(
        getScriptService=lambda: shared_service,
        c=SimpleNamespace(sf=SimpleNamespace(getScriptService=lambda: shared_service)),
    )
    assert list(core_functions._iter_script_services(duplicate_conn)) == [
        shared_service
    ]

    preferred_scripts = [
        SimpleNamespace(id=SimpleNamespace(val="bad-id")),
        SimpleNamespace(
            name=SimpleNamespace(val="other.py"),
            path=SimpleNamespace(val="other/other.py"),
            id=SimpleNamespace(val="10"),
        ),
        SimpleNamespace(
            name=SimpleNamespace(val=core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME),
            path=SimpleNamespace(val="other/path/script.py"),
            id=SimpleNamespace(val=None),
        ),
        SimpleNamespace(
            name=SimpleNamespace(val=core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME),
            path=SimpleNamespace(val="other/path/script.py"),
            id=SimpleNamespace(val="9"),
        ),
        SimpleNamespace(
            name=SimpleNamespace(val=core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME),
            path=SimpleNamespace(
                val="omero/import_scripts/Manage_Zarr_ManagedRepository.py"
            ),
            id=SimpleNamespace(val="5"),
        ),
        SimpleNamespace(
            name=SimpleNamespace(val=core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME),
            path=SimpleNamespace(
                val="omero/import_scripts/Manage_Zarr_ManagedRepository.py"
            ),
            id=SimpleNamespace(val="6"),
        ),
    ]

    class _WorkingService:
        def getScripts(self):
            return preferred_scripts

    conn = SimpleNamespace(
        getScriptService=lambda: _raise(RuntimeError("primary getter exploded")),
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getScriptService=lambda: _WorkingService(),
            )
        ),
    )
    assert len(list(core_functions._iter_script_services(conn))) == 1
    assert (
        core_functions._find_script_id_by_name(
            conn,
            core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME,
            preferred_path_fragment="omero/import_scripts",
        )
        == 6
    )

    failing_conn = SimpleNamespace(
        getScriptService=lambda: SimpleNamespace(
            getScripts=lambda: _raise(RuntimeError("script listing exploded"))
        ),
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getScriptService=lambda: SimpleNamespace(getScripts=lambda: [])
            )
        ),
    )
    assert (
        core_functions._find_script_id_by_name(
            failing_conn, core_functions.ZARR_MANAGED_REPO_SCRIPT_NAME
        )
        is None
    )


def test_script_output_and_managed_repo_launch_helpers_cover_retry_and_failure_paths(
    monkeypatch, tmp_path
) -> None:
    assert core_functions._extract_script_outputs(
        "\n".join(
            [
                "* Message = staged successfully",
                "Managed_Path=/managed/demo.zarr",
                "ignored line",
            ]
        )
    ) == {
        "Message": "staged successfully",
        "Managed_Path": "/managed/demo.zarr",
    }

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(
        core_functions, "_find_script_id_by_name", lambda *args, **kwargs: 17
    )
    monkeypatch.setattr(core_functions, "_get_root_password", lambda: "root-secret")
    monkeypatch.setattr(core_functions, "_build_cli_env", lambda: {"BASE": "1"})
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 45)
    monkeypatch.setattr(core_functions, "_get_script_start_timeout_seconds", lambda: 10)
    monkeypatch.setattr(core_functions, "_get_script_start_retry_seconds", lambda: 0)

    now_values = iter([100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(core_functions.time, "time", lambda: next(now_values))
    sleeps = []
    monkeypatch.setattr(
        core_functions.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    attempted_cmds = []
    attempted_envs = []
    results = iter(
        [
            SimpleNamespace(
                returncode=1,
                stdout="Message = waiting",
                stderr="NoProcessorAvailable",
            ),
            SimpleNamespace(
                returncode=0,
                stdout="Message = staged successfully\nManaged_Path = /managed/demo.zarr",
                stderr="",
            ),
        ]
    )

    def _run(cmd, **kwargs):
        attempted_cmds.append(cmd)
        attempted_envs.append(kwargs["env"])
        return next(results)

    monkeypatch.setattr(core_functions.subprocess, "run", _run)

    source_path = tmp_path / "source.ome.zarr"
    ok, outputs, message = core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
        source_path=source_path,
        managed_path=Path("/OMERO/Managed/demo.ome.zarr"),
    )

    assert ok is True
    assert outputs == {
        "Message": "staged successfully",
        "Managed_Path": "/managed/demo.zarr",
    }
    assert message == "staged successfully"
    assert any(arg == f"Source_Path={source_path}" for arg in attempted_cmds[0])
    assert any(
        arg == "Managed_Path=/OMERO/Managed/demo.ome.zarr" for arg in attempted_cmds[0]
    )
    assert attempted_envs[0]["OMERO_PASSWORD"] == "root-secret"
    assert sleeps == [0]

    monkeypatch.setattr(
        core_functions.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=3, stdout="", stderr=""),
    )
    monkeypatch.setattr(core_functions.time, "time", lambda: 200.0)

    ok, outputs, message = core_functions._run_zarr_managed_repo_script(
        "cleanup",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
    )

    assert ok is False
    assert outputs == {}
    assert message == "Managed-repository Zarr helper failed with exit code 3."


def test_background_user_connection_yields_none_when_details_missing(
    monkeypatch,
) -> None:
    """_background_user_connection yields None when host/port/username is missing."""
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    with core_functions._background_user_connection("", host="h", port=4064) as conn:
        assert conn is None

    with core_functions._background_user_connection("u", host="", port=4064) as conn:
        assert conn is None

    with core_functions._background_user_connection("u", host="h", port=None) as conn:
        assert conn is None


def test_background_user_connection_with_session_key(monkeypatch) -> None:
    """_background_user_connection uses existing session key and closes connection."""
    closed = {"count": 0}

    class FakeConn:
        def close(self):
            closed["count"] += 1

    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: FakeConn(),
    )

    with core_functions._background_user_connection(
        "alice", session_key="abc123", host="omeroserver", port=4064
    ) as conn:
        assert conn is not None

    assert closed["count"] == 1


def test_background_user_connection_with_session_key_open_fails(monkeypatch) -> None:
    """_background_user_connection yields None when session open raises."""
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("conn refused")),
    )

    with core_functions._background_user_connection(
        "alice", session_key="abc123", host="omeroserver", port=4064
    ) as conn:
        assert conn is None


def test_background_user_connection_with_session_key_close_fails(
    monkeypatch,
) -> None:
    """_background_user_connection logs warning when connection close raises."""

    class FakeConn:
        def close(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: FakeConn(),
    )

    with core_functions._background_user_connection(
        "alice", session_key="abc123", host="omeroserver", port=4064
    ) as conn:
        assert conn is not None
    # No exception raised — warning was logged internally


def test_background_user_connection_without_session_key(monkeypatch) -> None:
    """_background_user_connection creates a background session when no key given."""
    from contextlib import contextmanager

    closed = {"count": 0}

    class FakeConn:
        def close(self):
            closed["count"] += 1

    @contextmanager
    def fake_background_session(*args, **kwargs):
        yield "generated-session-key"

    monkeypatch.setattr(
        core_functions, "_background_import_session", fake_background_session
    )
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: FakeConn(),
    )

    with core_functions._background_user_connection(
        "alice", host="omeroserver", port=4064
    ) as conn:
        assert conn is not None

    assert closed["count"] == 1


def test_background_user_connection_without_session_key_close_fails(
    monkeypatch,
) -> None:
    """_background_user_connection logs warning when background session close fails."""
    from contextlib import contextmanager

    class FakeConn:
        def close(self):
            raise RuntimeError("close failed")

    @contextmanager
    def fake_background_session(*args, **kwargs):
        yield "generated-session-key"

    monkeypatch.setattr(
        core_functions, "_background_import_session", fake_background_session
    )
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: FakeConn(),
    )

    with core_functions._background_user_connection(
        "alice", host="omeroserver", port=4064
    ) as conn:
        assert conn is not None
    # No exception raised — warning was logged internally


def test_background_user_connection_background_session_yields_empty_key(
    monkeypatch,
) -> None:
    """_background_user_connection yields None when background session produces empty key."""
    from contextlib import contextmanager

    @contextmanager
    def fake_background_session(*args, **kwargs):
        yield ""

    monkeypatch.setattr(
        core_functions, "_background_import_session", fake_background_session
    )
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("should not be called for empty key")
        ),
    )

    with core_functions._background_user_connection(
        "alice", host="omeroserver", port=4064
    ) as conn:
        assert conn is None
