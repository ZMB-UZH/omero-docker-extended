from __future__ import annotations

import json
from types import SimpleNamespace

from django.conf import settings
from django.test import RequestFactory

from omeroweb_omp_plugin.views import utils


def test_load_json_body_and_require_non_root_user(monkeypatch):
    """Verify load JSON body and require non root user.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in load JSON body and require non root user.
    """
    request = RequestFactory().post(
        "/",
        data=json.dumps({"value": 1}),
        content_type="application/json",
    )
    payload, error = utils.load_json_body(request)
    assert payload == {"value": 1}
    assert error is None

    bad_request = RequestFactory().post("/", data="{", content_type="application/json")
    payload, error = utils.load_json_body(bad_request)
    assert payload is None
    assert error == utils.errors.invalid_json_body()

    blocked = {}
    root_view = utils.require_non_root_user(
        lambda request, conn=None, url=None, **kwargs: (
            blocked.update({"conn": conn, "url": url, "kwargs": kwargs})
            or SimpleNamespace(status_code=200)
        )
    )
    monkeypatch.setattr(utils, "current_username", lambda request, conn: "root")
    forbidden = root_view(RequestFactory().get("/"), conn=object())
    assert forbidden.status_code == 403

    monkeypatch.setattr(utils, "current_username", lambda request, conn: "")
    unresolved = root_view(RequestFactory().get("/"), conn=object())
    assert unresolved.status_code == 403
    assert (
        json.loads(unresolved.content)["error"]
        == utils.errors.unable_to_determine_username()
    )

    monkeypatch.setattr(utils, "current_username", lambda request, conn: "alice")
    allowed = root_view(RequestFactory().get("/"), conn="conn", url="/api", flag=True)
    assert allowed.status_code == 200
    assert blocked == {"conn": "conn", "url": "/api", "kwargs": {"flag": True}}

    positional_allowed = root_view(RequestFactory().get("/"), "conn-2", "/api-2")
    assert positional_allowed.status_code == 200
    assert blocked == {"conn": "conn-2", "url": "/api-2", "kwargs": {}}


def test_resolve_omero_host_port_prefers_connection_then_settings_then_env(monkeypatch):
    """Verify resolve OMERO host port prefers connection then settings then env.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve OMERO host port prefers connection then settings then env.
    """
    assert utils.resolve_omero_host_port(
        SimpleNamespace(host="omero", port="4064")
    ) == (
        "omero",
        4064,
    )

    monkeypatch.setattr(settings, "OMERO_HOST", "settings-host", raising=False)
    monkeypatch.setattr(settings, "OMERO_PORT", "14064", raising=False)
    monkeypatch.setattr(
        utils,
        "get_env",
        lambda key, env_file=None: {
            "OMEROHOST": "env-host",
            "OMERO_PORT": "24064",
        }[key],
    )
    assert utils.resolve_omero_host_port(SimpleNamespace(host=None, port=None)) == (
        "settings-host",
        14064,
    )

    monkeypatch.delattr(settings, "OMERO_HOST", raising=False)
    monkeypatch.delattr(settings, "OMERO_PORT", raising=False)
    assert utils.resolve_omero_host_port(SimpleNamespace(host=None, port=None)) == (
        "env-host",
        24064,
    )

    assert utils.resolve_omero_host_port(SimpleNamespace(host="omero", port="bad")) == (
        "omero",
        None,
    )


def test_validate_user_password_without_session_cli_helpers(monkeypatch):
    """Check validate user password without exposing session CLI helpers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in password validation.
    when validation or the called operation fails.
    """
    monkeypatch.setattr(utils, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(utils, "resolve_omero_host_port", lambda conn: ("omero", 4064))

    class SuccessfulClient:
        """Test double for successful client behavior in this module."""

        def __init__(self):
            """Create `SuccessfulClient` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.closed = False
            self.calls = []

        def createSession(self, username, password):
            """Create the session for `SuccessfulClient`.

            Inputs: `username` username, `password` password. Output: None.
            """
            self.calls.append((username, password))

        def closeSession(self):
            """Close the session for `SuccessfulClient`.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self.closed = True

    client = SuccessfulClient()
    monkeypatch.setattr(utils.omero, "client", lambda host, port: client, raising=False)
    valid, error = utils.validate_user_password(SimpleNamespace(), "secret")
    assert valid is True
    assert error is None
    assert client.calls == [("alice", "secret")]
    assert client.closed is True

    missing, error = utils.validate_user_password(SimpleNamespace(), "")
    assert missing is False
    assert error == utils.errors.missing_password()

    monkeypatch.setattr(utils, "resolve_omero_host_port", lambda conn: (None, None))
    unavailable, error = utils.validate_user_password(SimpleNamespace(), "secret")
    assert unavailable is False
    assert error == utils.errors.validation_unavailable()

    monkeypatch.setattr(utils, "resolve_omero_host_port", lambda conn: ("omero", 4064))

    class FailingClient:
        """Test double for failing client behavior in this module."""

        @staticmethod
        def createSession(username, password):
            """Create the session for `FailingClient`.

            Inputs: `username` username, `password` password. Output: None. Raises:
            RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("bad password")

        @staticmethod
        def closeSession():
            """Close the session for `FailingClient`.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    monkeypatch.setattr(utils.omero, "client", lambda host, port: FailingClient())
    invalid, error = utils.validate_user_password(SimpleNamespace(), "wrong")
    assert invalid is False
    assert error == utils.errors.wrong_password()


def test_view_utils_do_not_expose_session_key_cli_helpers():
    """Verify view utilities do not expose session-key CLI helpers.

    Inputs: OMP view utilities. Output: asserts session-key argv helpers are absent.
    """
    assert not hasattr(utils, "get_session_key")
    assert not hasattr(utils, "build_omero_cli_base_command")
