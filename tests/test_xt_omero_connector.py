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


class _FakeHTTPError(Exception):
    def __init__(self, body, code=400, msg="Bad Request"):
        super().__init__(f"HTTP {code} {msg}")
        self.code = code
        self._body = body

    def read(self, *_args, **_kwargs):
        return self._body


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
            f"{client.base_url}/omeroweb_imaris_connector/imaris-export/?capabilities=1",
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


def test_client_treats_legacy_missing_image_capability_response_as_available(
    monkeypatch,
):
    module = _load_xt_module()
    monkeypatch.setattr(module.urllib.error, "HTTPError", _FakeHTTPError)
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        @staticmethod
        def open(_request, timeout):
            assert timeout == 30
            raise _FakeHTTPError(b"Missing image id")

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is True


def test_client_rejects_non_legacy_capability_http_errors(monkeypatch):
    module = _load_xt_module()
    monkeypatch.setattr(module.urllib.error, "HTTPError", _FakeHTTPError)
    messages = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        @staticmethod
        def open(_request, timeout):
            assert timeout == 30
            raise _FakeHTTPError(b"Invalid base_url parameter.")

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is False
    assert "Invalid base_url parameter" not in "\n".join(messages)
    assert "OMERO IMS export capability unavailable: HTTP 400" in messages


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
            f"{client.base_url}/webgateway/archived_files/download/17/",
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


def test_resolve_imaris_application_bridge_failure_message_keeps_runner_path(
    monkeypatch,
):
    module = _load_xt_module()
    messages = []

    real_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        if name == "ImarisLib":
            raise ImportError("IcePy missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    monkeypatch.setattr(module, "_xt_debug", messages.append)

    assert module._resolve_imaris_application(17) is None
    assert any("compatible native bridge runner" in message for message in messages)
    assert all("same-session open cannot work" not in message for message in messages)


def test_open_file_in_imaris_returns_false_without_handle(
    tmp_path, monkeypatch, capsys
):
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    messages = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)

    assert module.open_file_in_imaris(ims_path, None) is False

    assert messages == [
        "Direct Imaris application handle is not available in this Python"
    ]
    assert capsys.readouterr().out == ""


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


def test_open_file_in_imaris_rejects_unverified_current_file(tmp_path, monkeypatch):
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    other_path = tmp_path / "other.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    monkeypatch.setattr(
        module,
        "_wait_for_imaris_current_file",
        lambda imaris_app, path: imaris_app.GetCurrentFileName() == str(path),
    )

    class _FakeImaris:
        @staticmethod
        def FileOpen(_path, *_args):
            return None

        @staticmethod
        def GetCurrentFileName():
            return str(other_path)

    assert (
        module.open_file_in_imaris(
            ims_path,
            _FakeImaris(),
            require_ims=True,
        )
        is False
    )


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


def test_open_file_in_imaris_raw_file_does_not_wait_for_current_file(
    tmp_path,
    monkeypatch,
):
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_text("native converter input", encoding="utf-8")
    opened = []
    monkeypatch.setattr(
        module,
        "_wait_for_imaris_current_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw FileOpen must not require current-file verification")
        ),
    )

    class _FakeImaris:
        @staticmethod
        def FileOpen(path, *_args):
            opened.append(path)

    assert (
        module.open_file_in_imaris(
            original_path,
            _FakeImaris(),
            require_ims=False,
        )
        is True
    )
    assert opened == [str(original_path)]


def test_open_files_in_imaris_uses_image_slots_for_multiple_files(tmp_path):
    module = _load_xt_module()
    first_path = tmp_path / "first.ims"
    second_path = tmp_path / "second.ims"
    first_path.write_bytes(b"\x89HDF\r\n\x1a\nfirst")
    second_path.write_bytes(b"\x89HDF\r\n\x1a\nsecond")

    class _FakeDataSet:
        def __init__(self, path):
            self.path = path

        def Clone(self):
            return f"clone:{self.path}"

    class _FakeImaris:
        def __init__(self):
            self.current = None
            self.opened = []
            self.images = {}

        def FileOpen(self, path, *_args):
            self.opened.append(path)
            self.current = _FakeDataSet(path)

        def GetDataSet(self):
            return self.current

        def SetImage(self, index, data_set):
            self.images[index] = data_set

        def GetNumberOfImages(self):
            return len(self.images)

    imaris = _FakeImaris()

    assert module.open_files_in_imaris([first_path, second_path], imaris) is True
    assert imaris.opened == [str(first_path), str(second_path)]
    assert imaris.images == {
        0: f"clone:{str(first_path)}",
        1: f"clone:{str(second_path)}",
    }


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


