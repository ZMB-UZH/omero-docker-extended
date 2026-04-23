from __future__ import annotations

import ast
import importlib.util
import builtins
import json
import ntpath
import os
import subprocess
import sys
import types
from pathlib import Path

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


TEST_LOGIN_VALUE = "test-login-value"
_TEST_CSRF_FIXTURE = "xref-session-123"
_TEST_BASE_URL = "{}://omero.example.org:4090".format("http")


class _FakeHTTPResponse:
    def __init__(self, body=b"", headers=None, final_url="https://omero.example.org/"):
        self._body = body
        self._offset = 0
        self.headers = headers or {}
        self._final_url = final_url
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self):
        return self._final_url


def test_xt_script_annotations_stay_python37_runtime_safe():
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=_XT_SCRIPT)
    unsupported = []
    builtin_generics = {"list", "dict", "tuple", "set", "frozenset", "type"}

    for node in ast.walk(tree):
        annotation = None
        if isinstance(node, ast.AnnAssign):
            annotation = node.annotation
        elif isinstance(node, ast.arg):
            annotation = node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotation = node.returns

        if annotation is None:
            continue

        for annotation_node in ast.walk(annotation):
            if isinstance(annotation_node, ast.BinOp) and isinstance(
                annotation_node.op, ast.BitOr
            ):
                unsupported.append(
                    f"line {annotation_node.lineno}: PEP 604 union annotation"
                )
            if (
                isinstance(annotation_node, ast.Subscript)
                and isinstance(annotation_node.value, ast.Name)
                and annotation_node.value.id in builtin_generics
            ):
                unsupported.append(
                    f"line {annotation_node.lineno}: builtin generic annotation"
                )

    assert unsupported == []


def test_create_request_with_cookies_relies_on_cookie_jar_for_get():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    client.csrf_token = _TEST_CSRF_FIXTURE

    request = client._create_request_with_cookies(
        "https://omero.example.org:4090/api/v0/m/projects/"
    )

    assert request.get_header("Cookie") is None
    assert request.get_header("User-agent") == "OMERO-ImarisXT/1.0"


def test_create_request_with_cookies_adds_csrf_headers_without_cookie_override():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
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


def test_client_detects_omero_ims_export_capability():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        @staticmethod
        def open(request, timeout):
            opened_urls.append((request.full_url, timeout))
            return _FakeHTTPResponse(b'{"omero_ims_export": true}')

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is True
    assert opened_urls == [
        (
            f"{_TEST_BASE_URL}/omeroweb_imaris_connector/imaris-export/?capabilities=1",
            30,
        )
    ]


def test_client_treats_non_object_capability_response_as_unavailable():
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        @staticmethod
        def open(_request, _timeout):
            return _FakeHTTPResponse(b"[]")

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is False


def test_client_download_original_file_uses_archived_files_endpoint_and_safe_name(
    tmp_path,
):
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        @staticmethod
        def open(request, timeout):
            opened_urls.append((request.full_url, timeout))
            return _FakeHTTPResponse(
                b"original bytes",
                headers={
                    "Content-Disposition": 'attachment; filename="../bad;marker=x.lif"',
                    "content-length": "14",
                },
            )

    client.opener = _FakeOpener()

    downloaded = client.download_original_file(17, str(tmp_path), "fallback.lif")

    assert opened_urls == [
        (
            f"{_TEST_BASE_URL}/webgateway/archived_files/download/17/",
            module.EXPORT_TIMEOUT + 60,
        )
    ]
    assert Path(downloaded).name == "bad_marker_x.lif"
    assert Path(downloaded).read_bytes() == b"original bytes"


def test_resolve_imaris_application_uses_imarislib_factory(monkeypatch):
    module = _load_xt_module()
    expected = object()

    class _FakeImarisLibFactory:
        @staticmethod
        def GetApplication(app_id):
            assert app_id == 17
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=_FakeImarisLibFactory)
    monkeypatch.setitem(sys.modules, "ImarisLib", fake_module)

    assert module._resolve_imaris_application(17) is expected


