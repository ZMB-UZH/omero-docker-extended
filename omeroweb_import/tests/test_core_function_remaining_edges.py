from __future__ import annotations

from iter_test_helpers import next_or_fail

import errno
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions


class _Upload:
    """Test double for upload behavior in this module."""

    def __init__(self, *chunks: bytes):
        """Create `_Upload` with its default state.

        Inputs: `*chunks`. Output: None.
        """
        self._chunks = chunks

    def chunks(self):
        """Return the chunks for `_Upload`.

        Inputs: none. Output: `list`.
        """
        return list(self._chunks)


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


def _session_context(session_key):
    """Build a background-session context manager returning a fixed key.

    Inputs: `session_key`. Output: callable context factory.
    """

    @contextmanager
    def _context(*args, **kwargs):
        """Yield the fixed background session key.

        Inputs: `*args`, `**kwargs`. Output: context manager yield.
        """
        yield session_key

    return _context


def test_directory_helpers_cover_parent_creation_and_permission_failures(
    tmp_path, monkeypatch
):
    """Verify the directory helpers cover parent creation and permission failures safety boundary.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `original_mkdir` result. Raises: OSError for the exercised failure path.
    """
    target = tmp_path / "nested" / "file.txt"
    assert core_functions._ensure_parent_dir(target) is True
    assert target.parent.exists()

    failing_target = tmp_path / "failing" / "file.txt"
    original_mkdir = Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        """Return the failing mkdir.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `original_mkdir` result. Raises: OSError when validation or external operations
        fail.
        """
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
        """Return the failing chmod.

        Inputs: `mode`. Output: `original_chmod` result. Raises: OSError when validation or the called operation fails.
        """
        if self == secure_dir:
            raise OSError("chmod failed")
        return original_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", failing_chmod)
    assert core_functions._ensure_dir_with_permissions(secure_dir, 0o755) is True
    monkeypatch.setattr(Path, "chmod", original_chmod)

    failing_create = tmp_path / "failing-create"

    def mkdir_target_failure(self, *args, **kwargs):
        """Return the mkdir target failure.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `original_mkdir` result. Raises: OSError when validation or external operations
        fail.
        """
        if self == failing_create:
            raise OSError("create failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_target_failure)
    assert core_functions._ensure_dir_with_permissions(failing_create, 0o700) is False
    monkeypatch.setattr(Path, "mkdir", original_mkdir)

    original_exists = Path.exists
    failing_exists = tmp_path / "failing-exists"

    def exists_failure(self):
        """Return the exists failure.

        Inputs: none. Output: `original_exists` result. Raises: OSError when validation or the called operation fails.
        """
        if self == failing_exists:
            raise OSError("exists failed")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", exists_failure)
    assert core_functions._ensure_dir_with_permissions(failing_exists, 0o700) is False


def test_staged_upload_helpers_cover_runtime_and_oserror_fallbacks(
    tmp_path, monkeypatch
):
    """Verify staged upload helpers cover runtime and oserror fallbacks.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in staged upload helpers cover runtime and oserror fallbacks.
    """
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


def test_staged_upload_checksum_helpers_cover_validation_edges(tmp_path) -> None:
    """Verify staged upload checksum helpers cover validation edges.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in staged upload checksum helpers cover validation edges.
    """
    upload_root = tmp_path / "uploads"
    staged_dir = upload_root / "_staged"
    staged_dir.mkdir(parents=True)
    (staged_dir / "file.bin").write_bytes(b"abc")

    assert core_functions._reset_staged_upload_file(
        upload_root, "../escape"
    ).startswith("Invalid filename")
    invalid_path_result = core_functions._staged_upload_chunk_matches(
        upload_root,
        "../escape",
        0,
        3,
        "0" * 64,
    )
    assert invalid_path_result[0] is False
    assert "Invalid filename" in invalid_path_result[1]
    bad_digest_result = core_functions._staged_upload_chunk_matches(
        upload_root,
        "_staged/file.bin",
        0,
        3,
        "not-a-digest",
    )
    assert bad_digest_result[0] is False
    assert "chunk_sha256" in bad_digest_result[1]
    assert core_functions._staged_upload_chunk_matches(
        upload_root,
        "_staged/file.bin",
        0,
        10,
        "0" * 64,
    ) == (False, None)
    assert core_functions._staged_upload_chunk_matches(
        upload_root,
        "_staged/missing.bin",
        0,
        3,
        "0" * 64,
    ) == (False, None)


def test_staged_upload_checksum_reports_runtime_and_storage_failures(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify staged upload checksum reports runtime and storage failures.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in staged upload checksum reports runtime and storage failures.
    """
    upload_root = tmp_path / "uploads"
    staged_dir = upload_root / "_staged"
    staged_dir.mkdir(parents=True)
    (staged_dir / "file.bin").write_bytes(b"abc")

    monkeypatch.setattr(
        core_functions,
        "_managed_parent_runtime_error",
        lambda *args, **kwargs: "unsafe staged parent",
    )
    assert core_functions._staged_upload_chunk_matches(
        upload_root,
        "_staged/file.bin",
        0,
        3,
        "0" * 64,
    ) == (False, "unsafe staged parent")

    monkeypatch.setattr(
        core_functions,
        "_managed_parent_runtime_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_managed_parent_directory_fd",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("directory fd failed")),
    )
    already_saved, match_error = core_functions._staged_upload_chunk_matches(
        upload_root,
        "_staged/file.bin",
        0,
        3,
        "0" * 64,
    )
    assert already_saved is False
    assert core_functions._is_managed_upload_internal_error(match_error) is True


def test_dataset_name_and_legacy_option_helpers_cover_overrides(monkeypatch) -> None:
    """Verify dataset name and legacy option helpers cover overrides.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in dataset name and legacy option helpers cover overrides.
    """
    with pytest.raises(TypeError, match="Unexpected converter option"):
        core_functions._build_bioformats2raw_command(
            "/in",
            "/out",
            {},
            unsupported=True,
        )
    for raw_name in (17, " ", "bad\nname", "a" * 256):
        normalized, error = core_functions._normalize_dataset_name_override(raw_name)
        if raw_name == 17:
            assert normalized == "17"
            assert error is None
        else:
            assert normalized is None
            assert error

    job_dict = {"dataset_name_override": "Chosen"}
    assert (
        core_functions._dataset_name_for_job_entry(
            job_dict,
            {"relative_path": "folder/image.tif"},
            "Orphans",
        )
        == "Chosen"
    )
    assert (
        core_functions._dataset_name_for_job_relative_path(
            job_dict,
            "folder/image.tif",
            "Orphans",
        )
        == "Chosen"
    )
    with pytest.raises(TypeError, match="Unexpected upload update"):
        core_functions._apply_upload_updates("job-id", [], upload_errors=[], extra=True)


def test_units_ids_and_normalization_connection_cover_fallback_paths(
    monkeypatch,
) -> None:
    """Verify units IDs and normalization connection cover fallback paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in units IDs and normalization connection cover fallback paths.
    """
    units_class = SimpleNamespace(
        _enumerators={
            "MICROMETER": SimpleNamespace(name="MICROMETER"),
            "NANOMETER": SimpleNamespace(name="NANOMETER"),
        }
    )
    assert [
        unit.name for unit in core_functions._iter_units_length_values(units_class)
    ] == [
        "MICROMETER",
        "NANOMETER",
    ]

    obj = SimpleNamespace(
        _obj=SimpleNamespace(),
        getId=lambda: SimpleNamespace(getValue=lambda: 42),
    )
    assert core_functions._get_id(obj) == 42

    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert (
        core_functions._open_import_name_normalization_connection(
            "session",
            "omero",
            4064,
            7,
        )
        is None
    )

    assert (
        core_functions._iter_units_length_values(SimpleNamespace(_enumerators=())) == []
    )


def test_import_job_entry_dataset_override_selects_dataset_before_import(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify import job entry dataset override selects dataset before import.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in import job entry dataset override selects dataset before import.
    """
    upload_root = tmp_path / "uploads"
    staged_file = upload_root / "_staged" / "image.tif"
    staged_file.parent.mkdir(parents=True)
    staged_file.write_bytes(b"pixels")
    captured = {}

    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (staged_file, None),
    )

    def build_normalization_context(entry, dataset_id, *, file_path):
        """Capture the dataset ID considered for import-name normalization.

        Inputs: `entry`, `dataset_id`, `file_path`. Output: None.
        """
        captured["normalization_dataset_id"] = dataset_id

    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        build_normalization_context,
    )
    monkeypatch.setattr(
        core_functions,
        "_coerce_import_name_normalization_context",
        lambda context: context,
    )
    monkeypatch.setattr(
        core_functions, "_background_import_session", _session_context("background")
    )
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 30)

    def fake_import_file(**kwargs):
        """Capture the dataset ID passed to the OMERO CLI import helper.

        Inputs: `**kwargs`. Output: tuple.
        """
        captured["import_dataset_id"] = kwargs["dataset_id"]
        return False, "", "import failed"

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions, "_extract_imported_object_ids", lambda output: []
    )
    monkeypatch.setattr(
        core_functions, "_extract_imported_image_ids", lambda output: []
    )

    result = core_functions._import_job_entry(
        {
            "index": 0,
            "relative_path": "folder/image.tif",
            "staged_path": "_staged/image.tif",
        },
        upload_root,
        "session",
        "omeroserver",
        4064,
        {"Override Dataset": 44},
        "folder",
        dataset_name_override="Override Dataset",
        username="alice",
        group_name="users",
    )

    assert captured == {
        "normalization_dataset_id": 44,
        "import_dataset_id": 44,
    }
    assert result["status"] == "error"


