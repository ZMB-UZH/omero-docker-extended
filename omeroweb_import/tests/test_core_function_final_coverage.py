from __future__ import annotations

from iter_test_helpers import next_or_fail

import json
import subprocess
import sys
import types
from contextlib import contextmanager
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


class _Params:
    """Test double for params behavior in this module."""

    def __init__(self):
        """Create `_Params` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.values = {}

    def add(self, key, value):
        """Add the add for `_Params`.

        Inputs: `key` lookup key, `value` input value. Output: None.
        """
        self.values[key] = value

    def addId(self, value):
        """Add the ID for `_Params`.

        Inputs: `value` input value. Output: None.
        """
        self.values["id"] = value


def _job_state(monkeypatch, job):
    """Return the job state.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `job`. Output: `state`.
    """
    state = {"job": job}
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: state["job"])

    def update_job(job_id, mutator):
        """Update the job.

        Inputs: `job_id`, `mutator`. Output: update job result.
        """
        state["job"] = mutator(state["job"])
        return state["job"]

    monkeypatch.setattr(core_functions, "_update_job", update_job)
    return state


def test_core_function_misc_edge_helpers_cover_remaining_lines(
    monkeypatch, tmp_path: Path
):
    """Verify core function misc edge helpers cover remaining lines.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in core function misc edge helpers cover remaining lines.
    """
    fake_units = types.ModuleType("omero.model.enums")
    pixel = SimpleNamespace(name="PIXEL")
    meter = SimpleNamespace(name="METER")
    fake_units.UnitsLength = SimpleNamespace(
        PIXEL=pixel,
        METER=meter,
        _enumerators={"pixel": pixel, "meter": meter},
    )
    monkeypatch.setitem(sys.modules, "omero.model.enums", fake_units)
    core_functions._units_length_for_name.cache_clear()
    core_functions._units_length_by_normalized_name.cache_clear()
    core_functions._units_length_symbol_aliases.cache_clear()

    job = {
        "files": [
            {"relative_path": "img.tif", "staged_path": "_staged/img.tif"},
            {"relative_path": "img2.tif"},
            {"relative_path": "good.txt"},
        ]
    }
    units = [
        {"relative_path": "active.dat", "import_skip": False},
        {"relative_path": "other.dat", "import_skip": False},
    ]

    monkeypatch.setenv("EDGE_INT_VALUE", "abc")
    monkeypatch.setattr(core_functions, "INT_SANITIZER", __import__("re").compile("^$"))
    monkeypatch.setattr(
        core_functions,
        "_generate_orphan_dataset_name",
        lambda: "UploadRoot_TEST",
    )
    monkeypatch.setattr(
        core_functions,
        "_prepare_request_job_import_datasets",
        lambda job_id, job_dict, conn: (job_dict, None),
    )
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: {"job_id": job_id})

    assert core_functions._get_env_int("EDGE_INT_VALUE", 7, 1, 10) == 7
    assert core_functions._safe_relative_path(".") is None
    assert core_functions._normalize_sem_edx_associations(
        {
            "": ["good.txt"],
            "img2.tif": "not-a-list",
            "img.tif": ["", "good.bin", "good.txt"],
        },
        job["files"],
    ) == {"img.tif": ["good.txt"]}
    assert core_functions._units_length_for_name("") is pixel
    assert core_functions._units_length_for_name("meter") is meter
    assert core_functions._link_dataset_to_project(object(), 0, 7) is False
    assert (
        core_functions._link_dataset_to_project(
            SimpleNamespace(
                getUpdateService=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            ),
            1,
            2,
        )
        is False
    )
    assert (
        core_functions._get_session_key(
            SimpleNamespace(getSessionId=lambda: (_ for _ in ()).throw(RuntimeError()))
        )
        is None
    )
    assert core_functions._get_session_key(SimpleNamespace()) is None
    assert (
        core_functions._logical_unit_is_directory_package_root(
            {"relative_path": "", "dataset_relative_path": ""}
        )
        is False
    )
    assert (
        core_functions._dataset_name_for_import_entry({}, "UploadRoot_TEST")
        == "UploadRoot_TEST"
    )
    assert (
        core_functions._planned_import_units_for_request(
            {"planned_import_units": "invalid", "files": job["files"]}
        )
        == []
    )
    assert (
        core_functions._planned_import_units_for_request(
            {
                "planned_import_units": [
                    "invalid",
                    {
                        "relative_path": "missing.dat",
                        "dataset_relative_path": "missing.dat",
                        "covered_relative_paths": ["missing.dat"],
                    },
                ],
                "files": units,
            }
        )
        == []
    )
    orphan_name, planned_dataset_names = (
        core_functions._plan_request_job_dataset_targets(
            {
                "planned_import_units": [],
                "files": [
                    "invalid",
                    {"relative_path": "skip.dat", "import_skip": True},
                    {"relative_path": ""},
                ],
            }
        )
    )
    assert orphan_name is None
    assert planned_dataset_names == []
    orphan_name, planned_dataset_names = (
        core_functions._plan_request_job_dataset_targets(
            {
                "orphan_dataset_name": None,
                "planned_import_units": [
                    {
                        "relative_path": "",
                        "dataset_relative_path": "",
                        "covered_relative_paths": ["active.dat"],
                    }
                ],
                "files": units,
            }
        )
    )
    assert orphan_name == "UploadRoot_TEST"
    assert planned_dataset_names == ["UploadRoot_TEST"]
    prepared_job, prepared_error = (
        core_functions._prepare_uploaded_job_for_request_path_import(
            "a" * 32,
            {
                "job_id": "a" * 32,
                "compatibility_enabled": True,
                "status": "checking",
                "planned_import_units": [],
            },
            conn=None,
        )
    )
    assert prepared_error is None
    assert prepared_job["status"] == "checking"

    upload_root = tmp_path / "uploads" / ("b" * 32)
    upload_root.mkdir(parents=True)
    monkeypatch.setattr(
        core_functions, "_get_upload_root", lambda: tmp_path / "uploads"
    )
    monkeypatch.setattr(
        core_functions, "_build_import_units", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda *_args, **_kwargs: (True, None),
    )
    monkeypatch.setattr(core_functions, "_save_job", lambda payload: True)
    updated_job, error = core_functions._prepare_job_import_datasets(
        "b" * 32,
        {"job_id": "b" * 32},
    )
    assert error is None
    assert updated_job == {"job_id": "b" * 32}

    cli_home = tmp_path / "cli-home"
    cli_home.mkdir()
    config_path = core_functions._write_cli_ice_config(
        cli_home, 17, str(cli_home / "missing-base.cfg")
    )
    assert config_path is not None
    assert config_path.read_text(encoding="utf-8") == "omero.keep_alive=17\n"
    assert core_functions._extract_imported_object_ids("") == []
    assert core_functions._parse_cli_id("no ids here", "Image") is None


def test_load_job_and_path_size_helpers_cover_corrupt_and_oserror_paths(
    monkeypatch, tmp_path: Path
):
    """Verify the load job and path size helpers cover corrupt and oserror paths safety boundary.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture. Output: None after assertions pass. Raises: LockException, OSError when validation or the called operation fails.
    """
    job_id = "a" * 32
    job_path = tmp_path / f"{job_id}.json"
    job_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_safe_job_id", lambda value: True)
    monkeypatch.setattr(core_functions, "_job_path", lambda value: job_path)
    monkeypatch.setattr(
        core_functions, "_job_lock_path", lambda value: tmp_path / "job.lock"
    )
    monkeypatch.setattr(core_functions, "JOB_LOCK_RETRIES", 1)
    monkeypatch.setattr(core_functions.time, "sleep", lambda seconds: None)

    class _DeletingLock:
        """Test double for deleting lock behavior in this module."""

        def __init__(self, *args, **kwargs):
            """Create `_DeletingLock` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            """Enter `_DeletingLock`'s context-managed fake resource.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            job_path.unlink()

        def __exit__(self, exc_type, exc, tb):
            """Exit `_DeletingLock`'s context-managed fake resource.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(core_functions.portalocker, "Lock", _DeletingLock)
    assert core_functions._load_job(job_id) is None

    job_path.write_text("{}", encoding="utf-8")

    class _FailingLock:
        """Test double for failing lock behavior in this module."""

        def __init__(self, *args, **kwargs):
            """Create `_FailingLock` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            """Enter `_FailingLock`'s context-managed fake resource.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            external operations fail.
            """
            raise core_functions.portalocker.exceptions.LockException("busy")

        def __exit__(self, exc_type, exc, tb):
            """Exit `_FailingLock`'s context-managed fake resource.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(core_functions.portalocker, "Lock", _FailingLock)
    monkeypatch.setattr(
        core_functions,
        "_read_job_file",
        lambda value: (_ for _ in ()).throw(json.JSONDecodeError("bad json", "{}", 0)),
    )
    assert core_functions._load_job(job_id) is None

    class _BrokenFilePath:
        """Test double for broken file path behavior in this module."""

        @staticmethod
        def is_file():
            """Return whether file.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def stat():
            """Record the stat call on `_BrokenFilePath` for later assertions.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            raise OSError("stat failed")

    class _BrokenDirPath:
        """Test double for broken dir path behavior in this module."""

        @staticmethod
        def is_file():
            """Return whether file.

            Inputs: none. Output: bool.
            """
            return False

        @staticmethod
        def rglob(pattern):
            """Record the rglob call on `_BrokenDirPath` for later assertions.

            Inputs: `pattern`. Output: None. Raises: OSError for the exercised failure path.
            """
            raise OSError("walk failed")

    assert core_functions._get_path_total_size(_BrokenFilePath()) == 0
    assert core_functions._get_path_total_size(_BrokenDirPath()) == 0


