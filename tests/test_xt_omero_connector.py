from __future__ import annotations

import importlib.util
import sys
import types


def _load_xt_module():
    tkinter_module = types.ModuleType("tkinter")
    tkinter_module.messagebox = types.SimpleNamespace()
    sys.modules.setdefault("tkinter", tkinter_module)

    spec = importlib.util.spec_from_file_location(
        "xt_omero_connector",
        "/opt/omero/XTOmeroConnector.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_create_request_with_cookies_relies_on_cookie_jar_for_get():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", "pass")
    client.session_id = "session-123"
    client.csrf_token = "csrf-123"

    request = client._create_request_with_cookies(
        "http://omero.example.org:4090/api/v0/m/projects/"
    )

    assert request.get_header("Cookie") is None
    assert request.get_header("User-agent") == "OMERO-ImarisXT/1.0"


def test_create_request_with_cookies_adds_csrf_headers_without_cookie_override():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", "pass")
    client.session_id = "session-123"
    client.csrf_token = "csrf-123"

    request = client._create_request_with_cookies(
        "http://omero.example.org:4090/api/v0/m/projects/",
        data=b"{}",
        method="POST",
    )

    assert request.get_header("Cookie") is None
    assert request.get_header("X-csrftoken") == "csrf-123"
    assert request.get_header("Referer") == client.base_url