def test_managed_runtime_and_job_file_helpers_cover_remaining_error_paths(
    tmp_path, monkeypatch
):
    """Confirm managed runtime and job file helpers cover remaining error paths exposes the expected failure.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `original_unlink` result. Raises: OSError for the exercised failure path.
    """
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
    monkeypatch.setattr(core_functions.os, "close", closed.append)
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
        """Return the failing unlink.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `original_unlink` result. Raises: OSError when validation or external operations
        fail.
        """
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
    """Confirm job update and parameter helpers cover generic dict and error paths exposes the expected failure.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions when job update and parameter helpers cover generic dict and error paths stops reporting the expected error.
    """
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
        SimpleNamespace(
            rstring=lambda value: ("RString", value),
            rlist=lambda values: ("RList", values),
        ),
        raising=False,
    )
    generic_calls = {}
    params = SimpleNamespace(add=generic_calls.setdefault)
    core_functions._params_add_string(params, "name", "value")
    assert generic_calls == {"name": ("RString", "value")}

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
    monkeypatch.setattr(core_functions, "rlong", lambda value: ("RLong", value))
    long_params = SimpleNamespace(add=generic_calls.setdefault)
    core_functions._params_add_long(long_params, "count", 7)
    assert generic_calls == {"count": ("RLong", 7)}

    generic_calls.clear()
    list_params = SimpleNamespace(add=generic_calls.setdefault)
    core_functions._params_add_string_list(list_params, "names", ["a", 2])
    assert generic_calls == {"names": ("RList", [("RString", "a"), ("RString", "2")])}

    with pytest.raises(AttributeError):
        core_functions._params_add_string(SimpleNamespace(), "name", "value")
    with pytest.raises(AttributeError):
        core_functions._params_add_long(SimpleNamespace(), "count", 7)
    with pytest.raises(AttributeError):
        core_functions._params_add_string_list(SimpleNamespace(), "names", ["a"])


