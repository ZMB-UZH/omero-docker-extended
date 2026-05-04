from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from django.test import RequestFactory

from omeroweb_omp_plugin.views import index_view


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


class _Owner:
    """Test double for owner behavior in this module."""

    def __init__(self, owner_id, name="owner"):
        """Create `_Owner` with `owner_id` and `name`.

        Inputs: `owner_id`, `name`. Output: None.
        """
        self._id = owner_id
        self._name = name

    def getId(self):
        """Return `_Owner`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._id)

    def getOmeName(self):
        """Return the fake OMERO name.

        Inputs: none. Output: `self._name`.
        """
        return self._name


class _Permissions:
    """Test double for permissions behavior in this module."""

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
        """Create `_Permissions` with `label`.

        Inputs: `label`, `read`, `write`, `annotate`, `group_read`, `group_write`,
        `group_annotate`. Output: None.
        """
        self._label = label
        self._read = read
        self._write = write
        self._annotate = annotate
        self._group_read = group_read
        self._group_write = group_write
        self._group_annotate = group_annotate

    def __str__(self):
        """Return `_Permissions` as test-readable text.

        Inputs: none. Output: `self._label`.
        """
        return self._label

    def isRead(self):
        """Report the read boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `self._read`.
        """
        return self._read

    def isWrite(self):
        """Report the write boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `self._write`.
        """
        return self._write

    def isAnnotate(self):
        """Report the annotate boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `self._annotate`.
        """
        return self._annotate

    def canAnnotate(self):
        """Report the annotate boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `self._annotate`.
        """
        return self._annotate

    def isGroupRead(self):
        """Return whether `_Permissions` grants group-read access.

        Inputs: none. Output: `self._group_read`.
        """
        return self._group_read

    def isGroupWrite(self):
        """Return whether `_Permissions` grants group-write access.

        Inputs: none. Output: `self._group_write`.
        """
        return self._group_write

    def isGroupAnnotate(self):
        """Return whether `_Permissions` grants group-annotate access.

        Inputs: none. Output: `self._group_annotate`.
        """
        return self._group_annotate


class _Details:
    """Test double for details behavior in this module."""

    def __init__(self, *, owner=None, permissions=None, group=None):
        """Create `_Details` with its default state.

        Inputs: `owner`, `permissions`, `group`. Output: None.
        """
        self._owner = owner
        self._permissions = permissions
        self._group = group

    def getOwner(self):
        """Return the fake owner.

        Inputs: none. Output: `self._owner`.
        """
        return self._owner

    def getPermissions(self):
        """Return `_Details`'s fake permissions object.

        Inputs: none. Output: `self._permissions`.
        """
        return self._permissions

    def getGroup(self):
        """Return the group for `_Details`.

        Inputs: none. Output: `_group`.
        """
        return self._group


class _Group:
    """Test double for group behavior in this module."""

    def __init__(self, group_id, permissions, member_count=1):
        """Create `_Group` with `group_id`, `permissions`, and `member_count`.

        Inputs: `group_id`, `permissions`, `member_count`. Output: None.
        """
        self.id = group_id
        self._permissions = permissions
        self._member_count = member_count
        self._details = _Details(permissions=permissions)

    def getId(self):
        """Return `_Group`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getDetails(self):
        """Return the details for `_Group`.

        Inputs: none. Output: `_details`.
        """
        return self._details

    def getPermissions(self):
        """Return `_Group`'s fake permissions object.

        Inputs: none. Output: `self._permissions`.
        """
        return self._permissions

    def getMemberCount(self):
        """Return the fake member count value used by this test double.

        Inputs: none. Output: `self._member_count`.
        """
        return self._member_count


