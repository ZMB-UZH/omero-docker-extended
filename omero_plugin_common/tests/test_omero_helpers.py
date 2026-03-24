from __future__ import annotations

from types import SimpleNamespace

from omero_plugin_common import omero_helpers


class _ValueBox:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _BrokenValueBox:
    def getValue(self):
        raise RuntimeError("boom")

    def __str__(self) -> str:
        return "fallback-text"


class _OwnerStub:
    def __init__(self, owner_id, *, ome_name=None, name=None, first_name=None):
        self._owner_id = owner_id
        self._ome_name = ome_name
        self._name = name
        self._first_name = first_name

    def getId(self):
        return _ValueBox(self._owner_id)

    def getOmeName(self):
        if self._ome_name is None:
            raise AttributeError("missing ome name")
        return _ValueBox(self._ome_name)

    def getName(self):
        if self._name is None:
            raise AttributeError("missing display name")
        return _ValueBox(self._name)

    def getFirstName(self):
        if self._first_name is None:
            raise AttributeError("missing first name")
        return _ValueBox(self._first_name)


class _DetailsStub:
    def __init__(self, *, owner=None, permissions=None):
        self._owner = owner
        self._permissions = permissions

    def getOwner(self):
        return self._owner

    def getPermissions(self):
        return self._permissions


class _PermissionsStub:
    def __init__(self, *, can_read, can_write):
        self._can_read = can_read
        self._can_write = can_write

    def isRead(self):
        return self._can_read

    def isWrite(self):
        return self._can_write


def test_get_text_prefers_value_then_val_then_string_fallback():
    assert omero_helpers.get_text(_ValueBox("primary")) == "primary"
    assert omero_helpers.get_text(SimpleNamespace(val="secondary")) == "secondary"
    assert omero_helpers.get_text(_BrokenValueBox()) == "fallback-text"


def test_get_id_uses_internal_obj_then_falls_back_to_get_id():
    internal = SimpleNamespace(_obj=SimpleNamespace(id=SimpleNamespace(val=17)))
    via_method = SimpleNamespace(getId=lambda: _ValueBox(42))
    missing = SimpleNamespace(getId=lambda: (_ for _ in ()).throw(RuntimeError("no id")))

    assert omero_helpers.get_id(internal) == 17
    assert omero_helpers.get_id(via_method) == 42
    assert omero_helpers.get_id(missing) is None


def test_get_owner_id_and_is_owned_by_user_handle_details_fallbacks():
    owner = _OwnerStub(11, ome_name="alice")
    details_object = SimpleNamespace(getDetails=lambda: _DetailsStub(owner=owner))
    owner_object = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("no details")),
        getOwner=lambda: owner,
    )
    missing_owner = SimpleNamespace(getDetails=lambda: _DetailsStub(owner=None))

    assert omero_helpers.get_owner_id(details_object) == 11
    assert omero_helpers.get_owner_id(owner_object) == 11
    assert omero_helpers.get_owner_id(missing_owner) is None
    assert omero_helpers.is_owned_by_user(details_object, "11") is True
    assert omero_helpers.is_owned_by_user(details_object, 99) is False
    assert omero_helpers.is_owned_by_user(missing_owner, 11) is False
    assert omero_helpers.is_owned_by_user(missing_owner, None) is True


def test_current_user_and_owner_username_helpers_cover_all_fallbacks():
    conn = SimpleNamespace(getUser=lambda: SimpleNamespace(getId=lambda: _ValueBox(23)))
    broken_conn = SimpleNamespace(getUser=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    owner_with_name = _OwnerStub(7, ome_name="carol")
    owner_with_display_name = _OwnerStub(8, ome_name=None, name="Display Name")
    owner_with_first_name = _OwnerStub(9, ome_name=None, name=None, first_name="Dana")
    owner_without_names = _OwnerStub(10)

    assert omero_helpers._current_user_id(conn) == 23
    assert omero_helpers._current_user_id(broken_conn) is None
    assert (
        omero_helpers._get_owner_username(
            SimpleNamespace(getDetails=lambda: _DetailsStub(owner=owner_with_name))
        )
        == "carol"
    )
    assert (
        omero_helpers._get_owner_username(
            SimpleNamespace(getDetails=lambda: _DetailsStub(owner=owner_with_display_name))
        )
        == "Display Name"
    )
    assert (
        omero_helpers._get_owner_username(
            SimpleNamespace(getDetails=lambda: _DetailsStub(owner=owner_with_first_name))
        )
        == "Dana"
    )
    assert (
        omero_helpers._get_owner_username(
            SimpleNamespace(
                getDetails=lambda: _DetailsStub(owner=owner_without_names),
            )
        )
        == "10"
    )
    assert omero_helpers._get_owner_username(None) == ""


def test_has_read_write_permissions_prefers_callables_then_permissions_fallback():
    editable = SimpleNamespace(canEdit=lambda: True)
    writable = SimpleNamespace(
        canEdit=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        canWrite=lambda: True,
    )
    permission_based = SimpleNamespace(
        getDetails=lambda: _DetailsStub(permissions=_PermissionsStub(can_read=True, can_write=True))
    )
    read_only = SimpleNamespace(
        getDetails=lambda: _DetailsStub(permissions=_PermissionsStub(can_read=True, can_write=False))
    )

    assert omero_helpers._has_read_write_permissions(editable) is True
    assert omero_helpers._has_read_write_permissions(writable) is True
    assert omero_helpers._has_read_write_permissions(permission_based) is True
    assert omero_helpers._has_read_write_permissions(read_only) is False
    assert omero_helpers._has_read_write_permissions(None) is False
