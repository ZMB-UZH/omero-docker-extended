from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from django.test import RequestFactory

from omeroweb_omp_plugin.views import index_view


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _Owner:
    def __init__(self, owner_id, name="owner"):
        self._id = owner_id
        self._name = name

    def getId(self):
        return _Value(self._id)

    def getOmeName(self):
        return self._name


class _Permissions:
    def __init__(
        self,
        label,
        *,
        read=True,
        write=False,
        annotate=False,
        group_read=True,
        group_write=False,
        group_annotate=False,
    ):
        self._label = label
        self._read = read
        self._write = write
        self._annotate = annotate
        self._group_read = group_read
        self._group_write = group_write
        self._group_annotate = group_annotate

    def __str__(self):
        return self._label

    def isRead(self):
        return self._read

    def isWrite(self):
        return self._write

    def isAnnotate(self):
        return self._annotate

    def canAnnotate(self):
        return self._annotate

    def isGroupRead(self):
        return self._group_read

    def isGroupWrite(self):
        return self._group_write

    def isGroupAnnotate(self):
        return self._group_annotate


class _Details:
    def __init__(self, *, owner=None, permissions=None, group=None):
        self._owner = owner
        self._permissions = permissions
        self._group = group

    def getOwner(self):
        return self._owner

    def getPermissions(self):
        return self._permissions

    def getGroup(self):
        return self._group


class _Group:
    def __init__(self, group_id, permissions, member_count=1):
        self.id = group_id
        self._permissions = permissions
        self._member_count = member_count
        self._details = _Details(permissions=permissions)

    def getId(self):
        return _Value(self.id)

    def getDetails(self):
        return self._details

    def getPermissions(self):
        return self._permissions

    def getMemberCount(self):
        return self._member_count


class _Project:
    def __init__(self, project_id, name, *, owner=None, permissions=None, group=None):
        self.id = project_id
        self._name = name
        self._owner = owner
        self._permissions = permissions
        self._group = group
        self._details = _Details(
            owner=owner,
            permissions=permissions,
            group=group,
        )

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return self._name

    def getDetails(self):
        return self._details

    def getOwner(self):
        return self._owner

    def getPermissions(self):
        return self._permissions


class _Dataset:
    def __init__(self, dataset_id, name):
        self.id = dataset_id
        self._name = name

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return self._name


class _ImageObject:
    def __init__(self, image_id, name):
        self.id = image_id
        self._name = name

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return self._name


class _BrokenProject(_Project):
    def getDetails(self):
        raise RuntimeError("details unavailable")


class _ServiceOpts:
    def __init__(self, initial_group="4"):
        self.current_group = initial_group
        self.set_calls = []

    def getOmeroGroup(self):
        return self.current_group

    def setOmeroGroup(self, value):
        self.set_calls.append(value)
        self.current_group = value


class _Conn:
    def __init__(self, user_id=10, username="alice"):
        self.SERVICE_OPTS = _ServiceOpts()
        self._user = SimpleNamespace(
            getId=lambda: _Value(user_id),
            getName=lambda: username,
            getGroups=lambda: [],
        )
        self.projects = []
        self.list_projects = []
        self.groups = []
        self.members_by_group = {}
        self.project_by_id = {}
        self.raise_all_groups = False
        self.raise_opts_groups = False

    def getUser(self):
        return self._user

    def getGroupsMemberOf(self):
        return list(self.groups)

    def getObjects(self, object_type, opts=None):
        if object_type == "Project":
            if opts == {"group": "-1"}:
                if self.raise_opts_groups:
                    raise RuntimeError("opts failed")
                return iter(self.projects)
            if self.SERVICE_OPTS.current_group == "-1":
                if self.raise_all_groups:
                    raise RuntimeError("all groups failed")
                return iter(self.projects)
            return iter(self.list_projects)
        if object_type == "Experimenter":
            return iter(self.members_by_group.get(opts["group"], []))
        raise AssertionError(f"Unexpected object request: {object_type}")

    def listProjects(self):
        return list(self.list_projects)

    def getObject(self, object_type, object_id):
        assert object_type == "Project"
        return self.project_by_id.get(int(object_id))


def _json_payload(response):
    return json.loads(response.content.decode("utf-8"))


