from __future__ import annotations

import sys
import types
from pathlib import Path

from omeroweb_import.views import core_functions


class _DummyLock:
    def __init__(self, acquired=True):
        self._acquired = acquired
        self.timeout = None
        self.released = False

    def acquire(self, timeout=None):
        self.timeout = timeout
        return self._acquired

    def release(self):
        self.released = True


class _Value:
    def __init__(self, value):
        self.val = value

    def getValue(self):
        return self.val


class _ImageId:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _ImageRow:
    def __init__(self, image_id):
        self._image_id = image_id

    def getId(self):
        return _ImageId(self._image_id)


def _job_state(monkeypatch, job):
    state = {"job": job}

    def load_job(job_id):
        assert job_id == job["job_id"]
        return state["job"]

    def save_job(job_dict):
        state["job"] = job_dict
        return True

    def update_job(job_id, mutator):
        assert job_id == job["job_id"]
        state["job"] = mutator(state["job"])
        return state["job"]

    monkeypatch.setattr(core_functions, "_load_job", load_job)
    monkeypatch.setattr(core_functions, "_save_job", save_job)
    monkeypatch.setattr(core_functions, "_update_job", update_job)
    return state


def test_find_image_by_name_prefers_dataset_search_and_global_fallback(monkeypatch):
    params_seen = []

    class _Params:
        def addLong(self, key, value):
            params_seen.append(("long", key, value))

        def addString(self, key, value):
            params_seen.append(("string", key, value))

        def page(self, offset, size):
            params_seen.append(("page", offset, size))

    monkeypatch.setattr(
        core_functions.omero,
        "sys",
        types.SimpleNamespace(ParametersI=_Params),
        raising=False,
    )

    class _QueryService:
        def __init__(self):
            self.calls = []

        def findAllByQuery(self, query, params, service_opts):
            self.calls.append(query)
            if "JOIN FETCH i.datasetLinks" in query:
                return [_ImageRow(5)]
            return [_ImageRow(9), _ImageRow(10)]

    query_service = _QueryService()
    looked_up = []
    conn = types.SimpleNamespace(
        getQueryService=lambda: query_service,
        SERVICE_OPTS=object(),
        getObject=lambda obj_type, image_id: (
            looked_up.append((obj_type, image_id)) or {"id": image_id}
        ),
    )

    assert core_functions._find_image_by_name(conn, "sample.ome.tif", dataset_id=7) == {
        "id": 5
    }
    assert looked_up == [("Image", 5)]
    assert any(call[0] == "long" and call[2] == 7 for call in params_seen)

    def failing_dataset_search(query, params, service_opts):
        if "JOIN FETCH i.datasetLinks" in query:
            raise RuntimeError("dataset query failed")
        return [_ImageRow(11), _ImageRow(12)]

    query_service.findAllByQuery = failing_dataset_search
    looked_up.clear()
    assert core_functions._find_image_by_name(conn, "sample.ome.tif", dataset_id=7) == {
        "id": 11
    }
    assert looked_up == [("Image", 11)]
    assert core_functions._find_image_by_name(conn, "", dataset_id=7) is None