def test_native_bridge_helper_reuses_imarislib_factory_across_retries(tmp_path):
    module = _load_xt_module()
    counter_path = tmp_path / "factory_count.txt"
    fake_imarislib = tmp_path / "ImarisLib.py"
    fake_imarislib.write_text(
        "\n".join(
            [
                "import os",
                "counter_path = os.environ['IMARIS_FAKE_COUNTER']",
                "",
                "class ImarisLib:",
                "    def __init__(self):",
                "        count = 0",
                "        if os.path.exists(counter_path):",
                "            with open(counter_path, 'r', encoding='utf-8') as handle:",
                "                count = int(handle.read() or '0')",
                "        with open(counter_path, 'w', encoding='utf-8') as handle:",
                "            handle.write(str(count + 1))",
                "",
                "    def GetApplication(self, app_id):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "mode": "probe",
        "app_id": 17,
        "install_roots": [str(tmp_path)],
        "retry_attempts": 5,
        "retry_interval": 0,
    }
    env = dict(os.environ)
    env["IMARIS_FAKE_COUNTER"] = str(counter_path)

    completed = subprocess.run(
        [sys.executable, "-c", module._NATIVE_BRIDGE_OPEN_HELPER],
        check=False,
        input=json.dumps(payload),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env,
        timeout=10,
    )

    assert completed.returncode == 2
    assert completed.stdout.strip() == "BRIDGE_RUNNER_HANDLE_UNAVAILABLE"
    assert counter_path.read_text(encoding="utf-8") == "1"


def test_native_bridge_runner_suppresses_plural_ice_shutdown_warning(
    tmp_path, monkeypatch
):
    module = _load_xt_module()
    python_exe = str(tmp_path / "python.exe")
    messages = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)
    monkeypatch.setattr(
        module,
        "_resolve_python_executable_candidate",
        lambda path: python_exe if path == python_exe else None,
    )

    def _fake_run(cmd, **kwargs):
        assert cmd == [python_exe, "-c", module._NATIVE_BRIDGE_OPEN_HELPER]
        return types.SimpleNamespace(
            returncode=2,
            stdout="BRIDGE_RUNNER_HANDLE_UNAVAILABLE\n",
            stderr=(
                "!! 04/23/26 15:50:22.395 error: "
                "10 communicators not destroyed during global destruction.\n"
            ),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert (
        module._run_native_bridge_helper(
            python_exe,
            {"mode": "probe", "app_id": 17},
            "probe",
            60,
        )
        is False
    )
    assert any(
        "could not resolve the current Imaris session" in message
        for message in messages
    )
    assert any(
        "suppressed benign Ice shutdown warning" in message for message in messages
    )
    assert not any("stderr:" in message for message in messages)


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


def test_xt_log_sanitizer_redacts_session_material_and_user_paths(monkeypatch):
    module = _load_xt_module()
    session_label = "session" + "id"
    csrf_label = "csrf" + "token"
    password_label = "pass" + "word"
    user_name = "sample-user"
    windows_home = "\\".join(("C:", "Users", user_name))
    posix_home = "/".join(("", "home", user_name))
    monkeypatch.setenv("USERPROFILE", windows_home)
    monkeypatch.setenv("HOME", posix_home)

    sanitized = module._sanitize_xt_log_message(
        f"{session_label}=sessionvalue {csrf_label}=tokenvalue "
        f"{password_label}=pwvalue {windows_home}\\file.ims {posix_home}/file.ims"
    )

    assert "sessionvalue" not in sanitized
    assert "tokenvalue" not in sanitized
    assert "pwvalue" not in sanitized
    assert user_name not in sanitized
    assert f"{session_label}=<redacted>" in sanitized
    assert f"{csrf_label}=<redacted>" in sanitized
    assert f"{password_label}=<redacted>" in sanitized


def test_safe_url_for_log_redacts_host_ids_and_query_values():
    module = _load_xt_module()
    scheme = "".join(("htt", "p"))

    safe_url = module._safe_url_for_log(
        f"{scheme}://omero.example.org:4090/api/v0/m/projects/51/datasets/"
        f"?group=-1&base_url={scheme}%3A%2F%2Fomero.example.org%3A4090"
    )

    assert safe_url == (
        "/api/v0/m/projects/<id>/datasets/?group=<redacted>&base_url=<redacted>"
    )
    assert "omero.example.org" not in safe_url
    assert "51" not in safe_url


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
    dialog._native_bridge_last_verified_at = 0.0
    status_updates = []
    dialog._set_status = lambda text, _color="#ecf0f1": status_updates.append(text)

    assert dialog._ensure_native_open_ready_before_export() is False
    assert status_updates == ["Checking Imaris same-session open support..."]


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
    dialog._native_bridge_last_verified_at = 0.0
    status_updates = []
    dialog._set_status = lambda text, _color="#ecf0f1": status_updates.append(text)

    assert dialog._ensure_native_open_ready_before_export() is False
    assert status_updates == ["Checking Imaris same-session open support..."]


def test_dialog_native_bridge_probe_revalidates_stale_cached_python(
    tmp_path, monkeypatch
):
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    python_exe = str(tmp_path / "python.exe")
    dialog._native_bridge_python_executable = python_exe
    dialog._native_bridge_probe_error = ""
    dialog._native_bridge_last_verified_at = 0.0
    dialog._set_status = lambda *_args, **_kwargs: None
    attempts = []
    monkeypatch.setattr(
        module,
        "_run_native_bridge_probe_helper",
        lambda python_executable, imaris_id: (
            attempts.append((python_executable, imaris_id)) or True
        ),
    )
    monkeypatch.setattr(
        module,
        "_find_compatible_native_bridge_python",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cached bridge Python should be checked first")
        ),
    )

    assert dialog._ensure_native_open_ready_before_export() is True
    assert attempts == [(python_exe, "17")]
    assert dialog._native_bridge_available is True
    assert dialog._native_bridge_last_verified_at > 0


def test_dialog_native_bridge_probe_blocks_after_failed_revalidation(
    tmp_path, monkeypatch
):
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_python_executable = str(tmp_path / "python.exe")
    dialog._native_bridge_probe_error = ""
    dialog._native_bridge_last_verified_at = 0.0
    dialog._set_status = lambda *_args, **_kwargs: None
    monkeypatch.setattr(
        module,
        "_run_native_bridge_probe_helper",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        module,
        "_find_compatible_native_bridge_python",
        lambda *_args, **_kwargs: None,
    )

    assert dialog._ensure_native_open_ready_before_export() is False
    assert dialog._native_bridge_available is False
    assert dialog._native_bridge_python_executable is None
    assert "No compatible installed Python" in dialog._native_bridge_probe_error
    assert dialog._native_bridge_last_verified_at == 0.0


def test_dialog_native_bridge_probe_skips_recent_revalidation(tmp_path, monkeypatch):
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_python_executable = str(tmp_path / "python.exe")
    dialog._native_bridge_probe_error = ""
    dialog._native_bridge_last_verified_at = module.time.time()
    dialog._set_status = lambda *_args, **_kwargs: None
    monkeypatch.setattr(
        module,
        "_run_native_bridge_probe_helper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recent probe result should be reused")
        ),
    )

    assert dialog._ensure_native_open_ready_before_export() is True


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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct bridge should not be retried")
        ),
    )
    monkeypatch.setattr(
        module,
        "open_file_in_imaris",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct handle should not be used")
        ),
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