def test_owner_and_permission_helpers_use_fallback_accessors():
    owner = _Owner(7, "alice")
    read_write = _Permissions("rwrw--", read=True, write=True)
    read_annotate = _Permissions(
        "rwra--",
        read=True,
        write=False,
        annotate=True,
        group_read=True,
        group_write=False,
        group_annotate=True,
    )
    broken = _BrokenProject(1, "Broken", owner=owner, permissions=read_write)
    annotate_project = _Project(
        2,
        "Annotate",
        owner=owner,
        permissions=read_annotate,
    )

    assert index_view._get_owner_id(broken) == 7
    assert index_view._is_owned_by_user(broken, 7) is True
    assert index_view._get_owner_username(broken) == "alice"
    assert index_view._has_read_write_permissions(broken) is True
    assert index_view._has_read_annotate_permissions(annotate_project) is True


def test_iter_accessible_projects_restores_group_after_fallback():
    conn = _Conn()
    project = _Project(1, "Fallback")
    conn.projects = [project]
    conn.raise_all_groups = True

    projects = list(index_view._iter_accessible_projects(conn))

    assert projects == [project]
    assert conn.SERVICE_OPTS.set_calls == ["-1", "4"]
    assert conn.SERVICE_OPTS.current_group == "4"


def test_group_helpers_detect_collaboration_modes_and_membership():
    conn = _Conn()
    rw_group = _Group(1, _Permissions("rwrw--", group_read=True, group_write=True), 3)
    ra_group = _Group(
        2,
        _Permissions(
            "rwra--",
            group_read=True,
            group_write=False,
            group_annotate=True,
        ),
        2,
    )
    conn.groups = [rw_group, ra_group]
    conn.members_by_group = {"3": [object(), object(), object(), object()]}

    count_from_members = index_view._group_member_count(
        conn,
        SimpleNamespace(
            getId=lambda: _Value(3),
            getMemberCount=lambda: (_ for _ in ()).throw(RuntimeError("no count")),
            getMembers=lambda: (_ for _ in ()).throw(RuntimeError("no members")),
            getExperimenters=lambda: (_ for _ in ()).throw(RuntimeError("no exp")),
            getExperimenterIds=lambda: (_ for _ in ()).throw(RuntimeError("no ids")),
        ),
    )

    assert index_view._group_is_read_write(rw_group) is True
    assert index_view._group_is_read_annotate(ra_group) is True
    assert index_view._group_has_other_members(conn, rw_group) is True
    assert index_view._has_collaboration_groups(conn) is True
    assert index_view._is_user_in_group(conn, 2, 10) is True
    assert count_from_members == 4


def test_collect_project_payload_separates_owned_and_collaboration_projects(
    monkeypatch,
):
    conn = _Conn()
    owner = _Owner(10, "alice")
    other_owner = _Owner(11, "bob")
    rw_group = _Group(1, _Permissions("rwrw--", group_read=True, group_write=True), 3)
    ra_group = _Group(
        2,
        _Permissions(
            "rwra--",
            group_read=True,
            group_write=False,
            group_annotate=True,
        ),
        2,
    )
    private_group = _Group(3, _Permissions("rw----", group_read=True), 1)
    owned = _Project(1, "Owned", owner=owner, group=private_group)
    collab = _Project(2, "Collab", owner=other_owner, group=rw_group)
    annotate = _Project(3, "Annotate", owner=other_owner, group=ra_group)
    hidden = _Project(4, "Hidden", owner=other_owner, group=private_group)
    conn.groups = [rw_group, ra_group]

    monkeypatch.setattr(
        index_view,
        "_iter_accessible_projects",
        lambda current_conn: [owned, collab, annotate, hidden],
    )
    monkeypatch.setattr(
        index_view, "_has_collaboration_groups", lambda current_conn: True
    )

    payload = index_view._collect_project_payload(conn, 10)

    assert payload["owned"] == [{"id": "1", "name": "Owned"}]
    assert payload["collab"] == [
        {"id": "2", "name": "Collab", "owner": "bob", "access": "read_write"}
    ]
    assert payload["collab_annotate"] == [
        {"id": "3", "name": "Annotate", "owner": "bob", "access": "read_annotate"}
    ]
    assert payload["collab_available"] is True


def test_get_accessible_project_returns_expected_access_levels():
    conn = _Conn()
    owner = _Owner(10, "alice")
    other_owner = _Owner(11, "bob")
    rw_group = _Group(1, _Permissions("rwrw--", group_read=True, group_write=True), 2)
    owned = _Project(1, "Owned", owner=owner, group=rw_group)
    collab = _Project(2, "Collab", owner=other_owner, group=rw_group)
    conn.project_by_id = {1: owned, 2: collab}
    conn.groups = [rw_group]

    assert index_view._get_accessible_project(conn, "1", 10) == (owned, "owned")
    assert index_view._get_accessible_project(conn, "2", 10) == (collab, "read_write")
    assert index_view._get_accessible_project(conn, "99", 10) == (None, None)