class _Project:
    """Test double for project behavior in this module."""

    def __init__(self, project_id, name, *, owner=None, permissions=None, group=None):
        """Create `_Project` with `project_id` and `name`.

        Inputs: `project_id`, `name`, `owner`, `permissions`, `group`. Output: None.
        """
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
        """Return `_Project`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_Project`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def getDetails(self):
        """Return the details for `_Project`.

        Inputs: none. Output: `_details`.
        """
        return self._details

    def getOwner(self):
        """Return the fake owner.

        Inputs: none. Output: `self._owner`.
        """
        return self._owner

    def getPermissions(self):
        """Return `_Project`'s fake permissions object.

        Inputs: none. Output: `self._permissions`.
        """
        return self._permissions


class _Dataset:
    """Test double for dataset behavior in this module."""

    def __init__(self, dataset_id, name):
        """Create `_Dataset` with `dataset_id` and `name`.

        Inputs: `dataset_id`, `name`. Output: None.
        """
        self.id = dataset_id
        self._name = name

    def getId(self):
        """Return `_Dataset`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_Dataset`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name


class _ImageObject:
    """Test double for image object behavior in this module."""

    def __init__(self, image_id, name):
        """Create `_ImageObject` with `image_id` and `name`.

        Inputs: `image_id`, `name`. Output: None.
        """
        self.id = image_id
        self._name = name

    def getId(self):
        """Return `_ImageObject`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_ImageObject`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name


class _BrokenProject(_Project):
    """Test double for broken project behavior in this module."""

    def getDetails(self):
        """Return the details for `_BrokenProject`.

        Inputs: caller provides no extra arguments. Output: returns the fake value described above.
        """
        raise RuntimeError("details unavailable")


class _ServiceOpts:
    """Test double for service opts behavior in this module."""

    def __init__(self, initial_group="4"):
        """Create `_ServiceOpts` with `initial_group`.

        Inputs: `initial_group`. Output: None.
        """
        self.current_group = initial_group
        self.set_calls = []

    def getOmeroGroup(self):
        """Return the fake omero group value used by this test double.

        Inputs: none. Output: `self.current_group`.
        """
        return self.current_group

    def setOmeroGroup(self, value):
        """Set the OMERO Group for `_ServiceOpts`.

        Inputs: `value` input value. Output: None.
        """
        self.set_calls.append(value)
        self.current_group = value


class _Conn:
    """Test double for conn behavior in this module."""

    def __init__(self, user_id=10, username="alice"):
        """Create `_Conn` with `user_id` and `username`.

        Inputs: `user_id`, `username`. Output: None.
        """
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
        """Return the fake user.

        Inputs: none. Output: `self._user`.
        """
        return self._user

    def getGroupsMemberOf(self):
        """Return the fake groups member of value used by this test double.

        Inputs: none. Output: `list` result.
        """
        return list(self.groups)

    def getObjects(self, object_type, opts=None):
        """Return the objects for `_Conn`.

        Inputs: `object_type`, `opts`. Output: `iter` result. Raises: AssertionError,
        RuntimeError when validation or the called operation fails.
        """
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
        """Return list projects.

        Inputs: none. Output: `list` result.
        """
        return list(self.list_projects)

    def getObject(self, object_type, object_id):
        """Return the object for `_Conn`.

        Inputs: `object_type`, `object_id`. Output: `get` result.
        """
        assert object_type == "Project"
        return self.project_by_id.get(int(object_id))


def _json_payload(response):
    """Return the JSON payload.

    Inputs: `response` response object. Output: `loads` result.
    """
    return json.loads(response.content.decode("utf-8"))


def test_owner_and_permission_helpers_use_fallback_accessors():
    """Verify the owner and permission helpers use fallback accessors safety boundary.

    Inputs: OMP service fakes. Output: fails on regressions when owner and permission helpers use fallback accessors accepts unsafe input.
    """
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
    """Verify iter accessible projects restores group after fallback.

    Inputs: OMP service fakes. Output: fails on regressions in iter accessible projects restores group after fallback.
    """
    conn = _Conn()
    project = _Project(1, "Fallback")
    conn.projects = [project]
    conn.raise_all_groups = True

    projects = list(index_view._iter_accessible_projects(conn))

    assert projects == [project]
    assert conn.SERVICE_OPTS.set_calls == ["-1", "4"]
    assert conn.SERVICE_OPTS.current_group == "4"