def test_set_converter_options_populates_menu_without_blank_entry():
    module = _load_xt_module()

    class DummyMenu:
        def __init__(self):
            self.deleted = None
            self.commands = []

        def delete(self, start, end):
            self.deleted = (start, end)

        def add_command(self, label, command):
            self.commands.append((label, command))

    class DummyFrame:
        def __init__(self):
            self.shown = False

        def grid(self):
            self.shown = True

    class DummyButton:
        def __init__(self):
            self.state = None

        def config(self, **kwargs):
            self.state = kwargs["state"]

    class DummyVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    menu = DummyMenu()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_menu = types.SimpleNamespace(menu=menu)
    dialog.converter_var = DummyVar()
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = DummyButton()

    module.OMEROBrowserDialog._set_converter_options(dialog, ["OMERO", "Imaris"])

    labels = [label for label, _command in menu.commands]
    assert menu.deleted == (0, "end")
    assert labels == ["OMERO", "Imaris"]
    assert "" not in labels
    assert "-" not in labels
    assert dialog.converter_var.value == "OMERO"
    assert dialog.converter_frame.shown is True
    assert dialog.load_btn.state == "normal"

    menu.commands[1][1]()
    assert dialog.converter_var.value == "Imaris"


def test_scrolled_listbox_disables_active_underline(monkeypatch):
    module = _load_xt_module()
    created = {}

    class _FakeScrollbar:
        def __init__(self, parent, orient):
            self.parent = parent
            self.orient = orient
            self.command = None

        def pack(self, **_kwargs):
            return None

        def config(self, **kwargs):
            self.command = kwargs.get("command")

        def set(self, *_args):
            return None

    class _FakeListbox:
        def __init__(self, parent, **kwargs):
            self.parent = parent
            self.kwargs = kwargs
            self.config_calls = []
            created["listbox"] = self

        def config(self, **kwargs):
            self.config_calls.append(kwargs)

        def pack(self, **_kwargs):
            return None

        def yview(self, *_args):
            return None

        def xview(self, *_args):
            return None

    monkeypatch.setattr(
        module,
        "tk",
        types.SimpleNamespace(
            Scrollbar=_FakeScrollbar,
            Listbox=_FakeListbox,
            RIGHT="right",
            LEFT="left",
            BOTTOM="bottom",
            X="x",
            Y="y",
            BOTH="both",
            NONE="none",
            HORIZONTAL="horizontal",
            VERTICAL="vertical",
        ),
    )

    listbox = module.OMEROBrowserDialog._build_scrolled_listbox(object())

    assert listbox is created["listbox"]
    assert listbox.kwargs["activestyle"] == "none"


