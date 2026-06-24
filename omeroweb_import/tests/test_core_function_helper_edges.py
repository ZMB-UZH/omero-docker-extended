from __future__ import annotations

from iter_test_helpers import next_or_fail

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


def _raise(exc):
    """Record the raise call on the test double for later assertions.

    Inputs: `exc`. Output: None. Raises: exc when validation or external operations
    fail.
    """
    raise exc


def test_identity_owner_and_permission_helpers_cover_edge_failures(monkeypatch) -> None:
    """Verify the identity owner and permission helpers cover edge failures safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when identity owner and permission helpers cover edge failures accepts unsafe input.
    when validation or the called operation fails.
    """
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
        """Test double for fallback owner behavior in this module."""

        @staticmethod
        def getOmeName():
            """Return the fake OMERO name.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("ome name exploded")

        @staticmethod
        def getName():
            """Return `_FallbackOwner`'s fake object name.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val="")

        @staticmethod
        def getFirstName():
            """Return the fake first name.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val="")

    monkeypatch.setattr(core_functions, "_get_id", lambda owner: 42)

    def _fallback_details():
        """Return the fallback details.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(getOwner=_FallbackOwner)

    assert (
        core_functions._get_owner_username(
            SimpleNamespace(getDetails=_fallback_details)
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
    """Verify project listing and payload helpers cover restore and failure paths result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in project listing and payload helpers cover restore and failure paths.
    when validation or the called operation fails.
    """
    assert list(core_functions._iter_accessible_projects(None)) == []

    class _ServiceOpts:
        """Test double for service opts behavior in this module."""

        def __init__(self, *, group="5", fail_get=False, fail_restore=False):
            """Create `_ServiceOpts` with its default state.

            Inputs: `group`, `fail_get`, `fail_restore`. Output: None.
            """
            self.group = group
            self.fail_get = fail_get
            self.fail_restore = fail_restore
            self.set_calls = []

        def getOmeroGroup(self):
            """Return the fake omero group value used by this test double.

            Inputs: none. Output: `group`. Raises: RuntimeError when validation or
            external operations fail.
            """
            if self.fail_get:
                raise RuntimeError("group read exploded")
            return self.group

        def setOmeroGroup(self, value):
            """Set the OMERO Group for `_ServiceOpts`.

            Inputs: `value` input value. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            self.set_calls.append(value)
            self.group = value
            if self.fail_restore and value == "5":
                raise RuntimeError("restore exploded")

    restore_opts = _ServiceOpts(fail_restore=True)

    def _restore_get_objects(model, opts=None):
        """Return the restore get objects.

        Inputs: `model`, `opts`. Output: `iter` result. Raises: RuntimeError when validation or the called operation fails.
        """
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


def test_find_image_by_name_covers_global_not_found_and_errors(monkeypatch) -> None:
    """Verify image lookup fallback returns None for miss and query failures.

    Inputs: pytest monkeypatch fixture. Output: asserts image lookup failure paths.
    """
    monkeypatch.setattr(
        core_functions.omero.sys,
        "ParametersI",
        lambda: SimpleNamespace(values={}),
    )

    empty_query = SimpleNamespace(findAllByQuery=lambda *_args: [])
    empty_conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: empty_query,
    )
    assert core_functions._find_image_by_name(empty_conn, "missing.ome.tif") is None

    failing_query = SimpleNamespace(
        findAllByQuery=lambda *_args: _raise(RuntimeError("query failed"))
    )
    failing_conn = SimpleNamespace(
        SERVICE_OPTS=object(),
        getQueryService=lambda: failing_query,
    )
    assert core_functions._find_image_by_name(failing_conn, "missing.ome.tif") is None

    broken_conn = SimpleNamespace(
        getQueryService=lambda: _raise(RuntimeError("service failed"))
    )
    assert core_functions._find_image_by_name(broken_conn, "missing.ome.tif") is None


def test_dataset_and_native_zarr_helpers_cover_unhappy_paths(
    monkeypatch, tmp_path
) -> None:
    """Verify dataset and native Zarr helpers cover unhappy paths.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` temporary path fixture.
    Output: None. Raises: RuntimeError when validation or the called operation fails.
    """

    class _LengthWithRawFallback:
        """Test double for length with raw fallback behavior in this module."""

        val = "2.5"

        @staticmethod
        def getValue():
            """Return `_LengthWithRawFallback`'s fake OMERO value.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("value exploded")

        @staticmethod
        def getUnit():
            """Return the unit for `_LengthWithRawFallback`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("unit exploded")

    class _BadLength:
        """Test double for bad length behavior in this module."""

        val = "not-a-number"

        @staticmethod
        def getValue():
            """Return `_BadLength`'s fake OMERO value.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
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
    """Confirm background import session covers missing error and cleanup paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when background import session covers missing error and cleanup paths stops reporting the expected error.
    when validation or the called operation fails.
    """
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
        """Test double for session service behavior in this module."""

        @staticmethod
        def createSessionWithTimeouts(principal, user_timeout_ms, group_timeout_ms):
            """Create the session With Timeouts for `_SessionService`.

            Inputs: `principal`, `user_timeout_ms`, `group_timeout_ms`. Output:
            `SimpleNamespace` result.
            """
            created.append((principal, user_timeout_ms, group_timeout_ms))
            return SimpleNamespace(getUuid=lambda: _Value("background-session"))

        @staticmethod
        def closeSession(session):
            """Close the session for `_SessionService`.

            Inputs: `session`. Output: None. Raises: RuntimeError when validation or
            external operations fail.
            """
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


def test_open_admin_connection_covers_connect_error_cleanup(monkeypatch) -> None:
    """Verify failed admin connections clean up without leaking exceptions.

    Inputs: pytest monkeypatch fixture. Output: asserts failed connections return None.
    """
    monkeypatch.setenv("ROOTPASS", "root-password")
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: core_functions.JobServiceCredentials("root", "password", "", False),
    )

    class _ConnectFalse:
        """Gateway double for a failed connect path."""

        SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda _group: None)

        @staticmethod
        def connect():
            """Return failed connection status.

            Inputs: none. Output: False.
            """
            return False

        @staticmethod
        def getLastError():
            """Raise while reading the last error.

            Inputs: none. Output: raises RuntimeError.
            """
            raise RuntimeError("last error unavailable")

        @staticmethod
        def close():
            """Raise during cleanup.

            Inputs: none. Output: raises RuntimeError.
            """
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        core_functions, "BlitzGateway", lambda *args, **kwargs: _ConnectFalse()
    )
    assert core_functions._open_admin_connection("omeroserver", 4064) is None

    class _ConnectRaises:
        """Gateway double for an exception during connect."""

        SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda _group: None)

        @staticmethod
        def connect():
            """Raise while connecting.

            Inputs: none. Output: raises RuntimeError.
            """
            raise RuntimeError("connect failed")

        @staticmethod
        def close():
            """Raise during cleanup.

            Inputs: none. Output: raises RuntimeError.
            """
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        core_functions, "BlitzGateway", lambda *args, **kwargs: _ConnectRaises()
    )
    assert core_functions._open_admin_connection("omeroserver", 4064) is None


def test_open_service_connection_closes_on_outer_exception(monkeypatch) -> None:
    """Verify unexpected group-context errors close the job-service connection.

    Inputs: pytest monkeypatch fixture. Output: asserts outer exception cleanup.
    """
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: core_functions.JobServiceCredentials(
            "job-service",
            "secret",
            "",
            False,
        ),
    )

    class _Gateway:
        """Gateway double that connects, then raises during cleanup."""

        SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda _group: None)

        @staticmethod
        def connect():
            """Return a successful connection.

            Inputs: none. Output: True.
            """
            return True

        @staticmethod
        def close():
            """Raise during exception cleanup.

            Inputs: none. Output: raises RuntimeError.
            """
            raise RuntimeError("close failed")

    class _BadGroupId:
        """Value whose integer conversion violates Python's int protocol."""

        @staticmethod
        def __int__():
            """Return a non-int while converting the group id.

            Inputs: none. Output: string, so `int()` raises TypeError.
            """
            return "bad group"

    monkeypatch.setattr(
        core_functions, "BlitzGateway", lambda *args, **kwargs: _Gateway()
    )
    with pytest.raises(TypeError, match="__int__"):
        core_functions._open_service_connection(
            "omeroserver",
            4064,
            group_id=_BadGroupId(),
        )


def test_shared_transfer_helpers_cover_symlink_and_cleanup_error_paths(
    monkeypatch, tmp_path: Path
) -> None:
    """Confirm shared transfer helpers cover symlink and cleanup error paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions when shared transfer helpers cover symlink and cleanup error paths stops reporting the expected error.
    """
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
        lambda name, create=False: transfer_root,
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


def test_prepare_server_readable_zarr_source_rejects_staged_symlink_member(
    monkeypatch, tmp_path: Path
) -> None:
    """Verify shared native-Zarr transfer copying refuses staged symlinks.

    Inputs: pytest fixtures. Output: asserts symlinked staged members are rejected.
    """
    source = tmp_path / "upload" / "sample.zarr"
    (source / "0").mkdir(parents=True)
    outside_payload = tmp_path / "outside-payload.bin"
    outside_payload.write_bytes(b"outside")
    try:
        (source / "0" / "0.0").symlink_to(outside_payload)
    except OSError as exc:
        pytest.skip(f"filesystem does not allow symlinks: {exc}")

    transfer_root = tmp_path / "shared-transfer"
    transfer_root.mkdir()
    monkeypatch.setattr(
        core_functions,
        "get_plugin_tmp_dir",
        lambda name, create=False: transfer_root,
    )

    def unexpected_native_prepare(path):
        """Fail if native preparation receives a symlinked tree.

        Inputs: staged path. Output: raises AssertionError.
        """
        raise AssertionError(f"native prepare should not receive {path}")

    monkeypatch.setattr(
        core_functions,
        "_prepare_native_zarr_copy",
        unexpected_native_prepare,
    )

    shared_source, shared_parent, error = (
        core_functions._prepare_server_readable_zarr_source(source)
    )

    assert shared_source is None
    assert shared_parent is None
    assert "symlinked member" in (error or "")
    assert outside_payload.read_bytes() == b"outside"
    assert list(transfer_root.iterdir()) == []


def test_zarr_tree_posix_copy_rejects_racy_and_special_entries(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Verify import Zarr copy rejects unsafe POSIX filesystem races.

    Inputs: pytest fixtures. Output: asserts racy and special entries are rejected.
    """
    if core_functions.os.name != "posix" or not hasattr(
        core_functions.os, "O_NOFOLLOW"
    ):
        pytest.skip("POSIX no-follow copy path is not available")

    with pytest.raises(RuntimeError, match="Failed to open staged Zarr source safely"):
        core_functions._copy_zarr_tree_without_symlinks_posix(
            tmp_path / "missing.zarr",
            tmp_path / "dest-missing.zarr",
        )

    source = tmp_path / "source.zarr"
    source.mkdir()
    directory_fd = core_functions.os.open(
        source,
        core_functions.os.O_RDONLY
        | getattr(core_functions.os, "O_DIRECTORY", 0)
        | getattr(core_functions.os, "O_NOFOLLOW", 0),
    )
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(core_functions.os, "listdir", lambda _fd: ["bad/name"])
            with pytest.raises(RuntimeError, match="Invalid staged Zarr member name"):
                core_functions._copy_zarr_tree_from_directory_fd(
                    directory_fd,
                    tmp_path / "dest-invalid-name.zarr",
                    "source.zarr",
                )

        (source / "0").write_text("pixels", encoding="utf-8")
        with monkeypatch.context() as scoped:
            scoped.setattr(
                core_functions.os,
                "stat",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("stat failed")),
            )
            with pytest.raises(
                RuntimeError, match="Failed to inspect staged Zarr member"
            ):
                core_functions._copy_zarr_tree_from_directory_fd(
                    directory_fd,
                    tmp_path / "dest-stat.zarr",
                    "source.zarr",
                )
    finally:
        core_functions.os.close(directory_fd)

    dir_source = tmp_path / "dir-source.zarr"
    (dir_source / "0").mkdir(parents=True)
    real_fstat = core_functions.os.fstat
    with monkeypatch.context() as scoped:
        scoped.setattr(
            core_functions.os,
            "fstat",
            lambda fd: SimpleNamespace(st_mode=stat.S_IFREG),
        )
        with pytest.raises(RuntimeError, match="Staged Zarr source is not a directory"):
            core_functions._copy_zarr_tree_without_symlinks_posix(
                dir_source,
                tmp_path / "dest-source-not-dir.zarr",
            )
    with monkeypatch.context() as scoped:
        fstat_calls = {"count": 0}

        def fake_child_dir_fstat(fd):
            """Return regular-file mode for a child directory fd.

            Inputs: file descriptor. Output: fake stat result.
            """
            fstat_calls["count"] += 1
            if fstat_calls["count"] == 2:
                return SimpleNamespace(st_mode=stat.S_IFREG)
            return real_fstat(fd)

        scoped.setattr(core_functions.os, "fstat", fake_child_dir_fstat)
        with pytest.raises(RuntimeError, match="member is not a directory"):
            core_functions._copy_zarr_tree_without_symlinks_posix(
                dir_source,
                tmp_path / "dest-child-dir-race.zarr",
            )

    file_source = tmp_path / "file-source.zarr"
    file_source.mkdir()
    (file_source / "0").write_text("pixels", encoding="utf-8")
    with monkeypatch.context() as scoped:
        fstat_calls = {"count": 0}

        def fake_child_file_fstat(fd):
            """Return directory mode for a child regular-file fd.

            Inputs: file descriptor. Output: fake stat result.
            """
            fstat_calls["count"] += 1
            if fstat_calls["count"] == 2:
                return SimpleNamespace(st_mode=stat.S_IFDIR)
            return real_fstat(fd)

        scoped.setattr(core_functions.os, "fstat", fake_child_file_fstat)
        with pytest.raises(RuntimeError, match="member is not a regular file"):
            core_functions._copy_zarr_tree_without_symlinks_posix(
                file_source,
                tmp_path / "dest-child-file-race.zarr",
            )

    if not hasattr(core_functions.os, "mkfifo"):
        pytest.skip("FIFO creation is not available")
    special_source = tmp_path / "special-source.zarr"
    special_source.mkdir()
    core_functions.os.mkfifo(special_source / "pipe")
    with pytest.raises(RuntimeError, match="unsupported member"):
        core_functions._copy_zarr_tree_without_symlinks_posix(
            special_source,
            tmp_path / "dest-special.zarr",
        )

    wrapper_source = tmp_path / "wrapper-source.zarr"
    wrapper_source.mkdir()
    (wrapper_source / "0").write_text("pixels", encoding="utf-8")
    wrapper_destination = tmp_path / "wrapper-dest.zarr"
    with monkeypatch.context() as scoped:
        scoped.setattr(core_functions.os, "name", "nt", raising=False)
        core_functions._copy_zarr_tree_without_symlinks(
            wrapper_source, wrapper_destination
        )
    assert (wrapper_destination / "0").read_text(encoding="utf-8") == "pixels"


def test_script_service_helpers_cover_deduping_and_selection() -> None:
    """Verify the script service helpers cover deduping and selection execution contract.

    Inputs: import-job fakes. Output: fails on regressions in script service helpers cover deduping and selection integration.
    """
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
        """Test double for working service behavior in this module."""

        @staticmethod
        def getScripts():
            """Return the scripts for `_WorkingService`.

            Inputs: none. Output: `preferred_scripts`.
            """
            return preferred_scripts

    conn = SimpleNamespace(
        getScriptService=lambda: _raise(RuntimeError("primary getter exploded")),
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getScriptService=_WorkingService,
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
    """Verify the script output and managed repo launch helpers cover retry and failure paths execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in script output and managed repo launch helpers cover retry and failure paths integration.
    """
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
    monkeypatch.setattr(core_functions.time, "time", lambda: next_or_fail(now_values))
    sleeps = []
    monkeypatch.setattr(core_functions.time, "sleep", sleeps.append)

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
        """Return the fake subprocess result for cmd and kwargs.

        Inputs: `cmd`, `**kwargs`. Output: `next_or_fail` result.
        """
        attempted_cmds.append(cmd)
        attempted_envs.append(kwargs["env"])
        return next_or_fail(results)

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
    """Verify background user connection yields none when details missing.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection yields none when details missing.
    """
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
    """Verify background user connection with session key.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection with session key.
    """
    closed = {"count": 0}

    class FakeConn:
        """Test double for fake conn."""

        @staticmethod
        def close():
            """Close `FakeConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
    """Confirm background user connection with session key open fails exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection with session key open fails.
    """
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
    """Confirm background user connection with session key close fails exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection with session key close fails.
    when validation or the called operation fails.
    """

    class FakeConn:
        """Test double for fake conn."""

        @staticmethod
        def close():
            """Close `FakeConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
    """Verify background user connection without session key.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection without session key.
    """
    from contextlib import contextmanager

    closed = {"count": 0}

    class FakeConn:
        """Test double for fake conn."""

        @staticmethod
        def close():
            """Close `FakeConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            closed["count"] += 1

    @contextmanager
    def fake_background_session(*args, **kwargs):
        """Simulate background session so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        iterator of yielded items.
        """
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
    """Confirm background user connection without session key close fails exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection without session key close fails.
    when validation or the called operation fails.
    """
    from contextlib import contextmanager

    class FakeConn:
        """Test double for fake conn."""

        @staticmethod
        def close():
            """Close `FakeConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    @contextmanager
    def fake_background_session(*args, **kwargs):
        """Simulate background session so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        iterator of yielded items.
        """
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
    """Verify background user connection background session yields empty key.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in background user connection background session yields empty key.
    """
    from contextlib import contextmanager

    @contextmanager
    def fake_background_session(*args, **kwargs):
        """Simulate background session so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        iterator of yielded items.
        """
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
