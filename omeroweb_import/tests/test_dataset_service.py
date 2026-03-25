from __future__ import annotations

from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from omeroweb_import.services.omero import dataset_service


class _FakeValue:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _FakeDatasetI:
    def __init__(self, dataset_id=None, _loaded=True):
        self._id = dataset_id
        self.name = None

    def setName(self, value):
        self.name = value

    def getId(self):
        return _FakeValue(self._id)


class _FakeProjectI:
    def __init__(self, project_id, _loaded):
        self.project_id = project_id


class _FakeProjectDatasetLinkI:
    def __init__(self):
        self.parent = None
        self.child = None

    def setParent(self, parent):
        self.parent = parent

    def setChild(self, child):
        self.child = child


class _FakeDatasetChild:
    def __init__(self, dataset_id, name):
        self.id = dataset_id
        self._name = name

    def getName(self):
        return self._name


class _FakeProject:
    def __init__(
        self,
        project_id,
        name,
        *,
        owner_id=None,
        can_write=False,
        owner_name=None,
        children=None,
    ):
        self.id = project_id
        self._name = name
        self.owner_id = owner_id
        self.can_write = can_write
        self.owner_name = owner_name
        self._children = list(children or [])

    def getName(self):
        return self._name

    def listChildren(self):
        return list(self._children)


class _FakeExistingDataset:
    def __init__(self, dataset_id, *, expose_id=True):
        self.id = dataset_id if expose_id else None
        self._dataset_id = dataset_id

    def getId(self):
        return _FakeValue(self._dataset_id)


class _FakeUpdateService:
    def __init__(self):
        self.saved_links = []
        self.saved_datasets = []

    def saveAndReturnObject(self, obj):
        if isinstance(obj, _FakeDatasetI):
            if obj._id is None:
                obj._id = 77
            self.saved_datasets.append(obj)
            return obj
        self.saved_links.append(obj)
        return obj


class _FakeSecrets:
    def __init__(self, values):
        self._values = iter(values)

    def choice(self, _alphabet):
        return next(self._values)


class _FakeServiceOpts:
    def __init__(self, *, group="5", fail_get=False):
        self.group = group
        self.fail_get = fail_get
        self.set_calls = []

    def getOmeroGroup(self):
        if self.fail_get:
            raise RuntimeError("cannot read group")
        return self.group

    def setOmeroGroup(self, value):
        self.set_calls.append(value)


@pytest.fixture()
def dataset_module(monkeypatch):
    monkeypatch.setattr(dataset_service, "PurePosixPath", PurePosixPath, raising=False)
    monkeypatch.setattr(dataset_service, "secrets", _FakeSecrets("ABCD"), raising=False)
    monkeypatch.setattr(dataset_service, "ORPHAN_SUFFIX_ALPHANUM", "ABCDEF", raising=False)
    monkeypatch.setattr(dataset_service, "ORPHAN_SUFFIX_LENGTH", 4, raising=False)
    monkeypatch.setattr(dataset_service, "ORPHAN_DATASET_PREFIX", "UploadRoot", raising=False)
    monkeypatch.setattr(dataset_service, "OMERO_CLI", "/usr/bin/omero", raising=False)
    monkeypatch.setattr(
        dataset_service,
        "settings",
        SimpleNamespace(OMERO_HOST="fallback-host", OMERO_PORT="4064"),
        raising=False,
    )
    monkeypatch.setattr(dataset_service, "_get_id", lambda obj: getattr(obj, "id", None), raising=False)
    monkeypatch.setattr(dataset_service, "_get_text", lambda value: value, raising=False)
    monkeypatch.setattr(
        dataset_service,
        "_is_owned_by_user",
        lambda proj, user_id: getattr(proj, "owner_id", None) == user_id,
        raising=False,
    )
    monkeypatch.setattr(
        dataset_service,
        "_has_read_write_permissions",
        lambda proj: getattr(proj, "can_write", False),
        raising=False,
    )
    monkeypatch.setattr(
        dataset_service,
        "_get_owner_username",
        lambda proj: getattr(proj, "owner_name", None),
        raising=False,
    )
    monkeypatch.setattr(dataset_service, "DatasetI", _FakeDatasetI, raising=False)
    monkeypatch.setattr(
        dataset_service,
        "ProjectDatasetLinkI",
        _FakeProjectDatasetLinkI,
        raising=False,
    )
    monkeypatch.setattr(dataset_service, "ProjectI", _FakeProjectI, raising=False)
    monkeypatch.setattr(dataset_service, "rstring", lambda value: value, raising=False)
    return dataset_service