def test_selected_images_returns_all_valid_indexes():
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    first = {"id": 1, "name": "first"}
    second = {"id": 2, "name": "second"}
    third = {"id": 3, "name": "third"}
    dialog.images_data = [first, second, third]
    dialog.ilist = types.SimpleNamespace(
        curselection=lambda: ("0", "2", "99", "not-an-index")
    )

    assert module.OMEROBrowserDialog._selected_images(dialog) == [first, third]


def test_load_routes_single_selection_to_single_worker(monkeypatch):
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    image = {"id": 1, "name": "single"}
    dialog.images_data = [image]
    dialog.ilist = types.SimpleNamespace(curselection=lambda: (0,))
    dialog.converter_var = types.SimpleNamespace(get=lambda: "OMERO")
    dialog.load_btn = types.SimpleNamespace(config=lambda **_kwargs: None)
    dialog._load_worker = lambda *_args: None
    dialog._load_multiple_worker = lambda *_args: None
    confirmations = []
    threads = []
    monkeypatch.setattr(
        module.messagebox,
        "askyesno",
        lambda title, message: confirmations.append((title, message)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        module.messagebox,
        "showwarning",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    class _FakeThread:
        def __init__(self, target, args, daemon):
            threads.append({"target": target, "args": args, "daemon": daemon})

        @staticmethod
        def start():
            return None

    monkeypatch.setattr(module.threading, "Thread", _FakeThread)

    module.OMEROBrowserDialog._load(dialog)

    assert "single" in confirmations[0][1]
    assert threads == [
        {
            "target": dialog._load_worker,
            "args": (image, "OMERO"),
            "daemon": True,
        }
    ]


def test_load_routes_multi_selection_to_multi_worker(monkeypatch):
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    first = {"id": 1, "name": "first"}
    second = {"id": 2, "name": "second"}
    dialog.images_data = [first, second]
    dialog.ilist = types.SimpleNamespace(curselection=lambda: (0, 1))
    dialog.converter_var = types.SimpleNamespace(get=lambda: "Imaris")
    dialog.load_btn = types.SimpleNamespace(config=lambda **_kwargs: None)
    dialog._load_worker = lambda *_args: None
    dialog._load_multiple_worker = lambda *_args: None
    confirmations = []
    threads = []
    monkeypatch.setattr(
        module.messagebox,
        "askyesno",
        lambda title, message: confirmations.append((title, message)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        module.messagebox,
        "showwarning",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    class _FakeThread:
        def __init__(self, target, args, daemon):
            threads.append({"target": target, "args": args, "daemon": daemon})

        @staticmethod
        def start():
            return None

    monkeypatch.setattr(module.threading, "Thread", _FakeThread)

    module.OMEROBrowserDialog._load(dialog)

    assert "2 selected images" in confirmations[0][1]
    assert threads == [
        {
            "target": dialog._load_multiple_worker,
            "args": ([first, second], "Imaris"),
            "daemon": True,
        }
    ]


def test_load_worker_imaris_converter_opens_original_with_native_fileopen(
    tmp_path,
):
    module = _load_xt_module()
    original_file = tmp_path / "sample.lif"
    original_file.write_bytes(b"native input")
    calls = []
    opened = []

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


def test_load_multiple_worker_omero_waits_for_all_downloads_before_open(tmp_path):
    module = _load_xt_module()
    first_ims = tmp_path / "first.ims"
    second_ims = tmp_path / "second.ims"
    first_ims.write_bytes(b"\x89HDF\r\n\x1a\nfirst")
    second_ims.write_bytes(b"\x89HDF\r\n\x1a\nsecond")
    files_by_id = {11: str(first_ims), 12: str(second_ims)}
    events = []
    info_messages = []

    def _download_ims_export(image_id, download_dir, fallback_name):
        assert not any(event[0] == "open" for event in events)
        events.append(("download", image_id, Path(download_dir).name, fallback_name))
        return files_by_id[image_id]

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_ims_export=_download_ims_export,
        download_original_file=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("original download must not run")
        ),
    )
    dialog._ensure_native_open_ready_before_export = lambda: True
    dialog._set_status = lambda *_args, **_kwargs: None
    dialog._show_info = lambda _title, message: info_messages.append(message)
    dialog._show_error = lambda *_args, **_kwargs: None
    dialog._reenable_load_button = lambda: None
    dialog._invoke_on_ui_thread = lambda callback, wait=True: (
        None if not wait else callback()
    )

    def _open_downloaded_files(paths, require_ims=True):
        events.append(("open", tuple(paths), require_ims))
        assert [event[0] for event in events] == ["download", "download", "open"]
        return True

    dialog._open_downloaded_files_in_imaris = _open_downloaded_files

    module.OMEROBrowserDialog._load_multiple_worker(
        dialog,
        [{"id": 11, "name": "first"}, {"id": 12, "name": "second"}],
        "OMERO",
    )

    assert events == [
        ("download", 11, "img_11", "img_11.ims"),
        ("download", 12, "img_12", "img_12.ims"),
        ("open", (str(first_ims), str(second_ims)), True),
    ]
    assert dialog.temp_files == [str(first_ims), str(second_ims)]
    assert "after every download completed" in info_messages[0]


def test_load_multiple_worker_imaris_batches_originals_without_native_bridge(
    tmp_path,
):
    module = _load_xt_module()
    first_original = tmp_path / "first.lif"
    second_original = tmp_path / "second.czi"
    first_original.write_bytes(b"first")
    second_original.write_bytes(b"second")
    files_by_id = {21: str(first_original), 22: str(second_original)}
    events = []
    opened = []

    def _download_original_file(image_id, download_dir, fallback_name):
        assert not opened
        events.append(("download", image_id, Path(download_dir).name, fallback_name))
        return files_by_id[image_id]

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_original_file=_download_original_file,
        download_ims_export=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("IMS export must not run")
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
    dialog._open_downloaded_files_in_imaris = lambda paths, require_ims=True: (
        opened.append((list(paths), require_ims)) or True
    )

    module.OMEROBrowserDialog._load_multiple_worker(
        dialog,
        [{"id": 21, "name": "first.lif"}, {"id": 22, "name": "second.czi"}],
        "Imaris",
    )

    assert events == [
        ("download", 21, "img_21", "first.lif"),
        ("download", 22, "img_22", "second.czi"),
    ]
    assert opened == [([str(first_original), str(second_original)], False)]
    assert dialog.temp_files == [str(first_original), str(second_original)]


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


def test_load_worker_failure_logs_without_raw_traceback(tmp_path, monkeypatch, capsys):
    module = _load_xt_module()
    messages = []
    errors = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_ims_export=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("download failed")
        )
    )
    dialog._ensure_native_open_ready_before_export = lambda: True
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

    captured = capsys.readouterr()
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    assert errors == ["download failed"]
    assert "Load worker failed: RuntimeError: download failed" in messages