def test_verify_import_helpers_and_dataset_creation(monkeypatch):
    class _Params:
        def __init__(self):
            self.values = {}

        def addId(self, value):
            self.values["id"] = value

        def add(self, key, value):
            self.values[key] = value

        def addList(self, key, value):
            self.values[key] = list(value)

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

    class _QueryService:
        def __init__(self):
            self.calls = []

        def projection(self, query, params, service_opts):
            self.calls.append((query, dict(params.values)))
            if "externalInfo.lsid = :lsid" in query:
                return [[_Value("31")]]
            if "externalInfo.lsid like :lsid_prefix" in query:
                return []
            if "JOIN i.datasetLinks" in query:
                return [[_Value("41")], [_Value("42")]]
            return []

    class _Conn:
        def __init__(self):
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=lambda value: setattr(self, "group", value)
            )
            self.query_service = _QueryService()
            self.closed = False
            self.saved = []
            self.project_links = []

        def getQueryService(self):
            return self.query_service

        def close(self):
            self.closed = True

        def getUpdateService(self):
            return types.SimpleNamespace(
                saveAndReturnObject=lambda obj, opts=None: types.SimpleNamespace(
                    getId=lambda: _ImageId(77)
                ),
                saveObject=lambda link, opts=None: self.project_links.append(link),
            )

    class _AdminConn:
        def __init__(self, user_conn):
            self.user_conn = user_conn
            self.closed = False

        def suConn(self, username):
            self.username = username
            return self.user_conn

        def close(self):
            self.closed = True

    conn = _Conn()
    admin_conn = _AdminConn(conn)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    monkeypatch.setattr(
        core_functions,
        "DatasetI",
        lambda *args, **kwargs: types.SimpleNamespace(
            setName=lambda value: None,
            getId=lambda: _ImageId(77),
        ),
        raising=False,
    )

    image_ids = core_functions._verify_import_via_api(
        "alice",
        "omeroserver",
        4064,
        9,
        "imported.ome.tif",
        "input.ome.tif",
        group_name="users_private",
    )
    assert image_ids == ["41", "42"]
    dataset_query, dataset_params = conn.query_service.calls[-1]
    assert "i.name IN (:names)" in dataset_query
    assert dataset_params["names"] == ["imported.ome.tif", "input.ome.tif"]
    assert conn.closed is True
    assert admin_conn.closed is True

    monkeypatch.setattr(
        core_functions,
        "_verify_import_via_api",
        lambda username, host, port, dataset_id, import_name, file_name, **kwargs: [
            "fallback-id"
        ],
    )
    conn = _Conn()
    admin_conn = _AdminConn(conn)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert core_functions._verify_zarr_import_via_api(
        "alice",
        "omeroserver",
        4064,
        "imported.zarr",
        "image.zarr",
        expected_lsid="/managed/root/image.zarr",
        dataset_id=9,
        group_id=5,
    ) == ["31"]
    assert conn.group == "5"

    conn = _Conn()
    admin_conn = _AdminConn(conn)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    assert core_functions._verify_zarr_import_via_api(
        "alice",
        "omeroserver",
        4064,
        "imported.zarr",
        "image.zarr",
        expected_lsid_prefix="/managed/root/image.zarr",
        dataset_id=9,
    ) == ["fallback-id"]

    class _CreatedDataset:
        def __init__(self, dataset_id=None, _loaded=True):
            self.dataset_id = dataset_id

        def setName(self, value):
            self.name = value

        def getId(self):
            return _ImageId(self.dataset_id)

    omero_model = types.ModuleType("omero.model")
    omero_model.DatasetI = _CreatedDataset
    omero_model.ProjectDatasetLinkI = lambda: types.SimpleNamespace(
        setParent=lambda value: None, setChild=lambda value: None
    )
    omero_model.ProjectI = lambda dataset_id, loaded: (dataset_id, loaded)
    monkeypatch.setitem(sys.modules, "omero.model", omero_model)
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: _AdminConn(_Conn()),
    )
    assert (
        core_functions._create_dataset_via_admin_connection(
            "alice",
            "omeroserver",
            4064,
            "Dataset A",
            group_name="users_private",
            project_id=9,
        )
        == 77
    )


def test_verify_imported_zarr_images_renderable_reports_dimension_lsid_and_thumbnail_errors(
    monkeypatch,
):
    class _Image:
        def __init__(
            self,
            image_id,
            *,
            sizes=(1, 1, 1, 1, 1),
            lsid="/managed/root/image.zarr",
            thumbs=None,
            image_exists=True,
            external_info=True,
        ):
            self._id = image_id
            self._sizes = sizes
            self._thumbs = list(thumbs or [b"thumb96", b"thumb256"])
            details = types.SimpleNamespace(
                externalInfo=object() if external_info else None
            )
            self._obj = types.SimpleNamespace(details=details) if image_exists else None
            self._lsid = lsid

        def getSizeX(self):
            return self._sizes[0]

        def getSizeY(self):
            return self._sizes[1]

        def getSizeZ(self):
            return self._sizes[2]

        def getSizeC(self):
            return self._sizes[3]

        def getSizeT(self):
            return self._sizes[4]

        def getThumbnail(self, size, direct=True):
            if not self._thumbs:
                raise RuntimeError("thumbnail failure")
            value = self._thumbs.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

    class _Conn:
        def __init__(self, image):
            self.image = image
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=lambda value: setattr(self, "group", value)
            )
            self.closed = False

        def getObject(self, obj_type, image_id):
            return self.image

        def close(self):
            self.closed = True

    class _AdminConn:
        def __init__(self, conn):
            self.conn = conn
            self.closed = False

        def suConn(self, username):
            self.username = username
            return self.conn

        def close(self):
            self.closed = True

    image = _Image(51)
    conn = _Conn(image)
    admin_conn = _AdminConn(conn)
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    monkeypatch.setattr(
        core_functions,
        "_query_image_external_info",
        lambda conn, image_id: (image._lsid, "ngff"),
    )
    ok, errors = core_functions._verify_imported_zarr_images_renderable(
        "alice",
        "omeroserver",
        4064,
        ["51", "51"],
        expected_lsid="/managed/root/image.zarr",
        group_name="users_private",
    )
    assert ok is True
    assert errors == []
    assert conn.group == "users_private"
    assert conn.closed is True
    assert admin_conn.closed is True

    failing_cases = [
        (
            _Image(52, sizes=(0, 1, 1, 1, 1)),
            {},
            "invalid dimensions",
        ),
        (
            _Image(53, external_info=False),
            {},
            "missing externalInfo",
        ),
        (
            _Image(54, lsid="/wrong/path"),
            {"expected_lsid_prefix": "/managed/root/image.zarr"},
            "unexpected externalInfo.lsid",
        ),
        (
            _Image(55, thumbs=[RuntimeError("thumb broke")]),
            {},
            "thumbnail 96x96 failed",
        ),
    ]
    for image, kwargs, error_fragment in failing_cases:
        conn = _Conn(image)
        admin_conn = _AdminConn(conn)
        monkeypatch.setattr(
            core_functions,
            "_open_admin_connection",
            lambda host, port, _admin=admin_conn: _admin,
        )
        monkeypatch.setattr(
            core_functions,
            "_query_image_external_info",
            lambda conn, image_id, _image=image: (_image._lsid, "ngff"),
        )
        ok, errors = core_functions._verify_imported_zarr_images_renderable(
            "alice",
            "omeroserver",
            4064,
            [str(image._id)],
            **kwargs,
        )
        assert ok is False
        assert any(error_fragment in message for message in errors)


