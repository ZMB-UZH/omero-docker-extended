from __future__ import annotations

from types import SimpleNamespace

from omeroweb_omp_plugin.views import index_view


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


def test_owner_permission_and_group_helpers_cover_remaining_fallbacks(monkeypatch):
    """Verify owner permission and group helpers cover remaining fallbacks.

    Inputs: `monkeypatch`. Output: computed value. Raises on invalid or unavailable
    state.

    state.
    """
    plain_owner = SimpleNamespace(getId=lambda: 17)
    details_obj = SimpleNamespace(
        getDetails=lambda: SimpleNamespace(getOwner=lambda: plain_owner)
    )
    fallback_obj = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("missing details")),
        getOwner=lambda: plain_owner,
    )

    assert index_view._get_owner_id(None) is None
    assert index_view._get_owner_id(details_obj) == 17
    assert index_view._get_owner_id(fallback_obj) == 17

    assert index_view._current_user_id(SimpleNamespace(getUser=lambda: None)) is None
    assert index_view._is_owned_by_user(None, 1) is False
    assert (
        index_view._is_owned_by_user(SimpleNamespace(getDetails=lambda: None), 1)
        is False
    )
    assert (
        index_view._is_owned_by_user(
            SimpleNamespace(
                getDetails=lambda: SimpleNamespace(
                    getOwner=lambda: SimpleNamespace(getId=lambda: "bad")
                )
            ),
            1,
        )
        is False
    )

    assert index_view._get_owner_username(None) == ""
    assert (
        index_view._get_owner_username(
            SimpleNamespace(
                getDetails=lambda: (_ for _ in ()).throw(
                    RuntimeError("details failed")
                ),
                getOwner=lambda: (_ for _ in ()).throw(RuntimeError("owner failed")),
            )
        )
        == ""
    )

    first_name_owner = SimpleNamespace(
        getOmeName=lambda: (_ for _ in ()).throw(RuntimeError("ome failed")),
        getName=lambda: "",
        getFirstName=lambda: "Alice",
    )
    assert (
        index_view._get_owner_username(
            SimpleNamespace(getDetails=lambda: None, getOwner=lambda: first_name_owner)
        )
        == "Alice"
    )

    id_fallback_owner = SimpleNamespace(
        getOmeName=lambda: "",
        getName=lambda: "",
        getFirstName=lambda: "",
        getId=lambda: _Value(33),
    )
    assert (
        index_view._get_owner_username(
            SimpleNamespace(getDetails=lambda: None, getOwner=lambda: id_fallback_owner)
        )
        == "33"
    )
    assert (
        index_view._get_owner_username(
            SimpleNamespace(
                getDetails=lambda: None,
                getOwner=lambda: SimpleNamespace(
                    getOmeName=lambda: "",
                    getName=lambda: "",
                    getFirstName=lambda: "",
                    getId=lambda: (_ for _ in ()).throw(RuntimeError("id failed")),
                ),
            )
        )
        == ""
    )

    class _MissingAttrPermissions:
        """Represent missing attr permissions."""

        def __getattr__(self, name):
            """Return a dynamic attribute value by name.

            Inputs: `name`. Output: None. Raises on invalid or unavailable state.
            """
            raise AttributeError(name)

    class _FailingPermissions:
        """Represent failing permissions."""

        @staticmethod
        def failing():
            """Failing.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("flag failed")

    assert index_view._permissions_flag(_MissingAttrPermissions(), "isRead") is False
    assert (
        index_view._permissions_flag(
            _FailingPermissions(),
            "failing",
        )
        is False
    )
    assert index_view._permissions_flag(SimpleNamespace(isRead=True), "isRead") is True
    assert (
        index_view._has_read_write_permissions(
            SimpleNamespace(getDetails=lambda: None, getPermissions=lambda: None)
        )
        is False
    )
    assert (
        index_view._has_read_annotate_permissions(
            SimpleNamespace(
                getDetails=lambda: SimpleNamespace(
                    getPermissions=lambda: SimpleNamespace(
                        isRead=lambda: True,
                        isWrite=lambda: False,
                        isAnnotate=lambda: True,
                    )
                )
            )
        )
        is True
    )

    assert index_view._iter_member_groups(None) == []
    assert (
        index_view._iter_member_groups(
            SimpleNamespace(
                getGroupsMemberOf=lambda: [],
                getUser=lambda: SimpleNamespace(
                    getGroups=lambda: (_ for _ in ()).throw(
                        RuntimeError("groups failed")
                    )
                ),
            )
        )
        == []
    )

    class _BadCountGroup:
        """Represent bad count group."""

        @staticmethod
        def getMemberCount():
            """Return Member Count.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val="bad")

        @staticmethod
        def getMembers():
            """Return Members.

            Inputs: none. Output: `object` result.
            """
            return object()

        @staticmethod
        def getExperimenters():
            """Return Experimenters.

            Inputs: none. Output: `object` result.
            """
            return object()

        @staticmethod
        def getExperimenterIds():
            """Return Experimenter IDs.

            Inputs: none. Output: `object` result.
            """
            return object()

    bad_count_group = _BadCountGroup()
    assert (
        index_view._group_member_count(
            SimpleNamespace(getObjects=lambda *args, **kwargs: []), bad_count_group
        )
        == 0
    )
    assert (
        index_view._group_member_count(
            SimpleNamespace(
                getObjects=lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("lookup failed")
                )
            ),
            SimpleNamespace(
                getMemberCount=lambda: None,
                getMembers=lambda: None,
                getExperimenters=lambda: None,
                getExperimenterIds=lambda: None,
                getId=lambda: _Value(9),
            ),
        )
        == 0
    )
    assert (
        index_view._group_member_count(object(), SimpleNamespace(getId=lambda: None))
        == 0
    )