def test_group_helpers_detect_collaboration_modes_and_membership():
    """Verify group helpers detect collaboration modes and membership.

    Inputs: OMP service fakes. Output: fails on regressions in group helpers detect collaboration modes and membership.
    """
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
    """Verify collect project payload separates owned and collaboration projects result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in collect project payload separates owned and collaboration projects.
    """
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
    """Verify get accessible project returns expected access levels result shape.

    Inputs: OMP service fakes. Output: fails on regressions in get accessible project returns expected access levels.
    """
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
    """Verify index list datasets requires project and uses owner filter.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index list datasets requires project and uses owner filter.
    """
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
    """Verify index ai regex returns local suggestion result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index ai regex returns local suggestion.
    """
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
    """Verify index ai parse attaches image IDs.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index ai parse attaches image IDs.
    """
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
    """Check index preview renders rows and caps variables renders the expected surface.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index preview renders rows and caps variables.
    """
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
    """Verify list projects and root status return JSON.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in list projects and root status return JSON.
    """
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


def test_permission_and_group_helpers_support_attribute_style_wrappers():
    """Verify the permission and group helpers support attribute style wrappers safety boundary.

    Inputs: OMP service fakes. Output: fails on regressions when permission and group helpers support attribute style wrappers accepts unsafe input.
    """
    permissions = _Permissions("rwrw--", read=True, write=True)
    attr_owner = SimpleNamespace(
        getName="alice-property",
        getId=lambda: _Value(12),
    )
    attr_project = SimpleNamespace(
        getDetails=lambda: None,
        permissions=permissions,
        getOwner=lambda: attr_owner,
    )
    attr_group = SimpleNamespace(
        getMemberCount=lambda: _Value(3),
        getDetails=lambda: None,
        getPermissions=lambda: permissions,
        getId=lambda: _Value(9),
    )

    assert index_view._get_permissions(attr_project) is permissions
    assert index_view._has_read_write_permissions(attr_project) is True
    assert index_view._get_owner_username(attr_project) == "alice-property"
    assert index_view._group_member_count(_Conn(), attr_group) == 3


def test_index_ai_regex_remote_paths_cover_credential_and_provider_failures(
    monkeypatch,
):
    """Verify index ai regex remote paths cover credential and provider failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index ai regex remote paths cover credential and provider failures.
    """
    factory = RequestFactory()
    request = factory.post(
        "/",
        data={
            "action": "ai_regex",
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

    monkeypatch.setattr(index_view, "current_username", lambda *_args: "")
    response = inspect.unwrap(index_view.index)(request, conn=conn)
    assert response.status_code == 400
    assert (
        _json_payload(response)["error"]
        == index_view.errors.unable_to_determine_username()
    )

    monkeypatch.setattr(index_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(index_view, "get_ai_credential", lambda *_args: "")
    response = inspect.unwrap(index_view.index)(request, conn=conn)
    assert response.status_code == 400
    assert _json_payload(response)["error"] == index_view.errors.ai_api_key_required()

    monkeypatch.setattr(
        index_view,
        "get_ai_credential",
        lambda *_args: (_ for _ in ()).throw(
            index_view.AiCredentialStoreError("backend unavailable")
        ),
    )
    response = inspect.unwrap(index_view.index)(request, conn=conn)
    assert response.status_code == 500
    assert (
        _json_payload(response)["error"]
        == index_view.errors.ai_credentials_fetch_failed()
    )

    monkeypatch.setattr(index_view, "get_ai_credential", lambda *_args: "api-key")
    monkeypatch.setattr(
        index_view,
        "generate_ai_regex",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            index_view.AiAssistError("provider rejected")
        ),
    )
    response = inspect.unwrap(index_view.index)(request, conn=conn)
    assert response.status_code == 400
    assert (
        _json_payload(response)["error"]
        == index_view.errors.unable_to_process_filenames()
    )

    monkeypatch.setattr(
        index_view,
        "generate_ai_regex",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    response = inspect.unwrap(index_view.index)(request, conn=conn)
    assert response.status_code == 500
    assert (
        _json_payload(response)["error"]
        == index_view.errors.unable_to_process_filenames()
    )


def test_index_ai_parse_validates_provider_inputs_and_rate_limits(monkeypatch):
    """Verify index ai parse validates provider inputs and rate limits.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index ai parse validates provider inputs and rate limits.
    """
    conn = _Conn()
    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )

    # Local provider is accepted (routes to Ollama) but fails when no
    # filenames are available from the selected datasets.
    local_provider = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "local",
            },
        ),
        conn=conn,
    )
    assert local_provider.status_code == 400
    assert (
        _json_payload(local_provider)["error"]
        == index_view.errors.no_filenames_available()
    )

    missing_datasets = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "x",
                "provider": "openai",
            },
        ),
        conn=conn,
    )
    assert missing_datasets.status_code == 400
    assert (
        _json_payload(missing_datasets)["error"]
        == index_view.errors.datasets_required()
    )

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (False, 17)
    )
    rate_limited = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "openai",
            },
        ),
        conn=conn,
    )
    assert rate_limited.status_code == 429
    assert _json_payload(rate_limited)["error"] == index_view.build_rate_limit_message(
        17
    )