def test_run_compatibility_check_inner_updates_idle_disabled_and_result_paths(
    tmp_path: Path, monkeypatch
):
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(
        core_functions, "_refresh_job_status", core_functions._refresh_job_status
    )
    monkeypatch.setattr(core_functions.time, "time", lambda: 1000.0)

    job_id = "b" * 32
    idle_job = {
        "job_id": job_id,
        "session_key": "session",
        "host": "omeroserver",
        "port": 4064,
        "files": [{"relative_path": "a.ome.tif", "status": "uploaded"}],
        "compatibility_enabled": True,
        "compatibility_thread_active": True,
        "compatibility_status": "checking",
        "incompatible_files": ["a.ome.tif"],
        "planned_import_units": ["stale"],
        "dataset_map": {},
        "orphan_dataset_name": None,
    }
    state = _job_state(monkeypatch, idle_job)
    monkeypatch.setattr(
        core_functions, "_build_import_units", lambda *args, **kwargs: []
    )

    core_functions._run_compatibility_check_inner(job_id)

    assert state["job"]["planned_import_units"] == []
    assert state["job"]["compatibility_thread_active"] is False
    assert state["job"]["compatibility_status"] == "incompatible"

    compatible_job = {
        "job_id": job_id,
        "session_key": "session",
        "host": "omeroserver",
        "port": 4064,
        "files": [{"relative_path": "a.ome.tif", "status": "uploaded"}],
        "compatibility_enabled": False,
        "compatibility_thread_active": True,
        "compatibility_status": "checking",
        "incompatible_files": [],
        "planned_import_units": [],
        "dataset_map": {},
        "orphan_dataset_name": None,
    }
    state = _job_state(monkeypatch, compatible_job)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda *args, **kwargs: [
            {
                "relative_path": "a.ome.tif",
                "staged_path": "_staged/a.ome.tif",
                "covered_indexes": [0],
                "covered_relative_paths": ["a.ome.tif"],
            }
        ],
    )

    core_functions._run_compatibility_check_inner(job_id)

    assert state["job"]["planned_import_units"] == [
        {
            "covered_relative_paths": ["a.ome.tif"],
            "dataset_relative_path": "a.ome.tif",
            "relative_path": "a.ome.tif",
        }
    ]
    assert state["job"]["compatibility_thread_active"] is False
    assert state["job"]["compatibility_status"] == "compatible"

    staged_file = upload_root / job_id / "_staged" / "a.ome.tif"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("payload", encoding="utf-8")
    checking_job = {
        "job_id": job_id,
        "session_key": "session",
        "host": "omeroserver",
        "port": 4064,
        "files": [
            {
                "relative_path": "a.ome.tif",
                "status": "uploaded",
                "compatibility": None,
            },
            {
                "relative_path": "b.ome.tif",
                "status": "uploaded",
                "compatibility": None,
            },
        ],
        "compatibility_enabled": True,
        "compatibility_thread_active": True,
        "compatibility_status": "checking",
        "incompatible_files": [],
        "planned_import_units": [],
        "dataset_map": {"Default": 9},
        "orphan_dataset_name": "Default",
        "job_batch_size": 1,
    }
    state = _job_state(monkeypatch, checking_job)
    started_threads = []
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda *args, **kwargs: [
            {
                "relative_path": "a.ome.tif",
                "staged_path": "_staged/a.ome.tif",
                "covered_indexes": [0],
                "covered_relative_paths": ["a.ome.tif"],
            }
        ],
    )
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job: 1)
    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (root / staged_path, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_dataset_name_for_import_entry",
        lambda unit, orphan_dataset_name: orphan_dataset_name,
    )
    monkeypatch.setattr(
        core_functions,
        "_check_import_compatibility",
        lambda *args, **kwargs: {
            "status": "compatible",
            "details": "ready",
            "import_backend": "bioformats",
            "native_zarr_plan": {"kind": "native"},
        },
    )
    monkeypatch.setattr(
        core_functions, "_should_start_compatibility_check", lambda job: True
    )
    monkeypatch.setattr(
        core_functions,
        "_start_compatibility_check_thread",
        lambda target_job_id: started_threads.append(target_job_id),
    )

    core_functions._run_compatibility_check_inner(job_id)

    assert state["job"]["files"][0]["compatibility"] == "compatible"
    assert state["job"]["files"][0]["compatibility_details"] == "ready"
    assert state["job"]["files"][0]["import_backend"] == "bioformats"
    assert state["job"]["files"][0]["native_zarr_plan"] == {"kind": "native"}
    assert state["job"]["compatibility_status"] == "checking"
    assert state["job"]["compatibility_thread_active"] is False
    assert started_threads == [job_id]