def test_project_iteration_payload_and_wrapper_helpers_cover_remaining_paths(
    monkeypatch,
):
    """Verify project iteration payload and wrapper helpers cover remaining paths.

    Inputs: `monkeypatch`. Output: computed value. Raises on invalid or unavailable
    state.

    state.
    """
    assert list(index_view._iter_accessible_projects(None)) == []

    all_groups_project = SimpleNamespace(name="all-groups")

    class _ServiceOpts:
        """Represent service opts."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.current_group = "4"
            self.restore_failed = False

        def getOmeroGroup(self):
            """Return OMERO Group.

            Inputs: none. Output: `self.current_group`.
            """
            return self.current_group

        def setOmeroGroup(self, value):
            """Set OMERO Group.

            Inputs: `value`. Output: None. Raises on invalid or unavailable state.
            """
            if value == "4" and self.restore_failed:
                raise RuntimeError("restore failed")
            self.current_group = value

    all_groups_conn = SimpleNamespace(
        SERVICE_OPTS=_ServiceOpts(),
        getObjects=lambda object_type, opts=None: [all_groups_project],
        listProjects=lambda: [],
    )
    assert list(index_view._iter_accessible_projects(all_groups_conn)) == [
        all_groups_project
    ]

    failing_opts = _ServiceOpts()
    failing_opts.restore_failed = True

    class _FailingConn:
        """Represent failing conn."""

        SERVICE_OPTS = failing_opts

        @staticmethod
        def getObjects(object_type, opts=None):
            """Return Objects.

            Inputs: `object_type`, `opts`. Output: None. Raises on invalid or
            unavailable state.
            """
            raise RuntimeError("query failed")

        @staticmethod
        def listProjects():
            """Return list projects.

            Inputs: none. Output: list.
            """
            return [SimpleNamespace(name="listed")]

    assert [
        project.name for project in index_view._iter_accessible_projects(_FailingConn())
    ] == ["listed"]

    broken_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(
            getOmeroGroup=lambda: (_ for _ in ()).throw(RuntimeError("group failed")),
            setOmeroGroup=lambda value: None,
        ),
        getObjects=lambda object_type, opts=None: (_ for _ in ()).throw(
            RuntimeError("query failed")
        ),
        listProjects=lambda: (_ for _ in ()).throw(RuntimeError("list failed")),
    )
    assert list(index_view._iter_accessible_projects(broken_conn)) == []

    assert index_view._get_accessible_project(
        SimpleNamespace(getObject=lambda *_args: None), "", 7
    ) == (
        None,
        None,
    )
    assert index_view._get_accessible_project(
        SimpleNamespace(
            getObject=lambda *_args: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
        "5",
        7,
    ) == (None, None)
    assert index_view._get_accessible_project(
        SimpleNamespace(
            getObject=lambda *_args: SimpleNamespace(getDetails=lambda: None)
        ),
        "5",
        7,
    ) == (None, None)

    group = SimpleNamespace(getId=lambda: _Value(11))
    project = SimpleNamespace(
        getDetails=lambda: SimpleNamespace(getGroup=lambda: group)
    )
    monkeypatch.setattr(index_view, "_is_owned_by_user", lambda *_args: False)
    monkeypatch.setattr(index_view, "_is_user_in_group", lambda *_args: False)
    assert index_view._get_accessible_project(
        SimpleNamespace(getObject=lambda *_args: project),
        "5",
        7,
    ) == (None, None)

    monkeypatch.setattr(index_view, "_is_user_in_group", lambda *_args: True)
    monkeypatch.setattr(index_view, "_group_is_read_write", lambda *_args: False)
    monkeypatch.setattr(index_view, "_group_is_read_annotate", lambda *_args: False)
    assert index_view._get_accessible_project(
        SimpleNamespace(getObject=lambda *_args: project),
        "5",
        7,
    ) == (None, None)

    anonymous = SimpleNamespace(
        getName=lambda: "Anonymous",
        getDetails=lambda: SimpleNamespace(getGroup=lambda: None),
    )
    missing_group_id = SimpleNamespace(
        getName=lambda: "Missing Group",
        getDetails=lambda: SimpleNamespace(
            getGroup=lambda: SimpleNamespace(getId=lambda: None)
        ),
    )
    monkeypatch.setattr(
        index_view,
        "_iter_accessible_projects",
        lambda conn: [anonymous, missing_group_id],
    )
    monkeypatch.setattr(index_view, "_has_collaboration_groups", lambda conn: False)
    monkeypatch.setattr(
        index_view, "get_id", lambda obj: None if obj is anonymous else 5
    )
    assert index_view._collect_project_payload(object(), 7) == {
        "owned": [],
        "collab": [],
        "collab_annotate": [],
        "collab_available": False,
    }

    monkeypatch.setattr(
        index_view,
        "_iter_accessible_projects",
        lambda conn: (_ for _ in ()).throw(RuntimeError("listing failed")),
    )
    error_payload = index_view._collect_project_payload(object(), 7)
    assert error_payload["owned"] == []

    monkeypatch.setattr(
        index_view.messages,
        "index_messages",
        lambda: (_ for _ in ()).throw(RuntimeError("message failure")),
    )
    assert index_view._safe_index_messages_json() == "{}"

    monkeypatch.setattr(index_view, "suggest_separator_regex", "::".join)
    assert index_view._suggest_separator_regex(["a", "b"]) == "a::b"