def test_collect_project_payload_separates_owned_and_collaborative_projects(dataset_module, monkeypatch):
    monkeypatch.setattr(
        dataset_module,
        "_iter_accessible_projects",
        lambda conn: iter(
            [
                _FakeProject(11, "Owned", owner_id=7),
                _FakeProject(12, "Shared", can_write=True, owner_name="bob"),
                _FakeProject(13, "ReadOnly", can_write=False, owner_name="carol"),
                _FakeProject(None, "MissingId", owner_id=7),
            ]
        ),
    )

    payload = dataset_module._collect_project_payload(conn=object(), user_id=7)

    assert payload == {
        "owned": [{"id": "11", "name": "Owned"}],
        "collab": [{"id": "12", "name": "Shared", "owner": "bob"}],
    }


def test_collect_project_payload_hides_iteration_failures(dataset_module, monkeypatch):
    def _boom(_conn):
        raise RuntimeError("listing failed")

    monkeypatch.setattr(dataset_module, "_iter_accessible_projects", _boom)

    assert dataset_module._collect_project_payload(conn=object(), user_id=1) == {
        "owned": [],
        "collab": [],
    }


def test_dataset_name_helpers_and_orphan_generation_follow_upload_contract(dataset_module, monkeypatch):
    monkeypatch.setattr(dataset_module, "secrets", _FakeSecrets("WXYZ"), raising=False)

    assert dataset_module._dataset_name_for_path("image.ome.tif", "UploadRoot_TEST") == "UploadRoot_TEST"
    assert dataset_module._dataset_name_for_path("dataset/subdir/image.ome.tif") == "dataset\\subdir"
    assert dataset_module._generate_orphan_dataset_name() == "UploadRoot_WXYZ"


def test_find_project_dataset_and_link_dataset_cover_success_and_failures(dataset_module):
    project = _FakeProject(
        3,
        "Project",
        children=[_FakeDatasetChild(41, "Other"), _FakeDatasetChild(42, "Target")],
    )
    update_service = _FakeUpdateService()
    conn = SimpleNamespace(
        getObject=lambda model, project_id: project if (model, project_id) == ("Project", 3) else None,
        getUpdateService=lambda: update_service,
    )

    assert dataset_module._find_project_dataset(conn, 3, "Target") == 42
    assert dataset_module._find_project_dataset(conn, 0, "Target") is None
    assert dataset_module._find_project_dataset(conn, 3, "") is None
    assert dataset_module._link_dataset_to_project(conn, 21, 3) is True
    assert isinstance(update_service.saved_links[0], _FakeProjectDatasetLinkI)
    assert update_service.saved_links[0].parent.project_id == 3
    assert update_service.saved_links[0].child._id == 21
    assert dataset_module._link_dataset_to_project(conn, 0, 3) is False