def test_process_import_job_covers_lock_timeout_success_and_failure_cleanup(
    tmp_path: Path, monkeypatch
):
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 2000.0)

    job_id = "c" * 32
    timeout_job = {
        "job_id": job_id,
        "username": "alice",
        "files": [],
        "errors": [],
        "messages": [],
        "status": "ready",
    }
    timeout_state = _job_state(monkeypatch, timeout_job)
    timeout_lock = _DummyLock(acquired=False)
    monkeypatch.setattr(
        core_functions, "_get_import_lock", lambda username: timeout_lock
    )

    core_functions._process_import_job(job_id)

    assert timeout_lock.timeout == 900
    assert timeout_state["job"]["status"] == "error"
    assert any(
        "another import is stuck" in message
        for message in timeout_state["job"]["errors"]
    )

    cleanup_target = upload_root / job_id / "_staged" / "sample.ome.tif"
    cleanup_target.parent.mkdir(parents=True, exist_ok=True)
    cleanup_target.write_text("payload", encoding="utf-8")
    success_job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_name": "users_private",
        "session_key": "session",
        "files": [
            {
                "relative_path": "sample.ome.tif",
                "status": "uploaded",
                "size": 5,
                "errors": [],
            }
        ],
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"Default": 11},
        "orphan_dataset_name": "Default",
        "imported_bytes": 0,
        "total_bytes": 5,
        "sem_edx_associations": {},
        "sem_edx_settings": {},
        "special_upload": "",
    }
    success_state = _job_state(monkeypatch, success_job)
    success_lock = _DummyLock(acquired=True)
    removed_jobs = []
    deferred_jobs = []
    monkeypatch.setattr(
        core_functions, "_get_import_lock", lambda username: success_lock
    )
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job: 1)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda job, upload_root: [
            {
                "relative_path": "sample.ome.tif",
                "covered_indexes": [0],
                "cleanup_staged_paths": ["_staged/sample.ome.tif"],
            }
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job, entries: (True, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_import_job_entry",
        lambda *args, **kwargs: {
            "status": "imported",
            "covered_indexes": [0],
            "cleanup_staged_paths": ["_staged/sample.ome.tif"],
            "rel_path": "sample.ome.tif",
        },
    )
    monkeypatch.setattr(
        core_functions,
        "safe_remove_job_data",
        lambda target_job_id, root: removed_jobs.append((target_job_id, root)),
    )
    monkeypatch.setattr(
        core_functions,
        "_mark_failed_job_for_deferred_cleanup",
        lambda target_job_id: deferred_jobs.append(target_job_id) or True,
    )

    core_functions._process_import_job(job_id)

    assert success_lock.released is True
    assert success_state["job"]["status"] == "done"
    assert success_state["job"]["imported_bytes"] == 5
    assert cleanup_target.exists() is False
    assert removed_jobs == [(job_id, upload_root)]
    assert deferred_jobs == []

    failure_job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_name": "users_private",
        "session_key": "session",
        "files": [
            {
                "relative_path": "sample.ome.tif",
                "status": "uploaded",
                "size": 5,
                "errors": [],
            }
        ],
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"Default": 11},
        "orphan_dataset_name": "Default",
        "imported_bytes": 0,
        "total_bytes": 5,
        "sem_edx_associations": {},
        "sem_edx_settings": {},
        "special_upload": "",
    }
    failure_state = _job_state(monkeypatch, failure_job)
    monkeypatch.setattr(
        core_functions, "_get_import_lock", lambda username: _DummyLock(acquired=True)
    )
    monkeypatch.setattr(
        core_functions,
        "_import_job_entry",
        lambda *args, **kwargs: {
            "status": "error",
            "covered_indexes": [0],
            "entry_error": "bad import",
            "job_error": "job failed",
            "job_message": "job failed",
        },
    )

    core_functions._process_import_job(job_id)

    assert failure_state["job"]["status"] == "error"
    assert "job failed" in failure_state["job"]["errors"]
    assert deferred_jobs == [job_id]


