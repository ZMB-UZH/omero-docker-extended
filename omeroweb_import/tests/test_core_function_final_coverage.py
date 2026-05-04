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
    """Represent value."""

    def __init__(self, value):
        """Initialize the instance.

        Inputs: `value`. Output: None.
        """
        self.val = value

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self.val`.
        """
        return self.val


class _Params:
    """Represent params."""

    def __init__(self):
        """Initialize the instance.

        Inputs: none. Output: None.
        """
        self.values = {}

    def add(self, key, value):
        """Add.

        Inputs: `key`, `value`. Output: None.
        """
        self.values[key] = value

    def addId(self, value):
        """Add ID.

        Inputs: `value`. Output: None.
        """
        self.values["id"] = value


def _job_state(monkeypatch, job):
    """Job state.

    Inputs: `monkeypatch`, `job`. Output: computed value.
    """
    state = {"job": job}
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: state["job"])

    def update_job(job_id, mutator):
        """Update job.

        Inputs: `job_id`, `mutator`. Output: `state['job']`.
        """
        state["job"] = mutator(state["job"])
        return state["job"]

    monkeypatch.setattr(core_functions, "_update_job", update_job)
    return state


def test_core_function_misc_edge_helpers_cover_remaining_lines(
    monkeypatch, tmp_path: Path
):
    """Verify core function misc edge helpers cover remaining lines.

    Inputs: `monkeypatch`, `tmp_path`. Output: None.
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
    """Verify load job and path size helpers cover corrupt and oserror paths.

    Inputs: `monkeypatch`, `tmp_path`. Output: bool. Raises on invalid or unavailable
    state.

    state.
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
        """Represent deleting lock."""

        def __init__(self, *args, **kwargs):
            """Initialize the instance.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: None.
            """
            job_path.unlink()

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(core_functions.portalocker, "Lock", _DeletingLock)
    assert core_functions._load_job(job_id) is None

    job_path.write_text("{}", encoding="utf-8")

    class _FailingLock:
        """Represent failing lock."""

        def __init__(self, *args, **kwargs):
            """Initialize the instance.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise core_functions.portalocker.exceptions.LockException("busy")

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

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
        """Represent broken file path."""

        @staticmethod
        def is_file():
            """Return whether file.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def stat():
            """Stat.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise OSError("stat failed")

    class _BrokenDirPath:
        """Represent broken dir path."""

        @staticmethod
        def is_file():
            """Return whether file.

            Inputs: none. Output: bool.
            """
            return False

        @staticmethod
        def rglob(pattern):
            """Rglob.

            Inputs: `pattern`. Output: None. Raises on invalid or unavailable state.
            """
            raise OSError("walk failed")

    assert core_functions._get_path_total_size(_BrokenFilePath()) == 0
    assert core_functions._get_path_total_size(_BrokenDirPath()) == 0


def test_import_file_find_image_and_connection_helpers_cover_remaining_paths(
    monkeypatch, tmp_path: Path
):
    """Verify import file find image and connection helpers cover remaining paths.

    Inputs: `monkeypatch`, `tmp_path`. Output: computed value. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    target = tmp_path / "sample.ome.tif"
    target.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        core_functions,
        "_run_omero_cli",
        lambda cmd, timeout=None: SimpleNamespace(
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

    def _run_streaming_zero(cmd, *, env, timeout, on_tick):
        """Streaming zero.

        Inputs: `cmd`, `env`, `timeout`, `on_tick`. Output: `SimpleNamespace` result.
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
        """Represent failing root conn."""

        def __init__(self, mode):
            """Initialize the instance.

            Inputs: `mode`. Output: None.
            """
            self.mode = mode
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        def connect(self):
            """Open the connection.

            Inputs: none. Output: bool. Raises on invalid or unavailable state.
            """
            if self.mode == "raise":
                raise RuntimeError("connect exploded")
            return False

        @staticmethod
        def getLastError():
            """Return Last Error.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("no last error")

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
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
        """Represent service conn."""

        def __init__(self, *args, **kwargs):
            """Initialize the instance.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
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

    Inputs: `monkeypatch`, `tmp_path`. Output: yielded values. Raises on invalid or
    unavailable state.

    unavailable state.
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
        """Represent image."""

        def __init__(self, image_id, name):
            """Initialize the instance.

            Inputs: `image_id`, `name`. Output: None.
            """
            self._id = image_id
            self._name = name

        def getName(self):
            """Return the fake object name.

            Inputs: none. Output: `self._name`.
            """
            return self._name

        def setName(self, value):
            """Set Name.

            Inputs: `value`. Output: None.
            """
            self._name = value

        @staticmethod
        def save():
            """Persist the object state.

            Inputs: none. Output: None.
            """
            return None

        def getId(self):
            """Return the fake OMERO identifier.

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
        """Represent broken image."""

        def setName(self, value):
            """Set Name.

            Inputs: `value`. Output: None. Raises on invalid or unavailable state.
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
        """Represent original file i."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self._id = 0

        def setName(self, value):
            """Set Name.

            Inputs: `value`. Output: None.
            """
            self.name = value

        def setPath(self, value):
            """Set Path.

            Inputs: `value`. Output: None.
            """
            self.path = value

        def setSize(self, value):
            """Set Size.

            Inputs: `value`. Output: None.
            """
            self.size = value

        def setMimetype(self, value):
            """Set Mimetype.

            Inputs: `value`. Output: None.
            """
            self.mimetype = value

        def getId(self):
            """Return the fake OMERO identifier.

            Inputs: none. Output: `_Value` result.
            """
            return _Value(self._id)

        def proxy(self):
            """Proxy.

            Inputs: none. Output: `self`.
            """
            return self

    class _FileAnnotationI:
        """Represent file annotation i."""

        def setNs(self, value):
            """Set Ns.

            Inputs: `value`. Output: None.
            """
            self.ns = value

        def setFile(self, value):
            """Set File.

            Inputs: `value`. Output: None.
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
        """Represent file annotation wrapper."""

        def __init__(self, conn, annotation):
            """Initialize the instance.

            Inputs: `conn`, `annotation`. Output: None.
            """
            self.annotation = annotation

    omero_gateway = types.ModuleType("omero.gateway")
    omero_gateway.FileAnnotationWrapper = _FileAnnotationWrapper
    monkeypatch.setitem(sys.modules, "omero.gateway", omero_gateway)

    txt_path = tmp_path / "spectrum.txt"
    txt_path.write_text("energy,count\n1,2\n", encoding="utf-8")

    class _BadPath:
        """Represent bad path."""

        name = "bad.txt"

        @staticmethod
        def read_bytes():
            """Return read bytes.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise OSError("read failed")

        def __str__(self):
            """Return the string representation.

            Inputs: none. Output: `self.name`.
            """
            return self.name

    @contextmanager
    def _missing_background_user_connection(*args, **kwargs):
        """Missing background user connection.

        Inputs: `*args`, `**kwargs`. Output: yielded values.
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
        """Missing image background user connection.

        Inputs: `*args`, `**kwargs`. Output: yielded values.
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
        """Represent raw file store."""

        def setFileId(self, value):
            """Set File ID.

            Inputs: `value`. Output: None.
            """
            self.file_id = value

        def write(self, data, offset, length):
            """Write data to the resource.

            Inputs: `data`, `offset`, `length`. Output: None.
            """
            self.payload = data[offset : offset + length]

        def save(self):
            """Persist the object state.

            Inputs: none. Output: None.
            """
            self.saved = True

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("close failed")

    class _UpdateService:
        """Represent update service."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self._next_id = 100

        def saveAndReturnObject(self, obj):
            """Save and return object.

            Inputs: `obj`. Output: `obj`.
            """
            if hasattr(obj, "_id"):
                obj._id = self._next_id
                self._next_id += 1
            return obj

    class _ImageObj:
        """Represent image obj."""

        def linkAnnotation(self, wrapper):
            """Link annotation.

            Inputs: `wrapper`. Output: None.
            """
            self.wrapper = wrapper

    class _UserConn:
        """Represent user conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.c = SimpleNamespace(
                sf=SimpleNamespace(createRawFileStore=_RawFileStore)
            )

        @staticmethod
        def getUpdateService():
            """Return Update Service.

            Inputs: none. Output: `_UpdateService` result.
            """
            return _UpdateService()

        @staticmethod
        def getObject(kind, image_id):
            """Return Object.

            Inputs: `kind`, `image_id`. Output: `_ImageObj` result.
            """
            return _ImageObj()

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
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
        """User background connection.

        Inputs: `*args`, `**kwargs`. Output: yielded values.
        """
        yield _UserConn()

    monkeypatch.setattr(
        core_functions,
        "_background_user_connection",
        _user_background_connection,
    )

    class _BadPlotPath:
        """Represent bad plot path."""

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

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise OSError("plot read failed")

        def __str__(self):
            """Return the string representation.

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

    Inputs: `monkeypatch`, `tmp_path`. Output: computed value. Raises on invalid or
    unavailable state.

    unavailable state.
    """

    class _Relative:
        """Represent relative."""

        def __init__(self, text):
            """Initialize the instance.

            Inputs: `text`. Output: None.
            """
            self.text = text

        def as_posix(self):
            """As posix.

            Inputs: none. Output: `self.text`.
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
            """Initialize the instance.

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

            Inputs: none. Output: `self`. Raises on invalid or unavailable state.
            """
            if self.resolve_error:
                raise OSError("resolve failed")
            return self

        def relative_to(self, other):
            """Relative to.

            Inputs: `other`. Output: `_Relative` result. Raises on invalid or
            unavailable state.

            unavailable state.
            """
            if self.relative_error:
                raise ValueError("outside root")
            return _Relative(self.relative_text)

        def __str__(self):
            """Return the string representation.

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
        """Represent closing conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def getQueryService():
            """Return Query Service.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(
                projection=lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("projection failed")
                )
            )

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("close failed")

    class _ClosingAdmin:
        """Represent closing admin."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.conn = _ClosingConn()

        def suConn(self, username):
            """Su conn.

            Inputs: `username`. Output: `self.conn`.
            """
            return self.conn

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
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
        """Represent render conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def getObject(kind, image_id):
            """Return Object.

            Inputs: `kind`, `image_id`. Output: `render_image`.
            """
            return render_image

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("close failed")

    class _RenderAdmin:
        """Represent render admin."""

        @staticmethod
        def suConn(username):
            """Su conn.

            Inputs: `username`. Output: `_RenderConn` result.
            """
            return _RenderConn()

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
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
        """Represent verify conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def getQueryService():
            """Return Query Service.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(
                projection=lambda *args, **kwargs: [[SimpleNamespace(val=9)]]
            )

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("close failed")

    class _VerifyAdmin:
        """Represent verify admin."""

        @staticmethod
        def suConn(username):
            """Su conn.

            Inputs: `username`. Output: `_VerifyConn` result.
            """
            return _VerifyConn()

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
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