def test_index_preview_rejects_invalid_ai_payloads_regexes_and_empty_results(
    monkeypatch,
):
    """Confirm index preview rejects invalid ai payloads regexes and empty results is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index preview rejects invalid ai payloads regexes and empty results.
    """
    conn = _Conn()
    rendered = {}

    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    monkeypatch.setattr(index_view, "reverse", lambda name: "/omp/projects/")
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context=None, status=200: (
            rendered.update(
                {"template": template, "context": context or {}, "status": status}
            )
            or rendered.copy()
        ),
    )

    missing_ai_payload = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "ai_parse",
            },
        ),
        conn=conn,
    )
    assert missing_ai_payload["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"]
        == index_view.errors.ai_parsing_data_missing()
    )

    invalid_ai_payload = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "ai_parse",
                "ai_parsed_json": "{broken",
            },
        ),
        conn=conn,
    )
    assert invalid_ai_payload["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"]
        == index_view.errors.invalid_ai_parsing_data()
    )

    invalid_regex = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "regex",
                "separator": "[",
            },
        ),
        conn=conn,
    )
    assert invalid_regex["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"]
        == index_view.errors.invalid_regex_pattern()
    )

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [],
    )
    empty_preview = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert empty_preview["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"] == index_view.errors.no_data_to_process()
    )