def test_attach_txt_to_image_service_saves_raw_file_store_and_links_plot(
    tmp_path: Path, monkeypatch
):
    txt_path = tmp_path / "spectrum.txt"
    txt_path.write_text("energy,count\n1,2\n", encoding="utf-8")
    plot_path = tmp_path / "spectrum.png"
    plot_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    table_calls = []

    class _OriginalFileI:
        def __init__(self):
            self._id = 0
            self.name = None
            self.path = None
            self.size = None
            self.mimetype = None

        def setName(self, value):
            self.name = value

        def setPath(self, value):
            self.path = value

        def setSize(self, value):
            self.size = value

        def setMimetype(self, value):
            self.mimetype = value

        def getId(self):
            return _Value(self._id)

        def proxy(self):
            return self

    class _FileAnnotationI:
        def __init__(self):
            self.ns = None
            self.file = None

        def setNs(self, value):
            self.ns = value

        def setFile(self, value):
            self.file = value

    class _FileAnnotationWrapper:
        def __init__(self, conn, annotation):
            self.conn = conn
            self.annotation = annotation

    omero_model = types.ModuleType("omero.model")
    omero_model.FileAnnotationI = _FileAnnotationI
    omero_model.OriginalFileI = _OriginalFileI
    monkeypatch.setitem(sys.modules, "omero.model", omero_model)

    omero_rtypes = types.ModuleType("omero.rtypes")
    omero_rtypes.rstring = lambda value: value
    omero_rtypes.rlong = lambda value: value
    monkeypatch.setitem(sys.modules, "omero.rtypes", omero_rtypes)

    omero_gateway = types.ModuleType("omero.gateway")
    omero_gateway.FileAnnotationWrapper = _FileAnnotationWrapper
    monkeypatch.setitem(sys.modules, "omero.gateway", omero_gateway)

    stores = []
    linked_annotations = []

    class _RawFileStore:
        def __init__(self):
            self.file_id = None
            self.payload = b""
            self.saved = False
            self.closed = False

        def setFileId(self, value):
            self.file_id = value

        def write(self, data, offset, length):
            self.payload = data[offset : offset + length]

        def save(self):
            self.saved = True

        def close(self):
            self.closed = True

    class _UpdateService:
        def __init__(self):
            self.saved = []
            self._next_id = 101

        def saveAndReturnObject(self, obj):
            if hasattr(obj, "_id"):
                obj._id = self._next_id
                self._next_id += 1
            self.saved.append(obj)
            return obj

    update_service = _UpdateService()

    class _Image:
        def linkAnnotation(self, wrapper):
            linked_annotations.append(wrapper.annotation)

    image = _Image()

    class _UserConn:
        def __init__(self):
            self.closed = False
            self.c = types.SimpleNamespace(
                sf=types.SimpleNamespace(createRawFileStore=self._create_raw_file_store)
            )

        def _create_raw_file_store(self):
            store = _RawFileStore()
            stores.append(store)
            return store

        def getUpdateService(self):
            return update_service

        def getObject(self, object_type, object_id):
            assert (object_type, object_id) == ("Image", 99)
            return image

        def close(self):
            self.closed = True

    user_conn = _UserConn()
    monkeypatch.setattr(
        core_functions,
        "_open_user_owned_background_connection",
        lambda *args, **kwargs: user_conn,
    )
    sem_edx_parser = types.ModuleType("omeroweb_import.services.omero.sem_edx_parser")
    sem_edx_parser.attach_sem_edx_tables = (
        lambda conn, image_id, source_path, persist_table=True: (
            table_calls.append((image_id, source_path, persist_table)) or 77
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.services.omero.sem_edx_parser",
        sem_edx_parser,
    )

    core_functions._attach_txt_to_image_service(
        types.SimpleNamespace(),
        99,
        txt_path,
        "alice",
        create_tables=True,
        plot_path=plot_path,
        session_key="session",
        host="omeroserver",
        port=4064,
        group_id=5,
    )

    assert table_calls == [(99, txt_path, True)]
    assert len(stores) == 2
    assert stores[0].payload == txt_path.read_bytes()
    assert stores[1].payload == plot_path.read_bytes()
    assert all(store.saved is True for store in stores)
    assert all(store.closed is True for store in stores)
    assert len(linked_annotations) == 2
    assert user_conn.closed is True


def test_verify_import_and_cleanup_imported_images_cover_dataset_and_admin_paths(
    monkeypatch,
):
    dataset = types.SimpleNamespace(
        listChildren=lambda: [
            types.SimpleNamespace(getName=lambda: "match.ome.tif"),
            types.SimpleNamespace(getName=lambda: "other.ome.tif"),
        ]
    )
    conn = types.SimpleNamespace(
        getObject=lambda object_type, object_id: (
            dataset if object_type == "Dataset" else None
        ),
        getObjects=lambda object_type, attributes=None: [
            types.SimpleNamespace(getName=lambda: "global.ome.tif")
        ],
    )

    assert core_functions._verify_import(conn, "match.ome.tif", dataset_id=7) is True
    assert core_functions._verify_import(conn, "missing.ome.tif", dataset_id=7) is False
    assert core_functions._verify_import(conn, "global.ome.tif") is True

    class _AdminConn:
        def __init__(self):
            self.groups = []
            self.deleted = []
            self.closed = False
            self.SERVICE_OPTS = types.SimpleNamespace(setOmeroGroup=self.groups.append)

        def deleteObjects(self, object_type, object_ids, wait=True):
            self.deleted.append((object_type, object_ids, wait))

        def close(self):
            self.closed = True

    admin_conn = _AdminConn()
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )

    core_functions._cleanup_imported_images("omeroserver", 4064, ["10", "bad", "11"])

    assert admin_conn.groups == ["-1"]
    assert admin_conn.deleted == [("Image", [10, 11], True)]
    assert admin_conn.closed is True