def test_resolve_imaris_application_retries_until_handle_available(monkeypatch):
    module = _load_xt_module()
    expected = object()
    calls = {"count": 0}

    class _RetryingImarisLibFactory:
        @staticmethod
        def GetApplication(app_id):
            assert app_id == 17
            calls["count"] += 1
            if calls["count"] < 3:
                return None
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=_RetryingImarisLibFactory)
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
        @staticmethod
        def GetApplication(app_id):
            assert app_id == 17
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=_FakeImarisLibFactory)
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


def test_open_file_in_imaris_uses_live_handle_for_valid_ims(tmp_path):
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    opened = []

    class _FakeImaris:
        @staticmethod
        def FileOpen(path, *_args):
            opened.append(path)

    assert module.open_file_in_imaris(ims_path, _FakeImaris()) is True
    assert opened == [str(ims_path)]


def test_open_file_in_imaris_rejects_non_ims_before_live_handle(tmp_path):
    module = _load_xt_module()
    plain_path = tmp_path / "plain.txt"
    plain_path.write_text("not ims", encoding="utf-8")
    opened = []

    class _FakeImaris:
        @staticmethod
        def FileOpen(path, *_args):
            opened.append(path)

    assert module.open_file_in_imaris(plain_path, _FakeImaris()) is False
    assert opened == []


def test_open_file_in_imaris_allows_original_file_for_imaris_converter(tmp_path):
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_text("native converter input", encoding="utf-8")
    opened = []

    class _FakeImaris:
        @staticmethod
        def FileOpen(path, *_args):
            opened.append(path)

    assert (
        module.open_file_in_imaris(original_path, _FakeImaris(), require_ims=False)
        is True
    )
    assert opened == [str(original_path)]


def test_open_file_in_imaris_does_not_launch_fallback_when_live_handle_fails(tmp_path):
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")

    class _FailingImaris:
        @staticmethod
        def FileOpen(_path, *_args):
            raise RuntimeError("bridge failed")

    assert module.open_file_in_imaris(ims_path, _FailingImaris()) is False


def test_parse_python_launcher_paths_handles_windows_launcher_output():
    module = _load_xt_module()
    output = """Installed Pythons found by C:\\Windows\\py.exe Launcher for Windows
 -3.9-64        C:\\Program Files\\Python39\\python.exe *
 -3.11-64       C:\\ProgramData\\anaconda3\\python.exe
"""

    assert module._parse_python_launcher_paths(output) == [
        r"C:\Program Files\Python39\python.exe",
        r"C:\ProgramData\anaconda3\python.exe",
    ]


