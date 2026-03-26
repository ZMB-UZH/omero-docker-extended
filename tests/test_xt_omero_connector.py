from __future__ import annotations

import importlib.util
import builtins
import ntpath
import os
import sys
import types

_XT_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "XTOmeroConnector.py",
)


def _load_xt_module():
    tkinter_module = types.ModuleType("tkinter")
    tkinter_module.messagebox = types.SimpleNamespace()
    sys.modules.setdefault("tkinter", tkinter_module)

    spec = importlib.util.spec_from_file_location(
        "xt_omero_connector",
        _XT_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


TEST_AUTH_VALUE = "test-fixture-auth"
_TEST_CSRF_FIXTURE = "xref-session-123"


def test_create_request_with_cookies_relies_on_cookie_jar_for_get():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_AUTH_VALUE)
    client.session_id = "session-123"
    client.csrf_token = _TEST_CSRF_FIXTURE

    request = client._create_request_with_cookies(
        "https://omero.example.org:4090/api/v0/m/projects/"
    )

    assert request.get_header("Cookie") is None
    assert request.get_header("User-agent") == "OMERO-ImarisXT/1.0"


def test_create_request_with_cookies_adds_csrf_headers_without_cookie_override():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_AUTH_VALUE)
    client.session_id = "session-123"
    client.csrf_token = _TEST_CSRF_FIXTURE

    request = client._create_request_with_cookies(
        "https://omero.example.org:4090/api/v0/m/projects/",
        data=b"{}",
        method="POST",
    )

    assert request.get_header("Cookie") is None
    assert request.get_header("X-csrftoken") == _TEST_CSRF_FIXTURE
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

    assert (
        module._resolve_imaris_application(17, retries=3, retry_interval=0.01)
        is expected
    )
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


def test_open_file_in_imaris_returns_false_without_handle():
    module = _load_xt_module()
    assert module.open_file_in_imaris("C:\\temp\\demo.ims", None) is False


def test_find_imaris_executable_prefers_env_override(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setenv("IMARIS_EXE", r"C:\Custom\Imaris.exe")
    monkeypatch.setattr(
        module.os.path, "isfile", lambda path: path == r"C:\Custom\Imaris.exe"
    )

    assert module._find_imaris_executable() == r"C:\Custom\Imaris.exe"


def test_prepare_imaris_xt_environment_adds_bundled_paths(monkeypatch):
    module = _load_xt_module()
    original_sys_path = list(module.sys.path)
    original_os_path = module.os.path
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setattr(module.os, "path", ntpath, raising=False)
    monkeypatch.setenv("IMARIS_HOME", r"C:\Program Files\Bitplane\Imaris 11.0.0")
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    existing_dirs = {
        r"C:\Program Files\Bitplane\Imaris 11.0.0",
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT",
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3",
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\DLLs",
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\Lib",
    }
    monkeypatch.setattr(
        module.os.path,
        "isdir",
        lambda path: module.os.path.normpath(path) in existing_dirs,
    )
    added_dll_dirs = []
    monkeypatch.setattr(
        module.os,
        "add_dll_directory",
        lambda path: (
            added_dll_dirs.append(module.os.path.normpath(path)) or f"handle:{path}"
        ),
        raising=False,
    )

    prepared = module._prepare_imaris_xt_environment()
    added_paths = prepared["paths"]

    assert r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3" in added_paths
    assert module.sys.path[0] in added_paths
    assert (
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3"
        in module.os.environ["PATH"]
    )
    assert (
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\DLLs"
        in prepared["dll_dirs"]
    )
    assert r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\DLLs" in added_dll_dirs
    module.sys.path[:] = original_sys_path
    monkeypatch.setattr(module.os, "path", original_os_path, raising=False)


def test_collect_imaris_xt_diagnostics_reports_import_failures(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(
        module,
        "_find_imaris_executable",
        lambda: r"C:\Program Files\Bitplane\Imaris 11.0.0\Imaris.exe",
    )
    monkeypatch.setattr(
        module,
        "_iter_imaris_install_roots",
        lambda: [r"C:\Program Files\Bitplane\Imaris 11.0.0"],
    )
    monkeypatch.setattr(
        module,
        "_safe_path_exists",
        lambda path: path.endswith("Imaris.exe") or path.endswith(r"\XT"),
    )

    original_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        if name == "ImarisLib":
            raise ImportError("ImarisLib missing")
        if name == "IcePy":
            raise ImportError("IcePy missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    diagnostics = module._collect_imaris_xt_diagnostics()

    assert diagnostics["python_version_short"]
    assert diagnostics["imaris_executable_exists"] is True
    assert "has_add_dll_directory" in diagnostics
    assert diagnostics["imarislib_import"]["ok"] is False
    assert diagnostics["icepy_import"]["ok"] is False


def test_resolve_imaris_application_returns_direct_handle():
    module = _load_xt_module()
    direct_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)

    assert module._resolve_imaris_application(direct_handle) is direct_handle
