from __future__ import annotations

from types import SimpleNamespace

from omeroweb_import.strings import errors as import_errors
from omeroweb_import.views import core_functions


class _Value:
    def __init__(self, value):
        self.val = value

    def getValue(self):
        return self.val


class _Owner:
    def __init__(self, owner_id, *, ome_name=None, first_name=None):
        self._owner_id = owner_id
        self._ome_name = ome_name
        self._first_name = first_name

    def getId(self):
        return _Value(self._owner_id)

    def getOmeName(self):
        if self._ome_name is None:
            raise RuntimeError("no ome name")
        return self._ome_name

    def getFirstName(self):
        return self._first_name


class _Permissions:
    def __init__(self, can_read, can_write):
        self._can_read = can_read
        self._can_write = can_write

    def isRead(self):
        return self._can_read

    def isWrite(self):
        return self._can_write


class _Details:
    def __init__(self, *, owner=None, permissions=None):
        self._owner = owner
        self._permissions = permissions

    def getOwner(self):
        return self._owner

    def getPermissions(self):
        return self._permissions


class _NamedProject:
    def __init__(
        self,
        project_id,
        name,
        *,
        owner_id=None,
        owner_name=None,
        permissions=None,
        children=None,
    ):
        self._project_id = project_id
        self._name = name
        self._details = _Details(
            owner=_Owner(owner_id or 0, ome_name=owner_name),
            permissions=permissions,
        )
        self._children = list(children or [])

    def getId(self):
        return _Value(self._project_id)

    def getName(self):
        return self._name

    def getDetails(self):
        return self._details

    def listChildren(self):
        return list(self._children)


class _DatasetChild:
    def __init__(self, dataset_id, name):
        self._dataset_id = dataset_id
        self._name = name

    def getId(self):
        return _Value(self._dataset_id)

    def getName(self):
        return self._name


class _ExistingDataset:
    def __init__(self, dataset_id):
        self._dataset_id = dataset_id

    def getId(self):
        return _Value(self._dataset_id)


def test_owner_and_permission_helpers_cover_fallback_paths() -> None:
    owner = _Owner(7, ome_name="alice")
    details_obj = SimpleNamespace(
        getDetails=lambda: _Details(owner=owner, permissions=_Permissions(True, True))
    )
    fallback_owner = _Owner(8, ome_name=None, first_name=None)
    fallback_obj = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("no details")),
        getOwner=lambda: fallback_owner,
        canEdit=lambda: False,
        canWrite=lambda: True,
    )

    assert core_functions._get_owner_id(details_obj) == 7
    assert core_functions._current_user_id(SimpleNamespace(getUser=lambda: owner)) == 7
    assert core_functions._is_owned_by_user(details_obj, 7) is True
    assert core_functions._is_owned_by_user(details_obj, 8) is False
    assert core_functions._get_owner_username(details_obj) == "alice"
    assert core_functions._get_owner_username(fallback_obj) == "8"
    assert core_functions._has_read_write_permissions(details_obj) is True
    assert core_functions._has_read_write_permissions(fallback_obj) is True


def test_iter_accessible_projects_and_collect_project_payload_cover_fallbacks() -> None:
    service_opts = SimpleNamespace(
        current="5",
        set_calls=[],
        getOmeroGroup=lambda: service_opts.current,
        setOmeroGroup=lambda value: (
            service_opts.set_calls.append(value)
            or setattr(service_opts, "current", value)
        ),
    )
    owned = _NamedProject(11, "Owned", owner_id=7, owner_name="alice")
    collab = _NamedProject(
        12,
        "Collab",
        owner_id=9,
        owner_name="bob",
        permissions=_Permissions(True, True),
    )

    def _get_objects(model, opts=None):
        assert model == "Project"
        if opts is None and service_opts.current == "-1":
            raise RuntimeError("cross-group query failed")
        if opts == {"group": "-1"}:
            return iter([owned, collab])
        raise RuntimeError("unexpected path")

    conn = SimpleNamespace(SERVICE_OPTS=service_opts, getObjects=_get_objects)
    payload = core_functions._collect_project_payload(conn, user_id=7)

    assert payload == {
        "owned": [{"id": "11", "name": "Owned"}],
        "collab": [{"id": "12", "name": "Collab", "owner": "bob"}],
    }
    assert service_opts.set_calls == ["-1", "5"]

    fallback_conn = SimpleNamespace(
        SERVICE_OPTS=service_opts,
        getObjects=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        listProjects=lambda: ["project-a"],
    )
    assert list(core_functions._iter_accessible_projects(fallback_conn)) == [
        "project-a"
    ]


