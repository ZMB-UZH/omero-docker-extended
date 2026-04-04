from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions


class _Upload:
    def __init__(self, *chunks: bytes):
        self._chunks = chunks

    def chunks(self):
        return list(self._chunks)


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


def test_directory_helpers_cover_parent_creation_and_permission_failures(
    tmp_path, monkeypatch
):
    target = tmp_path / "nested" / "file.txt"
    assert core_functions._ensure_parent_dir(target) is True
    assert target.parent.exists()

    failing_target = tmp_path / "failing" / "file.txt"
    original_mkdir = Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if self == failing_target.parent:
            raise OSError("mkdir failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)
    assert core_functions._ensure_parent_dir(failing_target) is False
    monkeypatch.setattr(Path, "mkdir", original_mkdir)

    secure_dir = tmp_path / "secure"
    assert core_functions._ensure_dir_with_permissions(secure_dir, 0o700) is True
    assert secure_dir.exists()

    original_chmod = Path.chmod

    def failing_chmod(self, mode):
        if self == secure_dir:
            raise OSError("chmod failed")
        return original_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", failing_chmod)
    assert core_functions._ensure_dir_with_permissions(secure_dir, 0o755) is True
    monkeypatch.setattr(Path, "chmod", original_chmod)

    failing_create = tmp_path / "failing-create"

    def mkdir_target_failure(self, *args, **kwargs):
        if self == failing_create:
            raise OSError("create failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_target_failure)
    assert core_functions._ensure_dir_with_permissions(failing_create, 0o700) is False
    monkeypatch.setattr(Path, "mkdir", original_mkdir)

    original_exists = Path.exists
    failing_exists = tmp_path / "failing-exists"

    def exists_failure(self):
        if self == failing_exists:
            raise OSError("exists failed")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", exists_failure)
    assert core_functions._ensure_dir_with_permissions(failing_exists, 0o700) is False


def test_staged_upload_helpers_cover_runtime_and_oserror_fallbacks(
    tmp_path, monkeypatch
):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()

    _, _, append_error = core_functions._append_upload_chunks_to_staged_path(
        upload_root,
        "../escape",
        _Upload(b"chunk"),
    )
    assert "Invalid filename" in append_error

    runtime_error = "runtime validation failed"
    monkeypatch.setattr(
        core_functions,
        "_managed_parent_runtime_error",
        lambda *args, **kwargs: runtime_error,
    )
    assert core_functions._append_upload_chunks_to_staged_path(
        upload_root,
        "_staged/file.bin",
        _Upload(b"chunk"),
    ) == (None, None, runtime_error)
    assert (
        core_functions._reset_staged_upload_file(upload_root, "_staged/file.bin")
        == runtime_error
    )
    assert core_functions._staged_upload_size(upload_root, "_staged/file.bin") == (
        None,
        runtime_error,
    )
    assert core_functions._replace_staged_upload_file(
        upload_root,
        "_staged/file.bin",
        _Upload(b"chunk"),
    ) == (None, runtime_error)

    monkeypatch.setattr(
        core_functions,
        "_managed_parent_runtime_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_managed_parent_directory_fd",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk exploded")),
    )

    _, _, append_error = core_functions._append_upload_chunks_to_staged_path(
        upload_root,
        "_staged/file.bin",
        _Upload(b"chunk"),
    )
    assert core_functions._is_managed_upload_internal_error(append_error) is True

    reset_error = core_functions._reset_staged_upload_file(
        upload_root, "_staged/file.bin"
    )
    assert core_functions._is_managed_upload_internal_error(reset_error) is True

    _, size_error = core_functions._staged_upload_size(upload_root, "_staged/file.bin")
    assert core_functions._is_managed_upload_internal_error(size_error) is True

    _, replace_error = core_functions._replace_staged_upload_file(
        upload_root,
        "_staged/file.bin",
        _Upload(b"chunk"),
    )
    assert core_functions._is_managed_upload_internal_error(replace_error) is True


def test_managed_runtime_and_job_file_helpers_cover_remaining_error_paths(
    tmp_path, monkeypatch
):
    original_os_open = core_functions.os.open
    original_os_close = core_functions.os.close
    upload_root = tmp_path / "uploads"
    jobs_root = tmp_path / "jobs"
    upload_root.mkdir()
    jobs_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_fsync_jobs_directory", lambda: None)

    monkeypatch.setattr(
        core_functions,
        "_managed_safe_component_name",
        lambda child_name, display_path: child_name,
    )
    monkeypatch.setattr(
        core_functions,
        "_managed_child_lstat",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError(errno.ELOOP, "symlink loop")
        ),
    )
    opened_fd = None
    try:
        with pytest.raises(core_functions._ManagedPathValidationError):
            opened_fd = core_functions._open_managed_upload_file_fd(
                3, "file.bin", 0, "file.bin"
            )
    finally:
        if opened_fd is not None:
            core_functions.os.close(opened_fd)

    monkeypatch.setattr(
        core_functions,
        "_managed_relative_path_validation_error",
        lambda *args, **kwargs: "validation failed",
    )
    assert (
        core_functions._managed_runtime_validation_error(upload_root, ("bad",))
        == "validation failed"
    )
    assert (
        core_functions._managed_parent_runtime_error(upload_root, ("bad",))
        == "validation failed"
    )

    monkeypatch.setattr(
        core_functions,
        "_managed_relative_path_validation_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_validate_existing_managed_path_segments",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert (
        core_functions._managed_runtime_validation_error(
            upload_root, ("dir", "file.txt")
        )
        is None
    )
    monkeypatch.setattr(
        core_functions,
        "_validate_existing_managed_path_segments",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("bad path")),
    )
    assert "Invalid filename" in core_functions._managed_runtime_validation_error(
        upload_root, ("dir", "file.txt")
    )

    monkeypatch.setattr(
        core_functions,
        "_managed_parent_directory_fd",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("bad parent")),
    )
    assert "Invalid filename" in core_functions._managed_parent_runtime_error(
        upload_root, ("dir", "file.txt")
    )

    closed = []
    monkeypatch.setattr(
        core_functions,
        "_managed_parent_directory_fd",
        lambda *args, **kwargs: (91, ""),
    )
    monkeypatch.setattr(core_functions.os, "close", lambda fd: closed.append(fd))
    assert "Invalid filename" in core_functions._managed_parent_runtime_error(
        upload_root, ("dir", "file.txt")
    )
    assert closed == [91]
    monkeypatch.setattr(core_functions.os, "close", original_os_close)

    monkeypatch.setattr(
        core_functions,
        "_managed_root_relative_parts",
        lambda path: (upload_root, ()),
    )
    assert core_functions._resolve_managed_directory_path(upload_root) == upload_root
    monkeypatch.setattr(
        core_functions,
        "_managed_root_relative_parts",
        lambda path: (upload_root, ("..",)),
    )
    with pytest.raises(core_functions._ManagedPathValidationError):
        core_functions._resolve_managed_directory_path(upload_root / "invalid")
    monkeypatch.setattr(
        core_functions,
        "_validate_existing_managed_path_segments",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(core_functions.os, "open", original_os_open)

    monkeypatch.setattr(
        core_functions.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(RuntimeError("replace failed")),
    )
    original_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.parent == jobs_root and self.suffix == ".tmp":
            raise OSError("unlink failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(RuntimeError, match="replace failed"):
        core_functions._write_job_file("a" * 32, {"job_id": "a" * 32})

    for temp_path in jobs_root.glob(f".{'a' * 32}.json.*.tmp"):
        original_unlink(temp_path)


def test_job_update_and_parameter_helpers_cover_generic_dict_and_error_paths(
    tmp_path, monkeypatch
):
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    assert (
        core_functions._robust_update_job("../bad", lambda job: job, retries=1) is None
    )

    valid_job_id = "a" * 32
    assert (
        core_functions._robust_update_job(valid_job_id, lambda job: job, retries=1)
        is None
    )

    job_path = jobs_root / f"{valid_job_id}.json"
    job_path.write_text("{not-json", encoding="utf-8")
    assert (
        core_functions._robust_update_job(valid_job_id, lambda job: job, retries=1)
        is None
    )

    monkeypatch.setattr(
        core_functions.omero,
        "rtypes",
        SimpleNamespace(rstring=lambda value: f"wrapped:{value}"),
        raising=False,
    )
    generic_calls = {}
    params = SimpleNamespace(
        add=lambda key, value: generic_calls.setdefault(key, value)
    )
    core_functions._params_add_string(params, "name", "value")
    assert generic_calls == {"name": "wrapped:value"}

    dict_params = SimpleNamespace(values={})
    core_functions._params_add_string(dict_params, "name", "value")
    core_functions._params_add_long(dict_params, "count", 7)
    core_functions._params_add_string_list(dict_params, "names", ["a", 2])
    assert dict_params.values == {
        "name": "value",
        "count": 7,
        "names": ["a", "2"],
    }

    generic_calls.clear()
    long_params = SimpleNamespace(
        add=lambda key, value: generic_calls.setdefault(key, value)
    )
    core_functions._params_add_long(long_params, "count", 7)
    assert generic_calls == {"count": 7}

    generic_calls.clear()
    list_params = SimpleNamespace(
        add=lambda key, value: generic_calls.setdefault(key, value)
    )
    core_functions._params_add_string_list(list_params, "names", ["a", 2])
    assert generic_calls == {"names": ["a", "2"]}

    with pytest.raises(AttributeError):
        core_functions._params_add_string(SimpleNamespace(), "name", "value")
    with pytest.raises(AttributeError):
        core_functions._params_add_long(SimpleNamespace(), "count", 7)
    with pytest.raises(AttributeError):
        core_functions._params_add_string_list(SimpleNamespace(), "names", ["a"])


def test_connection_and_dataset_helpers_cover_admin_and_service_edge_cases(
    monkeypatch,
):
    assert (
        core_functions._create_dataset_via_admin_connection(
            "alice",
            "omeroserver",
            4064,
            "Dataset",
        )
        is None
    )

    class _AdminConn:
        def __init__(self, conn):
            self._conn = conn

        def suConn(self, username):
            return self._conn

        def close(self):
            raise RuntimeError("admin close exploded")

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: _AdminConn(None),
    )
    assert (
        core_functions._create_dataset_via_admin_connection(
            "alice",
            "omeroserver",
            4064,
            "Dataset",
        )
        is None
    )

    group_calls = []

    class _UpdateService:
        def saveAndReturnObject(self, dataset, opts):
            raise RuntimeError("save failed")

        def saveObject(self, link, opts):
            group_calls.append(("linked", link, opts))

    class _DatasetConn:
        def __init__(self):
            self.SERVICE_OPTS = SimpleNamespace(
                setOmeroGroup=lambda value: group_calls.append(("group", value))
            )

        def getUpdateService(self):
            return _UpdateService()

        def close(self):
            raise RuntimeError("dataset close exploded")

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: _AdminConn(_DatasetConn()),
    )
    assert (
        core_functions._create_dataset_via_admin_connection(
            "alice",
            "omeroserver",
            4064,
            "Dataset",
            group_id=7,
            project_id=5,
        )
        is None
    )
    assert ("group", "7") in group_calls

    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("service-user", "", "", True),
    )
    assert core_functions._open_service_connection("omeroserver", 4064) is None

    class _BlitzConn:
        def __init__(self, connect_result, *, fail_group=False):
            self._connect_result = connect_result
            self._fail_group = fail_group
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=self._set_group)

        def _set_group(self, value):
            if self._fail_group:
                raise RuntimeError("group exploded")

        def connect(self):
            if isinstance(self._connect_result, Exception):
                raise self._connect_result
            return self._connect_result

        def close(self):
            raise RuntimeError("close exploded")

        def getLastError(self):
            return "last-error"

    connect_attempts = iter(
        [
            _BlitzConn(RuntimeError("connect exploded")),
            _BlitzConn(False),
            _BlitzConn(True, fail_group=True),
        ]
    )
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda *args, **kwargs: next(connect_attempts),
    )

    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("service-user", "service-pass", "", True),
    )
    assert core_functions._open_service_connection("omeroserver", 4064) is None
    assert core_functions._open_service_connection("omeroserver", 4064) is None

    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("service-user", "service-pass", "not-an-int", True),
    )
    conn = core_functions._open_service_connection("omeroserver", 4064, group_id=9)
    assert conn is not None

    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda session_key, host, port: None,
    )
    assert (
        core_functions._open_group_scoped_session_connection(
            "session",
            "omeroserver",
            4064,
            group_id=9,
        )
        is None
    )

    scoped_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(
            setOmeroGroup=lambda value: (_ for _ in ()).throw(
                RuntimeError("scoped group exploded")
            )
        )
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda session_key, host, port: scoped_conn,
    )
    assert (
        core_functions._open_group_scoped_session_connection(
            "session",
            "omeroserver",
            4064,
            group_id=9,
        )
        is scoped_conn
    )