def test_iter_native_bridge_python_executables_uses_py_launcher_and_skips_current(
    monkeypatch,
):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        module.sys, "executable", r"C:\Program Files\Python39\python.exe"
    )
    monkeypatch.setattr(
        module,
        "_iter_windows_python_launchers",
        lambda: iter([r"C:\Windows\py.exe"]),
    )
    resolved = {
        r"C:\Program Files\Python39\python.exe": r"C:\Program Files\Python39\python.exe",
        r"C:\ProgramData\anaconda3\python.exe": r"C:\ProgramData\anaconda3\python.exe",
    }
    monkeypatch.setattr(
        module,
        "_resolve_python_executable_candidate",
        lambda path: resolved.get(path),
    )

    def _fake_run(cmd, **kwargs):
        assert cmd == [r"C:\Windows\py.exe", "-0p"]
        assert kwargs["check"] is False
        assert kwargs["stdin"] is subprocess.DEVNULL
        return types.SimpleNamespace(
            returncode=0,
            stdout=(
                " -3.9-64        C:\\Program Files\\Python39\\python.exe *\n"
                " -3.11-64       C:\\ProgramData\\anaconda3\\python.exe\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert list(module._iter_native_bridge_python_executables()) == [
        r"C:\ProgramData\anaconda3\python.exe"
    ]


def test_native_bridge_runner_uses_fixed_python_command_and_json_payload(
    tmp_path, monkeypatch
):
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    python_exe = r"C:\ProgramData\anaconda3\python.exe"
    monkeypatch.setattr(
        module,
        "_resolve_python_executable_candidate",
        lambda path: python_exe if path == python_exe else None,
    )
    monkeypatch.setattr(
        module,
        "_iter_imaris_install_roots",
        lambda: [r"C:\Program Files\Bitplane\Imaris 11.0.0"],
    )
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = json.loads(kwargs["input"])
        assert cmd == [python_exe, "-c", module._NATIVE_BRIDGE_OPEN_HELPER]
        assert kwargs["check"] is False
        assert kwargs["universal_newlines"] is True
        assert "shell" not in kwargs
        assert payload["mode"] == "open"
        assert payload["file_path"] == str(ims_path)
        assert payload["require_ims"] is True
        assert payload["app_id"] == 17
        assert payload["install_roots"] == [r"C:\Program Files\Bitplane\Imaris 11.0.0"]
        return types.SimpleNamespace(
            returncode=0,
            stdout="BRIDGE_RUNNER_OPENED\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert module._run_native_bridge_open_helper(python_exe, ims_path, "17") is True
    assert len(calls) == 1


def test_native_bridge_runner_allows_original_file_when_ims_not_required(
    tmp_path, monkeypatch
):
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_bytes(b"native input")
    python_exe = r"C:\ProgramData\anaconda3\python.exe"
    monkeypatch.setattr(
        module,
        "_resolve_python_executable_candidate",
        lambda path: python_exe if path == python_exe else None,
    )
    monkeypatch.setattr(
        module,
        "_iter_imaris_install_roots",
        lambda: [r"C:\Program Files\Bitplane\Imaris 11.0.0"],
    )
    payloads = []

    def _fake_run(cmd, **kwargs):
        payloads.append(json.loads(kwargs["input"]))
        return types.SimpleNamespace(
            returncode=0,
            stdout="BRIDGE_RUNNER_OPENED\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert (
        module._run_native_bridge_open_helper(
            python_exe,
            original_path,
            "17",
            require_ims=False,
        )
        is True
    )
    assert payloads[0]["file_path"] == str(original_path)
    assert payloads[0]["require_ims"] is False


def test_native_bridge_probe_helper_checks_bridge_without_file_open(monkeypatch):
    module = _load_xt_module()
    python_exe = r"C:\ProgramData\anaconda3\python.exe"
    monkeypatch.setattr(
        module,
        "_resolve_python_executable_candidate",
        lambda path: python_exe if path == python_exe else None,
    )
    monkeypatch.setattr(
        module,
        "_iter_imaris_install_roots",
        lambda: [r"C:\Program Files\Bitplane\Imaris 11.0.0"],
    )

    def _fake_run(cmd, **kwargs):
        payload = json.loads(kwargs["input"])
        assert cmd == [python_exe, "-c", module._NATIVE_BRIDGE_OPEN_HELPER]
        assert payload["mode"] == "probe"
        assert "file_path" not in payload
        assert payload["app_id"] == 17
        return types.SimpleNamespace(
            returncode=0,
            stdout="BRIDGE_RUNNER_PROBE_OK\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert module._run_native_bridge_probe_helper(python_exe, "17") is True


def test_safe_download_filename_removes_paths_markers_and_reserved_names():
    module = _load_xt_module()

    assert (
        module._safe_download_filename(
            r"..\hidden\demo;marker=abc.lif",
            "fallback.lif",
        )
        == "demo_marker_abc.lif"
    )
    assert module._safe_download_filename("CON", "fallback.lif") == "_CON"
    assert module._safe_download_filename("..", "fallback.ims", ".ims") == (
        "fallback.ims"
    )
    assert module._safe_download_filename("", "img_1", ".ims") == "img_1.ims"


def test_native_bridge_runner_rejects_non_ims_before_subprocess(tmp_path, monkeypatch):
    module = _load_xt_module()
    plain_path = tmp_path / "plain.txt"
    plain_path.write_text("not ims", encoding="utf-8")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))

    assert (
        module._run_native_bridge_open_helper(
            r"C:\ProgramData\anaconda3\python.exe",
            plain_path,
            "17",
        )
        is False
    )
    assert calls == []


def test_native_bridge_runner_requires_numeric_imaris_id(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    attempts = []
    monkeypatch.setattr(
        module,
        "_iter_native_bridge_python_executables",
        lambda: iter([r"C:\ProgramData\anaconda3\python.exe"]),
    )
    monkeypatch.setattr(
        module,
        "_run_native_bridge_open_helper",
        lambda *args: attempts.append(args) or True,
    )

    assert (
        module._open_file_in_imaris_with_native_bridge_runner("demo.ims", None) is False
    )
    assert attempts == []


def test_native_bridge_runner_tries_discovered_python_until_success(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        module,
        "_iter_native_bridge_python_executables",
        lambda: iter(
            [
                r"C:\Program Files\Python39\python.exe",
                r"C:\ProgramData\anaconda3\python.exe",
            ]
        ),
    )
    monkeypatch.setattr(
        module, "_resolve_python_executable_candidate", lambda path: path
    )
    attempts = []

    def _fake_helper(python_executable, file_path, imaris_id, require_ims=True):
        attempts.append((python_executable, file_path, imaris_id, require_ims))
        return python_executable.endswith(r"anaconda3\python.exe")

    monkeypatch.setattr(module, "_run_native_bridge_open_helper", _fake_helper)

    assert (
        module._open_file_in_imaris_with_native_bridge_runner(
            r"C:\exports\demo.ims", "17"
        )
        is True
    )
    assert attempts == [
        (r"C:\Program Files\Python39\python.exe", r"C:\exports\demo.ims", "17", True),
        (r"C:\ProgramData\anaconda3\python.exe", r"C:\exports\demo.ims", "17", True),
    ]


def test_dialog_native_bridge_probe_runs_before_export_and_blocks_when_unavailable():
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = False
    dialog._native_bridge_python_executable = None
    dialog._native_bridge_probe_error = "bridge unavailable"
    status_updates = []
    dialog._set_status = lambda text, _color="#ecf0f1": status_updates.append(text)

    assert dialog._ensure_native_open_ready_before_export() is False
    assert status_updates == ["Checking native Imaris bridge..."]


def test_dialog_native_bridge_probe_does_not_trust_non_opening_handle():
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = object()
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = False
    dialog._native_bridge_probe_error = "bridge unavailable"
    status_updates = []
    dialog._set_status = lambda text, _color="#ecf0f1": status_updates.append(text)

    assert dialog._ensure_native_open_ready_before_export() is False
    assert status_updates == ["Checking native Imaris bridge..."]


def test_dialog_native_bridge_probe_uses_cached_python_for_open(monkeypatch):
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_python_executable = r"C:\ProgramData\anaconda3\python.exe"
    dialog._set_status = lambda *_args, **_kwargs: None
    attempts = []
    monkeypatch.setattr(
        module,
        "_resolve_imaris_application",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        module,
        "_open_file_in_imaris_with_native_bridge_runner",
        lambda file_path, imaris_id, preferred_python_executable=None, require_ims=True: (
            attempts.append(
                (file_path, imaris_id, preferred_python_executable, require_ims)
            )
            or True
        ),
    )

    assert dialog._open_downloaded_file_in_imaris(r"C:\exports\demo.ims") is True
    assert attempts == [
        (
            r"C:\exports\demo.ims",
            "17",
            r"C:\ProgramData\anaconda3\python.exe",
            True,
        )
    ]


def test_detect_converter_options_defaults_omero_when_server_supports_it():
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog._start_native_bridge_probe = lambda: None
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: True)

    assert dialog._detect_converter_options_after_connection() == ["OMERO", "Imaris"]


def test_detect_converter_options_hides_omero_without_server_capability():
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog._start_native_bridge_probe = lambda: None
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: False)

    assert dialog._detect_converter_options_after_connection() == ["Imaris"]


