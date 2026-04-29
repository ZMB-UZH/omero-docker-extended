from __future__ import annotations

import logging
from types import SimpleNamespace

from omero_plugin_common import omero_helpers, request_utils, string_utils


class _ValueBox:
    """Represent value box."""

    def __init__(self, value):
        self._value = value

    def getValue(self):
        """Return get value."""
        return self._value


class _BrokenValueBox:
    """Represent broken value box."""

    @staticmethod
    def getValue():
        """Return get value."""
        raise RuntimeError("boom")

    def __str__(self) -> str:
        return "fallback-text"


class _OwnerStub:
    """Represent owner stub."""

    def __init__(self, owner_id, *, ome_name=None, name=None, first_name=None):
        self._owner_id = owner_id
        self._ome_name = ome_name
        self._name = name
        self._first_name = first_name

    def getId(self):
        """Return get identifier."""
        return _ValueBox(self._owner_id)

    def getOmeName(self):
        """Return get ome name."""
        if self._ome_name is None:
            raise AttributeError("missing ome name")
        return _ValueBox(self._ome_name)

    def getName(self):
        """Return get name."""
        if self._name is None:
            raise AttributeError("missing display name")
        return _ValueBox(self._name)

    def getFirstName(self):
        """Return get first name."""
        if self._first_name is None:
            raise AttributeError("missing first name")
        return _ValueBox(self._first_name)


class _OwnerWithBrokenId:
    """Represent owner with broken identifier."""

    @staticmethod
    def getId():
        """Return get identifier."""
        raise RuntimeError("broken owner id")


class _DetailsStub:
    """Represent details stub."""

    def __init__(self, *, owner=None, permissions=None):
        self._owner = owner
        self._permissions = permissions

    def getOwner(self):
        """Return get owner."""
        return self._owner

    def getPermissions(self):
        """Return get permissions."""
        return self._permissions


class _PermissionsStub:
    """Represent permissions stub."""

    def __init__(self, *, can_read, can_write):
        self._can_read = can_read
        self._can_write = can_write

    def isRead(self):
        """Handle is read."""
        return self._can_read

    def isWrite(self):
        """Handle is write."""
        return self._can_write


def test_omero_helper_accessors_cover_value_resolution_owner_fallbacks_and_permissions():
    """Verify test OMERO helper accessors cover value resol behavior."""
    internal = SimpleNamespace(_obj=SimpleNamespace(id=SimpleNamespace(val=17)))
    via_method = SimpleNamespace(getId=lambda: _ValueBox(42))
    missing = SimpleNamespace(
        getId=lambda: (_ for _ in ()).throw(RuntimeError("no id"))
    )
    owner = _OwnerStub(11, ome_name="alice")
    details_object = SimpleNamespace(getDetails=lambda: _DetailsStub(owner=owner))
    owner_object = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("no details")),
        getOwner=lambda: owner,
    )
    fallback_owner_object = SimpleNamespace(
        getDetails=lambda: _DetailsStub(owner=_OwnerWithBrokenId()),
        getOwner=lambda: owner,
    )
    missing_owner = SimpleNamespace(getDetails=lambda: _DetailsStub(owner=None))
    conn = SimpleNamespace(getUser=lambda: SimpleNamespace(getId=lambda: _ValueBox(23)))
    broken_conn = SimpleNamespace(
        getUser=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    owner_with_name = _OwnerStub(7, ome_name="carol")
    owner_with_display_name = _OwnerStub(8, ome_name=None, name="Display Name")
    owner_with_first_name = _OwnerStub(9, ome_name=None, name=None, first_name="Dana")
    owner_without_names = _OwnerStub(10)
    editable = SimpleNamespace(canEdit=lambda: True)
    writable = SimpleNamespace(
        canEdit=lambda: (_ for _ in ()).throw(RuntimeError("skip")),
        canWrite=lambda: True,
    )
    permission_based = SimpleNamespace(
        getDetails=lambda: _DetailsStub(
            permissions=_PermissionsStub(can_read=True, can_write=True)
        )
    )
    read_only = SimpleNamespace(
        getDetails=lambda: _DetailsStub(
            permissions=_PermissionsStub(can_read=True, can_write=False)
        )
    )

    assert omero_helpers.get_text(_ValueBox("primary")) == "primary"
    assert omero_helpers.get_text(SimpleNamespace(val="secondary")) == "secondary"
    assert omero_helpers.get_text(_BrokenValueBox()) == "fallback-text"
    assert omero_helpers.get_id(internal) == 17
    assert omero_helpers.get_id(via_method) == 42
    assert omero_helpers.get_id(missing) is None
    assert omero_helpers.get_owner_id(details_object) == 11
    assert omero_helpers.get_owner_id(owner_object) == 11
    assert omero_helpers.get_owner_id(fallback_owner_object) == 11
    assert omero_helpers.get_owner_id(missing_owner) is None
    assert omero_helpers.is_owned_by_user(details_object, "11") is True
    assert omero_helpers.is_owned_by_user(fallback_owner_object, 11) is True
    assert omero_helpers.is_owned_by_user(details_object, 99) is False
    assert omero_helpers.is_owned_by_user(missing_owner, 11) is False
    assert omero_helpers.is_owned_by_user(missing_owner, None) is True
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
            SimpleNamespace(
                getDetails=lambda: _DetailsStub(owner=owner_with_display_name)
            )
        )
        == "Display Name"
    )
    assert (
        omero_helpers._get_owner_username(
            SimpleNamespace(
                getDetails=lambda: _DetailsStub(owner=owner_with_first_name)
            )
        )
        == "Dana"
    )
    assert (
        omero_helpers._get_owner_username(
            SimpleNamespace(getDetails=lambda: _DetailsStub(owner=owner_without_names))
        )
        == "10"
    )
    assert omero_helpers._get_owner_username(fallback_owner_object) == "alice"
    assert omero_helpers._get_owner_username(None) == ""
    assert omero_helpers._has_read_write_permissions(editable) is True
    assert omero_helpers._has_read_write_permissions(writable) is True
    assert omero_helpers._has_read_write_permissions(permission_based) is True
    assert omero_helpers._has_read_write_permissions(read_only) is False
    assert omero_helpers._has_read_write_permissions(None) is False