def test_process_import_job_handles_sem_edx_associations_and_plot_imports(
    tmp_path: Path, monkeypatch
):
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 3000.0)

    job_id = "d" * 32
    staged_txt = upload_root / job_id / "_staged" / "spectra" / "sample.txt"
    staged_txt.parent.mkdir(parents=True, exist_ok=True)
    staged_txt.write_text("energy,count\n1,2\n", encoding="utf-8")

    plot_source = tmp_path / "sample_plot.png"
    plot_source.write_bytes(b"\x89PNG\r\n\x1a\n")

    job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_id": 5,
        "group_name": "users_private",
        "session_key": "session",
        "files": [
            {
                "relative_path": "images/sample.ome.tif",
                "status": "uploaded",
                "size": 5,
                "errors": [],
            },
            {
                "relative_path": "spectra/sample.txt",
                "staged_path": "_staged/spectra/sample.txt",
                "status": "uploaded",
                "size": 3,
                "errors": [],
            },
        ],
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"images": 11},
        "orphan_dataset_name": "images",
        "imported_bytes": 0,
        "total_bytes": 8,
        "sem_edx_associations": {},
        "sem_edx_settings": {
            "create_tables": True,
            "create_figures_attachments": True,
            "create_figures_images": True,
        },
        "special_upload": "sem_edx_spectra",
    }
    state = _job_state(monkeypatch, job)
    job_lock = _DummyLock(acquired=True)
    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: job_lock)
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job: 1)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda job_dict, root: [
            {
                "relative_path": "images/sample.ome.tif",
                "covered_indexes": [0],
                "cleanup_staged_paths": [],
            }
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job_dict, entries: (True, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_build_sem_edx_associations_from_entries",
        lambda entries: {"images/sample.ome.tif": ["spectra/sample.txt"]},
    )

    class _ImportedImage:
        def __init__(self):
            self._obj = types.SimpleNamespace(id=types.SimpleNamespace(val=301))

        def listParents(self):
            return [types.SimpleNamespace(getId=lambda: 88)]

    imported_image = _ImportedImage()

    class _ServiceConn:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    service_conn = _ServiceConn()
    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda host, port, group_id=None: service_conn,
    )
    monkeypatch.setattr(
        core_functions,
        "_batch_find_images_by_name",
        lambda conn, names, dataset_id: (
            {"sample.ome.tif": imported_image}
            if dataset_id == 11 or dataset_id is None
            else {}
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (root / staged_path, None),
    )
    sem_edx_parser = types.ModuleType("omeroweb_import.services.omero.sem_edx_parser")
    sem_edx_parser.create_edx_spectrum_plot = lambda txt_path: plot_source
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.services.omero.sem_edx_parser",
        sem_edx_parser,
    )

    attached = []
    monkeypatch.setattr(
        core_functions,
        "_attach_txt_to_image_service",
        lambda conn, image_id, txt_path, username, create_tables, plot_path=None, **kwargs: (
            attached.append(
                {
                    "image_id": image_id,
                    "txt_path": txt_path,
                    "username": username,
                    "create_tables": create_tables,
                    "plot_path": plot_path,
                    "kwargs": kwargs,
                }
            )
        ),
    )

    plot_imports = []

    def fake_import_job_entry(entry, *args, **kwargs):
        if entry.get("relative_path") == "images/sample.ome.tif":
            return {
                "status": "imported",
                "covered_indexes": [0],
                "cleanup_staged_paths": [],
                "rel_path": "images/sample.ome.tif",
            }
        plot_imports.append(
            (
                entry.get("relative_path"),
                entry.get("dataset_id_override"),
                entry.get("staged_path"),
            )
        )
        return {"status": "imported"}

    monkeypatch.setattr(core_functions, "_import_job_entry", fake_import_job_entry)

    removed_jobs = []
    deferred_jobs = []
    monkeypatch.setattr(
        core_functions,
        "safe_remove_job_data",
        lambda target_job_id, root: removed_jobs.append((target_job_id, root)),
    )
    monkeypatch.setattr(
        core_functions,
        "_mark_failed_job_for_deferred_cleanup",
        lambda target_job_id: deferred_jobs.append(target_job_id) or True,
    )

    core_functions._process_import_job(job_id)

    assert job_lock.released is True
    assert service_conn.closed is True
    assert state["job"]["status"] == "done"
    assert state["job"]["files"][0]["status"] == "imported"
    assert state["job"]["files"][1]["status"] == "imported"
    assert state["job"]["imported_bytes"] == 8
    assert any(
        "derived 1 TXT attachment" in message for message in state["job"]["messages"]
    )
    assert any(
        "Txt attachment success" in message for message in state["job"]["messages"]
    )
    assert any("sample_plot.png" in message for message in state["job"]["messages"])
    assert len(attached) == 1
    assert attached[0]["image_id"] == 301
    assert attached[0]["txt_path"] == staged_txt
    assert attached[0]["plot_path"] == plot_source
    assert attached[0]["kwargs"]["session_key"] == "session"
    assert plot_imports == [
        (
            "images/sample_plot.png",
            88,
            core_functions._build_staged_relative_path("images/sample_plot.png"),
        )
    ]
    assert removed_jobs == [(job_id, upload_root)]
    assert deferred_jobs == []