def test_import_file_find_image_and_connection_helpers_cover_remaining_paths(
    monkeypatch, tmp_path: Path
):
    """Verify import file find image and connection helpers cover remaining paths.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture. Output: `SimpleNamespace` result. Raises: RuntimeError when validation or
    external operations fail.
    """
    target = tmp_path / "sample.ome.tif"
    target.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        core_functions,
        "_run_omero_cli",
        lambda cmd, timeout=None, stdin_text=None: SimpleNamespace(
            returncode=1, stdout="stdout", stderr="stderr"
        ),
    )
    ok, stdout, stderr = core_functions._import_file(
        None,
        "session",
        "omeroserver",
        4064,
        target,
    )
    assert (ok, stdout, stderr) == (False, "stdout", "stderr")

    monkeypatch.setattr(core_functions, "_build_cli_env", lambda: {})
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 5)

    def _run_streaming_zero(cmd, *, env, timeout, on_tick, stdin_text=None):
        """Run the streaming zero.

        Inputs: `cmd`, `env` mapping, `timeout`, `on_tick`, optional `stdin_text`.
        Output: `SimpleNamespace`.
        """
        on_tick(123, 0.0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core_functions, "_run_omero_cli_streaming", _run_streaming_zero)
    monkeypatch.setattr(core_functions, "_get_path_total_size", lambda path: 0)
    zero_job = {"imported_bytes": 0}
    assert (
        core_functions._import_file(
            None,
            "session",
            "omeroserver",
            4064,
            target,
            progress_job=zero_job,
        )[0]
        is True
    )

    monkeypatch.setattr(core_functions, "_get_path_total_size", lambda path: 9)
    monkeypatch.setattr(core_functions, "_read_proc_rchar", lambda pid: None)
    monkeypatch.setattr(
        core_functions,
        "_save_job",
        lambda payload: (_ for _ in ()).throw(RuntimeError("save failed")),
    )
    progress_job = {"imported_bytes": 1}
    assert (
        core_functions._import_file(
            None,
            "session",
            "omeroserver",
            4064,
            target,
            progress_job=progress_job,
        )[0]
        is True
    )
    assert progress_job["import_progress_bytes"] == 10

    monkeypatch.setattr(
        core_functions.omero,
        "sys",
        types.SimpleNamespace(ParametersI=_Params),
        raising=False,
    )
    assert (
        core_functions._find_image_by_name(
            SimpleNamespace(
                SERVICE_OPTS=object(),
                getQueryService=lambda: SimpleNamespace(
                    findAllByQuery=lambda *args, **kwargs: []
                ),
                getObject=lambda object_type, image_id: None,
            ),
            "missing.ome.tif",
            dataset_id=7,
        )
        is None
    )
    assert (
        core_functions._find_image_by_name(
            SimpleNamespace(
                SERVICE_OPTS=object(),
                getQueryService=lambda: SimpleNamespace(
                    findAllByQuery=lambda query, params, service_opts: (
                        (_ for _ in ()).throw(RuntimeError("global failed"))
                        if "JOIN FETCH i.datasetLinks" not in query
                        else []
                    )
                ),
                getObject=lambda object_type, image_id: None,
            ),
            "broken.ome.tif",
        )
        is None
    )
    assert (
        core_functions._find_image_by_name(
            SimpleNamespace(
                getQueryService=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            ),
            "broken.ome.tif",
        )
        is None
    )

    monkeypatch.setattr(core_functions, "_get_root_password", lambda: "rootpass")
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("svc", "svc-pass", None, False),
    )

    class _FailingRootConn:
        """Test double for failing root conn behavior in this module."""

        def __init__(self, mode):
            """Create `_FailingRootConn` with `mode`.

            Inputs: `mode`. Output: None.
            """
            self.mode = mode
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        def connect(self):
            """Open the connection for `_FailingRootConn`.

            Inputs: none. Output: `bool`. Raises: RuntimeError when validation or
            external operations fail.
            """
            if self.mode == "raise":
                raise RuntimeError("connect exploded")
            return False

        @staticmethod
        def getLastError():
            """Return `_FailingRootConn`'s fake last-error text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no last error")

        @staticmethod
        def close():
            """Close `_FailingRootConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close exploded")

    states = iter(["fail", "raise"])
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda *args, **kwargs: _FailingRootConn(next_or_fail(states)),
    )
    assert core_functions._open_admin_connection("omeroserver", 4064) is None
    assert core_functions._open_admin_connection("omeroserver", 4064) is None

    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("svc", "svc-pass", "", False),
    )

    class _ServiceConn:
        """Test double for service conn behavior in this module."""

        def __init__(self, *args, **kwargs):
            """Create `_ServiceConn` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection for `_ServiceConn`.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def close():
            """Close `_ServiceConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close exploded")

    monkeypatch.setattr(core_functions, "BlitzGateway", _ServiceConn)
    with pytest.raises(ValueError):
        core_functions._open_service_connection(
            "omeroserver",
            4064,
            group_id="not-an-int",
        )


