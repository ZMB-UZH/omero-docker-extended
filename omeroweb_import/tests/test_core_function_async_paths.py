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