def test_process_import_job_handles_sem_edx_reconnect_and_attachment_edge_cases(
    tmp_path: Path, monkeypatch
):
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 3600.0)

    job_id = "f" * 32
    first_image = "images/sample.ome.tif"
    second_image = "images/missing.ome.tif"
    first_txts = [
        "spectra/no-id.txt",
        "spectra/missing-entry.txt",
        "spectra/staged-error.txt",
        "spectra/missing-file.txt",
        "spectra/plot-stage-error.txt",
        "spectra/plot-copy-error.txt",
        "spectra/plot-import-error.txt",
        "spectra/attach-error.txt",
        "spectra/attach-ok-1.txt",
        "spectra/attach-ok-2.txt",
    ]
    second_txts = ["spectra/image-missing.txt"]

    files = [
        {
            "relative_path": first_image,
            "status": "uploaded",
            "size": 5,
            "errors": [],
        },
        {
            "relative_path": second_image,
            "status": "uploaded",
            "size": 5,
            "errors": [],
        },
    ]
    for relative_path in first_txts + second_txts:
        if relative_path == "spectra/missing-entry.txt":
            continue
        staged_path = f"_staged/{relative_path}"
        files.append(
            {
                "relative_path": relative_path,
                "staged_path": staged_path,
                "status": "uploaded",
                "size": 1,
                "errors": [],
            }
        )
        if relative_path != "spectra/missing-file.txt":
            target = upload_root / job_id / staged_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("energy,count\n1,2\n", encoding="utf-8")

    job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_id": 5,
        "group_name": "users_private",
        "session_key": "session",
        "files": files,
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"images": 11},
        "orphan_dataset_name": "images",
        "imported_bytes": 0,
        "total_bytes": 20,
        "sem_edx_associations": {},
        "sem_edx_settings": {
            "create_tables": True,
            "create_figures_attachments": True,
            "create_figures_images": True,
        },
        "special_upload": "sem_edx_spectra",
    }
    state = _job_state(monkeypatch, job)
    job_lock = _DummyLock(acquired=True)
    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: job_lock)
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job_dict: 1)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda job_dict, root: [
            {
                "relative_path": first_image,
                "covered_indexes": [0],
                "cleanup_staged_paths": [],
            },
            {
                "relative_path": second_image,
                "covered_indexes": [1],
                "cleanup_staged_paths": [],
            },
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job_dict, entries: (True, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_build_sem_edx_associations_from_entries",
        lambda entries: {first_image: list(first_txts), second_image: list(second_txts)},
    )

    class _ImportedImage:
        def __init__(self):
            self._obj = types.SimpleNamespace(id=types.SimpleNamespace(val=301))

        def listParents(self):
            raise RuntimeError("parents unavailable")

    imported_image = _ImportedImage()

    class _ServiceConn:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def close(self):
            self.closed = True

    connections = [_ServiceConn("initial"), _ServiceConn("reopened")]
    connection_iter = iter(connections)
    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda host, port, group_id=None: next(connection_iter),
    )

    validate_iter = iter((False,))
    monkeypatch.setattr(
        core_functions,
        "_validate_session",
        lambda conn: next(validate_iter, True),
    )

    batch_calls = []

    def _batch_find(conn, names, dataset_id):
        batch_calls.append((conn.name, tuple(sorted(names)), dataset_id))
        if "sample.ome.tif" in names:
            return {"sample.ome.tif": imported_image}
        return {}

    monkeypatch.setattr(core_functions, "_batch_find_images_by_name", _batch_find)

    def _resolve_staged(root, staged_path):
        target = root / staged_path
        name = target.name
        if name == "staged-error.txt":
            return None, "Rejected staged text path"
        if name == "missing-file.txt":
            return target, None
        if name == "plot-stage-error.png":
            return None, "Rejected staged plot path"
        return target, None

    monkeypatch.setattr(core_functions, "_resolve_staged_target_path", _resolve_staged)

    sem_edx_parser = types.ModuleType("omeroweb_import.services.omero.sem_edx_parser")

    def _create_plot(txt_path):
        plot_path = tmp_path / f"{txt_path.stem}.png"
        plot_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return plot_path

    sem_edx_parser.create_edx_spectrum_plot = _create_plot
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.services.omero.sem_edx_parser",
        sem_edx_parser,
    )

    copied_plots = []

    def _copy2(src, dst):
        copied_plots.append(dst.name)
        if dst.name == "plot-copy-error.png":
            raise RuntimeError("copy failed")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    monkeypatch.setattr(core_functions.shutil, "copy2", _copy2)

    id_values = iter((None, 301, 301, 301, 301, 301, 301, 301, 301, 301))
    monkeypatch.setattr(core_functions, "_get_id", lambda image_obj: next(id_values))

    attached = []

    def _attach_txt(
        conn,
        image_id,
        txt_path,
        username,
        create_tables,
        plot_path=None,
        **kwargs,
    ):
        attached.append((txt_path.name, plot_path and plot_path.name))
        if txt_path.name == "attach-error.txt":
            raise RuntimeError("attach exploded")

    monkeypatch.setattr(core_functions, "_attach_txt_to_image_service", _attach_txt)

    plot_imports = []

    def _import_job_entry(entry, *args, **kwargs):
        relative_path = entry.get("relative_path")
        if relative_path == first_image:
            return {
                "status": "imported",
                "covered_indexes": [0],
                "cleanup_staged_paths": [],
                "rel_path": relative_path,
            }
        if relative_path == second_image:
            return {
                "status": "imported",
                "covered_indexes": [1],
                "cleanup_staged_paths": [],
                "rel_path": relative_path,
            }
        plot_imports.append(relative_path)
        if relative_path.endswith("plot-import-error.png"):
            return {
                "status": "error",
                "job_error": "plot import failed",
                "job_message": "plot import failed",
            }
        return {"status": "imported"}

    monkeypatch.setattr(core_functions, "_import_job_entry", _import_job_entry)

    removed_jobs = []
    deferred_jobs = []
    monkeypatch.setattr(
        core_functions,
        "safe_remove_job_data",
        lambda target_job_id, root: removed_jobs.append((target_job_id, root)),
    )
    monkeypatch.setattr(
        core_functions,
        "_mark_failed_job_for_deferred_cleanup",
        lambda target_job_id: deferred_jobs.append(target_job_id) or True,
    )

    core_functions._process_import_job(job_id)

    assert job_lock.released is True
    assert all(conn.closed for conn in connections)
    assert any(call[0] == "reopened" for call in batch_calls)
    assert state["job"]["status"] == "error"
    assert any(
        "Txt attachment failure: no-id.txt into sample.ome.tif" in message
        for message in state["job"]["messages"]
    )
    assert any(
        "Txt attachment failure: image-missing.txt into missing.ome.tif" in message
        for message in state["job"]["messages"]
    )
    assert any(
        "plot import failed" in message for message in state["job"]["messages"]
    )
    assert any(
        "Rejected staged text path" in error for error in state["job"]["errors"]
    )
    assert any(
        "Rejected staged plot path" in error for error in state["job"]["errors"]
    )
    assert any(
        "Failed to stage SEM-EDX plot PNG for import: plot-copy-error.png" in error
        for error in state["job"]["errors"]
    )
    assert any(name == "attach-error.txt" for name, _plot in attached)
    assert "images/plot-import-error.png" in plot_imports
    assert removed_jobs == []
    assert deferred_jobs == [job_id]