def test_dataset_target_helpers_cover_existing_new_and_planned_units(
    monkeypatch,
) -> None:
    project = _NamedProject(
        3,
        "Project",
        children=[_DatasetChild(41, "Other"), _DatasetChild(42, "Target")],
    )

    class _NewDataset:
        def __init__(self):
            self.name = None

        def setName(self, value):
            self.name = value

    monkeypatch.setattr(core_functions, "DatasetI", _NewDataset)
    monkeypatch.setattr(core_functions, "rstring", lambda value: value)
    monkeypatch.setattr(
        core_functions.settings, "OMERO_HOST", "fallback-host", raising=False
    )
    monkeypatch.setattr(core_functions.settings, "OMERO_PORT", "4064", raising=False)

    update_service = SimpleNamespace(
        saveAndReturnObject=lambda dataset: SimpleNamespace(getId=lambda: _Value(77))
    )

    def _get_objects(model, *args, **kwargs):
        if model == "Dataset":
            name = kwargs.get("attributes", {}).get("name")
            if name == "Existing":
                return iter([_ExistingDataset(55)])
            return iter([])
        raise AssertionError(f"unexpected model lookup: {model}")

    conn = SimpleNamespace(
        getObject=lambda model, project_id: (
            project if (model, project_id) == ("Project", 3) else None
        ),
        getObjects=_get_objects,
        getUpdateService=lambda: update_service,
        SERVICE_OPTS=SimpleNamespace(),
    )

    dataset_map = {}
    assert core_functions._find_project_dataset(conn, 3, "Target") == 42
    assert core_functions._get_or_create_dataset(conn, "Target", dataset_map, 3) == 42
    assert core_functions._get_or_create_dataset(conn, "Existing", dataset_map) == 55
    assert core_functions._get_or_create_dataset(conn, "Fresh", dataset_map) == 77
    assert dataset_map == {"Target": 42, "Existing": 55, "Fresh": 77}
    assert core_functions._resolve_omero_host_port(
        SimpleNamespace(host=None, port="bad")
    ) == ("fallback-host", None)
    assert (
        core_functions._get_session_key(
            SimpleNamespace(getSessionId=lambda: "session-123")
        )
        == "session-123"
    )

    monkeypatch.setattr(
        core_functions, "_generate_orphan_dataset_name", lambda: "UploadRoot_TEST"
    )
    orphan_dataset_name, dataset_names = core_functions._plan_job_dataset_targets(
        {"orphan_dataset_name": None},
        [
            {"relative_path": "top-level.ome.tif"},
            {"relative_path": "folder/sample.ome.tif"},
        ],
    )
    assert orphan_dataset_name == "UploadRoot_TEST"
    assert dataset_names == ["UploadRoot_TEST", "folder"]

    valid_unit = {
        "relative_path": "bundle/data.bin",
        "dataset_relative_path": "bundle/data.bin",
        "covered_relative_paths": ["bundle/data.bin", "bundle/meta.json"],
        "group_header_name": "bundle",
    }
    assert core_functions._serialize_import_unit_plan(valid_unit) == valid_unit
    assert core_functions._serialize_import_unit_plan({"relative_path": ""}) is None

    planned_job = {
        "planned_import_units": [valid_unit, valid_unit, {"relative_path": "missing"}],
        "files": [
            {"relative_path": "bundle/data.bin"},
            {"relative_path": "bundle/meta.json"},
            {"relative_path": "skip.bin", "import_skip": True},
        ],
    }
    assert core_functions._planned_import_units_for_request(planned_job) == [valid_unit]
    assert core_functions._plan_request_job_dataset_targets(planned_job) == (
        None,
        ["bundle"],
    )


def test_request_path_dataset_preparation_covers_success_and_failure(
    monkeypatch,
) -> None:
    group_calls = []

    class _Conn:
        SERVICE_OPTS = SimpleNamespace(
            setOmeroGroup=lambda value: group_calls.append(value)
        )

    monkeypatch.setattr(core_functions, "_save_job", lambda job: True)
    monkeypatch.setattr(
        core_functions,
        "_get_or_create_dataset",
        lambda conn, name, dataset_map, project_id=None: dataset_map.setdefault(
            name, 21
        ),
    )

    job = {
        "job_id": "f" * 32,
        "group_id": 4,
        "project_id": 9,
        "dataset_map": {},
        "orphan_dataset_name": None,
        "planned_import_units": [
            {
                "relative_path": "bundle/data.bin",
                "dataset_relative_path": "bundle/data.bin",
                "covered_relative_paths": ["bundle/data.bin"],
            }
        ],
        "files": [{"relative_path": "bundle/data.bin"}],
    }

    prepared_job, error = core_functions._prepare_request_job_import_datasets(
        job["job_id"],
        job,
        conn=_Conn(),
    )

    assert prepared_job is job
    assert error is None
    assert group_calls == ["4"]
    assert job["dataset_map"] == {"bundle": 21}

    monkeypatch.setattr(
        core_functions,
        "_get_or_create_dataset",
        lambda conn, name, dataset_map, project_id=None: None,
    )
    failed_job, failed_error = core_functions._prepare_request_job_import_datasets(
        "g" * 32,
        {
            "job_id": "g" * 32,
            "group_id": 4,
            "project_id": 9,
            "dataset_map": {},
            "files": [{"relative_path": "folder/sample.ome.tif"}],
        },
        conn=_Conn(),
    )
    assert failed_job is None
    assert failed_error == import_errors.unable_prepare_import_destination()

    monkeypatch.setattr(
        core_functions,
        "_prepare_request_job_import_datasets",
        lambda job_id, job_dict, conn=None: (job_dict, None),
    )
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: {"job_id": job_id})
    monkeypatch.setattr(
        core_functions,
        "_start_compatibility_check_thread",
        lambda job_id: saved.setdefault("compat", job_id),
    )
    saved = {}
    checking_job, checking_error = (
        core_functions._prepare_uploaded_job_for_request_path_import(
            "h" * 32,
            {
                "job_id": "h" * 32,
                "status": "checking",
                "compatibility_enabled": True,
                "compatibility_thread_active": True,
                "files": [{"relative_path": "bundle/data.bin"}],
            },
            conn=_Conn(),
        )
    )
    assert checking_job["job_id"] == "h" * 32
    assert checking_error is None