def test_detect_converter_options_hides_dropdown_when_native_open_unavailable():
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = False
    dialog._native_bridge_probe_error = "bridge unavailable"
    dialog._start_native_bridge_probe = lambda: None
    dialog.client = types.SimpleNamespace(
        has_omero_ims_export_capability=lambda: (_ for _ in ()).throw(
            AssertionError("server capability must not be checked")
        )
    )

    assert dialog._detect_converter_options_after_connection() == []


def test_set_converter_options_hides_dropdown_and_disables_load():
    module = _load_xt_module()

    class DummyMenu:
        def __init__(self):
            self.deleted = False

        def delete(self, start, end):
            self.deleted = (start, end)

        def add_command(self, label, command):
            raise AssertionError("no command should be added without options")

    class DummyFrame:
        def __init__(self):
            self.hidden = False

        def pack_forget(self):
            self.hidden = True

    class DummyButton:
        def __init__(self):
            self.state = None

        def config(self, **kwargs):
            self.state = kwargs["state"]

    class DummyVar:
        def __init__(self):
            self.value = "OMERO"

        def set(self, value):
            self.value = value

    menu = DummyMenu()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_menu = {"menu": menu}
    dialog.converter_var = DummyVar()
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = DummyButton()

    module.OMEROBrowserDialog._set_converter_options(dialog, [])

    assert menu.deleted == (0, "end")
    assert dialog.converter_var.value == ""
    assert dialog.converter_frame.hidden is True
    assert dialog.load_btn.state == "disabled"