def test_index_landing_page_and_top_level_error_paths(monkeypatch):
    """Confirm index landing page and top level error paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when index landing page and top level error paths stops reporting the expected error.
    """
    conn = _Conn()
    rendered = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context=None, status=200: (
            rendered.update(
                {"template": template, "context": context or {}, "status": status}
            )
            or rendered.copy()
        ),
    )
    monkeypatch.setattr(
        index_view,
        "_collect_project_payload",
        lambda *_args: {"owned": [{"id": "1", "name": "Project"}]},
    )
    monkeypatch.setattr(index_view, "reverse", lambda name: "/omp/projects/")
    monkeypatch.setattr(
        index_view,
        "list_ai_provider_options",
        lambda: [{"value": "openai", "label": "OpenAI"}],
    )

    landing = inspect.unwrap(index_view.index)(RequestFactory().get("/"), conn=conn)

    assert landing["template"] == "omeroweb_omp_plugin/index.html"
    assert json.loads(rendered["context"]["ai_provider_options_json"]) == [
        {"value": "openai", "label": "OpenAI"}
    ]
    assert rendered["context"]["projects"] == {
        "owned": [{"id": "1", "name": "Project"}]
    }

    monkeypatch.setattr(
        index_view,
        "_collect_project_payload",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    error_response = inspect.unwrap(index_view.index)(
        RequestFactory().get("/"), conn=conn
    )

    assert error_response["template"] == "omeroweb_omp_plugin/index.html"
    assert rendered["status"] == 500
    assert rendered["context"]["error_message"] == index_view.errors.unexpected_error()


def test_helper_fallback_paths_cover_group_membership_and_permission_text(monkeypatch):
    """Verify the helper fallback paths cover group membership and permission text safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when helper fallback paths cover group membership and permission text accepts unsafe input.
    Raises: RuntimeError when validation or the called operation fails.
    """

    class _OwnerByName:
        """Test double for owner by name behavior in this module."""

        def __init__(self, owner_id):
            """Create `_OwnerByName` with `owner_id`.

            Inputs: `owner_id`. Output: None.
            """
            self._owner_id = owner_id

        def getId(self):
            """Return `_OwnerByName`'s fake OMERO identifier.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val=self._owner_id)

        @staticmethod
        def getOmeName():
            """Return the fake OMERO name.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing ome name")

        @staticmethod
        def getName():
            """Return `_OwnerByName`'s fake object name.

            Inputs: none. Output: 'fallback-name'.
            """
            return "fallback-name"

    class _PermissionText:
        """Test double for permission text behavior in this module."""

        def __str__(self):
            """Return `_PermissionText` as test-readable text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("string conversion failed")

        @staticmethod
        def isGroupRead():
            """Return whether `_PermissionText` grants group-read access.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def isGroupWrite():
            """Return whether `_PermissionText` grants group-write access.

            Inputs: none. Output: bool.
            """
            return False

        @staticmethod
        def isGroupAnnotate():
            """Return whether `_PermissionText` grants group-annotate access.

            Inputs: none. Output: bool.
            """
            return True

    owner = _OwnerByName(41)
    project = SimpleNamespace(
        getDetails=lambda: None,
        getOwner=lambda: owner,
        permissions=_PermissionText(),
    )
    conn = _Conn()
    fallback_group = SimpleNamespace(
        getId=lambda: _Value(4),
        getMemberCount=lambda: (_ for _ in ()).throw(RuntimeError("no count")),
        getMembers=lambda: [1, 2],
        getDetails=lambda: None,
        getPermissions=_PermissionText,
    )
    conn._user = SimpleNamespace(
        getId=lambda: (_ for _ in ()).throw(RuntimeError("bad user id")),
        getGroups=lambda: [fallback_group],
    )
    conn.getGroupsMemberOf = lambda: (_ for _ in ()).throw(RuntimeError("bad groups"))

    assert index_view._get_owner_username(project) == "fallback-name"
    assert index_view._current_user_id(conn) is None
    assert index_view._iter_member_groups(conn) == [fallback_group]
    assert index_view._group_member_count(conn, fallback_group) == 2
    assert index_view._group_is_read_annotate(fallback_group) is True
    assert index_view._group_is_read_write(fallback_group) is False


def test_index_request_validation_paths_cover_json_errors_and_rate_limits(monkeypatch):
    """Verify index request validation paths cover JSON errors and rate limits.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index request validation paths cover JSON errors and rate limits.
    """
    conn = _Conn()
    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(index_view, "reverse", lambda _name: "/omp/projects/")
    rendered = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context=None, status=200: (
            rendered.update(
                {"template": template, "context": context or {}, "status": status}
            )
            or rendered.copy()
        ),
    )

    missing_project = inspect.unwrap(index_view.index)(
        RequestFactory().post("/", data={"action": "list_datasets"}),
        conn=conn,
    )
    assert missing_project.status_code == 400
    assert (
        _json_payload(missing_project)["error"]
        == index_view.errors.select_project_first()
    )

    monkeypatch.setattr(index_view, "_current_user_id", lambda *_args: None)
    missing_user = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={"action": "ai_regex", "project": "5", "selected_datasets": "10"},
        ),
        conn=conn,
    )
    assert missing_user.status_code == 400
    assert (
        _json_payload(missing_user)["error"]
        == index_view.errors.unable_to_determine_username()
    )

    monkeypatch.setattr(index_view, "_current_user_id", lambda *_args: 10)
    monkeypatch.setattr(
        index_view, "_get_accessible_project", lambda *_args: (None, None)
    )
    inaccessible = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "openai",
            },
        ),
        conn=conn,
    )
    assert inaccessible.status_code == 400
    assert (
        _json_payload(inaccessible)["error"] == index_view.errors.select_project_first()
    )

    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    invalid_dataset_ids = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={"action": "ai_regex", "project": "5", "selected_datasets": "x, y"},
        ),
        conn=conn,
    )
    assert invalid_dataset_ids.status_code == 400
    assert (
        _json_payload(invalid_dataset_ids)["error"]
        == index_view.errors.datasets_required()
    )

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (False, 42)
    )
    preview_rate_limited = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert preview_rate_limited["template"] == "omeroweb_omp_plugin/index.html"
    assert rendered["context"]["error_message"] == index_view.build_rate_limit_message(
        42
    )


