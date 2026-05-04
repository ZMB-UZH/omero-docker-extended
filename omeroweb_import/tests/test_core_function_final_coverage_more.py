from __future__ import annotations

import contextlib
import errno
import logging
import os
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
        self.val = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self.val`.
        """
        return self.val


def test_core_function_misc_final_edges_cover_remaining_helper_branches(
    monkeypatch, tmp_path: Path
):
    """Verify core function misc final edges cover remaining helper branches.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in core function misc final edges cover remaining helper branches.
    """
    monkeypatch.setattr(
        core_functions,
        "_entry_requires_name_normalization",
        lambda entry, dataset_id: True,
    )
    monkeypatch.setattr(
        core_functions,
        "_logical_import_entry_display_name",
        lambda entry: "",
    )
    monkeypatch.setattr(
        core_functions,
        "_logical_import_entry_group_header_name",
        lambda entry: "group-header.ome.tif",
    )
    assert core_functions._build_import_name_normalization_context({}, 7) is None

    monkeypatch.setattr(core_functions, "JOB_LOCK_RETRIES", 0)
    monkeypatch.setattr(core_functions, "_safe_job_id", lambda value: True)
    monkeypatch.setattr(
        core_functions,
        "_job_path",
        lambda value: tmp_path / f"{value}.json",
    )
    monkeypatch.setattr(
        core_functions,
        "_job_lock_path",
        lambda value: tmp_path / f".{value}.lock",
    )
    (tmp_path / ("a" * 32 + ".json")).write_text("{}", encoding="utf-8")
    assert core_functions._load_job("a" * 32) is None

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: SimpleNamespace(
            suConn=lambda username: None, close=lambda: None
        ),
    )
    assert core_functions._finalize_imported_zarr_image_metadata(
        "alice",
        "omeroserver",
        4064,
        ["1"],
        managed_zarr=tmp_path / "store.zarr",
    ) == (
        False,
        [
            "Failed to open the importing user's session for native Zarr metadata finalization."
        ],
    )

    monkeypatch.setattr(core_functions, "_get_owner_id", lambda obj: None)
    assert (
        core_functions._is_owned_by_user(SimpleNamespace(getDetails=lambda: None), 7)
        is False
    )
    assert (
        core_functions._has_read_write_permissions(
            SimpleNamespace(
                canEdit=lambda: False,
                canWrite=lambda: False,
                getDetails=lambda: SimpleNamespace(
                    getPermissions=lambda: SimpleNamespace(
                        isRead=lambda: False,
                        isWrite=lambda: False,
                    )
                ),
            )
        )
        is False
    )
    assert (
        core_functions._logical_unit_is_directory_package_root(
            {
                "relative_path": ".",
                "dataset_relative_path": ".",
                "covered_relative_paths": [".", "./child"],
            }
        )
        is False
    )

    monkeypatch.setattr(
        core_functions,
        "_planned_import_units_for_request",
        lambda job_dict: [
            {
                "relative_path": "",
                "dataset_relative_path": "",
                "covered_relative_paths": ["one"],
            }
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_generate_orphan_dataset_name",
        lambda: "UploadRoot_TEST",
    )
    assert core_functions._plan_request_job_dataset_targets({"files": []}) == (
        "UploadRoot_TEST",
        ["UploadRoot_TEST"],
    )
    assert core_functions._prepare_uploaded_job_for_request_path_import(
        "a" * 32,
        {
            "job_id": "a" * 32,
            "compatibility_enabled": True,
            "status": "checking",
        },
        conn=None,
    ) == (
        {
            "job_id": "a" * 32,
            "compatibility_enabled": True,
            "status": "checking",
        },
        None,
    )

    assert (
        core_functions._verify_import(
            SimpleNamespace(
                getObjects=lambda *args, **kwargs: [
                    SimpleNamespace(getName=lambda: "other.ome.tif")
                ]
            ),
            "missing.ome.tif",
        )
        is False
    )


def test_managed_path_and_import_candidate_helpers_cover_remaining_lines(
    monkeypatch, tmp_path: Path
):
    """Verify the managed path and import candidate helpers cover remaining lines safety boundary.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture. Output: `should_match`. Raises: OSError, ValueError when validation or
    external operations fail.
    """
    real_os_open = os.open
    real_os_stat = os.stat

    assert core_functions._managed_relative_path_validation_error(
        tmp_path, ()
    ) == core_functions.errors.invalid_filename("")
    assert core_functions._managed_relative_path_validation_error(
        tmp_path,
        ("bad/name",),
    ) == core_functions.errors.invalid_filename("bad/name")
    assert core_functions._managed_relative_path_validation_error(
        tmp_path,
        ("segment",),
        max_bytes=1,
    ) == core_functions.errors.file_path_too_long("segment", 1)
    with pytest.raises(core_functions._ManagedPathValidationError):
        core_functions._validate_managed_relative_parts(tmp_path, ("..",))

    monkeypatch.setattr(
        core_functions.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(NotADirectoryError("boom")),
    )
    with pytest.raises(FileNotFoundError):
        fd = core_functions._open_trusted_managed_root_fd(tmp_path)
        os.close(fd)

    monkeypatch.setattr(
        core_functions.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError(errno.ELOOP, "symlink loop")
        ),
    )
    with pytest.raises(core_functions._ManagedPathValidationError):
        fd = core_functions._open_trusted_managed_root_fd(tmp_path)
        os.close(fd)
    monkeypatch.setattr(core_functions.os, "open", real_os_open)

    root_dir = tmp_path / "managed"
    child_dir = root_dir / "child"
    child_dir.mkdir(parents=True)
    root_fd = os.open(root_dir, core_functions._MANAGED_DIRECTORY_OPEN_FLAGS)
    try:
        child_fd = core_functions._open_managed_subdirectory_fd(
            root_fd, "child", "child"
        )
    finally:
        os.close(root_fd)
    os.close(child_fd)

    root_fd = os.open(root_dir, core_functions._MANAGED_DIRECTORY_OPEN_FLAGS)
    monkeypatch.setattr(
        core_functions.os,
        "stat",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("bad stat")),
    )
    with pytest.raises(core_functions._ManagedPathValidationError):
        core_functions._managed_child_lstat(root_fd, "child", "child")
    os.close(root_fd)
    monkeypatch.setattr(core_functions.os, "stat", real_os_stat)

    root_fd = os.open(root_dir, core_functions._MANAGED_DIRECTORY_OPEN_FLAGS)
    monkeypatch.setattr(
        core_functions,
        "_managed_child_lstat",
        lambda parent_fd, child_name, display_path: None,
    )
    monkeypatch.setattr(
        core_functions.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError(errno.ELOOP, "symlink loop")
        ),
    )
    with pytest.raises(core_functions._ManagedPathValidationError):
        fd = core_functions._open_managed_upload_file_fd(
            root_fd,
            "file.txt",
            os.O_CREAT,
            "file.txt",
        )
        os.close(fd)
    os.close(root_fd)

    close_calls = []
    monkeypatch.setattr(core_functions, "_open_managed_directory_fd", lambda root: 101)
    monkeypatch.setattr(
        core_functions,
        "_open_managed_subdirectory_fd",
        lambda dir_fd, directory_name, display_path: (_ for _ in ()).throw(
            FileNotFoundError("missing")
        ),
    )
    monkeypatch.setattr(
        core_functions.os,
        "close",
        close_calls.append,
    )
    with pytest.raises(core_functions._ManagedPathValidationError):
        core_functions._managed_parent_directory_fd(
            tmp_path,
            ("missing", "leaf.txt"),
            create_parents=False,
        )
    assert close_calls == [101]

    close_calls.clear()
    monkeypatch.setattr(core_functions, "_open_managed_directory_fd", lambda root: 202)
    monkeypatch.setattr(
        core_functions,
        "_open_managed_subdirectory_fd",
        lambda dir_fd, directory_name, display_path: (_ for _ in ()).throw(
            OSError("bad directory")
        ),
    )
    with pytest.raises(core_functions._ManagedPathValidationError):
        core_functions._managed_parent_directory_fd(
            tmp_path,
            ("broken", "leaf.txt"),
            create_parents=True,
        )
    assert close_calls == [202]

    monkeypatch.setattr(
        core_functions.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no fsync")),
    )
    assert core_functions._fsync_directory(tmp_path) is None

    original_extract_candidates = core_functions._extract_import_candidates
    original_parse_candidate = core_functions._parse_candidate_path_line
    original_parse_import_groups = core_functions._parse_import_groups

    class _CandidatePath:
        """Test double for candidate path behavior in this module."""

        __hash__ = None

        def __init__(self, should_match=False):
            """Create `_CandidatePath` with `should_match`.

            Inputs: `should_match`. Output: None.
            """
            self.should_match = should_match

        @staticmethod
        def resolve():
            """Resolve and return the path.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            raise OSError("resolve failed")

        def __eq__(self, other):
            """Return the eq.

            Inputs: `other`. Output: `should_match`.
            """
            return self.should_match

        @staticmethod
        def relative_to(other):
            """Record the relative to call on `_CandidatePath` for later assertions.

            Inputs: `other`. Output: None. Raises: ValueError when validation or
            external operations fail.
            """
            raise ValueError("outside")

    monkeypatch.setattr(
        core_functions,
        "_extract_import_candidates",
        lambda output: [str(tmp_path / "candidate")],
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_candidate_path_line",
        lambda line: _CandidatePath(),
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_import_groups",
        lambda output: [{"group_path": _CandidatePath(should_match=True)}],
    )
    expected_path = tmp_path / "expected.zarr"
    assert (
        core_functions._has_import_candidates_in_output(
            "candidate",
            expected_file_path=expected_path,
        )
        is True
    )
    monkeypatch.setattr(
        core_functions,
        "_extract_import_candidates",
        original_extract_candidates,
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_candidate_path_line",
        original_parse_candidate,
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_import_groups",
        original_parse_import_groups,
    )
    assert core_functions._extract_import_candidates("") == []
    assert core_functions._parse_candidate_path_line("") is None
    assert core_functions._parse_candidate_path_line('""') is None
    candidate_directory_line = f"{(tmp_path / 'path').as_posix()}/"
    assert core_functions._parse_candidate_path_line(candidate_directory_line) is None
    group_path = tmp_path / "a"
    assert core_functions._parse_import_groups(
        f"\n# Group: {group_path.as_posix()}\n"
    ) == [{"group_path": group_path, "members": []}]
    assert core_functions._relative_path_within_root("a/b", "") is False
    assert core_functions._common_relative_prefix([]) == ""
    assert core_functions._common_relative_prefix(["a/b", "x/y"]) == ""
    assert (
        core_functions._group_covers_all_active_paths_under_root(["a"], "", ["a"])
        is False
    )
    assert (
        core_functions._looks_like_directory_package_root(
            ["pkg.ome.zarr/.zattrs", "pkg.ome.zarr/0/0"],
            "pkg.ome.zarr",
            "pkg.ome.zarr/deeper/branch",
            ["pkg.ome.zarr/.zattrs", "pkg.ome.zarr/0/0"],
        )
        is True
    )
    assert (
        core_functions._collect_import_entries({"files": [{"relative_path": ""}]}) == []
    )
    assert (
        core_functions._collect_import_entries(
            {
                "files": [
                    {"relative_path": "a", "status": "uploaded", "import_skip": True}
                ]
            },
            for_compatibility=True,
        )
        == []
    )
    assert core_functions._build_import_units({"files": []}, tmp_path) == []


def test_core_function_routing_and_native_zarr_helpers_cover_remaining_lines(
    monkeypatch, tmp_path: Path
):
    """Verify core function routing and native Zarr helpers cover remaining lines.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in core function routing and native Zarr helpers cover remaining lines.
    """
    state = {"job": {"compatibility_status": "pending"}}

    def _update_job(job_id, mutator):
        """Update the job.

        Inputs: `job_id`, `mutator`. Output: update job result.
        """
        state["job"] = mutator(state["job"])
        return state["job"]

    thread_starts = []

    class _Thread:
        """Test double for thread behavior in this module."""

        def __init__(self, *, target, args, daemon):
            """Create `_Thread` with its default state.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self.args = args

        @staticmethod
        def start():
            """Start `_Thread`'s fake operation.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            thread_starts.append("started")

    monkeypatch.setattr(core_functions, "_update_job", _update_job)
    monkeypatch.setattr(core_functions, "_refresh_job_status", lambda job: job)
    monkeypatch.setattr(core_functions.time, "time", lambda: 1234.0)
    monkeypatch.setattr(core_functions.threading, "Thread", _Thread)
    core_functions._start_compatibility_check_thread("a" * 32)
    assert state["job"]["compatibility_status"] == "checking"
    assert thread_starts == ["started"]

    plan = core_functions._NativeZarrImportPlan(
        kind="ome_zarr",
        recognized_zarr=True,
        validation_error="bad layout",
        compatibility_details="details",
    )
    assert core_functions._serialize_native_zarr_plan(object()) is None
    serialized = core_functions._serialize_native_zarr_plan(plan)
    assert serialized is not None
    assert serialized["validation_error"] == "bad layout"
    assert core_functions._deserialize_native_zarr_plan(plan) is plan

    routed_unit = {}
    core_functions._attach_import_routing_fields(routed_unit, [])
    assert routed_unit == {}

    monkeypatch.setattr(
        core_functions,
        "_native_zarr_import_plan",
        lambda path: core_functions._NativeZarrImportPlan(),
    )
    assert "not supported" in core_functions._prepare_native_zarr_copy(
        tmp_path / "store.zarr"
    )

    admin_conn = SimpleNamespace(
        close=lambda: (_ for _ in ()).throw(RuntimeError("close failed"))
    )
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    monkeypatch.setattr(
        core_functions, "_find_script_id_by_name", lambda *args, **kwargs: 7
    )
    monkeypatch.setattr(core_functions, "_get_root_password", lambda: "")
    ok, outputs, message = core_functions._run_zarr_managed_repo_script(
        "stage",
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
        source_path=tmp_path / "source.zarr",
    )
    assert ok is False
    assert outputs == {}
    assert "ROOTPASS is missing" in message

    cleanup_admin = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=lambda value: None),
        deleteObjects=lambda *args, **kwargs: None,
        close=lambda: (_ for _ in ()).throw(RuntimeError("close failed")),
    )
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: cleanup_admin,
    )
    core_functions._cleanup_imported_images("omeroserver", 4064, ["11"])
    core_functions._cleanup_managed_zarr_path(
        "omeroserver",
        4064,
        username="alice",
        group_name="users_private",
        managed_path=None,
    )


def test_import_job_entry_covers_remaining_zarr_routing_paths(
    monkeypatch, tmp_path: Path
):
    """Verify import job entry covers remaining Zarr routing paths.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in import job entry covers remaining Zarr routing paths.
    """
    zarr_path = tmp_path / "plate.ome.zarr"
    zarr_path.mkdir()
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()

    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda current_root, staged_path: (zarr_path, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_background_import_session",
        lambda *args, **kwargs: contextlib.nullcontext("bg-session"),
    )
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(core_functions, "_native_zarr_import_enabled", lambda: True)
    monkeypatch.setattr(
        core_functions,
        "_deserialize_native_zarr_plan",
        lambda payload: core_functions._NativeZarrImportPlan(kind="ome_zarr"),
    )
    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda path: (_ for _ in ()).throw(FileNotFoundError("omero")),
    )
    monkeypatch.setattr(
        core_functions,
        "_import_file",
        lambda *args, **kwargs: (False, "", "import failed"),
    )
    monkeypatch.setattr(
        core_functions, "_verify_import_via_api", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        core_functions,
        "_extract_imported_object_ids",
        lambda output: [],
    )

    missing_cli = core_functions._import_job_entry(
        {
            "relative_path": "plate.ome.zarr",
            "staged_path": "_staged/plate.ome.zarr",
        },
        upload_root,
        None,
        "omeroserver",
        4064,
        {},
        None,
        username="alice",
    )
    assert missing_cli["status"] == "error"

    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda path: (_ for _ in ()).throw(RuntimeError("scan exploded")),
    )
    unexpected_error = core_functions._import_job_entry(
        {
            "relative_path": "plate.ome.zarr",
            "staged_path": "_staged/plate.ome.zarr",
        },
        upload_root,
        None,
        "omeroserver",
        4064,
        {},
        None,
        username="alice",
    )
    assert unexpected_error["status"] == "error"

    monkeypatch.setattr(
        core_functions,
        "_deserialize_native_zarr_plan",
        lambda payload: core_functions._NativeZarrImportPlan(),
    )
    precomputed_error = core_functions._import_job_entry(
        {
            "relative_path": "plate.ome.zarr",
            "staged_path": "_staged/plate.ome.zarr",
            "compatibility": "error",
            "compatibility_details": "precomputed failure",
            "import_backend": core_functions._ZARR_IMPORT_BACKEND_BIOFORMATS,
        },
        upload_root,
        None,
        "omeroserver",
        4064,
        {},
        None,
        username="alice",
    )
    assert precomputed_error["entry_error"] == "precomputed failure"


def test_core_function_import_name_and_compatibility_edges_cover_remaining_guards(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Verify core function import name and compatibility edges cover remaining guards.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture, `caplog` (pytest.LogCaptureFixture) pytest log capture fixture. Output:
    `str`. Raises: OSError when validation or the called operation fails.
    """
    managed_dir = tmp_path / "managed"
    original_directory_is_usable = core_functions._directory_is_usable
    monkeypatch.setattr(
        core_functions,
        "_resolve_managed_directory_path",
        lambda path: path,
    )
    monkeypatch.setattr(core_functions, "_directory_is_usable", lambda path: False)
    assert core_functions._ensure_dir(managed_dir) is False
    not_a_directory = tmp_path / "not-a-directory"
    not_a_directory.write_text("content", encoding="utf-8")
    assert original_directory_is_usable(not_a_directory) is False

    class _BrokenPath:
        """Test double for broken path behavior in this module."""

        @staticmethod
        def is_dir():
            """Return whether directory.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise OSError("stat failed")

        def __str__(self):
            """Return `_BrokenPath` as test-readable text.

            Inputs: none. Output: '/broken'.
            """
            return "/broken"

    assert original_directory_is_usable(_BrokenPath()) is False
    assert core_functions._summarize_cli_error_text("", "") == (
        "bioformats2raw reported no details"
    )
    assert core_functions._summarize_cli_error_text("", " \n\t ") == (
        "bioformats2raw reported no details"
    )

    assert core_functions._extract_imported_image_ids_for_normalization(
        "",
        fallback_image_ids=[None, " 7 ", "bad", 7, "8"],
    ) == [7, 8]
    assert (
        core_functions._logical_import_entry_source_display_name(
            {"relative_path": "folder/sample.ome.tif"}
        )
        == "sample.ome.tif"
    )
    assert core_functions._build_source_aware_image_name("", "Image A") == "Image A"
    assert core_functions._build_source_aware_image_name("source", "") == "source"
    assert core_functions._build_source_aware_image_name("source", "source") == "source"
    assert (
        core_functions._build_source_aware_image_name(
            "source",
            "source [Series A]",
        )
        == "source [Series A]"
    )
    assert core_functions._coerce_import_name_normalization_context("invalid") is None

    caplog.set_level(logging.WARNING, logger=core_functions.logger.name)
    monkeypatch.setattr(
        core_functions,
        "inspect_ome_zarr_image",
        lambda file_path: SimpleNamespace(
            image_node_relative_paths=("0", "1"),
            image_display_names=("Series A",),
        ),
    )
    (tmp_path / "plate.ome.zarr").mkdir()
    assert (
        core_functions._build_ome_zarr_import_name_normalization_context(
            {"relative_path": "plate.ome.zarr"},
            tmp_path / "plate.ome.zarr",
        )
        is None
    )
    assert "Ignoring inconsistent OME-Zarr naming metadata" in caplog.text

    original_extensions = core_functions.DIRECTORY_PACKAGE_EXTENSIONS
    original_source_display_name = (
        core_functions._logical_import_entry_source_display_name
    )
    core_functions.DIRECTORY_PACKAGE_EXTENSIONS = ("",)
    core_functions._logical_import_entry_source_display_name = lambda entry: ""

    class _NamelessDir:
        """Test double for nameless dir behavior in this module."""

        name = ""

        @staticmethod
        def is_dir():
            """Return whether directory.

            Inputs: none. Output: bool.
            """
            return True

    monkeypatch.setattr(
        core_functions,
        "inspect_ome_zarr_image",
        lambda file_path: SimpleNamespace(
            image_node_relative_paths=("0",),
            image_display_names=("Series A",),
        ),
    )
    try:
        assert (
            core_functions._build_ome_zarr_import_name_normalization_context(
                {},
                _NamelessDir(),
            )
            is None
        )
    finally:
        core_functions.DIRECTORY_PACKAGE_EXTENSIONS = original_extensions
        core_functions._logical_import_entry_source_display_name = (
            original_source_display_name
        )

    assert core_functions._extract_imported_image_ids(
        "Image:10\nCreated Image 10\nCreated Image 11"
    ) == [10, 11]

    class _Image:
        """Test double for image behavior in this module."""

        def __init__(self, image_id: int, name: str):
            """Create `_Image` with `image_id` and `name`.

            Inputs: `image_id`, `name`. Output: None.
            """
            self.id = image_id
            self._name = name
            self.saved = 0

        def getName(self):
            """Return `_Image`'s fake object name.

            Inputs: none. Output: `self._name`.
            """
            return self._name

        def setName(self, name):
            """Set the name for `_Image`.

            Inputs: `name` name. Output: None.
            """
            self._name = name

        def save(self):
            """Persist `_Image`'s fake object state.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self.saved += 1

    mismatch_images = {
        1: _Image(1, "one"),
        2: _Image(2, "two"),
    }
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: SimpleNamespace(
            getObject=lambda object_type, image_id: mismatch_images.get(image_id),
            close=lambda: None,
        ),
    )
    assert (
        core_functions._apply_import_name_normalization_context(
            {"relative_path": "plate.ome.zarr"},
            core_functions._ImportNameNormalizationContext(
                expected_image_names=("Series A",),
            ),
            [1, 2],
            "session",
            "omeroserver",
            4064,
            None,
        )
        == []
    )

    blank_target_images = {
        1: _Image(1, "existing"),
        2: _Image(2, "Series B"),
    }
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: SimpleNamespace(
            getObject=lambda object_type, image_id: blank_target_images.get(image_id),
            close=lambda: None,
        ),
    )
    assert (
        core_functions._apply_import_name_normalization_context(
            {"relative_path": "plate.ome.zarr"},
            core_functions._ImportNameNormalizationContext(
                expected_image_names=("", "Series B"),
            ),
            [1, 2],
            "session",
            "omeroserver",
            4064,
            None,
        )
        == []
    )
    assert blank_target_images[1].saved == 0
    assert blank_target_images[2].saved == 0

    rename_target_images = {
        1: _Image(1, "old name"),
        2: _Image(2, "Series B"),
    }
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: SimpleNamespace(
            getObject=lambda object_type, image_id: rename_target_images.get(image_id),
            close=lambda: None,
        ),
    )
    monkeypatch.setattr(core_functions, "_get_id", lambda obj: obj.id)
    assert core_functions._apply_import_name_normalization_context(
        {"relative_path": "plate.ome.zarr"},
        core_functions._ImportNameNormalizationContext(
            expected_image_names=("Series A", "Series B"),
        ),
        [1, 2],
        "session",
        "omeroserver",
        4064,
        None,
    ) == [1]
    assert rename_target_images[1].getName() == "Series A"
    assert rename_target_images[1].saved == 1
    assert rename_target_images[2].getName() == "Series B"
    assert rename_target_images[2].saved == 0

    assert (
        core_functions._apply_import_name_normalization_context(
            {"relative_path": "plate.ome.zarr"},
            core_functions._ImportNameNormalizationContext(group_header_name="group"),
            [1],
            "session",
            "omeroserver",
            4064,
            None,
        )
        == []
    )

    assert core_functions._classify_compatibility_output(
        0,
        "",
        "Permission denied while probing file",
    ) == ("error", "Permission denied while probing file")