def test_load_worker_imaris_converter_downloads_original_without_ims_check(tmp_path):
    module = _load_xt_module()
    original_file = tmp_path / "sample.lif"
    original_file.write_bytes(b"native input")
    calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_original_file=lambda image_id, download_dir, fallback_name: (
            calls.append(("original", image_id, Path(download_dir).name, fallback_name))
            or str(original_file)
        ),
        download_ims_export=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("OMERO converter must not run")
        ),
    )
    dialog._ensure_native_open_ready_before_export = lambda: True
    dialog._set_status = lambda *_args, **_kwargs: None
    dialog._show_info = lambda *_args, **_kwargs: None
    dialog._show_error = lambda *_args, **_kwargs: None
    dialog._reenable_load_button = lambda: None
    dialog._invoke_on_ui_thread = lambda callback, wait=True: (
        None if not wait else callback()
    )
    opened = []
    dialog._open_downloaded_file_in_imaris = lambda path, require_ims=True: (
        opened.append((path, require_ims)) or True
    )

    module.OMEROBrowserDialog._load_worker(
        dialog,
        {"id": 7, "name": "sample.lif"},
        "Imaris",
    )

    assert calls == [("original", 7, "img_7", "sample.lif")]
    assert opened == [(str(original_file), False)]
    assert dialog.temp_files == [str(original_file)]


def test_load_worker_omero_converter_downloads_ims_and_requires_ims(tmp_path):
    module = _load_xt_module()
    ims_file = tmp_path / "sample.ims"
    ims_file.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_ims_export=lambda image_id, download_dir, fallback_name: (
            calls.append(("ims", image_id, Path(download_dir).name, fallback_name))
            or str(ims_file)
        ),
        download_original_file=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Imaris converter must not run")
        ),
    )
    dialog._ensure_native_open_ready_before_export = lambda: True
    dialog._set_status = lambda *_args, **_kwargs: None
    dialog._show_info = lambda *_args, **_kwargs: None
    dialog._show_error = lambda *_args, **_kwargs: None
    dialog._reenable_load_button = lambda: None
    dialog._invoke_on_ui_thread = lambda callback, wait=True: (
        None if not wait else callback()
    )
    opened = []
    dialog._open_downloaded_file_in_imaris = lambda path, require_ims=True: (
        opened.append((path, require_ims)) or True
    )

    module.OMEROBrowserDialog._load_worker(
        dialog,
        {"id": 8, "name": "sample"},
        "OMERO",
    )

    assert calls == [("ims", 8, "img_8", "img_8.ims")]
    assert opened == [(str(ims_file), True)]
    assert dialog.temp_files == [str(ims_file)]


def test_load_worker_blocks_before_download_when_native_open_unavailable(tmp_path):
    module = _load_xt_module()
    download_calls = []
    errors = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_ims_export=lambda *_args, **_kwargs: download_calls.append("ims"),
        download_original_file=lambda *_args, **_kwargs: download_calls.append(
            "original"
        ),
    )
    dialog._ensure_native_open_ready_before_export = lambda: False
    dialog._set_status = lambda *_args, **_kwargs: None
    dialog._show_info = lambda *_args, **_kwargs: None
    dialog._show_error = lambda _title, message: errors.append(message)
    dialog._reenable_load_button = lambda: None
    dialog._invoke_on_ui_thread = lambda callback, wait=True: (
        None if not wait else callback()
    )

    module.OMEROBrowserDialog._load_worker(
        dialog,
        {"id": 9, "name": "sample"},
        "OMERO",
    )

    assert download_calls == []
    assert len(errors) == 1
    assert "Download/conversion was not started" in errors[0]