def test_import_candidate_and_probe_helpers_cover_remaining_path_edges(
    monkeypatch, tmp_path
):
    expected_path = SimpleNamespace(
        resolve=lambda: (_ for _ in ()).throw(OSError("resolve failed")),
        is_dir=lambda: False,
    )
    parsed_candidates = {
        "skip": None,
        "candidate": SimpleNamespace(resolve=lambda: Path("/other/location")),
    }
    monkeypatch.setattr(
        core_functions,
        "_extract_import_candidates",
        lambda output: ["skip", "candidate"],
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_candidate_path_line",
        lambda line: parsed_candidates.get(line),
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_import_groups",
        lambda output: [{"group_path": None}],
    )
    assert (
        core_functions._has_import_candidates_in_output(
            "stdout",
            expected_file_path=expected_path,
        )
        is False
    )

    assert (
        core_functions._looks_like_directory_package_root([], "", "", ["bundle/file"])
        is False
    )
    assert (
        core_functions._looks_like_directory_package_root(
            ["bundle.ome.zarr/.zattrs"],
            "bundle.ome.zarr",
            "other/path",
            ["bundle.ome.zarr/.zattrs"],
        )
        is False
    )
    assert (
        core_functions._looks_like_directory_package_root(
            ["bundle.ome.zarr/.zattrs", "bundle.ome.zarr/0/.zarray"],
            "bundle.ome.zarr",
            "bundle.ome.zarr/series/0",
            [
                "outside/file",
                "bundle.ome.zarr",
                "bundle.ome.zarr/.zattrs",
                "bundle.ome.zarr/0/.zarray",
            ],
        )
        is True
    )

    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda path: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )
    import_root = tmp_path / "demo"
    staged_root = tmp_path / "staged"
    assert core_functions._probe_import_path(
        import_root,
        staged_root,
        [],
        {},
    ) == {
        "coverage": set(),
        "groups": (),
        "returncode": 0,
        "stderr": "",
        "stdout": "",
    }