def test_index_list_datasets_requires_project_and_uses_owner_filter(monkeypatch):
    factory = RequestFactory()
    request = factory.post("/", data={"action": "list_datasets", "project": "5"})
    conn = _Conn()
    datasets = [{"id": 8, "name": "Dataset"}]
    captured = {}

    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    monkeypatch.setattr(
        index_view,
        "collect_dataset_summaries",
        lambda current_conn, project_id, owner_id=None: (
            captured.update({"project_id": project_id, "owner_id": owner_id})
            or datasets
        ),
    )

    response = inspect.unwrap(index_view.index)(request, conn=conn)

    assert _json_payload(response) == {"datasets": datasets}
    assert captured == {"project_id": "5", "owner_id": 10}


def test_index_ai_regex_returns_local_suggestion(monkeypatch):
    factory = RequestFactory()
    request = factory.post(
        "/",
        data={
            "action": "ai_regex",
            "project": "5",
            "selected_datasets": "10,11",
            "provider": "local",
        },
    )
    conn = _Conn()
    images = [SimpleNamespace(getName=lambda: "sample_A-01.tif")]

    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [(SimpleNamespace(), images)],
    )
    monkeypatch.setattr(
        index_view, "_suggest_separator_regex", lambda filenames: r"[-_]"
    )

    response = inspect.unwrap(index_view.index)(request, conn=conn)

    assert _json_payload(response) == {"regex": r"[-_]", "source": "local"}


def test_index_ai_parse_attaches_image_ids(monkeypatch):
    factory = RequestFactory()
    request = factory.post(
        "/",
        data={
            "action": "ai_parse",
            "project": "5",
            "selected_datasets": "10",
            "provider": "openai",
            "model": "gpt-5.4",
        },
    )
    conn = _Conn()
    image = _ImageObject(17, "sample_A-01.tif")

    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [(SimpleNamespace(), [image])],
    )
    monkeypatch.setattr(index_view, "get_ai_credential", lambda *_args: "api-key")
    monkeypatch.setattr(
        index_view,
        "generate_ai_parsed_values",
        lambda *_args, **_kwargs: {
            "rows": [{"values": ["sample", "A", "01"]}],
            "source": "ai",
        },
    )

    response = inspect.unwrap(index_view.index)(request, conn=conn)

    assert _json_payload(response) == {
        "rows": [{"img_id": 17, "values": ["sample", "A", "01"]}],
        "source": "ai",
    }


def test_index_preview_renders_rows_and_caps_variables(monkeypatch):
    factory = RequestFactory()
    request = factory.post(
        "/",
        data={
            "project": "5",
            "selected_datasets": "10",
            "separator_mode": "chars",
            "separator": "_-",
            "user_chunk_size": "7",
            "user_max_parsed": "2",
            "user_max_sets": "9",
        },
    )
    conn = _Conn()
    dataset = _Dataset(10, "Dataset")
    image = _ImageObject(17, "sample_A-01.tif")
    rendered = {}

    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [(dataset, [image])],
    )
    monkeypatch.setattr(
        index_view, "parse_filename", lambda *_args: ["sample", "A", "01"]
    )
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context=None, status=200: (
            rendered.update(
                {"template": template, "context": context, "status": status}
            )
            or rendered
        ),
    )

    response = inspect.unwrap(index_view.index)(request, conn=conn)

    assert response["template"] == "omeroweb_omp_plugin/preview.html"
    assert rendered["context"]["preview_count"] == 1
    assert rendered["context"]["chunk_size"] == 7
    assert rendered["context"]["max_variable_sets"] == 9
    assert rendered["context"]["max_vars"] == 2
    assert rendered["context"]["vars_limit_exceeded"] is True
    assert rendered["context"]["preview_rows"][0]["filename"] == "sample_A-01.tif"


def test_list_projects_and_root_status_return_json(monkeypatch):
    factory = RequestFactory()
    conn = _Conn(username="root")
    monkeypatch.setattr(
        index_view,
        "_collect_project_payload",
        lambda *_args: {"owned": [{"id": "1", "name": "Project"}]},
    )

    projects_response = inspect.unwrap(index_view.list_projects)(
        factory.get("/"), conn=conn
    )
    root_response = inspect.unwrap(index_view.root_status)(factory.get("/"), conn=conn)

    assert _json_payload(projects_response) == {
        "owned": [{"id": "1", "name": "Project"}]
    }
    assert _json_payload(root_response) == {"is_root_user": True}