def test_set_process_window_title_uses_windows_api_without_shell(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)

    class _FakeKernel32:
        calls = []

        @classmethod
        def SetConsoleTitleW(cls, title):
            cls.calls.append(title)
            return 1

    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=_FakeKernel32)
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert module._set_process_window_title("OMERO Connector") is True
    assert _FakeKernel32.calls == ["OMERO Connector"]


def test_is_ims_file_accepts_only_existing_regular_hdf5_files(tmp_path):
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")

    assert module.is_ims_file(ims_path) is True
    assert module.is_ims_file(tmp_path / "plain.txt") is False
    assert module.is_ims_file(tmp_path) is False
    assert module.is_ims_file(None) is False
    assert module.is_ims_file(b"demo.ims") is False
    assert module.is_ims_file(f"{ims_path}\x00suffix") is False


def test_xt_write_log_accepts_only_connector_logs_in_temp_root(tmp_path, monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))

    log_path = Path(module._xt_log_path())
    module._xt_write_log(str(log_path), "first line")
    assert log_path.read_text(encoding="utf-8") == "first line\n"

    outside_path = tmp_path.parent / "XTOmeroConnector_outside.log"
    module._xt_write_log(str(outside_path), "outside")
    assert not outside_path.exists()

    wrong_name = tmp_path / "unrelated.log"
    module._xt_write_log(str(wrong_name), "wrong name")
    assert not wrong_name.exists()

    symlink_path = tmp_path / "XTOmeroConnector_link.log"
    symlink_target = tmp_path.parent / "connector-link-target.log"
    symlink_path.symlink_to(symlink_target)
    module._xt_write_log(str(symlink_path), "through symlink")
    assert not symlink_target.exists()


def test_browser_dialog_reenable_load_button_uses_normal_state():
    module = _load_xt_module()
    module.tk.NORMAL = "normal"
    states = []
    dialog = types.SimpleNamespace(
        load_btn=types.SimpleNamespace(
            config=lambda **kwargs: states.append(kwargs["state"])
        )
    )

    module.OMEROBrowserDialog._reenable_load_button(dialog)

    assert states == ["normal"]


def test_browser_dialog_invoke_on_ui_thread_returns_callback_value():
    module = _load_xt_module()

    class _Root:
        @staticmethod
        def after(_delay, callback):
            callback()

    dialog = types.SimpleNamespace(root=_Root())

    assert (
        module.OMEROBrowserDialog._invoke_on_ui_thread(
            dialog,
            lambda: "callback-result",
        )
        == "callback-result"
    )


def test_browser_dialog_invoke_on_ui_thread_reraises_callback_error():
    module = _load_xt_module()

    class _Root:
        @staticmethod
        def after(_delay, callback):
            callback()

    dialog = types.SimpleNamespace(root=_Root())

    try:
        module.OMEROBrowserDialog._invoke_on_ui_thread(
            dialog,
            lambda: (_ for _ in ()).throw(RuntimeError("callback failed")),
        )
    except RuntimeError as exc:
        assert str(exc) == "callback failed"
    else:
        raise AssertionError("expected RuntimeError from callback")


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
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\private",
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\private\Ice",
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
    assert r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\private" in added_paths
    assert (
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\private\Ice"
        in added_dll_dirs
    )
    assert r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\DLLs" in added_dll_dirs
    module.sys.path[:] = original_sys_path
    monkeypatch.setattr(module.os, "path", original_os_path, raising=False)


def test_collect_imaris_xt_diagnostics_reports_import_failures(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "path", ntpath, raising=False)
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
    diagnostic_paths = {entry["path"] for entry in diagnostics["xt_candidate_paths"]}

    assert diagnostics["python_version_short"]
    assert diagnostics["imaris_executable_exists"] is True
    assert "has_add_dll_directory" in diagnostics
    assert (
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\private"
        in diagnostic_paths
    )
    assert (
        r"C:\Program Files\Bitplane\Imaris 11.0.0\XT\python3\private\Ice"
        in diagnostic_paths
    )
    assert diagnostics["imarislib_import"]["ok"] is False
    assert diagnostics["icepy_import"]["ok"] is False


def test_resolve_imaris_application_returns_direct_handle():
    module = _load_xt_module()
    direct_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)

    assert module._resolve_imaris_application(direct_handle) is direct_handle