def test_normalization_and_attachment_helpers_cover_remaining_paths(
    monkeypatch, tmp_path: Path
):
    """Verify normalization and attachment helpers cover remaining paths.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture. Output: iterator of yielded items. Raises: OSError, RuntimeError when validation or the called operation fails.
    """
    entry = {"relative_path": "folder/image.ome.tif"}
    context = {
        "desired_name": "image.ome.tif",
        "group_header_name": "group-header.ome.tif",
    }

    assert (
        core_functions._apply_import_name_normalization_context(
            entry,
            None,
            [1],
            "session",
            "omeroserver",
            4064,
            7,
        )
        == []
    )

    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: None,
    )
    assert (
        core_functions._apply_import_name_normalization_context(
            entry,
            context,
            [1],
            "session",
            "omeroserver",
            4064,
            7,
        )
        == []
    )

    class _Image:
        """Test double for image behavior in this module."""

        def __init__(self, image_id, name):
            """Create `_Image` with `image_id` and `name`.

            Inputs: `image_id`, `name`. Output: None.
            """
            self._id = image_id
            self._name = name

        def getName(self):
            """Return `_Image`'s fake object name.

            Inputs: none. Output: `self._name`.
            """
            return self._name

        def setName(self, value):
            """Set the name for `_Image`.

            Inputs: `value` input value. Output: None.
            """
            self._name = value

        @staticmethod
        def save():
            """Persist `_Image`'s fake object state.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        def getId(self):
            """Return `_Image`'s fake OMERO identifier.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self._id)

    images = {
        2: _Image(2, "already-custom"),
        3: _Image(3, "image.ome.tif [2]"),
    }
    conn = SimpleNamespace(
        getObject=lambda kind, image_id: images.get(image_id),
        close=lambda: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: conn,
    )
    assert (
        core_functions._apply_import_name_normalization_context(
            entry,
            context,
            [1, 2, 3],
            "session",
            "omeroserver",
            4064,
            7,
        )
        == []
    )

    class _BrokenImage(_Image):
        """Test double for broken image behavior in this module."""

        def setName(self, value):
            """Set the name for `_BrokenImage`.

            Inputs: `value` input value. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("rename failed")

    broken_conn = SimpleNamespace(
        getObject=lambda kind, image_id: _BrokenImage(image_id, "group-header.ome.tif"),
        close=lambda: (_ for _ in ()).throw(RuntimeError("close failed")),
    )
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: broken_conn,
    )
    assert (
        core_functions._apply_import_name_normalization_context(
            entry,
            context,
            [4],
            "session",
            "omeroserver",
            4064,
            7,
        )
        == []
    )

    class _OriginalFileI:
        """Test double for original file i behavior in this module."""

        def __init__(self):
            """Create `_OriginalFileI` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self._id = 0

        def setName(self, value):
            """Set the name for `_OriginalFileI`.

            Inputs: `value` input value. Output: None.
            """
            self.name = value

        def setPath(self, value):
            """Set the path for `_OriginalFileI`.

            Inputs: `value` input value. Output: None.
            """
            self.path = value

        def setSize(self, value):
            """Set the size for `_OriginalFileI`.

            Inputs: `value` input value. Output: None.
            """
            self.size = value

        def setMimetype(self, value):
            """Set the mimetype for `_OriginalFileI`.

            Inputs: `value` input value. Output: None.
            """
            self.mimetype = value

        def getId(self):
            """Return `_OriginalFileI`'s fake OMERO identifier.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self._id)

        def proxy(self):
            """Return the proxy for `_OriginalFileI`.

            Inputs: none. Output: `self`.
            """
            return self

    class _FileAnnotationI:
        """Test double for file annotation i behavior in this module."""

        def setNs(self, value):
            """Set the ns for `_FileAnnotationI`.

            Inputs: `value` input value. Output: None.
            """
            self.ns = value

        def setFile(self, value):
            """Set the file for `_FileAnnotationI`.

            Inputs: `value` input value. Output: None.
            """
            self.file = value

    omero_model = types.ModuleType("omero.model")
    omero_model.FileAnnotationI = _FileAnnotationI
    omero_model.OriginalFileI = _OriginalFileI
    monkeypatch.setitem(sys.modules, "omero.model", omero_model)

    omero_rtypes = types.ModuleType("omero.rtypes")
    omero_rtypes.rstring = lambda value: value
    omero_rtypes.rlong = lambda value: value
    monkeypatch.setitem(sys.modules, "omero.rtypes", omero_rtypes)

    class _FileAnnotationWrapper:
        """Test double for file annotation wrapper behavior in this module."""

        def __init__(self, conn, annotation):
            """Create `_FileAnnotationWrapper` with `conn` and `annotation`.

            Inputs: `conn`, `annotation`. Output: None.
            """
            self.annotation = annotation

    omero_gateway = types.ModuleType("omero.gateway")
    omero_gateway.FileAnnotationWrapper = _FileAnnotationWrapper
    monkeypatch.setitem(sys.modules, "omero.gateway", omero_gateway)

    txt_path = tmp_path / "spectrum.txt"
    txt_path.write_text("energy,count\n1,2\n", encoding="utf-8")

    class _BadPath:
        """Test double for bad path behavior in this module."""

        name = "bad.txt"

        @staticmethod
        def read_bytes():
            """Return read bytes.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise OSError("read failed")

        def __str__(self):
            """Return `_BadPath` as test-readable text.

            Inputs: none. Output: `self.name`.
            """
            return self.name

    @contextmanager
    def _missing_background_user_connection(*args, **kwargs):
        """Return the missing background user connection.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        iterator of yielded items.
        """
        yield None

    monkeypatch.setattr(
        core_functions,
        "_background_user_connection",
        _missing_background_user_connection,
    )
    with pytest.raises(RuntimeError, match="Failed to create connection as user"):
        core_functions._attach_txt_to_image_service(
            SimpleNamespace(),
            99,
            txt_path,
            "alice",
        )

    missing_image_conn = SimpleNamespace(
        c=SimpleNamespace(
            sf=SimpleNamespace(createRawFileStore=lambda: None),
        ),
        getUpdateService=lambda: None,
        getObject=lambda kind, image_id: None,
        close=lambda: (_ for _ in ()).throw(RuntimeError("close failed")),
    )

    @contextmanager
    def _missing_image_background_user_connection(*args, **kwargs):
        """Return the missing image background user connection.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        iterator of yielded items.
        """
        yield missing_image_conn

    monkeypatch.setattr(
        core_functions,
        "_background_user_connection",
        _missing_image_background_user_connection,
    )
    with pytest.raises(RuntimeError, match="Image:99 not found"):
        core_functions._attach_txt_to_image_service(
            SimpleNamespace(),
            99,
            txt_path,
            "alice",
        )

    class _RawFileStore:
        """Test double for raw file store behavior in this module."""

        def setFileId(self, value):
            """Set the file ID for `_RawFileStore`.

            Inputs: `value` input value. Output: None.
            """
            self.file_id = value

        def write(self, data, offset, length):
            """Write data to the resource.

            Inputs: `data`, `offset`, `length`. Output: None.
            """
            self.payload = data[offset : offset + length]

        def save(self):
            """Persist `_RawFileStore`'s fake object state.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self.saved = True

        @staticmethod
        def close():
            """Close `_RawFileStore`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    class _UpdateService:
        """Test double for update service behavior in this module."""

        def __init__(self):
            """Create `_UpdateService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self._next_id = 100

        def saveAndReturnObject(self, obj):
            """Return the fake saved OMERO object from coverage tests.

            Inputs: `obj`. Output: `obj`.
            """
            if hasattr(obj, "_id"):
                obj._id = self._next_id
                self._next_id += 1
            return obj

    class _ImageObj:
        """Test double for image obj behavior in this module."""

        def linkAnnotation(self, wrapper):
            """Record the link annotation call on `_ImageObj` for later assertions.

            Inputs: `wrapper`. Output: None.
            """
            self.wrapper = wrapper

    class _UserConn:
        """Test double for user conn behavior in this module."""

        def __init__(self):
            """Create `_UserConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.c = SimpleNamespace(
                sf=SimpleNamespace(createRawFileStore=_RawFileStore)
            )

        @staticmethod
        def getUpdateService():
            """Return `_UserConn`'s fake update service.

            Inputs: none. Output: `_UpdateService` result.
            """
            return _UpdateService()

        @staticmethod
        def getObject(kind, image_id):
            """Return the object for `_UserConn`.

            Inputs: `kind`, `image_id` OMERO image ID. Output: `_ImageObj` result.
            """
            return _ImageObj()

        @staticmethod
        def close():
            """Close `_UserConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    sem_edx_parser = types.ModuleType("omeroweb_import.services.omero.sem_edx_parser")
    sem_edx_parser.attach_sem_edx_tables = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(RuntimeError("table failed"))
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.services.omero.sem_edx_parser",
        sem_edx_parser,
    )

    @contextmanager
    def _user_background_connection(*args, **kwargs):
        """Return the user background connection.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        iterator of yielded items.
        """
        yield _UserConn()

    monkeypatch.setattr(
        core_functions,
        "_background_user_connection",
        _user_background_connection,
    )

    class _BadPlotPath:
        """Test double for bad plot path behavior in this module."""

        name = "plot.png"

        @staticmethod
        def exists():
            """Return whether the path exists.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def read_bytes():
            """Return read bytes.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise OSError("plot read failed")

        def __str__(self):
            """Return `_BadPlotPath` as test-readable text.

            Inputs: none. Output: `self.name`.
            """
            return self.name

    core_functions._attach_txt_to_image_service(
        SimpleNamespace(),
        99,
        txt_path,
        "alice",
        plot_path=_BadPlotPath(),
    )

    monkeypatch.setattr(
        core_functions,
        "_background_user_connection",
        _user_background_connection,
    )
    with pytest.raises(RuntimeError, match="Unable to read file"):
        core_functions._attach_txt_to_image_service(
            SimpleNamespace(),
            99,
            _BadPath(),
            "alice",
        )