def test_request_and_string_helpers_cover_user_resolution_json_fallbacks_and_payload_keys():
    """Verify test request and string helpers cover user re behavior."""
    conn = SimpleNamespace(
        getUser=lambda: SimpleNamespace(getName=lambda: "omero-user")
    )
    request = SimpleNamespace(user=SimpleNamespace(username="django-user"))
    json_request = SimpleNamespace(body=b'{"name":"value"}', POST={"ignored": True})
    form_request = SimpleNamespace(body=b"{not-json", POST={"field": "value"})
    invalid_json_request = SimpleNamespace(body=b"{not-json")
    invalid_utf8_request = SimpleNamespace(body=b"\xff")

    class FailingConn:
        """Represent failing conn."""

        @staticmethod
        def getUser():
            """Return get user."""
            raise RuntimeError("connection unavailable")

    assert request_utils.current_username(request, conn) == "omero-user"
    assert request_utils.current_username(request, FailingConn()) == "django-user"
    assert (
        request_utils.current_username(
            SimpleNamespace(user=object()),
            FailingConn(),
        )
        is None
    )
    assert request_utils.load_request_data(json_request) == {"name": "value"}
    assert request_utils.load_request_data(form_request) == {"field": "value"}
    data, error = request_utils.parse_json_body(json_request)
    assert data == {"name": "value"}
    assert error is None
    data, error = request_utils.parse_json_body(invalid_json_request)
    assert data is None
    assert error == "Request body is not valid JSON."
    data, error = request_utils.parse_json_body(invalid_utf8_request)
    assert data is None
    assert error == "Request body is not valid UTF-8."
    assert string_utils.snake_to_camel("alpha_beta_gamma") == "alphaBetaGamma"
    assert string_utils.snake_to_camel("single") == "single"
    assert string_utils.build_message_payload(
        ["confirm_irreversible_action", "retry_upload_job"],
        {
            "confirm_irreversible_action": lambda: "Proceed?",
            "retry_upload_job": lambda: "Retry the upload?",
        },
    ) == {
        "confirmIrreversible": "Proceed?",
        "retryUploadJob": "Retry the upload?",
    }


def test_omero_helper_debug_logs_sanitize_exception_text(caplog):
    """Verify test OMERO helper debug logs sanitize excepti behavior."""

    class ObjectWithUnsafeInternalId:
        """Represent object with unsafe internal identifier."""

        @property
        def _obj(self):
            raise RuntimeError("bad\nid")

        @staticmethod
        def getId():
            """Return get identifier."""
            return _ValueBox(31)

    caplog.set_level(logging.DEBUG, logger=omero_helpers.__name__)

    assert omero_helpers.get_id(ObjectWithUnsafeInternalId()) == 31

    messages = [record.getMessage() for record in caplog.records]
    assert any("bad\\\\nid" in message for message in messages)
    assert all("bad\nid" not in message for message in messages)
