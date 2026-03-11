from __future__ import annotations

import importlib.util
import builtins
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


def test_resolve_imaris_application_uses_imarislib_factory(monkeypatch):
    module = _load_xt_module()
    expected = object()

    class _FakeImarisLibFactory:
        def GetApplication(self, app_id):
            assert app_id == 17
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=lambda: _FakeImarisLibFactory())
    monkeypatch.setitem(sys.modules, "ImarisLib", fake_module)

    assert module._resolve_imaris_application(17) is expected


def test_resolve_imaris_application_retries_until_handle_available(monkeypatch):
    module = _load_xt_module()
    expected = object()
    calls = {"count": 0}

    class _RetryingImarisLibFactory:
        def GetApplication(self, app_id):
            assert app_id == 17
            calls["count"] += 1
            if calls["count"] < 3:
                return None
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=lambda: _RetryingImarisLibFactory())
    monkeypatch.setitem(sys.modules, "ImarisLib", fake_module)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    assert module._resolve_imaris_application(17, retries=3, retry_interval=0.01) is expected
    assert calls["count"] == 3


def test_resolve_imaris_application_accepts_numeric_string(monkeypatch):
    module = _load_xt_module()
    expected = object()

    class _FakeImarisLibFactory:
        def GetApplication(self, app_id):
            assert app_id == 17
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=lambda: _FakeImarisLibFactory())
    monkeypatch.setitem(sys.modules, "ImarisLib", fake_module)

    assert module._resolve_imaris_application("17") is expected


def test_resolve_imaris_application_returns_none_when_bridge_import_fails(monkeypatch):
    module = _load_xt_module()

    real_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        if name == "ImarisLib":
            raise ImportError("IcePy missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    assert module._resolve_imaris_application(17) is None


def test_open_file_in_imaris_falls_back_to_imaris_executable(monkeypatch):
    module = _load_xt_module()
    launched = {}

    monkeypatch.setattr(module, "_find_imaris_executable", lambda: r"C:\Program Files\Bitplane\Imaris 11.0.0\Imaris.exe")

    def _fake_popen(args):
        launched["args"] = args
        return object()

    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)
    assert module.open_file_in_imaris("C:\\temp\\demo.ims", None) is True
    assert launched["args"] == [
        r"C:\Program Files\Bitplane\Imaris 11.0.0\Imaris.exe",
        "C:\\temp\\demo.ims",
    ]


def test_find_imaris_executable_prefers_env_override(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setenv("IMARIS_EXE", r"C:\Custom\Imaris.exe")
    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == r"C:\Custom\Imaris.exe")

    assert module._find_imaris_executable() == r"C:\Custom\Imaris.exe"


def test_resolve_imaris_application_returns_direct_handle():
    module = _load_xt_module()
    direct_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)

    assert module._resolve_imaris_application(direct_handle) is direct_handle