def test_connection_and_dataset_helpers_cover_admin_and_service_edge_cases(
    monkeypatch,
):
    """Verify connection and dataset helpers cover admin and service edge cases.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in connection and dataset helpers cover admin and service edge cases.
    RuntimeError, _connect_result when validation or the called operation fails.
    """
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: None,
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

    class _AdminConn:
        """Test double for admin conn behavior in this module."""

        def __init__(self, conn):
            """Create `_AdminConn` with `conn`.

            Inputs: `conn`. Output: None.
            """
            self._conn = conn

        def suConn(self, username):
            """Return the su Conn for `_AdminConn`.

            Inputs: `username` username. Output: `_conn`.
            """
            return self._conn

        @staticmethod
        def close():
            """Close `_AdminConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
        """Test double for update service behavior in this module."""

        @staticmethod
        def saveAndReturnObject(dataset, opts):
            """Save the and Return Object for `_UpdateService`.

            Inputs: `dataset`, `opts`. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("save failed")

        @staticmethod
        def saveObject(link, opts):
            """Save the object for `_UpdateService`.

            Inputs: `link`, `opts`. Output: None.
            """
            group_calls.append(("linked", link, opts))

    class _DatasetConn:
        """Test double for dataset conn behavior in this module."""

        def __init__(self):
            """Create `_DatasetConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(
                setOmeroGroup=lambda value: group_calls.append(("group", value))
            )

        @staticmethod
        def getUpdateService():
            """Return `_DatasetConn`'s fake update service.

            Inputs: none. Output: `_UpdateService` result.
            """
            return _UpdateService()

        @staticmethod
        def close():
            """Close `_DatasetConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
        """Test double for blitz conn behavior in this module."""

        def __init__(self, connect_result, *, fail_group=False):
            """Create `_BlitzConn` with `connect_result`.

            Inputs: `connect_result`, `fail_group`. Output: None.
            """
            self._connect_result = connect_result
            self._fail_group = fail_group
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=self._set_group)

        def _set_group(self, value):
            """Set the group for `_BlitzConn`.

            Inputs: `value` input value. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            if self._fail_group:
                raise RuntimeError("group exploded")

        def connect(self):
            """Open the connection for `_BlitzConn`.

            Inputs: none. Output: `_connect_result`. Raises: _connect_result when validation or the called operation fails.
            """
            if isinstance(self._connect_result, Exception):
                raise self._connect_result
            return self._connect_result

        @staticmethod
        def close():
            """Close `_BlitzConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close exploded")

        @staticmethod
        def getLastError():
            """Return `_BlitzConn`'s fake last-error text.

            Inputs: none. Output: 'last-error'.
            """
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
        lambda *args, **kwargs: next_or_fail(connect_attempts),
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
    """Verify the import candidate and probe helpers cover remaining path edges safety boundary.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions when import candidate and probe helpers cover remaining path edges accepts unsafe input.
    """
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
        parsed_candidates.get,
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