def test_probe_and_verification_helpers_cover_remaining_paths(
    monkeypatch, tmp_path: Path
):
    """Verify probe and verification helpers cover remaining paths.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture. Output: `text`. Raises: OSError, RuntimeError, ValueError when validation or the called operation fails.
    """

    class _Relative:
        """Test double for relative behavior in this module."""

        def __init__(self, text):
            """Create `_Relative` with `text`.

            Inputs: `text`. Output: None.
            """
            self.text = text

        def as_posix(self):
            """Return the as posix for `_Relative`.

            Inputs: none. Output: `text`.
            """
            return self.text

    class _FakePath:
        """Test double for fake path."""

        def __init__(
            self,
            text,
            *,
            resolve_error=False,
            relative_error=False,
            relative_text=None,
        ):
            """Create `_FakePath` with `text`.

            Inputs: `text`, `resolve_error`, `relative_error`, `relative_text`. Output:
            None.

            None.
            """
            self.text = text
            self.resolve_error = resolve_error
            self.relative_error = relative_error
            self.relative_text = relative_text or text

        def resolve(self):
            """Resolve and return the path.

            Inputs: none. Output: `self`. Raises: OSError for the exercised failure path.
            """
            if self.resolve_error:
                raise OSError("resolve failed")
            return self

        def relative_to(self, other):
            """Return the relative to for `_FakePath`.

            Inputs: `other`. Output: `_Relative` result. Raises: ValueError when validation or the called operation fails.
            """
            if self.relative_error:
                raise ValueError("outside root")
            return _Relative(self.relative_text)

        def __str__(self):
            """Return `_FakePath` as test-readable text.

            Inputs: none. Output: `self.text`.
            """
            return self.text

    staged_root = _FakePath("staged-root", resolve_error=True)
    path = _FakePath("plate.zarr")
    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda current_path: subprocess.CompletedProcess(
            args=["omero", "import"],
            returncode=0,
            stdout="ignored",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_parse_import_groups",
        lambda output: [
            {
                "group_path": _FakePath(
                    "outside-group",
                    resolve_error=True,
                    relative_error=True,
                ),
                "members": [
                    _FakePath(
                        "outside-member",
                        resolve_error=True,
                        relative_error=True,
                    ),
                    _FakePath("inside-member", relative_text="good.txt"),
                ],
            }
        ],
    )
    result = core_functions._probe_import_path(
        path,
        staged_root,
        ["good.txt"],
        {},
    )
    assert result["coverage"] == {"good.txt"}

    job_id = "c" * 32
    upload_root = tmp_path / "uploads"
    (upload_root / job_id).mkdir(parents=True)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 5000.0)
    monkeypatch.setattr(
        core_functions,
        "_serialize_import_unit_plan",
        lambda unit: {"relative_path": unit.get("relative_path", "")},
    )
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job: 3)
    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda current_root, staged_path: (
            current_root / staged_path,
            None,
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_dataset_name_for_import_entry",
        lambda unit, orphan_dataset_name=None: "Dataset",
    )
    monkeypatch.setattr(
        core_functions,
        "_check_import_compatibility",
        lambda *args, **kwargs: {
            "status": "incompatible",
            "details": "nope",
            "import_backend": "native",
        },
    )
    monkeypatch.setattr(
        core_functions, "_compatibility_pending_entries", lambda job: []
    )
    monkeypatch.setattr(core_functions, "_refresh_job_status", lambda job: job)
    monkeypatch.setattr(
        core_functions,
        "_should_start_compatibility_check",
        lambda current_job: False,
    )

    incompatible_job = {
        "job_id": job_id,
        "host": "omeroserver",
        "port": 4064,
        "session_key": "session",
        "compatibility_enabled": True,
        "compatibility_thread_active": True,
        "compatibility_status": "checking",
        "files": [{"relative_path": "bad.ome.tif", "status": "uploaded"}],
    }
    incompatible_state = _job_state(monkeypatch, incompatible_job)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda current_job, current_root, for_compatibility=False: [
            {
                "relative_path": "skip-me",
                "covered_indexes": [0],
                "covered_relative_paths": ["skip-me"],
                "staged_path": "",
            },
            {
                "relative_path": "bad.ome.tif",
                "covered_indexes": [0, 99],
                "covered_relative_paths": ["bad.ome.tif"],
                "staged_path": "_staged/bad.ome.tif",
            },
        ],
    )
    core_functions._run_compatibility_check_inner(job_id)
    assert incompatible_state["job"]["files"][0]["compatibility"] == "incompatible"
    assert incompatible_state["job"]["compatibility_status"] == "incompatible"

    compatible_job = {
        "job_id": job_id,
        "host": "omeroserver",
        "port": 4064,
        "session_key": "session",
        "compatibility_enabled": True,
        "compatibility_thread_active": True,
        "compatibility_status": "checking",
        "files": [{"relative_path": "good.ome.tif", "status": "uploaded"}],
    }
    compatible_state = _job_state(monkeypatch, compatible_job)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda current_job, current_root, for_compatibility=False: [
            {
                "relative_path": "good.ome.tif",
                "covered_indexes": [0],
                "covered_relative_paths": ["good.ome.tif"],
                "staged_path": "_staged/good.ome.tif",
            }
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_check_import_compatibility",
        lambda *args, **kwargs: {"status": "compatible", "details": ""},
    )
    core_functions._run_compatibility_check_inner(job_id)
    assert compatible_state["job"]["compatibility_status"] == "compatible"

    monkeypatch.setattr(
        core_functions.omero,
        "sys",
        types.SimpleNamespace(ParametersI=_Params),
        raising=False,
    )
    monkeypatch.setattr(
        core_functions.omero,
        "rtypes",
        types.SimpleNamespace(rstring=lambda value: value),
        raising=False,
    )

    class _ClosingConn:
        """Test double for closing conn behavior in this module."""

        def __init__(self):
            """Create `_ClosingConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def getQueryService():
            """Return the fake query service value used by this test double.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(
                projection=lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("projection failed")
                )
            )

        @staticmethod
        def close():
            """Close `_ClosingConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    class _ClosingAdmin:
        """Test double for closing admin behavior in this module."""

        def __init__(self):
            """Create `_ClosingAdmin` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.conn = _ClosingConn()

        def suConn(self, username):
            """Return the su Conn for `_ClosingAdmin`.

            Inputs: `username` username. Output: `conn`.
            """
            return self.conn

        @staticmethod
        def close():
            """Close `_ClosingAdmin`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("admin close failed")

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: _ClosingAdmin(),
    )
    assert (
        core_functions._verify_zarr_import_via_api(
            "alice",
            "omeroserver",
            4064,
            "imported.zarr",
            "file.zarr",
            group_name="users_private",
            expected_lsid_prefix="/managed/root/file.zarr",
        )
        == []
    )

    render_image = SimpleNamespace(
        _obj=SimpleNamespace(
            details=SimpleNamespace(
                externalInfo=SimpleNamespace(
                    getLsid=lambda: _Value("/managed/root/file.zarr/0")
                )
            )
        ),
        getSizeX=lambda: 1,
        getSizeY=lambda: 1,
        getSizeZ=lambda: 1,
        getSizeC=lambda: 1,
        getSizeT=lambda: 1,
        getThumbnail=lambda size, direct=True: b"thumb",
    )

    class _RenderConn:
        """Test double for render conn behavior in this module."""

        def __init__(self):
            """Create `_RenderConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def getObject(kind, image_id):
            """Return the object for `_RenderConn`.

            Inputs: `kind`, `image_id` OMERO image ID. Output: `render_image`.
            """
            return render_image

        @staticmethod
        def close():
            """Close `_RenderConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    class _RenderAdmin:
        """Test double for render admin behavior in this module."""

        @staticmethod
        def suConn(username):
            """Return the su Conn for `_RenderAdmin`.

            Inputs: `username` username. Output: `_RenderConn` result.
            """
            return _RenderConn()

        @staticmethod
        def close():
            """Close `_RenderAdmin`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("admin close failed")

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: _RenderAdmin(),
    )
    monkeypatch.setattr(
        core_functions,
        "_query_image_external_info",
        lambda conn, image_id: ("", ""),
    )
    ok, errors = core_functions._verify_imported_zarr_images_renderable(
        "alice",
        "omeroserver",
        4064,
        ["1"],
        group_id=7,
    )
    assert ok is True
    assert errors == []

    class _VerifyConn:
        """Test double for verify conn behavior in this module."""

        def __init__(self):
            """Create `_VerifyConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def getQueryService():
            """Return the fake query service value used by this test double.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(
                projection=lambda *args, **kwargs: [[SimpleNamespace(val=9)]]
            )

        @staticmethod
        def close():
            """Close `_VerifyConn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    class _VerifyAdmin:
        """Test double for verify admin behavior in this module."""

        @staticmethod
        def suConn(username):
            """Return the su Conn for `_VerifyAdmin`.

            Inputs: `username` username. Output: `_VerifyConn` result.
            """
            return _VerifyConn()

        @staticmethod
        def close():
            """Close `_VerifyAdmin`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("admin close failed")

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: _VerifyAdmin(),
    )
    assert core_functions._verify_import_via_api(
        "alice",
        "omeroserver",
        4064,
        7,
        "imported.ome.tif",
        "fallback.ome.tif",
        group_id=7,
    ) == ["9"]
