from __future__ import annotations

import logging
from types import SimpleNamespace

from omero_plugin_common import omero_helpers, request_utils, string_utils


class _ValueBox:
    """Test double for value box behavior in this module."""

    def __init__(self, value):
        """Create `_ValueBox` with `value`.

        Inputs: `value`. Output: None.
        """
        self._value = value

    def getValue(self):
        """Return `_ValueBox`'s fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value


class _BrokenValueBox:
    """Test double for broken value box behavior in this module."""

    @staticmethod
    def getValue():
        """Return `_BrokenValueBox`'s fake OMERO value.

        Inputs: caller provides no extra arguments. Output: returns the fake value described above.
        """
        raise RuntimeError("boom")

    def __str__(self) -> str:
        """Return `_BrokenValueBox` as test-readable text.

        Inputs: none. Output: `str`.
        """
        return "fallback-text"


class _OwnerStub:
    """Test double for owner stub behavior in this module."""

    def __init__(self, owner_id, *, ome_name=None, name=None, first_name=None):
        """Create `_OwnerStub` with `owner_id`.

        Inputs: `owner_id`, `ome_name`, `name`, `first_name`. Output: None.
        """
        self._owner_id = owner_id
        self._ome_name = ome_name
        self._name = name
        self._first_name = first_name

    def getId(self):
        """Return `_OwnerStub`'s fake OMERO identifier.

        Inputs: none. Output: `_ValueBox` result.
        """
        return _ValueBox(self._owner_id)

    def getOmeName(self):
        """Return the OME Name for `_OwnerStub`.

        Inputs: none. Output: `_ValueBox` result. Raises: AttributeError when validation or the called operation fails.
        """
        if self._ome_name is None:
            raise AttributeError("missing ome name")
        return _ValueBox(self._ome_name)

    def getName(self):
        """Return the name for `_OwnerStub`.

        Inputs: none. Output: `_ValueBox` result. Raises: AttributeError when validation or the called operation fails.
        """
        if self._name is None:
            raise AttributeError("missing display name")
        return _ValueBox(self._name)

    def getFirstName(self):
        """Return the first Name for `_OwnerStub`.

        Inputs: none. Output: `_ValueBox` result. Raises: AttributeError when validation or the called operation fails.
        """
        if self._first_name is None:
            raise AttributeError("missing first name")
        return _ValueBox(self._first_name)


class _OwnerWithBrokenId:
    """Test double for owner with broken identifier behavior in this module."""

    @staticmethod
    def getId():
        """Return `_OwnerWithBrokenId`'s fake OMERO identifier.

        Inputs: caller provides no extra arguments. Output: returns the fake value described above.
        """
        raise RuntimeError("broken owner id")


class _DetailsStub:
    """Test double for details stub behavior in this module."""

    def __init__(self, *, owner=None, permissions=None):
        """Create `_DetailsStub` with its default state.

        Inputs: `owner`, `permissions`. Output: None.
        """
        self._owner = owner
        self._permissions = permissions

    def getOwner(self):
        """Return the fake owner.

        Inputs: none. Output: `self._owner`.
        """
        return self._owner

    def getPermissions(self):
        """Return `_DetailsStub`'s fake permissions object.

        Inputs: none. Output: `self._permissions`.
        """
        return self._permissions


def test_owner_from_details_or_method_returns_none_without_owner() -> None:
    """Verify owner from details or method returns none without owner result shape.

    Inputs: helper fakes. Output: fails on regressions in owner from details or method returns none without owner.
    """
    assert omero_helpers._owner_from_details_or_method(object()) is None


class _PermissionsStub:
    """Test double for permissions stub behavior in this module."""

    def __init__(self, *, can_read, can_write):
        """Create `_PermissionsStub` with its default state.

        Inputs: `can_read`, `can_write`. Output: None.
        """
        self._can_read = can_read
        self._can_write = can_write

    def isRead(self):
        """Report the read boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `self._can_read`.
        """
        return self._can_read

    def isWrite(self):
        """Report the write boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `self._can_write`.
        """
        return self._can_write


def test_omero_helper_accessors_cover_value_resolution_owner_fallbacks_and_permissions():
    """Verify OMERO helper accessors cover value resolution owner fallbacks and permissions.

    Inputs: helper fakes. Output: fails on regressions in OMERO helper accessors cover value resolution owner fallbacks and permissions.
    """
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
    """Verify request and string helpers cover user resolution JSON fallbacks and payload keys result shape.

    Inputs: helper fakes. Output: fails on regressions in request and string helpers cover user resolution JSON fallbacks and payload keys.
    """
    conn = SimpleNamespace(
        getUser=lambda: SimpleNamespace(getName=lambda: "omero-user")
    )
    request = SimpleNamespace(user=SimpleNamespace(username="django-user"))
    json_request = SimpleNamespace(body=b'{"name":"value"}', POST={"ignored": True})
    form_request = SimpleNamespace(body=b"{not-json", POST={"field": "value"})
    invalid_json_request = SimpleNamespace(body=b"{not-json")
    invalid_utf8_request = SimpleNamespace(body=b"\xff")

    class FailingConn:
        """Test double for failing conn behavior in this module."""

        @staticmethod
        def getUser():
            """Return the fake user.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
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
    """Confirm OMERO helper debug logs sanitize exception text exposes the expected failure.

    Inputs: pytest provides `caplog`. Output: fails on regressions when OMERO helper debug logs sanitize exception text stops reporting the expected error.
    Raises: RuntimeError when validation or the called operation fails.
    """

    class ObjectWithUnsafeInternalId:
        """Test double for object with unsafe internal identifier behavior in this module."""

        @property
        def _obj(self):
            """Record the obj call on `ObjectWithUnsafeInternalId` for later assertions.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            raise RuntimeError("bad\nid")

        @staticmethod
        def getId():
            """Return `ObjectWithUnsafeInternalId`'s fake OMERO identifier.

            Inputs: none. Output: `_ValueBox` result.
            """
            return _ValueBox(31)

    caplog.set_level(logging.DEBUG, logger=omero_helpers.__name__)

    assert omero_helpers.get_id(ObjectWithUnsafeInternalId()) == 31

    messages = [record.getMessage() for record in caplog.records]
    assert any("bad\\\\nid" in message for message in messages)
    assert all("bad\nid" not in message for message in messages)