def test_index_ai_provider_and_preview_fallbacks_cover_error_paths(monkeypatch):
    """Confirm index ai provider and preview fallbacks cover error paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when index ai provider and preview fallbacks cover error paths stops reporting the expected error.
    """
    conn = _Conn()
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

    ai_parse_no_filenames = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "openai",
            },
        ),
        conn=conn,
    )
    assert ai_parse_no_filenames.status_code == 400
    assert (
        _json_payload(ai_parse_no_filenames)["error"]
        == index_view.errors.no_filenames_available()
    )

    image = _ImageObject(17, "sample_A-01.tif")
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [(_Dataset(10, "Dataset"), [image])],
    )
    monkeypatch.setattr(index_view, "current_username", lambda *_args: "alice")
    monkeypatch.setattr(index_view, "get_ai_credential", lambda *_args: "api-key")
    monkeypatch.setattr(
        index_view,
        "generate_ai_parsed_values",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            index_view.AiAssistError("rejected")
        ),
    )
    ai_parse_rejected = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "openai",
            },
        ),
        conn=conn,
    )
    assert ai_parse_rejected.status_code == 400
    assert (
        _json_payload(ai_parse_rejected)["error"]
        == index_view.errors.unable_to_process_filenames()
    )

    monkeypatch.setattr(
        index_view,
        "generate_ai_parsed_values",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ai_parse_failed = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "action": "ai_parse",
                "project": "5",
                "selected_datasets": "10",
                "provider": "openai",
            },
        ),
        conn=conn,
    )
    assert ai_parse_failed.status_code == 500
    assert (
        _json_payload(ai_parse_failed)["error"]
        == index_view.errors.unable_to_process_filenames()
    )

    rendered = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context=None, status=200: (
            rendered.update(
                {"template": template, "context": context or {}, "status": status}
            )
            or rendered.copy()
        ),
    )
    monkeypatch.setattr(index_view, "reverse", lambda _name: "/omp/projects/")
    preview = inspect.unwrap(index_view.index)(
        RequestFactory().post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "ai_parse",
                "ai_parsed_json": json.dumps(
                    [
                        {"img_id": 17, "values": ["sample", "A"]},
                        {"img_id": "bad", "values": ["ignored"]},
                    ]
                ),
                "user_chunk_size": "bad",
                "user_max_parsed": "bad",
                "user_max_sets": "bad",
            },
        ),
        conn=conn,
    )
    assert preview["template"] == "omeroweb_omp_plugin/preview.html"
    assert rendered["context"]["chunk_size"] == index_view.CHUNK_SIZE
    assert (
        rendered["context"]["max_parsed_variables"] == index_view.MAX_PARSED_VARIABLES
    )
    assert (
        rendered["context"]["max_variable_sets"] == index_view.MAX_VARIABLE_SET_ENTRIES
    )
    assert rendered["context"]["preview_rows"][0]["img_id"] == 17


