from __future__ import annotations

from types import SimpleNamespace

from omero_plugin_common import request_utils


def test_current_username_prefers_connection_user_name() -> None:
    conn = SimpleNamespace(getUser=lambda: SimpleNamespace(getName=lambda: "omero-user"))
    request = SimpleNamespace(user=SimpleNamespace(username="django-user"))

    assert request_utils.current_username(request, conn) == "omero-user"


def test_current_username_falls_back_to_request_user_when_connection_lookup_fails() -> None:
    class FailingConn:
        def getUser(self):
            raise RuntimeError("connection unavailable")

    request = SimpleNamespace(user=SimpleNamespace(username="django-user"))

    assert request_utils.current_username(request, FailingConn()) == "django-user"


def test_current_username_returns_none_when_request_and_connection_are_unusable() -> None:
    class FailingConn:
        def getUser(self):
            raise RuntimeError("connection unavailable")

    request = SimpleNamespace(user=object())

    assert request_utils.current_username(request, FailingConn()) is None


def test_load_request_data_prefers_json_body_and_falls_back_to_post() -> None:
    json_request = SimpleNamespace(body=b'{"name":"value"}', POST={"ignored": True})
    form_request = SimpleNamespace(body=b"{not-json", POST={"field": "value"})

    assert request_utils.load_request_data(json_request) == {"name": "value"}
    assert request_utils.load_request_data(form_request) == {"field": "value"}


def test_parse_json_body_returns_data_or_explicit_error() -> None:
    valid_request = SimpleNamespace(body=b'{"name":"value"}')
    invalid_json_request = SimpleNamespace(body=b"{not-json")

    data, error = request_utils.parse_json_body(valid_request)
    assert data == {"name": "value"}
    assert error is None

    data, error = request_utils.parse_json_body(invalid_json_request)
    assert data is None
    assert error is not None


def test_parse_json_body_returns_decode_error_when_body_is_not_utf8() -> None:
    request = SimpleNamespace(body=b"\xff")

    data, error = request_utils.parse_json_body(request)

    assert data is None
    assert error is not None