def test_find_project_dataset_returns_none_when_project_lookup_or_listing_fails(dataset_module):
    lookup_conn = SimpleNamespace(getObject=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert dataset_module._find_project_dataset(lookup_conn, 3, "Target") is None

    project = _FakeProject(3, "Project")
    project.listChildren = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    list_conn = SimpleNamespace(getObject=lambda *_args, **_kwargs: project)
    assert dataset_module._find_project_dataset(list_conn, 3, "Target") is None


def test_link_dataset_to_project_returns_false_when_update_service_raises(dataset_module):
    conn = SimpleNamespace(
        getUpdateService=lambda: SimpleNamespace(
            saveAndReturnObject=lambda _obj: (_ for _ in ()).throw(RuntimeError("cannot link"))
        )
    )

    assert dataset_module._link_dataset_to_project(conn, 21, 3) is False


def test_resolve_host_port_and_get_session_key_use_connection_first_then_settings(dataset_module, monkeypatch):
    monkeypatch.setattr(
        dataset_module,
        "settings",
        SimpleNamespace(OMERO_HOST="settings-host", OMERO_PORT="bad-port"),
        raising=False,
    )

    assert dataset_module._resolve_omero_host_port(
        SimpleNamespace(host="omero.example.org", port="4065")
    ) == ("omero.example.org", 4065)
    assert dataset_module._resolve_omero_host_port(SimpleNamespace(_host=None, _port=None)) == (
        "settings-host",
        None,
    )

    assert dataset_module._get_session_key(SimpleNamespace(getSessionId=lambda: "session-1")) == "session-1"
    assert dataset_module._get_session_key(
        SimpleNamespace(getSessionId=lambda: (_ for _ in ()).throw(RuntimeError("expired")), _sessionUuid="uuid-2")
    ) is None
    assert dataset_module._get_session_key(SimpleNamespace(_session="legacy-session")) == "legacy-session"
    assert dataset_module._get_session_key(SimpleNamespace()) is None


def test_get_or_create_dataset_prefers_cache_project_matches_existing_objects_and_creation(
    dataset_module,
    monkeypatch,
):
    update_service = _FakeUpdateService()
    linked = []

    monkeypatch.setattr(
        dataset_module,
        "_link_dataset_to_project",
        lambda conn, dataset_id, project_id: linked.append((dataset_id, project_id)) or True,
    )

    dataset_map = {"Cached": 10}
    conn = SimpleNamespace(getUpdateService=lambda: update_service)
    assert dataset_module._get_or_create_dataset(conn, "Cached", dataset_map, project_id=9) == 10
    assert linked == []

    dataset_map = {}
    monkeypatch.setattr(dataset_module, "_find_project_dataset", lambda *_args, **_kwargs: 11)
    conn = SimpleNamespace(getUpdateService=lambda: update_service)
    assert dataset_module._get_or_create_dataset(conn, "ExistingProjectDataset", dataset_map, project_id=9) == 11
    assert dataset_map["ExistingProjectDataset"] == 11

    monkeypatch.setattr(dataset_module, "_find_project_dataset", lambda *_args, **_kwargs: None)
    dataset_map = {}
    conn = SimpleNamespace(
        getObjects=lambda model, attributes=None: iter([_FakeExistingDataset(12, expose_id=False)]),
        getUpdateService=lambda: update_service,
    )
    assert dataset_module._get_or_create_dataset(conn, "SharedDataset", dataset_map, project_id=9) == 12
    assert linked[-1] == (12, 9)

    dataset_map = {}
    conn = SimpleNamespace(
        getObjects=lambda *_args, **_kwargs: iter([]),
        getUpdateService=lambda: update_service,
    )
    assert dataset_module._get_or_create_dataset(conn, "NewDataset", dataset_map, project_id=9) == 77
    assert dataset_map["NewDataset"] == 77
    assert update_service.saved_datasets[-1].name == "NewDataset"
    assert linked[-1] == (77, 9)


def test_get_or_create_dataset_returns_none_for_missing_name_and_create_failures(dataset_module, monkeypatch):
    assert dataset_module._get_or_create_dataset(conn=object(), name="", dataset_map={}) is None

    monkeypatch.setattr(dataset_module, "_find_project_dataset", lambda *_args, **_kwargs: None)
    conn = SimpleNamespace(
        getObjects=lambda *_args, **_kwargs: iter([]),
        getUpdateService=lambda: SimpleNamespace(
            saveAndReturnObject=lambda _obj: (_ for _ in ()).throw(RuntimeError("cannot create"))
        ),
    )

    assert dataset_module._get_or_create_dataset(conn, "BrokenDataset", {}, project_id=9) is None


def test_build_omero_cli_command_places_connection_flags_before_subcommand(dataset_module):
    assert dataset_module._build_omero_cli_command(
        ["import", "/tmp/file.ome.tif"],
        session_key="session-1",
        host="omero.example.org",
        port=4064,
    ) == [
        "/usr/bin/omero",
        "-k",
        "session-1",
        "-s",
        "omero.example.org",
        "-p",
        "4064",
        "import",
        "/tmp/file.ome.tif",
    ]


def test_iter_accessible_projects_uses_cross_group_then_opts_then_fallbacks(dataset_module):
    first_opts = _FakeServiceOpts(group="5")
    first_conn = SimpleNamespace(
        SERVICE_OPTS=first_opts,
        getObjects=lambda model, opts=None: iter([_FakeProject(1, "CrossGroup")]),
        listProjects=lambda: iter(()),
    )
    assert [proj.id for proj in dataset_module._iter_accessible_projects(first_conn)] == [1]
    assert first_opts.set_calls == ["-1", "5"]

    second_opts = _FakeServiceOpts(group="7")

    def _second_get_objects(model, opts=None):
        if opts is None:
            raise RuntimeError("cross-group query failed")
        return iter([_FakeProject(2, "OptsFallback")])

    second_conn = SimpleNamespace(
        SERVICE_OPTS=second_opts,
        getObjects=_second_get_objects,
        listProjects=lambda: iter(()),
    )
    assert [proj.id for proj in dataset_module._iter_accessible_projects(second_conn)] == [2]
    assert second_opts.set_calls == ["-1", "7"]

    third_opts = _FakeServiceOpts(fail_get=True)
    state = {"calls": 0}

    def _third_get_objects(model, opts=None):
        state["calls"] += 1
        raise RuntimeError(f"query failed {state['calls']}")

    third_conn = SimpleNamespace(
        SERVICE_OPTS=third_opts,
        getObjects=_third_get_objects,
        listProjects=lambda: iter([_FakeProject(3, "ListProjectsFallback")]),
    )
    assert [proj.id for proj in dataset_module._iter_accessible_projects(third_conn)] == [3]
    assert third_opts.set_calls == ["-1"]