def test_index_helper_and_validation_edges_cover_remaining_branch_paths(monkeypatch):
    """Verify index helper and validation edges cover remaining branch paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index helper and validation edges cover remaining branch paths.
    Raises: RuntimeError when validation or the called operation fails.
    """

    class _OwnerWithVal:
        """Test double for owner with val behavior in this module."""

        @staticmethod
        def getOmeName():
            """Return the fake OMERO name.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no ome name")

        @staticmethod
        def getName():
            """Return `_OwnerWithVal`'s fake object name.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no display name")

        @staticmethod
        def getFirstName():
            """Return the fake first name.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no first name")

        @staticmethod
        def getId():
            """Return `_OwnerWithVal`'s fake OMERO identifier.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val=77)

    project = SimpleNamespace(getDetails=lambda: None, getOwner=_OwnerWithVal)
    assert index_view._get_owner_username(project) == "77"
    assert (
        index_view._has_read_annotate_permissions(
            SimpleNamespace(getDetails=lambda: None)
        )
        is False
    )

    conn = _Conn()
    fallback_project = _Project(12, "Fallback")
    conn.raise_all_groups = True
    conn.raise_opts_groups = True
    conn.list_projects = [fallback_project]
    assert list(index_view._iter_accessible_projects(conn)) == [fallback_project]

    class _BrokenPermissionText:
        """Test double for broken permission text behavior in this module."""

        def __str__(self):
            """Return `_BrokenPermissionText` as test-readable text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("bad permissions")

    broken_group = SimpleNamespace(
        getDetails=lambda: None,
        getPermissions=_BrokenPermissionText,
    )
    original_permissions_flag = index_view._permissions_flag
    monkeypatch.setattr(
        index_view,
        "_permissions_flag",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert index_view._group_is_read_write(broken_group) is False
    assert index_view._group_is_read_annotate(broken_group) is False
    original_iter_member_groups = index_view._iter_member_groups
    monkeypatch.setattr(
        index_view,
        "_iter_member_groups",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert index_view._is_user_in_group(object(), 1, 2) is False
    assert index_view._is_user_in_group(object(), None, 2) is False
    monkeypatch.setattr(index_view, "_permissions_flag", original_permissions_flag)
    monkeypatch.setattr(index_view, "_iter_member_groups", original_iter_member_groups)

    monkeypatch.setattr(
        index_view,
        "_iter_accessible_projects",
        lambda *_args: [
            _Project(1, "NoGroup", owner=_Owner(11, "bob"), group=None),
            _Project(
                2,
                "NoGroupId",
                owner=_Owner(11, "bob"),
                group=SimpleNamespace(getId=lambda: None),
            ),
        ],
    )
    monkeypatch.setattr(index_view, "_has_collaboration_groups", lambda *_args: False)
    assert index_view._collect_project_payload(_Conn(), 10) == {
        "owned": [],
        "collab": [],
        "collab_annotate": [],
        "collab_available": False,
    }
    monkeypatch.setattr(
        index_view,
        "_iter_accessible_projects",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert index_view._collect_project_payload(_Conn(), 10)["owned"] == []

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
    conn = _Conn()
    conn.project_by_id = {
        7: _Project(7, "Annotate", owner=_Owner(11, "bob"), group=ra_group)
    }
    conn.groups = [ra_group]
    assert index_view._get_accessible_project(conn, "7", 10)[1] == "read_annotate"

    factory = RequestFactory()
    conn = _Conn()
    monkeypatch.setattr(
        index_view, "_collect_project_payload", lambda *_args: {"owned": []}
    )
    monkeypatch.setattr(index_view, "reverse", lambda _name: "/omp/projects/")
    monkeypatch.setattr(index_view, "_current_user_id", lambda *_args: None)

    list_missing_user = inspect.unwrap(index_view.index)(
        factory.post("/", data={"action": "list_datasets", "project": "5"}),
        conn=conn,
    )
    assert list_missing_user.status_code == 400
    assert (
        _json_payload(list_missing_user)["error"]
        == index_view.errors.unable_to_determine_username()
    )

    monkeypatch.setattr(index_view, "_current_user_id", lambda *_args: 10)
    monkeypatch.setattr(
        index_view, "_get_accessible_project", lambda *_args: (None, None)
    )
    list_inaccessible = inspect.unwrap(index_view.index)(
        factory.post("/", data={"action": "list_datasets", "project": "5"}),
        conn=conn,
    )
    assert list_inaccessible.status_code == 400
    assert (
        _json_payload(list_inaccessible)["error"]
        == index_view.errors.select_project_first()
    )

    ai_regex_missing_project = inspect.unwrap(index_view.index)(
        factory.post(
            "/", data={"action": "ai_regex", "project": "", "selected_datasets": "10"}
        ),
        conn=conn,
    )
    assert ai_regex_missing_project.status_code == 400
    assert (
        _json_payload(ai_regex_missing_project)["error"]
        == index_view.errors.select_project_first()
    )

    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    ai_regex_missing_datasets = inspect.unwrap(index_view.index)(
        factory.post(
            "/", data={"action": "ai_regex", "project": "5", "selected_datasets": " , "}
        ),
        conn=conn,
    )
    assert ai_regex_missing_datasets.status_code == 400
    assert (
        _json_payload(ai_regex_missing_datasets)["error"]
        == index_view.errors.datasets_required()
    )

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [
            (
                _Dataset(10, "Dataset"),
                [
                    SimpleNamespace(
                        getName=lambda: (_ for _ in ()).throw(RuntimeError("bad name"))
                    )
                ],
            )
        ],
    )
    no_filenames = inspect.unwrap(index_view.index)(
        factory.post(
            "/", data={"action": "ai_regex", "project": "5", "selected_datasets": "10"}
        ),
        conn=conn,
    )
    assert no_filenames.status_code == 400
    assert (
        _json_payload(no_filenames)["error"]
        == index_view.errors.no_filenames_available()
    )

    rendered = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context=None, status=200: (
            rendered.update(
                {"template": template, "context": context or {}, "status": status}
            )
            or rendered.copy()
        ),
    )
    missing_project_preview = inspect.unwrap(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert missing_project_preview["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"] == index_view.errors.select_project_first()
    )

    monkeypatch.setattr(index_view, "_current_user_id", lambda *_args: None)
    missing_user_preview = inspect.unwrap(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert missing_user_preview["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"]
        == index_view.errors.unable_to_determine_username()
    )

    monkeypatch.setattr(index_view, "_current_user_id", lambda *_args: 10)
    monkeypatch.setattr(
        index_view, "_get_accessible_project", lambda *_args: (None, None)
    )
    inaccessible_preview = inspect.unwrap(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert inaccessible_preview["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"] == index_view.errors.select_project_first()
    )

    monkeypatch.setattr(
        index_view,
        "_get_accessible_project",
        lambda *_args: (_Project(5, "Project"), "owned"),
    )
    no_separator_preview = inspect.unwrap(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "   ",
            },
        ),
        conn=conn,
    )
    assert no_separator_preview["template"] == "omeroweb_omp_plugin/index.html"
    assert (
        rendered["context"]["error_message"] == index_view.errors.filename_input_empty()
    )

    no_dataset_preview = inspect.unwrap(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": " , ",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert no_dataset_preview["template"] == "omeroweb_omp_plugin/index.html"
    assert rendered["context"]["error_message"] == index_view.errors.datasets_required()

    monkeypatch.setattr(
        index_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        index_view,
        "collect_images_by_selected_datasets",
        lambda *_args, **_kwargs: [
            (
                _Dataset(10, "Dataset"),
                [
                    SimpleNamespace(
                        getId=lambda: _Value(17), getName=lambda: "sample_A-01.tif"
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        index_view,
        "parse_filename",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("bad parse")),
    )
    parse_failure_preview = inspect.unwrap(index_view.index)(
        factory.post(
            "/",
            data={
                "project": "5",
                "selected_datasets": "10",
                "separator_mode": "chars",
                "separator": "_",
            },
        ),
        conn=conn,
    )
    assert parse_failure_preview["template"] == "omeroweb_omp_plugin/preview.html"
    assert rendered["context"]["max_vars"] == 1
    assert rendered["context"]["preview_rows"] == []