def test_load_worker_blocks_imaris_download_when_native_open_unavailable(tmp_path):
    module = _load_xt_module()
    download_calls = []
    errors = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_original_file=lambda *_args, **_kwargs: download_calls.append(
            "original"
        )
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
        {"id": 10, "name": "sample"},
        "Imaris",
    )

    assert download_calls == []
    assert len(errors) == 1
    assert "Download was not started" in errors[0]


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


def test_browser_dialog_sets_initial_window_as_minimum_size():
    module = _load_xt_module()

    class DummyRoot:
        def __init__(self):
            self.updated = False
            self.geometry_value = None
            self.minimum_size = None
            self.resizable_value = None

        def update_idletasks(self):
            self.updated = True

        @staticmethod
        def winfo_width():
            return 980

        @staticmethod
        def winfo_height():
            return 680

        @staticmethod
        def winfo_reqwidth():
            return 1010

        @staticmethod
        def winfo_reqheight():
            return 720

        def geometry(self, value):
            self.geometry_value = value

        def minsize(self, width, height):
            self.minimum_size = (width, height)

        def resizable(self, width_enabled, height_enabled):
            self.resizable_value = (width_enabled, height_enabled)

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = DummyRoot()

    module.OMEROBrowserDialog._configure_initial_window_constraints(dialog)

    assert dialog.root.updated is True
    assert dialog.root.geometry_value == "1010x720"
    assert dialog.root.minimum_size == (1010, 720)
    assert dialog.root.resizable_value == (True, True)


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
    imaris_exe = r"C:\Apps\Imaris 11.0.0\Imaris.exe"
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setenv("IMARIS_EXE", imaris_exe)
    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == imaris_exe)

    assert module._find_imaris_executable() == imaris_exe


def test_imaris_version_gate_allows_11_and_future_but_rejects_older_or_unknown():
    module = _load_xt_module()

    assert module._is_supported_imaris_install_path(r"C:\Apps\Imaris 10.2.0") is False
    assert module._is_supported_imaris_install_path(r"C:\Apps\Imaris11") is True
    assert module._is_supported_imaris_install_path(r"C:\Apps\Imaris 11") is True
    assert module._is_supported_imaris_install_path(r"C:\Apps\Imaris 11.0.0") is True
    assert (
        module._is_supported_imaris_install_path(r"C:\Apps\Imaris 11.0.0.0.0.0") is True
    )
    assert module._is_supported_imaris_install_path(r"C:\Apps\Imaris 12.1.0") is True
    assert module._is_supported_imaris_install_path(r"C:\Apps\CustomImaris") is False


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
