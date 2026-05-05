from __future__ import annotations

import ast
import importlib.util
import builtins
import json
import ntpath
import os
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

_XT_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "XTOmeroConnector.py",
)


def _load_xt_module():
    """Load the XT module.

    Inputs: none. Output: `module`.
    """
    tkinter_module = types.ModuleType("tkinter")
    tkinter_module.messagebox = types.SimpleNamespace()
    tkinter_module.filedialog = types.SimpleNamespace()
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
    """Test double for fake httpresponse."""

    def __init__(self, body=b"", headers=None, final_url="https://omero.example.org/"):
        """Create `_FakeHTTPResponse` with `body`, `headers`, and `final_url`.

        Inputs: `body`, `headers`, `final_url`. Output: None.
        """
        self._body = body
        self._offset = 0
        self.headers = headers or {}
        self._final_url = final_url
        self.status = 200

    def __enter__(self):
        """Enter `_FakeHTTPResponse`'s context-managed fake resource.

        Inputs: none. Output: `self`.
        """
        return self

    @staticmethod
    def __exit__(*_args):
        """Exit `_FakeHTTPResponse`'s context-managed fake resource.

        Inputs: `*_args`. Output: bool.
        """
        return False

    def read(self, size=-1):
        """Read data from the resource.

        Inputs: `size`. Output: `chunk`.
        """
        if size is None or size < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self):
        """Return the final redirected URL.

        Inputs: none. Output: `self._final_url`.
        """
        return self._final_url


class _FakeHTTPError(Exception):
    """Test double for fake httperror."""

    def __init__(self, body, code=400, msg="Bad Request"):
        """Create `_FakeHTTPError` with `body`, `code`, and `msg`.

        Inputs: `body`, `code`, `msg`. Output: None.
        """
        super().__init__(f"HTTP {code} {msg}")
        self.code = code
        self._body = body

    def read(self, *_args, **_kwargs):
        """Read data from the resource.

        Inputs: `*_args`, `**_kwargs`. Output: `self._body`.
        """
        return self._body


class _FakeListbox:
    """Test double for fake listbox."""

    def __init__(self, items=None, selection=None):
        """Create `_FakeListbox` with `items` and `selection`.

        Inputs: `items`, `selection`. Output: None.
        """
        self.items = list(items or [])
        self.selection = set(selection or [])
        self.seen = []
        self.activated = []
        self.anchors = []
        self.focused = False

    def delete(self, start, end=None):
        """Delete the delete for `_FakeListbox`.

        Inputs: `start`, `end`. Output: None.
        """
        if start == 0:
            self.items = []
            self.selection.clear()

    def insert(self, index, value):
        """Record the insert call on `_FakeListbox` for later assertions.

        Inputs: `index`, `value` input value. Output: None.
        """
        if index in {"end", "END"}:
            self.items.append(value)
        else:
            self.items.insert(int(index), value)

    def curselection(self):
        """Return the curselection for `_FakeListbox`.

        Inputs: none. Output: `tuple`.
        """
        return tuple(sorted(self.selection))

    def selection_clear(self, *_args):
        """Record the selection clear call on `_FakeListbox` for later assertions.

        Inputs: `*_args`. Output: None.
        """
        self.selection.clear()

    def selection_set(self, index):
        """Record the selection set call on `_FakeListbox` for later assertions.

        Inputs: `index`. Output: None.
        """
        self.selection.add(int(index))

    @staticmethod
    def nearest(index):
        """Return the nearest for `_FakeListbox`.

        Inputs: `index`. Output: `int`.
        """
        return int(index)

    def size(self):
        """Return the size for `_FakeListbox`.

        Inputs: none. Output: `int` count.
        """
        return len(self.items)

    def activate(self, index):
        """Record the activate call on `_FakeListbox` for later assertions.

        Inputs: `index`. Output: None.
        """
        self.activated.append(int(index))

    def selection_anchor(self, index):
        """Record the selection anchor call on `_FakeListbox` for later assertions.

        Inputs: `index`. Output: None.
        """
        self.anchors.append(int(index))

    def see(self, index):
        """Record the see call on `_FakeListbox` for later assertions.

        Inputs: `index`. Output: None.
        """
        self.seen.append(int(index))

    def focus_set(self):
        """Record focus assignment.

        Inputs: none. Output: None.
        """
        self.focused = True


class _FakeEntry:
    """Test double for fake entry."""

    def __init__(self, value=""):
        """Create `_FakeEntry` with its default state.

        Inputs: optional `value`. Output: initializes fake state.
        """
        self.value = value
        self.configs = []

    def get(self):
        """Return the stored entry value.

        Inputs: none. Output: `self.value`.
        """
        return self.value

    def config(self, **kwargs):
        """Apply widget configuration.

        Inputs: `**kwargs`. Output: None.
        """
        self.configs.append(kwargs)


class _FakeButton:
    """Test double for fake button."""

    def __init__(self):
        """Create `_FakeButton` with its default state.

        Inputs: constructor receives no public arguments. Output: initializes fake state.
        """
        self.configs = []
        self.state = None

    def config(self, **kwargs):
        """Apply widget configuration.

        Inputs: `**kwargs`. Output: None.
        """
        self.configs.append(kwargs)
        if "state" in kwargs:
            self.state = kwargs["state"]


class _FakeVar:
    """Test double for fake var."""

    def __init__(self, value=""):
        """Create `_FakeVar` with `value`.

        Inputs: `value`. Output: None.
        """
        self.value = value

    def get(self):
        """Return the requested value.

        Inputs: none. Output: `self.value`.
        """
        return self.value

    def set(self, value):
        """Store the provided value.

        Inputs: `value`. Output: None.
        """
        self.value = value


def _make_refresh_dialog(module):
    """Create the refresh dialog.

    Inputs: `module` module object. Output: `dialog`.
    """
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = True
    dialog.client = object()
    dialog._refresh_generation = 1
    dialog._refresh_in_progress = True
    dialog._pid = "project-1"
    dialog._did = "dataset-1"
    dialog.projects_data = [{"id": "project-1", "name": "Old project"}]
    dialog.datasets_data = [{"id": "dataset-1", "name": "Old dataset"}]
    dialog.images_data = [{"id": "image-1", "name": "Old image"}]
    dialog.plist = _FakeListbox(["Old project"], selection={0})
    dialog.dlist = _FakeListbox(["Old dataset"], selection={0})
    dialog.ilist = _FakeListbox(["Old image"], selection={0})
    dialog.refresh_btn = _FakeButton()
    dialog.load_btn = _FakeButton()
    dialog.converter_var = _FakeVar("OMERO")
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
    dialog.status_updates = []
    dialog.errors = []
    dialog._set_status = lambda text, color="#ecf0f1": dialog.status_updates.append(
        (text, color)
    )
    dialog._show_error = lambda title, message: dialog.errors.append((title, message))
    dialog._invoke_on_ui_thread = lambda callback, wait=True: callback()
    return dialog


def test_xt_script_annotations_stay_python37_runtime_safe():
    """Verify the XT script annotations stay python37 runtime safe execution contract.

    Inputs: repository fixtures. Output: fails on regressions in XT script annotations stay python37 runtime safe integration.
    """
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


def test_xt_script_defers_tk_import_until_after_platform_gate():
    """Verify Tk is imported only after the platform gate can run.

    Inputs: repository fixtures. Output: fails on startup ordering regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    deferred_import_marker = "def _ensure_tk_loaded():"
    entrypoint_marker = "def XTOmeroConnector(aImarisId):"
    platform_gate_marker = "platform_status = _windows_platform_status()"
    tk_load_marker = "_ensure_tk_loaded()"

    assert "import tkinter" not in source[: source.index(deferred_import_marker)]
    entrypoint_source = source[source.index(entrypoint_marker) :]
    assert entrypoint_source.index(platform_gate_marker) < entrypoint_source.index(
        tk_load_marker
    )


def test_create_request_with_cookies_relies_on_cookie_jar_for_get():
    """Verify create request with cookies relies on cookie jar for get.

    Inputs: repository fixtures. Output: fails on regressions in create request with cookies relies on cookie jar for get.
    """
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
    """Verify create request with cookies adds csrf headers without cookie override.

    Inputs: repository fixtures. Output: fails on regressions in create request with cookies adds csrf headers without cookie override.
    """
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
    """Verify client detects OMERO IMS export capability.

    Inputs: repository fixtures. Output: fails on regressions in client detects OMERO IMS export capability.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `request` Django request, `timeout` timeout seconds. Output:
            `_FakeHTTPResponse` result.
            """
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
    """Verify client treats non object capability response as unavailable result shape.

    Inputs: repository fixtures. Output: fails on regressions in client treats non object capability response as unavailable.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(_request, _timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `_request`, `_timeout`. Output: `_FakeHTTPResponse` result.
            """
            return _FakeHTTPResponse(b"[]")

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is False


def test_client_treats_legacy_missing_image_capability_response_as_available(
    monkeypatch,
):
    """Verify client treats legacy missing image capability response as available result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in client treats legacy missing image capability response as available.
    _FakeHTTPError when validation or the called operation fails.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.urllib.error, "HTTPError", _FakeHTTPError)
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(_request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `_request`, `timeout` timeout seconds. Output: None. Raises:
            _FakeHTTPError when validation or the called operation fails.
            """
            assert timeout == 30
            raise _FakeHTTPError(b"Missing image id")

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is True


def test_client_rejects_non_legacy_capability_http_errors(monkeypatch):
    """Confirm client rejects non legacy capability HTTP errors is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in client rejects non legacy capability HTTP errors.
    _FakeHTTPError when validation or the called operation fails.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.urllib.error, "HTTPError", _FakeHTTPError)
    messages = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(_request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `_request`, `timeout` timeout seconds. Output: None. Raises:
            _FakeHTTPError when validation or the called operation fails.
            """
            assert timeout == 30
            raise _FakeHTTPError(b"Invalid base_url parameter.")

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is False
    assert "Invalid base_url parameter" not in "\n".join(messages)
    assert "OMERO IMS export capability unavailable: HTTP 400" in messages


def test_client_detects_folder_export_capability_from_start_endpoint():
    """Verify client detects folder export capability from start endpoint.

    Inputs: repository fixtures. Output: fails on regressions in client detects folder export capability from start endpoint.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `request` Django request, `timeout` timeout seconds. Output:
            `_FakeHTTPResponse` result.
            """
            opened_urls.append((request.full_url, timeout, request.data))
            return _FakeHTTPResponse(b'{"ok": false, "error": "No files provided."}')

    client.opener = _FakeOpener()

    assert client.get_folder_export_capability() == {"available": True, "reason": ""}
    assert opened_urls == [
        (
            f"{client.base_url}/omeroweb_import/start/",
            30,
            b"{}",
        )
    ]


def test_client_marks_root_folder_export_capability_as_unavailable():
    """Verify client marks root folder export capability as unavailable.

    Inputs: repository fixtures. Output: fails on regressions in client marks root folder export capability as unavailable.
    """
    module = _load_xt_module()
    module.urllib.error.HTTPError = _FakeHTTPError
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(_request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `_request`, `timeout` timeout seconds. Output: None. Raises:
            _FakeHTTPError when validation or the called operation fails.
            """
            assert timeout == 30
            raise _FakeHTTPError(
                b'{"error": "PLEASE LOGIN AS REGULAR USER\\nTO USE THIS PLUGIN"}',
                code=403,
                msg="Forbidden",
            )

    client.opener = _FakeOpener()

    capability = client.get_folder_export_capability()

    assert capability["available"] is False
    assert "root user" in capability["reason"].lower()


def test_client_start_folder_export_job_posts_dataset_override_and_normalizes_urls():
    """Check client start folder export job posts dataset override and normalizes URLs parsing against the documented contract.

    Inputs: repository fixtures. Output: fails on regressions in client start folder export job posts dataset override and normalizes URLs.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    calls = []

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `request` Django request, `timeout` timeout seconds. Output:
            `_FakeHTTPResponse` result.
            """
            calls.append((request.full_url, timeout, request.data))
            return _FakeHTTPResponse(
                json.dumps(
                    {
                        "ok": True,
                        "job_id": "abc123",
                        "upload_url": "http://localhost:4080/omeroweb_import/upload/abc123/",
                        "import_step_url": "/omeroweb_import/import/abc123/",
                        "status_url": "/omeroweb_import/status/abc123/",
                        "confirm_url": "/omeroweb_import/confirm/abc123/",
                    }
                ).encode("utf-8")
            )

    client.opener = _FakeOpener()

    payload = client.start_folder_export_job(
        "Dataset Root",
        [
            {"relative_path": "sub/file-a.tif", "size": 5},
            {"relative_path": "file-b.tif", "size": 0},
        ],
    )

    posted = json.loads(calls[0][2].decode("utf-8"))
    assert posted["dataset_name_override"] == "Dataset Root"
    assert posted["compatibility_enabled"] is True
    assert posted["files"] == [
        {"relative_path": "sub/file-a.tif", "size": 5},
        {"relative_path": "file-b.tif", "size": 0},
    ]
    assert payload["upload_url"] == (
        f"{client.base_url}/omeroweb_import/upload/abc123/"
    )
    assert payload["import_step_url"] == (
        f"{client.base_url}/omeroweb_import/import/abc123/"
    )


def test_folder_export_error_message_does_not_echo_html():
    """Confirm folder export error message does not echo html exposes the expected failure.

    Inputs: repository fixtures. Output: fails on regressions when folder export error message does not echo html stops reporting the expected error.
    """
    module = _load_xt_module()

    message = module.OMEROWebClient._payload_error_message(
        None,
        "<html><body>Traceback</body></html>",
        "Failed to start OMERO folder export.",
    )

    assert message == "Failed to start OMERO folder export."


def test_client_download_original_file_uses_archived_files_endpoint_and_safe_name(
    tmp_path,
):
    """Verify client download original file uses archived files endpoint and safe name.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in client download original file uses archived files endpoint and safe name.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(request, timeout):
            """Open `_FakeOpener`'s captured target.

            Inputs: `request` Django request, `timeout` timeout seconds. Output:
            `_FakeHTTPResponse` result.
            """
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
    """Verify resolve imaris application uses imarislib factory.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve imaris application uses imarislib factory.
    """
    module = _load_xt_module()
    expected = object()

    class _FakeImarisLibFactory:
        """Test double for fake imaris lib factory."""

        @staticmethod
        def GetApplication(app_id):
            """Return the application for `_FakeImarisLibFactory`.

            Inputs: `app_id`. Output: `expected`.
            """
            assert app_id == 17
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=_FakeImarisLibFactory)
    monkeypatch.setitem(sys.modules, "ImarisLib", fake_module)

    assert module._resolve_imaris_application(17) is expected


def test_resolve_imaris_application_retries_until_handle_available(monkeypatch):
    """Verify resolve imaris application retries until handle available.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve imaris application retries until handle available.
    """
    module = _load_xt_module()
    expected = object()
    calls = {"count": 0}

    class _RetryingImarisLibFactory:
        """Test double for retrying imaris lib factory behavior in this module."""

        @staticmethod
        def GetApplication(app_id):
            """Return the application for `_RetryingImarisLibFactory`.

            Inputs: `app_id`. Output: `expected`.
            """
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
    """Verify resolve imaris application accepts numeric string.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve imaris application accepts numeric string.
    """
    module = _load_xt_module()
    expected = object()

    class _FakeImarisLibFactory:
        """Test double for fake imaris lib factory."""

        @staticmethod
        def GetApplication(app_id):
            """Return the application for `_FakeImarisLibFactory`.

            Inputs: `app_id`. Output: `expected`.
            """
            assert app_id == 17
            return expected

    fake_module = types.SimpleNamespace(ImarisLib=_FakeImarisLibFactory)
    monkeypatch.setitem(sys.modules, "ImarisLib", fake_module)

    assert module._resolve_imaris_application("17") is expected


def test_resolve_imaris_application_returns_none_when_bridge_import_fails(monkeypatch):
    """Confirm resolve imaris application returns none when bridge import fails exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve imaris application returns none when bridge import fails.
    Raises: ImportError when validation or the called operation fails.
    """
    module = _load_xt_module()

    real_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        """Return the raising import.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `real_import` result. Raises: ImportError for the exercised failure path.
        """
        if name == "ImarisLib":
            raise ImportError("IcePy missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    assert module._resolve_imaris_application(17) is None


def test_resolve_imaris_application_bridge_failure_message_keeps_runner_path(
    monkeypatch,
):
    """Check that resolve imaris application bridge failure message keeps runner path remains stable.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when resolve imaris application bridge failure message keeps runner path accepts unsafe input.
    Raises: ImportError when validation or the called operation fails.
    """
    module = _load_xt_module()
    messages = []

    real_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        """Return the raising import.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `real_import` result. Raises: ImportError for the exercised failure path.
        """
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
    """Verify open file in imaris returns false without handle result shape.

    Inputs: pytest provides `tmp_path`, `monkeypatch`, `capsys`. Output: fails on regressions in open file in imaris returns false without handle.
    """
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
    """Verify open file in imaris uses live handle for valid IMS.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in open file in imaris uses live handle for valid IMS.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    opened = []

    class _FakeImaris:
        """Test double for fake imaris."""

        @staticmethod
        def FileOpen(path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            opened.append(path)

    assert module.open_file_in_imaris(ims_path, _FakeImaris()) is True
    assert opened == [str(ims_path)]


def test_open_file_in_imaris_rejects_unverified_current_file(tmp_path, monkeypatch):
    """Confirm open file in imaris rejects unverified current file is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in open file in imaris rejects unverified current file.
    """
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
        """Test double for fake imaris."""

        @staticmethod
        def FileOpen(_path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `_path`, `*_args`. Output: None.
            """
            return None

        @staticmethod
        def GetCurrentFileName():
            """Return the fake current file name value used by this test double.

            Inputs: none. Output: `str` result.
            """
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
    """Confirm open file in imaris rejects non IMS before live handle is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in open file in imaris rejects non IMS before live handle.
    """
    module = _load_xt_module()
    plain_path = tmp_path / "plain.txt"
    plain_path.write_text("not ims", encoding="utf-8")
    opened = []

    class _FakeImaris:
        """Test double for fake imaris."""

        @staticmethod
        def FileOpen(path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            opened.append(path)

    assert module.open_file_in_imaris(plain_path, _FakeImaris()) is False
    assert opened == []


def test_open_file_in_imaris_allows_original_file_for_imaris_converter(tmp_path):
    """Verify open file in imaris allows original file for imaris converter.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in open file in imaris allows original file for imaris converter.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_text("native converter input", encoding="utf-8")
    opened = []

    class _FakeImaris:
        """Test double for fake imaris."""

        current = ""

        def FileOpen(self, path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            opened.append((path, _args))
            self.current = path

        def GetCurrentFileName(self):
            """Return the fake current file name value used by this test double.

            Inputs: none. Output: `self.current`.
            """
            return self.current

    assert (
        module.open_file_in_imaris(original_path, _FakeImaris(), require_ims=False)
        is True
    )
    assert opened == [(str(original_path), ())]


def test_open_file_in_imaris_raw_file_uses_submission_only_verification(
    tmp_path,
    monkeypatch,
):
    """Verify open file in imaris raw file uses submission only verification.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in open file in imaris raw file uses submission only verification.
    """
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
    monkeypatch.setattr(
        module,
        "_wait_for_imaris_open_observable_effect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "raw FileOpen must not require observable-effect verification"
            )
        ),
    )

    class _FakeImaris:
        """Test double for fake imaris."""

        current = ""

        def FileOpen(self, path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            opened.append((path, _args))
            self.current = path

        def GetCurrentFileName(self):
            """Return the fake current file name value used by this test double.

            Inputs: none. Output: `self.current`.
            """
            return self.current

    assert (
        module.open_file_in_imaris(
            original_path,
            _FakeImaris(),
            require_ims=False,
        )
        is True
    )
    assert opened == [(str(original_path), ())]


def test_open_file_in_imaris_raw_file_accepts_successful_submission(
    tmp_path,
    monkeypatch,
):
    """Verify open file in imaris raw file accepts successful submission.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `str`.
    """
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
    monkeypatch.setattr(
        module,
        "_wait_for_imaris_open_observable_effect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "raw FileOpen must not require observable-effect verification"
            )
        ),
    )

    class _FakeImaris:
        """Test double for fake imaris."""

        @staticmethod
        def FileOpen(path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            opened.append((path, _args))

        @staticmethod
        def GetCurrentFileName():
            """Return the fake current file name value used by this test double.

            Inputs: none. Output: ''.
            """
            return ""

        @staticmethod
        def GetNumberOfImages():
            """Return the fake number of images value used by this test double.

            Inputs: none. Output: 1.
            """
            return 1

    assert (
        module.open_file_in_imaris(
            original_path,
            _FakeImaris(),
            require_ims=False,
        )
        is True
    )
    assert opened == [(str(original_path), ())]


def test_open_file_in_imaris_raw_file_retries_with_options_after_typeerror(tmp_path):
    """Verify open file in imaris raw file retries with options after typeerror.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in open file in imaris raw file retries with options after typeerror.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_text("native converter input", encoding="utf-8")
    opened = []

    class _FakeImaris:
        """Test double for fake imaris."""

        current = ""

        def FileOpen(self, *args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `*args` positional arguments. Output: None. Raises: TypeError when validation or the called operation fails.
            """
            opened.append(args)
            if len(args) == 1:
                raise TypeError("missing required positional argument: 'aOptions'")
            self.current = args[0]

        def GetCurrentFileName(self):
            """Return the fake current file name value used by this test double.

            Inputs: none. Output: `self.current`.
            """
            return self.current

    assert (
        module.open_file_in_imaris(
            original_path,
            _FakeImaris(),
            require_ims=False,
        )
        is True
    )
    assert opened == [
        (str(original_path),),
        (str(original_path), ""),
    ]


def test_open_files_in_imaris_uses_image_slots_for_multiple_files(tmp_path):
    """Verify open files in imaris uses image slots for multiple files.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in open files in imaris uses image slots for multiple files.
    """
    module = _load_xt_module()
    first_path = tmp_path / "first.ims"
    second_path = tmp_path / "second.ims"
    first_path.write_bytes(b"\x89HDF\r\n\x1a\nfirst")
    second_path.write_bytes(b"\x89HDF\r\n\x1a\nsecond")

    class _FakeDataSet:
        """Test double for fake data set."""

        def __init__(self, path):
            """Create `_FakeDataSet` with `path`.

            Inputs: `path`. Output: None.
            """
            self.path = path

        def GetSizeX(self):
            """Return `_FakeDataSet`'s fake SizeX value.

            Inputs: none. Output: `int` size.
            """
            return 1 if "first" in self.path else 2

        def Clone(self):
            """Clone the clone for `_FakeDataSet`.

            Inputs: none. Output: clone result.
            """
            return f"clone:{self.path}"

    class _FakeImaris:
        """Test double for fake imaris."""

        def __init__(self):
            """Create `_FakeImaris` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.current = None
            self.opened = []
            self.images = {}

        def FileOpen(self, path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            self.opened.append(path)
            self.current = _FakeDataSet(path)

        def GetDataSet(self):
            """Return the fake data set value used by this test double.

            Inputs: none. Output: `self.current`.
            """
            return self.current

        def SetImage(self, index, data_set):
            """Set the image for `_FakeImaris`.

            Inputs: `index`, `data_set`. Output: None.
            """
            self.images[index] = data_set

        def GetNumberOfImages(self):
            """Return the fake number of images value used by this test double.

            Inputs: none. Output: `len` result.
            """
            return len(self.images)

    imaris = _FakeImaris()

    assert module.open_files_in_imaris([first_path, second_path], imaris) is True
    assert imaris.opened == [str(first_path), str(second_path)]
    assert imaris.images == {
        0: f"clone:{str(first_path)}",
        1: f"clone:{str(second_path)}",
    }


def test_collect_local_folder_entries_returns_sorted_relative_paths(tmp_path):
    """Verify collect local folder entries returns sorted relative paths result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in collect local folder entries returns sorted relative paths.
    """
    module = _load_xt_module()
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "nested" / "a.txt").write_text("a", encoding="utf-8")

    entries = module._collect_local_folder_entries(tmp_path)

    assert [entry["relative_path"] for entry in entries] == [
        "b.txt",
        "nested/a.txt",
    ]


def test_collect_local_folder_entries_rejects_empty_folder(tmp_path):
    """Confirm collect local folder entries rejects empty folder is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in collect local folder entries rejects empty folder.
    """
    module = _load_xt_module()

    with pytest.raises(RuntimeError, match="does not contain any files"):
        module._collect_local_folder_entries(tmp_path)


def test_is_filesystem_root_detects_windows_and_posix_roots():
    """Verify is filesystem root detects windows and posix roots.

    Inputs: repository fixtures. Output: fails on regressions in is filesystem root detects windows and posix roots.
    """
    module = _load_xt_module()

    assert module._is_filesystem_root("/") is True
    assert module._is_filesystem_root(r"C:\\") is True
    assert module._is_filesystem_root(r"\\server\share") is True
    assert module._is_filesystem_root(r"\\server\share\\") is True
    assert module._is_filesystem_root(r"C:\\Users\\alice") is False
    assert module._is_filesystem_root(r"\\server\share\folder") is False


def test_structural_folder_path_validation_accepts_absolute_paths(tmp_path):
    """Verify structural folder path validation accepts absolute safe paths.

    Inputs: pytest provides `tmp_path`. Output: fails on path validation regressions.
    """
    module = _load_xt_module()

    assert module._is_structurally_valid_folder_path(r"C:\exports") is True
    assert module._is_structurally_valid_folder_path(r"C:/exports") is True
    assert module._is_structurally_valid_folder_path(r"\\server\share\folder") is True
    assert module._is_structurally_valid_folder_path(r"\\?\C:\long\exports") is True
    assert module._is_structurally_valid_folder_path(tmp_path) is True


def test_structural_folder_path_validation_rejects_malformed_windows_paths():
    """Verify structural folder path validation rejects unsafe typed Windows paths.

    Inputs: repository fixtures. Output: fails on path validation regressions.
    """
    module = _load_xt_module()

    rejected_paths = [
        "",
        "   ",
        r"C:exports",
        r"\exports",
        r"C:\bad<name",
        r"C:\exports\CON",
        r"C:\exports\child ",
        r"C:\exports\child.",
        r"C:\exports\..\child",
        r"C:\bad" + "\x00" + "path",
        r"\\.\GLOBALROOT\Device\HarddiskVolumeShadowCopy1",
        r"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1",
    ]

    assert all(
        module._is_structurally_valid_folder_path(path_value) is False
        for path_value in rejected_paths
    )


def test_select_local_folder_replaces_typed_path_after_native_selection(
    tmp_path, monkeypatch
):
    """Verify native folder selection replaces a manually typed path.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on selector regressions.
    """
    module = _load_xt_module()
    typed_folder = tmp_path / "typed"
    typed_folder.mkdir()
    selected_folder = tmp_path / "selected"
    selected_folder.mkdir()
    calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(str(typed_folder))

    def _fake_askdirectory(**kwargs):
        """Return a selected directory and record dialog options.

        Inputs: `**kwargs`. Output: `str`.
        """
        calls.append(kwargs)
        return str(selected_folder)

    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        _fake_askdirectory,
        raising=False,
    )

    module.OMEROBrowserDialog._select_local_folder(dialog)

    assert dialog.folder_path_var.get() == str(selected_folder)
    assert calls == [
        {
            "parent": dialog.root,
            "mustexist": True,
            "title": "Select folder to export to OMERO",
            "initialdir": str(typed_folder),
        }
    ]


def test_select_local_folder_cancel_preserves_typed_path(tmp_path, monkeypatch):
    """Verify cancelling native folder selection preserves the typed path.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on selector regressions.
    """
    module = _load_xt_module()
    typed_folder = tmp_path / "typed"
    typed_folder.mkdir()

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(str(typed_folder))

    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: "",
        raising=False,
    )

    module.OMEROBrowserDialog._select_local_folder(dialog)

    assert dialog.folder_path_var.get() == str(typed_folder)


def test_folder_path_placeholder_is_display_only_for_export_path():
    """Verify placeholder text is visual only and never becomes an export path.

    Inputs: repository fixtures. Output: fails on placeholder contract regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.folder_path_var = _FakeVar("")
    dialog.folder_path_entry = _FakeEntry()
    dialog._folder_path_placeholder_visible = False

    module.OMEROBrowserDialog._show_folder_path_placeholder(dialog)

    assert dialog.folder_path_var.get() == module.FOLDER_PATH_PLACEHOLDER
    assert dialog._current_local_folder_path() == ""
    assert dialog.folder_path_entry.configs[-1] == {
        "fg": module.FOLDER_PATH_PLACEHOLDER_FG
    }

    module.OMEROBrowserDialog._hide_folder_path_placeholder(dialog)

    assert dialog.folder_path_var.get() == ""
    assert dialog._current_local_folder_path() == ""
    assert dialog.folder_path_entry.configs[-1] == {"fg": module.FOLDER_PATH_TEXT_FG}


def test_select_local_folder_replaces_placeholder_with_native_selection(
    tmp_path, monkeypatch
):
    """Verify native folder selection replaces display-only placeholder text.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on selector regressions.
    """
    module = _load_xt_module()
    selected_folder = tmp_path / "selected"
    selected_folder.mkdir()
    calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(module.FOLDER_PATH_PLACEHOLDER)
    dialog.folder_path_entry = _FakeEntry()
    dialog._folder_path_placeholder_visible = True

    def _fake_askdirectory(**kwargs):
        """Return a selected directory and record dialog options.

        Inputs: `**kwargs`. Output: `str`.
        """
        calls.append(kwargs)
        return str(selected_folder)

    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        _fake_askdirectory,
        raising=False,
    )

    module.OMEROBrowserDialog._select_local_folder(dialog)

    assert dialog.folder_path_var.get() == str(selected_folder)
    assert dialog._current_local_folder_path() == str(selected_folder)
    assert dialog._folder_path_placeholder_visible is False
    assert dialog.folder_path_entry.configs[-1] == {"fg": module.FOLDER_PATH_TEXT_FG}
    assert calls == [
        {
            "parent": dialog.root,
            "mustexist": True,
            "title": "Select folder to export to OMERO",
        }
    ]


def test_select_folder_reports_write_error_immediately_and_disables_load(
    tmp_path, monkeypatch
):
    """Verify native folder selection fails fast when Imaris cannot write there.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on selector permission regressions.
    """
    module = _load_xt_module()
    selected_folder = tmp_path / "selected"
    selected_folder.mkdir()

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = object()
    dialog.folder_path_var = _FakeVar("")
    dialog.folder_path_entry = _FakeEntry()
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "empty"
    dialog._connected = True
    dialog.client = object()
    dialog.converter_var = _FakeVar("OMERO")
    dialog.load_btn = _FakeButton()
    dialog._load_in_progress = False
    dialog._folder_export_in_progress = False

    errors = []
    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: str(selected_folder),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "_folder_path_write_error",
        lambda _path: module.LOCAL_PATH_WRITE_ERROR_MESSAGE,
    )
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )

    module.OMEROBrowserDialog._select_local_folder(dialog)

    assert dialog.folder_path_var.get() == str(selected_folder)
    assert dialog._folder_path_write_state == "unwritable"
    assert dialog.load_btn.state == "disabled"
    assert errors == [
        (module.LOCAL_PATH_WRITE_ERROR_TITLE, module.LOCAL_PATH_WRITE_ERROR_MESSAGE)
    ]


def test_load_button_requires_connection_and_structural_folder_path():
    """Verify Load stays gated by connection, converter, and path structure.

    Inputs: repository fixtures. Output: fails on Load button gating regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_var = _FakeVar("OMERO")
    dialog.load_btn = _FakeButton()
    dialog._load_in_progress = False
    dialog._folder_export_in_progress = False
    dialog._connected = False
    dialog.client = None
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"

    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"

    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar("")
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"

    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_write_state = "unchecked"
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "normal"

    dialog._folder_path_write_state = "unwritable"
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"


def test_load_checks_typed_path_write_permission_before_confirmation(
    tmp_path, monkeypatch
):
    """Verify typed paths are write-checked when Load is clicked.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on typed path permission regressions.
    """
    module = _load_xt_module()
    missing_folder = tmp_path / "missing"
    dialog = object.__new__(module.OMEROBrowserDialog)
    image = {"id": 1, "name": "single"}
    dialog._connected = True
    dialog.client = object()
    dialog.images_data = [image]
    dialog.ilist = types.SimpleNamespace(curselection=lambda: (0,))
    dialog.converter_var = _FakeVar("OMERO")
    dialog.folder_path_var = _FakeVar(str(missing_folder))
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
    dialog.load_btn = _FakeButton()

    errors = []
    confirmations = []
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )
    monkeypatch.setattr(
        module.messagebox,
        "askyesno",
        lambda title, message: confirmations.append((title, message)) or True,
        raising=False,
    )

    module.OMEROBrowserDialog._load(dialog)

    assert errors == [
        (module.LOCAL_PATH_WRITE_ERROR_TITLE, module.LOCAL_PATH_WRITE_ERROR_MESSAGE)
    ]
    assert confirmations == []
    assert dialog.load_btn.state == "disabled"


def test_folder_path_write_check_rejects_missing_directory(tmp_path):
    """Verify the write probe rejects paths that do not name an existing folder.

    Inputs: pytest provides `tmp_path`. Output: fails on write-check regressions.
    """
    module = _load_xt_module()

    assert (
        module._folder_path_write_error(tmp_path / "missing")
        == module.LOCAL_PATH_WRITE_ERROR_MESSAGE
    )


def test_folder_path_write_check_rejects_malformed_path_before_probe(monkeypatch):
    """Verify malformed paths are rejected before any write probe.

    Inputs: pytest provides `monkeypatch`. Output: fails on write-check regressions.
    """
    module = _load_xt_module()

    monkeypatch.setattr(
        module.os,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("malformed path must not be opened")
        ),
    )

    assert (
        module._folder_path_write_error(r"C:\bad<name")
        == module.LOCAL_PATH_WRITE_ERROR_MESSAGE
    )


def test_connector_settings_env_path_uses_connector_user_folder(tmp_path):
    """Verify connector settings live in the user-scoped connector folder.

    Inputs: pytest provides `tmp_path`. Output: fails on user-settings path regressions.
    """
    module = _load_xt_module()

    assert module._connector_settings_env_path(tmp_path) == (
        tmp_path
        / module.AUTOSAVE_SETTINGS_DIR_NAME
        / module.AUTOSAVE_SETTINGS_FILE_NAME
    )


def test_connector_settings_writer_replaces_known_keys_and_drops_passwords(tmp_path):
    """Verify settings writes replace stale keys without preserving credentials.

    Inputs: pytest provides `tmp_path`. Output: fails on settings persistence regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        "\n".join(
            [
                "# operator note",
                'OMERO_CONNECTOR_HOST="old.example.org"',
                'OMERO_CONNECTOR_PORT="4064"',
                'OMERO_CONNECTOR_PORT="duplicate"',
                'OMERO_CONNECTOR_PASSWORD="do-not-keep"',
                'PASSWORD="do-not-keep-either"',
                'OTHER_CONNECTOR_NOTE="keep-me"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sensitive_key = "OMERO_CONNECTOR_" + "PASSWORD"
    sensitive_value = "not-persisted"
    settings = {
        module.CONNECTOR_SETTINGS_HOST_KEY: "omero.example.org",
        module.CONNECTOR_SETTINGS_PORT_KEY: "443",
        module.CONNECTOR_SETTINGS_USERNAME_KEY: "alice",
        module.CONNECTOR_SETTINGS_HTTPS_KEY: "true",
        module.CONNECTOR_SETTINGS_PATH_KEY: r"C:\Exports\A folder",
        module.CONNECTOR_SETTINGS_AUTOSAVE_KEY: "true",
        sensitive_key: sensitive_value,
    }

    module._atomic_write_connector_settings(settings, settings_path)

    content = settings_path.read_text(encoding="utf-8")
    loaded = module._load_connector_settings(settings_path)
    assert "# operator note" in content
    assert 'OTHER_CONNECTOR_NOTE="keep-me"' in content
    assert content.count(module.CONNECTOR_SETTINGS_PORT_KEY + "=") == 1
    assert "PASSWORD" not in content
    assert "do-not-keep" not in content
    assert sensitive_value not in content
    assert loaded[module.CONNECTOR_SETTINGS_HOST_KEY] == "omero.example.org"
    assert loaded[module.CONNECTOR_SETTINGS_PORT_KEY] == "443"
    assert loaded[module.CONNECTOR_SETTINGS_PATH_KEY] == r"C:\Exports\A folder"


def test_connector_settings_writer_tightens_private_file_modes(tmp_path):
    """Verify connector settings are owner-only after atomic writes.

    Inputs: pytest provides `tmp_path`. Output: fails on settings permission regressions.
    """
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not reliable on Windows")

    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir(mode=0o777)

    module._atomic_write_connector_settings({}, settings_path)

    directory_mode = stat.S_IMODE(settings_path.parent.stat().st_mode)
    file_mode = stat.S_IMODE(settings_path.stat().st_mode)
    assert directory_mode == module.PRIVATE_DIRECTORY_MODE
    assert file_mode == module.PRIVATE_FILE_MODE


def test_connector_settings_writer_rejects_settings_symlink(tmp_path):
    """Verify connector settings writes do not follow existing symlinks.

    Inputs: pytest provides `tmp_path`. Output: fails on symlink safety regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    target_path = tmp_path / "target.env"
    target_path.write_text("", encoding="utf-8")
    try:
        settings_path.symlink_to(target_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(OSError):
        module._atomic_write_connector_settings({}, settings_path)


def test_connector_settings_writer_rejects_settings_directory_symlink(tmp_path):
    """Verify settings writes do not follow a symlinked connector directory.

    Inputs: pytest provides `tmp_path`. Output: fails on directory symlink regressions.
    """
    module = _load_xt_module()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    settings_dir = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME
    try:
        settings_dir.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable on this platform")

    with pytest.raises(OSError):
        module._atomic_write_connector_settings(
            {},
            settings_dir / module.AUTOSAVE_SETTINGS_FILE_NAME,
        )


def test_connector_settings_load_skips_settings_directory_symlink(
    tmp_path, monkeypatch
):
    """Verify settings reads do not follow a symlinked connector directory.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on directory symlink regressions.
    """
    module = _load_xt_module()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real_path = real_dir / module.AUTOSAVE_SETTINGS_FILE_NAME
    real_path.write_text(
        f'{module.CONNECTOR_SETTINGS_HOST_KEY}="omero.example.org"\n',
        encoding="utf-8",
    )
    settings_dir = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME
    try:
        settings_dir.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable on this platform")
    logs = []
    monkeypatch.setattr(module, "_xt_debug", lambda message: logs.append(message))

    loaded = module._load_connector_settings(
        settings_dir / module.AUTOSAVE_SETTINGS_FILE_NAME
    )

    assert loaded == {}
    assert logs == ["Connector settings load skipped: settings directory is a symlink"]


def test_connector_settings_load_logs_malformed_values_without_crashing(
    tmp_path, monkeypatch
):
    """Verify malformed settings values are logged and ignored safely.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on parse-error handling regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        "\n".join(
            [
                'OMERO_CONNECTOR_HOST="unterminated',
                'OMERO_CONNECTOR_PORT="443"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    logs = []
    monkeypatch.setattr(module, "_xt_debug", lambda message: logs.append(message))

    loaded = module._load_connector_settings(settings_path)

    assert loaded == {module.CONNECTOR_SETTINGS_PORT_KEY: "443"}
    assert logs == [
        "Connector settings parse failed: OMERO_CONNECTOR_HOST on line 1 ignored"
    ]
    assert "unterminated" not in logs[0]


def test_connector_settings_snapshot_excludes_password_value(tmp_path):
    """Verify in-memory password entry values are never in persisted settings.

    Inputs: pytest provides `tmp_path`. Output: fails on password persistence regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(True)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False

    snapshot = module.OMEROBrowserDialog._connector_settings_snapshot(dialog)

    serialized = json.dumps(snapshot, sort_keys=True)
    assert "PASSWORD" not in serialized.upper()
    assert "super-secret" not in serialized
    assert snapshot == {
        module.CONNECTOR_SETTINGS_HOST_KEY: "omero.example.org",
        module.CONNECTOR_SETTINGS_PORT_KEY: "443",
        module.CONNECTOR_SETTINGS_USERNAME_KEY: "alice",
        module.CONNECTOR_SETTINGS_HTTPS_KEY: "true",
        module.CONNECTOR_SETTINGS_PATH_KEY: str(tmp_path),
        module.CONNECTOR_SETTINGS_AUTOSAVE_KEY: "true",
    }


def test_autosave_toggle_updates_settings_immediately_without_password(tmp_path):
    """Verify checkbox toggles write settings immediately after connection.

    Inputs: pytest provides `tmp_path`. Output: fails on autosave toggle regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    settings_path = module._connector_settings_env_path(tmp_path)
    dialog._connected = True
    dialog._settings_file_path = settings_path
    dialog._saved_settings = {}
    dialog._autosave_settings_write_error = ""
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(False)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False

    module.OMEROBrowserDialog._on_autosave_settings_changed(dialog)

    content = settings_path.read_text(encoding="utf-8")
    assert module.CONNECTOR_SETTINGS_AUTOSAVE_KEY + '="false"' in content
    assert "PASSWORD" not in content
    assert "super-secret" not in content


def test_autosave_write_failure_logs_and_keeps_dialog_usable(tmp_path, monkeypatch):
    """Verify settings write failures log and return without raising.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on write-error handling regressions.
    """
    module = _load_xt_module()
    blocked_settings_dir = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME
    blocked_settings_dir.write_text("not a directory", encoding="utf-8")
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._settings_file_path = (
        blocked_settings_dir / module.AUTOSAVE_SETTINGS_FILE_NAME
    )
    dialog._saved_settings = {}
    dialog._autosave_settings_write_error = ""
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(True)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    logs = []
    monkeypatch.setattr(module, "_xt_debug", lambda message: logs.append(message))

    assert module.OMEROBrowserDialog._write_autosave_settings(dialog) is False

    assert dialog._autosave_settings_write_error
    assert logs == ["Connector settings write failed: OSError"]
    assert "super-secret" not in "".join(logs)


def test_successful_connection_enables_autosave_and_writes_verified_settings(
    tmp_path, monkeypatch
):
    """Verify successful OMERO login enables autosave and writes current settings.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on connection autosave regressions.
    """
    module = _load_xt_module()
    created_clients = []

    class FakeClient:
        """Test double for a successful OMERO.web client."""

        def __init__(self, host, port, username, password, scheme="http"):
            """Create `FakeClient` and record connection arguments.

            Inputs: connection fields. Output: initializes fake client state.
            """
            self.host = host
            self.port = port
            self.username = username
            self.password = password
            self.scheme = scheme
            self.cookie_jar = None
            self.csrf_token = None
            self.session_id = None
            self.session_key = None
            created_clients.append(self)

        @staticmethod
        def connect():
            """Return a successful login result.

            Inputs: none. Output: bool.
            """
            return True

    monkeypatch.setattr(module, "OMEROWebClient", FakeClient)
    dialog = object.__new__(module.OMEROBrowserDialog)
    settings_path = module._connector_settings_env_path(tmp_path)
    converter_calls = []
    export_calls = []
    statuses = []
    dialog._connected = False
    dialog._connection_in_progress = False
    dialog.client = None
    dialog._settings_file_path = settings_path
    dialog._saved_settings = {}
    dialog._autosave_settings_write_error = ""
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(True)
    dialog.autosave_settings_check = _FakeButton()
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.connect_btn = _FakeButton()
    dialog.root = types.SimpleNamespace(update_idletasks=lambda: None)
    dialog._set_status = lambda text, color="#ecf0f1": statuses.append((text, color))
    dialog._set_connection_indicator = lambda _state: None
    dialog._schedule_health_ping = lambda: None
    dialog._load_projects = lambda: None
    dialog._detect_converter_options_after_connection = lambda: ["OMERO"]
    dialog._detect_folder_export_after_connection = lambda: {
        "available": True,
        "reason": "",
    }
    dialog._set_converter_options = lambda options: converter_calls.append(
        list(options)
    )
    dialog._set_folder_export_capability = lambda available, reason="": (
        export_calls.append((available, reason))
    )

    module.OMEROBrowserDialog._connect(dialog)

    content = settings_path.read_text(encoding="utf-8")
    assert created_clients[0].scheme == "https"
    assert dialog._connected is True
    assert dialog.autosave_settings_check.state == "normal"
    assert converter_calls == [[], ["OMERO"]]
    assert export_calls[-1] == (True, "")
    assert statuses[-1] == ("Connected to OMERO", "#d4edda")
    assert module.CONNECTOR_SETTINGS_HOST_KEY + '="omero.example.org"' in content
    assert module.CONNECTOR_SETTINGS_PORT_KEY + '="443"' in content
    assert module.CONNECTOR_SETTINGS_USERNAME_KEY + '="alice"' in content
    assert module.CONNECTOR_SETTINGS_HTTPS_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_PATH_KEY + f'="{tmp_path}"' in content
    assert "PASSWORD" not in content
    assert "super-secret" not in content


def test_browser_dialog_places_folder_selector_inside_connection_settings():
    """Verify folder selector UI stays inside the connection settings panel.

    Inputs: repository fixtures. Output: fails on UI layout regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    connection_marker = "conn_frame.grid_columnconfigure(7, weight=1)"
    selector_marker = "self.folder_path_entry = tk.Entry(\n            conn_frame,"
    browser_marker = "# Browser\n        browser = tk.Frame(self.root)"

    assert source.index(connection_marker) < source.index(selector_marker)
    assert source.index(selector_marker) < source.index(browser_marker)
    assert "folder_path_frame" not in source
    assert 'self._connection_label(conn_frame, "Path:").grid' in source
    assert 'FOLDER_PATH_PLACEHOLDER = "Type or select local path..."' in source
    assert (
        "self.folder_path_entry.grid(\n            row=2,\n            column=1,"
        in source
    )
    assert "columnspan=4,\n            sticky=tk.EW," in source
    assert "self.pass_entry.grid(\n            row=1, column=3, columnspan=2," in source
    assert "self.connect_btn.grid(row=0, column=5," in source
    assert "self.select_folder_btn.grid(row=2, column=5," in source
    assert (
        "self.autosave_settings_var = tk.BooleanVar(value=default_autosave_settings)"
        in source
    )
    assert 'text="Autosave settings"' in source
    assert 'text="Save settings"' not in source
    assert 'state=_tk_constant("DISABLED", "disabled")' in source
    assert "command=self._on_autosave_settings_changed" in source
    assert "bg=FOLDER_PATH_SELECT_BG" in source
    assert "activebackground=FOLDER_PATH_SELECT_ACTIVE_BG" in source
    assert "width=96" in source
    assert "height=38" in source
    assert 'text="Export folder to OMERO"' in source
    init_marker = source.index("def __init__(self, imaris, imaris_id=None):")
    settings_load = source.index(
        "self._saved_settings = _load_connector_settings", init_marker
    )
    tk_load = source.index("_ensure_tk_loaded()", init_marker)
    assert settings_load < tk_load


def test_connection_setting_labels_are_start_aligned_without_moving_entries():
    """Verify connection labels start-align while entry grid positions stay fixed.

    Inputs: repository fixtures. Output: fails on UI alignment regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    for label in ("Host", "Port", "Username", "Password", "Path"):
        assert f'self._connection_label(conn_frame, "{label}:").grid' in source

    assert 'anchor=_tk_constant("W", "w")' in source
    assert 'justify=_tk_constant("LEFT", "left")' in source
    assert "width=CONNECTION_LABEL_WIDTH" in source
    assert source.count('sticky=_tk_constant("NSEW", "nsew"), pady=5') >= 5
    assert "self.host_entry.grid(row=0, column=1, pady=5, padx=5)" in source
    assert "self.user_entry.grid(row=1, column=1, pady=5, padx=5)" in source


def test_converter_selector_remains_wired_in_connection_settings_panel():
    """Verify converter dropdown remains present in the connection settings panel.

    Inputs: repository fixtures. Output: fails on converter selector regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "self.converter_frame = tk.Frame(conn_frame)" in source
    assert 'tk.Label(self.converter_frame, text="Converter:").pack' in source
    assert "self.converter_menu = tk.Menubutton(" in source
    assert "self.converter_menu.pack(side=tk.LEFT)" in source
    assert (
        "self.converter_frame.grid(\n            row=0,\n            column=6,"
        in source
    )
    assert "rowspan=2,\n            sticky=tk.W," in source
    assert "self.converter_frame.grid_remove()" in source


def test_connection_settings_has_top_right_help_and_info_buttons():
    """Verify connection panel keeps responsive help and info icon buttons.

    Inputs: repository fixtures. Output: fails on connection panel icon regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "class _CircularIconButton(_RoundedButton):" in source
    assert "panel_icon_frame = tk.Frame(conn_frame)" in source
    assert "panel_icon_frame.grid(\n            row=0,\n            column=8," in source
    assert "rowspan=2,\n            sticky=tk.NE," in source
    assert "self.help_btn = _CircularIconButton(" in source
    assert 'text="?",' in source
    assert "self.help_btn.pack(side=tk.LEFT, padx=(0, 6))" in source
    assert "self.info_btn = _CircularIconButton(" in source
    assert 'text="i",' in source
    assert "self.info_btn.pack(side=tk.LEFT)" in source
    assert "CONNECTOR_PANEL_ICON_BG" in source
    assert "CONNECTOR_PANEL_ICON_ACTIVE_BG" in source


def test_status_text_aligns_with_load_button_start():
    """Verify bottom status text starts at the Load button's left edge.

    Inputs: repository fixtures. Output: fails on bottom status alignment regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "ACTION_ROW_HORIZONTAL_PAD = 10" in source
    assert "ACTION_BUTTON_PAD = 2" in source
    assert "STATUS_TEXT_PAD = ACTION_ROW_HORIZONTAL_PAD + ACTION_BUTTON_PAD" in source
    assert "actions.pack(fill=tk.X, padx=ACTION_ROW_HORIZONTAL_PAD" in source
    assert (
        "self.load_btn.grid(row=0, column=0, sticky=tk.W, padx=ACTION_BUTTON_PAD)"
        in source
    )
    assert "padx=STATUS_TEXT_PAD,\n            pady=5," in source


def test_action_buttons_keep_fixed_size_while_close_tracks_right_edge():
    """Verify action buttons stay fixed while only the row spacer expands.

    Inputs: repository fixtures. Output: fails on action-row resize regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "actions.grid_columnconfigure(2, weight=1)" in source
    assert "self.load_btn = _RoundedButton(" in source
    assert "width=260,\n            height=52," in source
    assert (
        "self.load_btn.grid(row=0, column=0, sticky=tk.W, padx=ACTION_BUTTON_PAD)"
        in source
    )
    assert (
        "self.export_btn.grid(row=0, column=1, sticky=tk.W, padx=ACTION_BUTTON_PAD)"
        in source
    )
    assert "close_btn = _RoundedButton(" in source
    assert "width=120,\n            height=52," in source
    assert (
        "close_btn.grid(row=0, column=3, sticky=tk.E, padx=ACTION_BUTTON_PAD)" in source
    )
    assert "self.load_btn.pack(" not in source
    assert "self.export_btn.pack(" not in source
    assert "close_btn.pack(" not in source


def test_export_folder_to_omero_starts_folder_worker_after_confirmation(
    tmp_path, monkeypatch
):
    """Verify export to OMERO starts folder worker after confirmation.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in export to OMERO starts folder worker after confirmation.
    """
    module = _load_xt_module()
    selected_folder = tmp_path / "selected"
    selected_folder.mkdir()

    busy_states = []
    statuses = []
    threads = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(str(selected_folder))
    dialog._export_folder_worker = lambda *_args: None
    dialog._set_actions_busy_for_export = busy_states.append
    dialog._set_status = lambda text, color="#ecf0f1": statuses.append((text, color))

    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("export action must use the selector row path")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module.messagebox,
        "askyesno",
        lambda *_args, **_kwargs: True,
        raising=False,
    )

    class _FakeThread:
        """Test double for fake thread."""

        def __init__(self, target, args, daemon):
            """Create `_FakeThread` with `target`, `args`, and `daemon`.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self.target = target
            self.args = args
            self.daemon = daemon
            threads.append({"target": target, "args": args, "daemon": daemon})

        @staticmethod
        def start():
            """Start `_FakeThread`'s fake operation.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    monkeypatch.setattr(module.threading, "Thread", _FakeThread)

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert busy_states == [True]
    assert statuses == [("Preparing folder export to OMERO...", "#fff3cd")]
    assert threads == [
        {
            "target": dialog._export_folder_worker,
            "args": (str(selected_folder), "selected"),
            "daemon": True,
        }
    ]


def test_export_folder_to_omero_rejects_filesystem_root(monkeypatch):
    """Confirm export to OMERO rejects filesystem root at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in export to OMERO rejects filesystem root.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(r"C:\\")
    dialog._set_actions_busy_for_export = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(AssertionError("busy state must not change"))
    dialog._set_status = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("status must not change")
    )

    errors = []
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert errors == [
        (
            "Invalid Folder",
            "Please select a regular folder, not a filesystem root.",
        )
    ]


def test_export_folder_to_omero_requires_existing_selector_path(monkeypatch):
    """Verify export rejects missing selector paths before worker startup.

    Inputs: pytest provides `monkeypatch`. Output: fails on export validation regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(r"C:\missing-folder")
    dialog._set_actions_busy_for_export = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(AssertionError("busy state must not change"))
    dialog._set_status = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("status must not change")
    )

    errors = []
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert errors == [
        (
            "Invalid Folder",
            "Please select or enter an existing folder.",
        )
    ]


def test_export_folder_to_omero_rejects_malformed_selector_path(monkeypatch):
    """Verify malformed typed selector paths do not crash the export action.

    Inputs: pytest provides `monkeypatch`. Output: fails on export validation regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar("C:\\bad\x00path")
    dialog._set_actions_busy_for_export = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(AssertionError("busy state must not change"))
    dialog._set_status = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("status must not change")
    )

    errors = []
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )
    monkeypatch.setattr(
        module.os.path,
        "isdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("embedded null byte")
        ),
    )

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert errors == [
        (
            "Invalid Folder",
            "Please select or enter an existing folder.",
        )
    ]


def test_export_folder_worker_uploads_folder_and_reports_success(tmp_path):
    """Verify export folder worker uploads folder and reports success.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in export folder worker uploads folder and reports success.
    """
    module = _load_xt_module()
    selected_folder = tmp_path / "batch"
    selected_folder.mkdir()
    (selected_folder / "first.txt").write_bytes(b"first")
    (selected_folder / "nested").mkdir()
    (selected_folder / "nested" / "second.txt").write_bytes(b"second")

    status_updates = []
    info_messages = []
    error_messages = []
    client_calls = []
    ui_callbacks = []

    status_sequence = iter(
        [
            {"status": "importing", "total_bytes": 11, "imported_bytes": 5},
            {"status": "done", "total_bytes": 11, "incompatible_files": []},
        ]
    )

    def _next_status(url):
        """Return the next status.

        Inputs: `url` URL. Output: `next` result.
        """
        client_calls.append(("status", url))
        return next(status_sequence, {})

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.client = types.SimpleNamespace(
        start_folder_export_job=lambda folder_name, entries: (
            client_calls.append(
                (
                    "start",
                    folder_name,
                    [(entry["relative_path"], entry["size"]) for entry in entries],
                )
            )
            or {
                "upload_url": "https://omero.example.org/upload/",
                "import_step_url": "https://omero.example.org/import/",
                "status_url": "https://omero.example.org/status/",
                "confirm_url": "https://omero.example.org/confirm/",
            }
        ),
        upload_folder_chunk=lambda *args: client_calls.append(("upload",) + args) or {},
        trigger_folder_export=lambda url: client_calls.append(("trigger", url)) or {},
        get_folder_export_status=_next_status,
        confirm_folder_export=lambda url: client_calls.append(("confirm", url)) or {},
    )
    dialog._set_status = lambda text, color="#ecf0f1": status_updates.append(
        (text, color)
    )
    dialog._show_info = lambda title, message: info_messages.append((title, message))
    dialog._show_error = lambda title, message: error_messages.append((title, message))
    dialog._invoke_on_ui_thread = lambda callback, wait=True: (
        ui_callbacks.append(wait),
        callback(),
    )[1]
    dialog._set_actions_busy_for_export = lambda active: client_calls.append(
        ("busy", active)
    )

    module.OMEROBrowserDialog._export_folder_worker(
        dialog,
        str(selected_folder),
        "batch",
    )

    assert client_calls[0] == (
        "start",
        "batch",
        [("first.txt", 5), ("nested/second.txt", 6)],
    )
    upload_calls = [call for call in client_calls if call[0] == "upload"]
    assert len(upload_calls) == 2
    assert upload_calls[0][1:] == (
        "https://omero.example.org/upload/",
        "first.txt",
        5,
        0,
        b"first",
        True,
    )
    assert upload_calls[1][1:] == (
        "https://omero.example.org/upload/",
        "nested/second.txt",
        6,
        0,
        b"second",
        True,
    )
    assert ("trigger", "https://omero.example.org/import/") in client_calls
    assert ("status", "https://omero.example.org/status/") in client_calls
    assert client_calls[-1] == ("busy", False)
    assert error_messages == []
    assert info_messages == [
        (
            "Folder Export Completed",
            "The folder was exported to OMERO root as dataset 'batch'.",
        )
    ]
    assert status_updates[-1] == ("Folder export completed in OMERO", "#d4edda")
    assert ui_callbacks[-1] is False


def test_images_ctrl_shift_click_adds_range_without_clearing_existing_selection():
    """Verify images ctrl shift click adds range without clearing existing selection.

    Inputs: repository fixtures. Output: fails on regressions in images ctrl shift click adds range without clearing existing selection.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.ilist = _FakeListbox(
        items=["a", "b", "c", "d", "e"],
        selection={0, 3},
    )
    dialog._image_selection_anchor = 0

    result = dialog._on_image_listbox_click(
        types.SimpleNamespace(widget=dialog.ilist, y=2, state=0x0001 | 0x0004)
    )

    assert result == "break"
    assert dialog.ilist.selection == {0, 1, 2, 3}
    assert dialog._image_selection_anchor == 0


def test_images_ctrl_click_toggles_single_selection_and_updates_anchor():
    """Verify images ctrl click toggles single selection and updates anchor.

    Inputs: repository fixtures. Output: fails on regressions in images ctrl click toggles single selection and updates anchor.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.ilist = _FakeListbox(items=["a", "b", "c"], selection={0})
    dialog._image_selection_anchor = 0

    result = dialog._on_image_listbox_click(
        types.SimpleNamespace(widget=dialog.ilist, y=2, state=0x0004)
    )

    assert result == "break"
    assert dialog.ilist.selection == {0, 2}
    assert dialog._image_selection_anchor == 2


def test_images_panel_click_sets_focus_for_native_border_highlight():
    """Verify Images clicks focus the listbox so Tk draws the active border.

    Inputs: repository fixtures. Output: fails on Images panel focus regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.ilist = _FakeListbox(items=["a", "b"], selection=set())
    dialog._image_selection_anchor = None

    result = dialog._on_image_listbox_click(
        types.SimpleNamespace(widget=dialog.ilist, y=1, state=0)
    )

    assert result == "break"
    assert dialog.ilist.focused is True
    assert dialog.ilist.selection == {1}
    assert dialog._image_selection_anchor == 1


def test_open_file_in_imaris_does_not_launch_fallback_when_live_handle_fails(tmp_path):
    """Confirm open file in imaris does not launch fallback when live handle fails exposes the expected failure.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in open file in imaris does not launch fallback when live handle fails.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")

    class _FailingImaris:
        """Test double for failing imaris behavior in this module."""

        @staticmethod
        def FileOpen(_path, *_args):
            """Record the file-open call on `_FailingImaris` for later assertions.

            Inputs: `_path`, `*_args`. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("bridge failed")

    assert module.open_file_in_imaris(ims_path, _FailingImaris()) is False


def test_parse_python_launcher_paths_handles_windows_launcher_output():
    """Verify parse python launcher paths handles windows launcher output.

    Inputs: repository fixtures. Output: fails on regressions in parse python launcher paths handles windows launcher output.
    """
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
    """Verify iter native bridge python executables uses py launcher and skips current.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in iter native bridge python executables uses py launcher and skips current.
    """
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
        resolved.get,
    )

    def _fake_run(cmd, **kwargs):
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
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
    """Verify the native bridge runner uses fixed python command and JSON payload execution contract.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in native bridge runner uses fixed python command and JSON payload integration.
    """
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
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
        calls.append((cmd, kwargs))
        payload = json.loads(kwargs["input"])
        assert cmd[0] == python_exe
        assert len(cmd) == 2
        assert "-c" not in cmd
        assert module._NATIVE_BRIDGE_OPEN_HELPER not in cmd
        assert (
            Path(cmd[1]).read_text(encoding="utf-8")
            == module._NATIVE_BRIDGE_OPEN_HELPER
        )
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
    assert not Path(calls[0][0][1]).exists()


def test_native_bridge_runner_allows_original_file_when_ims_not_required(
    tmp_path, monkeypatch
):
    """Verify native bridge runner allows original file when IMS not required.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in native bridge runner allows original file when IMS not required.
    """
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
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
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
    """Verify native bridge probe helper checks bridge without file open.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in native bridge probe helper checks bridge without file open.
    """
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
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
        payload = json.loads(kwargs["input"])
        assert cmd[0] == python_exe
        assert len(cmd) == 2
        assert "-c" not in cmd
        assert module._NATIVE_BRIDGE_OPEN_HELPER not in cmd
        assert (
            Path(cmd[1]).read_text(encoding="utf-8")
            == module._NATIVE_BRIDGE_OPEN_HELPER
        )
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
    """Verify native bridge helper reuses imarislib factory across retries.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in native bridge helper reuses imarislib factory across retries.
    """
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


def test_native_bridge_helper_prefers_one_argument_fileopen_for_originals(tmp_path):
    """Verify native bridge helper prefers one argument fileopen for originals.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in native bridge helper prefers one argument fileopen for originals.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_bytes(b"native input")
    calls_path = tmp_path / "calls.txt"
    fake_imarislib = tmp_path / "ImarisLib.py"
    fake_imarislib.write_text(
        "\n".join(
            [
                "import os",
                "calls_path = os.environ['IMARIS_FAKE_CALLS']",
                "",
                "class App:",
                "    def __init__(self):",
                "        self.current = ''",
                "",
                "    def FileOpen(self, *args):",
                "        with open(calls_path, 'a', encoding='utf-8') as handle:",
                "            handle.write(str(len(args)) + '\\n')",
                "        if len(args) == 1:",
                "            self.current = args[0]",
                "",
                "    def GetCurrentFileName(self):",
                "        return self.current",
                "",
                "class ImarisLib:",
                "    def GetApplication(self, app_id):",
                "        return App()",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "mode": "open",
        "app_id": 17,
        "install_roots": [str(tmp_path)],
        "retry_attempts": 1,
        "retry_interval": 0,
        "file_path": str(original_path),
        "require_ims": False,
        "open_verify_timeout": 0.01,
        "open_verify_interval": 0.01,
    }
    env = dict(os.environ)
    env["IMARIS_FAKE_CALLS"] = str(calls_path)

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

    assert completed.returncode == 0
    assert completed.stdout.strip() == "BRIDGE_RUNNER_OPENED"
    assert calls_path.read_text(encoding="utf-8").splitlines() == ["1"]


def test_native_bridge_helper_retries_with_options_after_typeerror_for_originals(
    tmp_path,
):
    """Verify native bridge helper retries with options after typeerror for originals.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in native bridge helper retries with options after typeerror for originals.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_bytes(b"native input")
    calls_path = tmp_path / "calls.txt"
    fake_imarislib = tmp_path / "ImarisLib.py"
    fake_imarislib.write_text(
        "\n".join(
            [
                "import os",
                "calls_path = os.environ['IMARIS_FAKE_CALLS']",
                "",
                "class App:",
                "    def __init__(self):",
                "        self.current = ''",
                "",
                "    def FileOpen(self, *args):",
                "        with open(calls_path, 'a', encoding='utf-8') as handle:",
                "            handle.write(str(len(args)) + '\\n')",
                "        if len(args) == 1:",
                "            raise TypeError(\"IApplicationPrx.FileOpen() missing 1 required positional argument: 'aOptions'\")",
                "        self.current = args[0]",
                "",
                "    def GetCurrentFileName(self):",
                "        return self.current",
                "",
                "class ImarisLib:",
                "    def GetApplication(self, app_id):",
                "        return App()",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "mode": "open",
        "app_id": 17,
        "install_roots": [str(tmp_path)],
        "retry_attempts": 1,
        "retry_interval": 0,
        "file_path": str(original_path),
        "require_ims": False,
        "open_verify_timeout": 0.01,
        "open_verify_interval": 0.01,
    }
    env = dict(os.environ)
    env["IMARIS_FAKE_CALLS"] = str(calls_path)

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

    assert completed.returncode == 0
    assert completed.stdout.strip() == "BRIDGE_RUNNER_OPENED"
    assert calls_path.read_text(encoding="utf-8").splitlines() == ["1", "2"]


def test_native_bridge_helper_accepts_original_submission_without_dataset_change(
    tmp_path,
):
    """Verify native bridge helper accepts original submission without dataset change.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in native bridge helper accepts original submission without dataset change.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_bytes(b"native input")
    calls_path = tmp_path / "calls.txt"
    fake_imarislib = tmp_path / "ImarisLib.py"
    fake_imarislib.write_text(
        "\n".join(
            [
                "import os",
                "calls_path = os.environ['IMARIS_FAKE_CALLS']",
                "",
                "class App:",
                "    def FileOpen(self, *args):",
                "        with open(calls_path, 'a', encoding='utf-8') as handle:",
                "            handle.write(str(len(args)) + '\\n')",
                "",
                "    def GetCurrentFileName(self):",
                "        return ''",
                "",
                "    def GetNumberOfImages(self):",
                "        return 1",
                "",
                "class ImarisLib:",
                "    def GetApplication(self, app_id):",
                "        return App()",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "mode": "open",
        "app_id": 17,
        "install_roots": [str(tmp_path)],
        "retry_attempts": 1,
        "retry_interval": 0,
        "file_path": str(original_path),
        "require_ims": False,
        "open_verify_timeout": 0.01,
        "open_verify_interval": 0.01,
    }
    env = dict(os.environ)
    env["IMARIS_FAKE_CALLS"] = str(calls_path)

    completed = subprocess.run(
        [sys.executable, "-c", module._NATIVE_BRIDGE_OPEN_HELPER],
        check=False,
        input=json.dumps(payload),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=env,
        timeout=15,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "BRIDGE_RUNNER_OPENED"
    assert calls_path.read_text(encoding="utf-8").splitlines() == ["1"]


def test_native_bridge_runner_suppresses_plural_ice_shutdown_warning(
    tmp_path, monkeypatch
):
    """Verify native bridge runner suppresses plural ice shutdown warning.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in native bridge runner suppresses plural ice shutdown warning.
    """
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
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
        assert cmd[0] == python_exe
        assert len(cmd) == 2
        assert "-c" not in cmd
        assert module._NATIVE_BRIDGE_OPEN_HELPER not in cmd
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


def test_native_bridge_runner_reports_raw_fileopen_as_submitted_request(
    tmp_path, monkeypatch
):
    """Verify native bridge runner reports raw fileopen as submitted request.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in native bridge runner reports raw fileopen as submitted request.
    """
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
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
        assert cmd[0] == python_exe
        assert len(cmd) == 2
        assert "-c" not in cmd
        assert module._NATIVE_BRIDGE_OPEN_HELPER not in cmd
        return types.SimpleNamespace(
            returncode=0,
            stdout="BRIDGE_RUNNER_OPENED\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert (
        module._run_native_bridge_helper(
            python_exe,
            {"mode": "open", "app_id": 17, "require_ims": False},
            "open",
            60,
        )
        is True
    )
    assert any(
        "submitted the original-file open request in the current Imaris session"
        in message
        for message in messages
    )
    assert not any("completed open request" in message for message in messages)


def test_native_bridge_runner_timeout_log_does_not_leak_helper_source(
    tmp_path,
    monkeypatch,
):
    """Verify native bridge runner timeout log does not leak helper source.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None after assertions pass. Raises: TimeoutExpired when validation or
    external operations fail.
    """
    module = _load_xt_module()
    python_exe = str(tmp_path / "python.exe")
    messages = []
    helper_paths = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)
    monkeypatch.setattr(
        module,
        "_resolve_python_executable_candidate",
        lambda path: python_exe if path == python_exe else None,
    )

    def _fake_run(cmd, **kwargs):
        """Raise a timeout carrying the command object.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: None. Raises:
        TimeoutExpired when validation or the called operation fails.
        """
        helper_paths.append(cmd[1])
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

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

    assert helper_paths
    assert not Path(helper_paths[0]).exists()
    assert any("timed out after 60 seconds" in message for message in messages)
    assert not any(module._NATIVE_BRIDGE_OPEN_HELPER in message for message in messages)
    assert not any("python -c" in message.lower() for message in messages)


def test_native_bridge_helper_exception_does_not_emit_traceback():
    """Confirm native bridge helper exception does not emit traceback exposes the expected failure.

    Inputs: repository fixtures. Output: fails on regressions when native bridge helper exception does not emit traceback stops reporting the expected error.
    """
    module = _load_xt_module()

    completed = subprocess.run(
        [sys.executable, "-c", module._NATIVE_BRIDGE_OPEN_HELPER],
        check=False,
        input="{",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=10,
    )

    assert completed.returncode == 70
    assert completed.stdout.strip() == "BRIDGE_RUNNER_EXCEPTION:JSONDecodeError"
    assert "Traceback" not in completed.stderr
    assert module._NATIVE_BRIDGE_OPEN_HELPER not in completed.stderr


def test_safe_download_filename_removes_paths_markers_and_reserved_names():
    """Check safe download filename removes paths markers and reserved names cleanup behavior.

    Inputs: repository fixtures. Output: fails on regressions in safe download filename removes paths markers and reserved names.
    """
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
    """Check that XT log sanitizer redacts session material and user paths keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in XT log sanitizer redacts session material and user paths.
    """
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
    """Check that safe URL for log redacts host IDs and query values keeps sensitive data out of output.

    Inputs: repository fixtures. Output: fails on regressions in safe URL for log redacts host IDs and query values.
    """
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


def test_download_chunk_size_is_bounded_runtime_configuration(monkeypatch):
    """Verify download chunk size is bounded runtime configuration.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in download chunk size is bounded runtime configuration.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.DOWNLOAD_CHUNK_SIZE_ENV, raising=False)

    assert (
        module._download_chunk_size_bytes() == module.DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES
    )

    monkeypatch.setenv(module.DOWNLOAD_CHUNK_SIZE_ENV, "not-an-int")
    assert (
        module._download_chunk_size_bytes() == module.DEFAULT_DOWNLOAD_CHUNK_SIZE_BYTES
    )

    monkeypatch.setenv(module.DOWNLOAD_CHUNK_SIZE_ENV, "1")
    assert module._download_chunk_size_bytes() == module.MIN_DOWNLOAD_CHUNK_SIZE_BYTES

    monkeypatch.setenv(
        module.DOWNLOAD_CHUNK_SIZE_ENV,
        str(module.MAX_DOWNLOAD_CHUNK_SIZE_BYTES * 2),
    )
    assert module._download_chunk_size_bytes() == module.MAX_DOWNLOAD_CHUNK_SIZE_BYTES

    monkeypatch.setenv(module.DOWNLOAD_CHUNK_SIZE_ENV, "131072")
    assert module._download_chunk_size_bytes() == 131072


def test_xt_connector_does_not_hardcode_selected_image_render_export():
    """Verify XT connector does not hardcode selected image render export.

    Inputs: repository fixtures. Output: fails on regressions in XT connector does not hardcode selected image render export.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "render_ome_tiff" not in source
    assert ".ome.tiff" not in source.lower()


def test_native_bridge_runner_rejects_non_ims_before_subprocess(tmp_path, monkeypatch):
    """Confirm native bridge runner rejects non IMS before subprocess is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in native bridge runner rejects non IMS before subprocess.
    """
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
    """Verify native bridge runner requires numeric imaris ID.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in native bridge runner requires numeric imaris ID.
    """
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
    """Verify native bridge runner tries discovered python until success.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in native bridge runner tries discovered python until success.
    """
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
        """Return the fake helper.

        Inputs: `python_executable`, `file_path` file path, `imaris_id`, `require_ims`.
        Output: `endswith` result.
        """
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
    """Confirm dialog native bridge probe runs before export and blocks when unavailable is rejected at the boundary.

    Inputs: repository fixtures. Output: fails on regressions in dialog native bridge probe runs before export and blocks when unavailable.
    """
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
    assert status_updates == [
        "Checking Imaris same-session open support...",
        "Opening a new Imaris session...",
    ]


def test_dialog_native_bridge_probe_does_not_trust_non_opening_handle():
    """Verify dialog native bridge probe does not trust non opening handle.

    Inputs: repository fixtures. Output: fails on regressions in dialog native bridge probe does not trust non opening handle.
    """
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
    assert status_updates == [
        "Checking Imaris same-session open support...",
        "Opening a new Imaris session...",
    ]


def test_dialog_native_bridge_probe_revalidates_stale_cached_python(
    tmp_path, monkeypatch
):
    """Verify dialog native bridge probe revalidates stale cached python.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in dialog native bridge probe revalidates stale cached python.
    """
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
    """Confirm dialog native bridge probe blocks after failed revalidation is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in dialog native bridge probe blocks after failed revalidation.
    """
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
    """Verify dialog native bridge probe skips recent revalidation.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in dialog native bridge probe skips recent revalidation.
    """
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
    """Verify dialog native bridge probe uses cached python for open.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in dialog native bridge probe uses cached python for open.
    """
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
    """Verify detect converter options defaults OMERO when server supports it.

    Inputs: repository fixtures. Output: fails on regressions in detect converter options defaults OMERO when server supports it.
    """
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
    """Verify detect converter options hides OMERO without server capability.

    Inputs: repository fixtures. Output: fails on regressions in detect converter options hides OMERO without server capability.
    """
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
    """Verify detect converter options hides dropdown when native open unavailable.

    Inputs: repository fixtures. Output: fails on regressions in detect converter options hides dropdown when native open unavailable.
    """
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
    """Verify set converter options hides dropdown and disables load.

    Inputs: repository fixtures. Output: fails on regressions in set converter options hides dropdown and disables load.
    """
    module = _load_xt_module()

    class DummyMenu:
        """Test double for dummy menu."""

        def __init__(self):
            """Create `DummyMenu` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.deleted = False

        def delete(self, start, end):
            """Delete the delete for `DummyMenu`.

            Inputs: `start`, `end`. Output: None.
            """
            self.deleted = (start, end)

        @staticmethod
        def add_command(label, command):
            """Add the command for `DummyMenu`.

            Inputs: `label`, `command`. Output: None. Raises: AssertionError when validation or the called operation fails.
            """
            raise AssertionError("no command should be added without options")

    class DummyFrame:
        """Test double for dummy frame."""

        def __init__(self):
            """Create `DummyFrame` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.hidden = False

        def pack_forget(self):
            """Remove pack geometry management.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self.hidden = True

    class DummyButton:
        """Test double for dummy button."""

        def __init__(self):
            """Create `DummyButton` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.state = None

        def config(self, **kwargs):
            """Apply widget configuration.

            Inputs: `**kwargs`. Output: None.
            """
            self.state = kwargs["state"]

    class DummyVar:
        """Test double for dummy var."""

        def __init__(self):
            """Create `DummyVar` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.value = "OMERO"

        def set(self, value):
            """Store the provided value.

            Inputs: `value`. Output: None.
            """
            self.value = value

    menu = DummyMenu()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_menu = {"menu": menu}
    dialog.converter_var = DummyVar()
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = DummyButton()
    dialog.refresh_btn = DummyButton()

    module.OMEROBrowserDialog._set_converter_options(dialog, [])

    assert menu.deleted == (0, "end")
    assert dialog.converter_var.value == ""
    assert dialog.converter_frame.hidden is True
    assert dialog.load_btn.state == "disabled"
    assert dialog.refresh_btn.state == "disabled"


def test_set_converter_options_populates_menu_without_blank_entry():
    """Verify set converter options populates menu without blank entry.

    Inputs: repository fixtures. Output: fails on regressions in set converter options populates menu without blank entry.
    """
    module = _load_xt_module()

    class DummyMenu:
        """Test double for dummy menu."""

        def __init__(self):
            """Create `DummyMenu` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.deleted = None
            self.commands = []

        def delete(self, start, end):
            """Delete the delete for `DummyMenu`.

            Inputs: `start`, `end`. Output: None.
            """
            self.deleted = (start, end)

        def add_command(self, label, command, **kwargs):
            """Add the command for `DummyMenu`.

            Inputs: `label`, `command`, `**kwargs` keyword arguments. Output: None.
            """
            self.commands.append((label, command, kwargs))

    class DummyFrame:
        """Test double for dummy frame."""

        def __init__(self):
            """Create `DummyFrame` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.shown = False

        def grid(self):
            """Apply grid geometry management.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self.shown = True

    class DummyButton:
        """Test double for dummy button."""

        def __init__(self):
            """Create `DummyButton` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.state = None

        def config(self, **kwargs):
            """Apply widget configuration.

            Inputs: `**kwargs`. Output: None.
            """
            self.state = kwargs["state"]

    class DummyVar:
        """Test double for dummy var."""

        def __init__(self):
            """Create `DummyVar` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.value = ""

        def set(self, value):
            """Store the provided value.

            Inputs: `value`. Output: None.
            """
            self.value = value

    menu = DummyMenu()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_menu = types.SimpleNamespace(menu=menu)
    dialog.converter_var = DummyVar()
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = DummyButton()
    dialog.refresh_btn = DummyButton()
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"

    module.OMEROBrowserDialog._set_converter_options(dialog, ["OMERO", "Imaris"])

    labels = [label for label, _command, _kwargs in menu.commands]
    assert menu.deleted == (0, "end")
    assert labels == ["OMERO", "Imaris"]
    assert "" not in labels
    assert "-" not in labels
    assert all(
        kwargs == {"font": module.CONVERTER_MENU_FONT, "hidemargin": True}
        for _label, _command, kwargs in menu.commands
    )
    assert dialog.converter_var.value == "OMERO"
    assert dialog.converter_frame.shown is True
    assert dialog.load_btn.state == "normal"
    assert dialog.refresh_btn.state == "normal"

    menu.commands[1][1]()
    assert dialog.converter_var.value == "Imaris"


def test_scrolled_listbox_disables_active_underline(monkeypatch):
    """Verify scrolled listbox disables active underline.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in scrolled listbox disables active underline.
    """
    module = _load_xt_module()
    created = {}

    class _FakeScrollbar:
        """Test double for fake scrollbar."""

        def __init__(self, parent, orient):
            """Create `_FakeScrollbar` with `parent` and `orient`.

            Inputs: `parent`, `orient`. Output: None.
            """
            self.parent = parent
            self.orient = orient
            self.command = None

        @staticmethod
        def pack(**_kwargs):
            """Apply pack geometry management.

            Inputs: `**_kwargs`. Output: None.
            """
            return None

        def config(self, **kwargs):
            """Apply widget configuration.

            Inputs: `**kwargs`. Output: None.
            """
            self.command = kwargs.get("command")

        @staticmethod
        def set(*_args):
            """Store the provided value.

            Inputs: `*_args`. Output: None.
            """
            return None

    class _FakeListbox:
        """Test double for fake listbox."""

        def __init__(self, parent, **kwargs):
            """Create `_FakeListbox` with `parent`.

            Inputs: `parent`, `**kwargs`. Output: None.
            """
            self.parent = parent
            self.kwargs = kwargs
            self.config_calls = []
            created["listbox"] = self

        def config(self, **kwargs):
            """Apply widget configuration.

            Inputs: `**kwargs`. Output: None.
            """
            self.config_calls.append(kwargs)

        @staticmethod
        def pack(**_kwargs):
            """Apply pack geometry management.

            Inputs: `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def yview(*_args):
            """Record the yview call on `_FakeListbox` for later assertions.

            Inputs: `*_args`. Output: None.
            """
            return None

        @staticmethod
        def xview(*_args):
            """Record the xview call on `_FakeListbox` for later assertions.

            Inputs: `*_args`. Output: None.
            """
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
    """Verify selected images returns all valid indexes result shape.

    Inputs: repository fixtures. Output: fails on regressions in selected images returns all valid indexes.
    """
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


def test_refresh_preserves_project_and_dataset_but_clears_image_selection():
    """Check that refresh preserves project and dataset but clears image selection remains stable.

    Inputs: repository fixtures. Output: fails on regressions in refresh preserves project and dataset but clears image selection.
    """
    module = _load_xt_module()
    dialog = _make_refresh_dialog(module)
    calls = []

    class _Client:
        """Test double for client behavior in this module."""

        @staticmethod
        def list_projects(**_kwargs):
            """Return list projects.

            Inputs: `**_kwargs`. Output: list.
            """
            calls.append("projects")
            return [
                {"id": "project-1", "name": "Project A"},
                {"id": "project-2", "name": "Project B"},
            ]

        @staticmethod
        def list_datasets(project_id, **_kwargs):
            """Return list datasets.

            Inputs: `project_id`, `**_kwargs`. Output: list.
            """
            calls.append(("datasets", project_id))
            return [
                {"id": "dataset-1", "name": "Dataset A"},
                {"id": "dataset-2", "name": "Dataset B"},
            ]

        @staticmethod
        def list_images(dataset_id, **_kwargs):
            """Return list images.

            Inputs: `dataset_id`, `**_kwargs`. Output: list.
            """
            calls.append(("images", dataset_id))
            return [
                {
                    "id": "image-1",
                    "name": "Image A",
                    "sizeX": 10,
                    "sizeY": 11,
                    "sizeZ": 1,
                    "sizeC": 1,
                    "sizeT": 1,
                },
                {
                    "id": "image-2",
                    "name": "Image B",
                    "sizeX": 20,
                    "sizeY": 21,
                    "sizeZ": 2,
                    "sizeC": 3,
                    "sizeT": 4,
                },
            ]

    dialog.client = _Client()

    module.OMEROBrowserDialog._refresh_worker(
        dialog,
        "project-1",
        "dataset-1",
        1,
    )

    assert calls == ["projects", ("datasets", "project-1"), ("images", "dataset-1")]
    assert dialog._pid == "project-1"
    assert dialog._did == "dataset-1"
    assert dialog.plist.items == ["Project A", "Project B"]
    assert dialog.dlist.items == ["Dataset A", "Dataset B"]
    assert dialog.ilist.items == ["Image A [10×11×1]", "Image B [20×21×2 C3 T4]"]
    assert dialog.plist.curselection() == (0,)
    assert dialog.dlist.curselection() == (0,)
    assert dialog.ilist.curselection() == ()
    assert dialog.refresh_btn.state == "normal"
    assert dialog.load_btn.state == "normal"
    assert dialog.status_updates[-1][0] == "OMERO browser refreshed"


def test_refresh_dataset_disappeared_keeps_project_and_clears_images():
    """Check that refresh dataset disappeared keeps project and clears images remains stable.

    Inputs: repository fixtures. Output: fails on regressions in refresh dataset disappeared keeps project and clears images.
    """
    module = _load_xt_module()
    dialog = _make_refresh_dialog(module)
    calls = []

    class _Client:
        """Test double for client behavior in this module."""

        @staticmethod
        def list_projects(**_kwargs):
            """Return list projects.

            Inputs: `**_kwargs`. Output: list.
            """
            calls.append("projects")
            return [{"id": "project-1", "name": "Project A"}]

        @staticmethod
        def list_datasets(project_id, **_kwargs):
            """Return list datasets.

            Inputs: `project_id`, `**_kwargs`. Output: list.
            """
            calls.append(("datasets", project_id))
            return [{"id": "dataset-2", "name": "Dataset B"}]

        @staticmethod
        def list_images(dataset_id, **_kwargs):
            """Return list images.

            Inputs: `dataset_id`, `**_kwargs`. Output: list.
            """
            calls.append(("images", dataset_id))
            return []

    dialog.client = _Client()

    module.OMEROBrowserDialog._refresh_worker(
        dialog,
        "project-1",
        "dataset-1",
        1,
    )

    assert calls == ["projects", ("datasets", "project-1")]
    assert dialog._pid == "project-1"
    assert dialog._did is None
    assert dialog.plist.items == ["Project A"]
    assert dialog.dlist.items == ["Dataset B"]
    assert dialog.ilist.items == []
    assert dialog.plist.curselection() == (0,)
    assert dialog.dlist.curselection() == ()
    assert dialog.ilist.curselection() == ()
    assert dialog.status_updates[-1][0] == (
        "Selected dataset is no longer available; datasets refreshed"
    )


def test_refresh_project_disappeared_clears_dataset_and_images():
    """Verify refresh project disappeared clears dataset and images.

    Inputs: repository fixtures. Output: fails on regressions in refresh project disappeared clears dataset and images.
    """
    module = _load_xt_module()
    dialog = _make_refresh_dialog(module)
    calls = []

    class _Client:
        """Test double for client behavior in this module."""

        @staticmethod
        def list_projects(**_kwargs):
            """Return list projects.

            Inputs: `**_kwargs`. Output: list.
            """
            calls.append("projects")
            return [{"id": "project-2", "name": "Project B"}]

        @staticmethod
        def list_datasets(project_id, **_kwargs):
            """Return list datasets.

            Inputs: `project_id`, `**_kwargs`. Output: list.
            """
            calls.append(("datasets", project_id))
            return []

        @staticmethod
        def list_images(dataset_id, **_kwargs):
            """Return list images.

            Inputs: `dataset_id`, `**_kwargs`. Output: list.
            """
            calls.append(("images", dataset_id))
            return []

    dialog.client = _Client()

    module.OMEROBrowserDialog._refresh_worker(
        dialog,
        "project-1",
        "dataset-1",
        1,
    )

    assert calls == ["projects"]
    assert dialog._pid is None
    assert dialog._did is None
    assert dialog.plist.items == ["Project B"]
    assert dialog.dlist.items == []
    assert dialog.ilist.items == []
    assert dialog.plist.curselection() == ()
    assert dialog.dlist.curselection() == ()
    assert dialog.ilist.curselection() == ()
    assert dialog.status_updates[-1][0] == (
        "Selected project is no longer available; projects refreshed"
    )


def test_refresh_ignores_stale_results_without_mutating_current_view():
    """Verify refresh ignores stale results without mutating current view.

    Inputs: repository fixtures. Output: fails on regressions in refresh ignores stale results without mutating current view.
    """
    module = _load_xt_module()
    dialog = _make_refresh_dialog(module)
    dialog._refresh_generation = 2

    module.OMEROBrowserDialog._apply_refresh_result(
        dialog,
        1,
        "project-1",
        "dataset-1",
        [{"id": "project-2", "name": "Project B"}],
        0,
        [],
        None,
        [],
    )

    assert dialog._pid == "project-1"
    assert dialog._did == "dataset-1"
    assert dialog.plist.items == ["Old project"]
    assert dialog.dlist.items == ["Old dataset"]
    assert dialog.ilist.items == ["Old image"]
    assert dialog.refresh_btn.configs == []
    assert dialog.load_btn.configs == []


def test_load_routes_single_selection_to_single_worker(tmp_path, monkeypatch):
    """Verify load routes single selection to single worker.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in load routes single selection to single worker.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    image = {"id": 1, "name": "single"}
    dialog.images_data = [image]
    dialog.ilist = types.SimpleNamespace(curselection=lambda: (0,))
    dialog.converter_var = types.SimpleNamespace(get=lambda: "OMERO")
    dialog.load_btn = types.SimpleNamespace(config=lambda **_kwargs: None)
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
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
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    class _FakeThread:
        """Test double for fake thread."""

        def __init__(self, target, args, daemon):
            """Create `_FakeThread` with `target`, `args`, and `daemon`.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self.target = target
            self.args = args
            self.daemon = daemon
            threads.append({"target": target, "args": args, "daemon": daemon})

        @staticmethod
        def start():
            """Start `_FakeThread`'s fake operation.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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


def test_load_routes_multi_selection_to_multi_worker(tmp_path, monkeypatch):
    """Verify load routes multi selection to multi worker.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in load routes multi selection to multi worker.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    first = {"id": 1, "name": "first"}
    second = {"id": 2, "name": "second"}
    dialog.images_data = [first, second]
    dialog.ilist = types.SimpleNamespace(curselection=lambda: (0, 1))
    dialog.converter_var = types.SimpleNamespace(get=lambda: "Imaris")
    dialog.load_btn = types.SimpleNamespace(config=lambda **_kwargs: None)
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
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
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    class _FakeThread:
        """Test double for fake thread."""

        def __init__(self, target, args, daemon):
            """Create `_FakeThread` with `target`, `args`, and `daemon`.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self.target = target
            self.args = args
            self.daemon = daemon
            threads.append({"target": target, "args": args, "daemon": daemon})

        @staticmethod
        def start():
            """Start `_FakeThread`'s fake operation.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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


def test_load_worker_imaris_converter_submits_original_with_native_fileopen(
    tmp_path,
):
    """Verify load worker imaris converter submits original with native fileopen.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in load worker imaris converter submits original with native fileopen.
    """
    module = _load_xt_module()
    original_file = tmp_path / "sample.lif"
    original_file.write_bytes(b"native input")
    calls = []
    opened = []
    statuses = []
    info_messages = []

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
    dialog._set_status = lambda text, color="#ecf0f1": statuses.append((text, color))
    dialog._show_info = lambda title, message: info_messages.append((title, message))
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
    assert statuses[-1][0] == "Submitted original file to Imaris"
    assert info_messages == [
        (
            "Submitted to Imaris",
            "Imaris accepted the original-file open request in the current "
            "session. A loaded dataset may not be observable yet because the "
            "native Imaris import workflow can continue interactively there.",
        )
    ]
    assert all("Opened original" not in status[0] for status in statuses)


def test_load_worker_omero_converter_downloads_ims_and_requires_ims(tmp_path):
    """Verify load worker OMERO converter downloads IMS and requires IMS.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in load worker OMERO converter downloads IMS and requires IMS.
    """
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
    """Verify load multiple worker OMERO waits for all downloads before open.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in load multiple worker OMERO waits for all downloads before open.
    """
    module = _load_xt_module()
    first_ims = tmp_path / "first.ims"
    second_ims = tmp_path / "second.ims"
    first_ims.write_bytes(b"\x89HDF\r\n\x1a\nfirst")
    second_ims.write_bytes(b"\x89HDF\r\n\x1a\nsecond")
    files_by_id = {11: str(first_ims), 12: str(second_ims)}
    events = []
    info_messages = []

    def _download_ims_export(image_id, download_dir, fallback_name):
        """Download the IMS export.

        Inputs: `image_id` OMERO image ID, `download_dir`, `fallback_name`. Output:
        download IMS export result.
        """
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
        """Open the downloaded files.

        Inputs: `paths`, `require_ims`. Output: `bool`.
        """
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


def test_load_multiple_worker_imaris_submits_originals_after_downloads(
    tmp_path,
):
    """Verify load multiple worker imaris submits originals after downloads.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in load multiple worker imaris submits originals after downloads.
    """
    module = _load_xt_module()
    first_original = tmp_path / "first.lif"
    second_original = tmp_path / "second.czi"
    first_original.write_bytes(b"first")
    second_original.write_bytes(b"second")
    files_by_id = {21: str(first_original), 22: str(second_original)}
    events = []
    opened = []
    statuses = []
    info_messages = []

    def _download_original_file(image_id, download_dir, fallback_name):
        """Download the original file.

        Inputs: `image_id` OMERO image ID, `download_dir`, `fallback_name`. Output:
        download original file result.
        """
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
    dialog._set_status = lambda text, color="#ecf0f1": statuses.append((text, color))
    dialog._show_info = lambda title, message: info_messages.append((title, message))
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
    assert statuses[-1][0] == "Submitted selected original files to Imaris"
    assert info_messages[0][0] == "Submitted to Imaris"
    assert "accepted the selected original-file open requests" in info_messages[0][1]


def test_load_worker_blocks_before_download_when_native_open_unavailable(tmp_path):
    """Confirm load worker blocks before download when native open unavailable is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in load worker blocks before download when native open unavailable.
    """
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
    """Verify load worker failure logs without raw traceback.

    Inputs: pytest provides `tmp_path`, `monkeypatch`, `capsys`. Output: fails on regressions in load worker failure logs without raw traceback.
    """
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
    """Confirm load worker blocks imaris download when native open unavailable is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in load worker blocks imaris download when native open unavailable.
    """
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
    """Verify set process window title uses windows API without shell.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in set process window title uses windows API without shell.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)

    class _FakeKernel32:
        """Test double for fake kernel32."""

        calls = []

        @classmethod
        def SetConsoleTitleW(cls, title):
            """Set the console Title W for `_FakeKernel32`.

            Inputs: `title`. Output: `int`.
            """
            cls.calls.append(title)
            return 1

    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=_FakeKernel32)
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert module._set_process_window_title("OMERO Connector") is True
    assert _FakeKernel32.calls == ["OMERO Connector"]


def test_windows_platform_status_supports_windows_10_and_11(monkeypatch):
    """Verify the startup platform gate accepts Windows 10 and Windows 11.

    Inputs: pytest provides `monkeypatch`. Output: fails on platform gate regressions.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)

    monkeypatch.setattr(
        module,
        "_read_windows_version_via_rtl_get_version",
        lambda: module._WindowsVersion(10, 0, 19045, "RtlGetVersion"),
    )
    windows_10_status = module._windows_platform_status()

    monkeypatch.setattr(
        module,
        "_read_windows_version_via_rtl_get_version",
        lambda: module._WindowsVersion(10, 0, 22631, "RtlGetVersion"),
    )
    windows_11_status = module._windows_platform_status()

    assert windows_10_status.supported is True
    assert windows_10_status.version.build == 19045
    assert "supported Windows 10.0.19045" in windows_10_status.message
    assert windows_11_status.supported is True
    assert windows_11_status.version.build == 22631
    assert "supported Windows 10.0.22631" in windows_11_status.message


def test_windows_platform_status_rejects_older_or_unreliable_platforms(
    monkeypatch,
):
    """Verify the startup platform gate rejects older or unverifiable systems.

    Inputs: pytest provides `monkeypatch`. Output: fails on platform gate regressions.
    """
    module = _load_xt_module()

    monkeypatch.setattr(module.os, "name", "posix", raising=False)
    non_windows_status = module._windows_platform_status()

    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        module,
        "_read_windows_version_via_rtl_get_version",
        lambda: module._WindowsVersion(6, 3, 9600, "RtlGetVersion"),
    )
    windows_81_status = module._windows_platform_status()

    monkeypatch.setattr(
        module,
        "_read_windows_version_via_rtl_get_version",
        lambda: None,
    )
    unknown_status = module._windows_platform_status()

    assert non_windows_status.supported is False
    assert "non-Windows" in non_windows_status.message
    assert windows_81_status.supported is False
    assert "Detected Windows 6.3.9600" in windows_81_status.message
    assert unknown_status.supported is False
    assert "could not be determined reliably" in unknown_status.message


def test_xt_entrypoint_blocks_before_gui_on_unsupported_platform(
    monkeypatch,
    capsys,
):
    """Verify unsupported platforms block before any GUI or Imaris startup work.

    Inputs: pytest provides `monkeypatch`, `capsys`. Output: fails on startup ordering regressions.
    """
    module = _load_xt_module()
    log_calls = []
    unsupported = module._WindowsPlatformStatus(
        supported=False,
        message=(
            "OMERO Connector requires Windows 10 or later. "
            "Detected Windows 6.3.9600 via RtlGetVersion; minimum is 10.0."
        ),
    )

    monkeypatch.setattr(module, "_windows_platform_status", lambda: unsupported)
    monkeypatch.setattr(
        module,
        "_xt_log_path",
        lambda: r"C:\Temp\XTOmeroConnector_20260505.log",
    )
    monkeypatch.setattr(
        module,
        "_xt_write_log",
        lambda log_path, message: log_calls.append((log_path, message)),
    )
    monkeypatch.setattr(
        module,
        "_set_process_window_title",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("window title must not be set before platform gate")
        ),
    )
    monkeypatch.setattr(
        module,
        "_log_imaris_xt_diagnostics",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("diagnostics must not run before platform gate")
        ),
    )
    monkeypatch.setattr(
        module,
        "_ensure_tk_loaded",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Tk must not load before platform gate")
        ),
    )
    monkeypatch.setattr(
        module,
        "OMEROBrowserDialog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("GUI must not open before platform gate")
        ),
    )

    module.XTOmeroConnector(None)

    captured = capsys.readouterr()
    assert "startup blocked" in captured.out
    assert "Windows 10 or later" in captured.out
    assert log_calls == [
        (
            r"C:\Temp\XTOmeroConnector_20260505.log",
            "XTOmeroConnector startup blocked: " + unsupported.message,
        )
    ]


def test_is_ims_file_accepts_only_existing_regular_hdf5_files(tmp_path):
    """Verify is IMS file accepts only existing regular hdf5 files.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in is IMS file accepts only existing regular hdf5 files.
    """
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
    """Verify XT write log accepts only connector logs in temp root.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in XT write log accepts only connector logs in temp root.
    """
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
    """Verify browser dialog reenable load button uses normal state.

    Inputs: repository fixtures. Output: fails on regressions in browser dialog reenable load button uses normal state.
    """
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
    """Verify browser dialog sets initial window as minimum size.

    Inputs: repository fixtures. Output: fails on regressions in browser dialog sets initial window as minimum size.
    """
    module = _load_xt_module()

    class DummyRoot:
        """Test double for dummy root."""

        def __init__(self):
            """Create `DummyRoot` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.updated = False
            self.geometry_value = None
            self.minimum_size = None
            self.resizable_value = None

        def update_idletasks(self):
            """Update the idletasks for `DummyRoot`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self.updated = True

        @staticmethod
        def winfo_width():
            """Return the winfo width for `DummyRoot`.

            Inputs: none. Output: `int`.
            """
            return 980

        @staticmethod
        def winfo_height():
            """Return the winfo height for `DummyRoot`.

            Inputs: none. Output: `int`.
            """
            return 680

        @staticmethod
        def winfo_reqwidth():
            """Return the winfo reqwidth for `DummyRoot`.

            Inputs: none. Output: `int`.
            """
            return 1010

        @staticmethod
        def winfo_reqheight():
            """Return the winfo reqheight for `DummyRoot`.

            Inputs: none. Output: `int`.
            """
            return 720

        def geometry(self, value):
            """Record the geometry call on `DummyRoot` for later assertions.

            Inputs: `value` input value. Output: None.
            """
            self.geometry_value = value

        def minsize(self, width, height):
            """Record the minsize call on `DummyRoot` for later assertions.

            Inputs: `width`, `height`. Output: None.
            """
            self.minimum_size = (width, height)

        def resizable(self, width_enabled, height_enabled):
            """Record the resizable call on `DummyRoot` for later assertions.

            Inputs: `width_enabled`, `height_enabled`. Output: None.
            """
            self.resizable_value = (width_enabled, height_enabled)

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = DummyRoot()

    module.OMEROBrowserDialog._configure_initial_window_constraints(dialog)

    assert dialog.root.updated is True
    assert dialog.root.geometry_value == "1010x760"
    assert dialog.root.minimum_size == (1010, 760)
    assert dialog.root.resizable_value == (True, True)


def test_browser_dialog_invoke_on_ui_thread_returns_callback_value():
    """Verify browser dialog invoke on UI thread returns callback value result shape.

    Inputs: repository fixtures. Output: fails on regressions in browser dialog invoke on UI thread returns callback value.
    """
    module = _load_xt_module()

    class _Root:
        """Test double for root behavior in this module."""

        @staticmethod
        def after(_delay, callback):
            """Record the after call on `_Root` for later assertions.

            Inputs: `_delay`, `callback`. Output: None.
            """
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
    """Confirm browser dialog invoke on UI thread reraises callback error exposes the expected failure.

    Inputs: repository fixtures. Output: fails on regressions when browser dialog invoke on UI thread reraises callback error stops reporting the expected error.
    """
    module = _load_xt_module()

    class _Root:
        """Test double for root behavior in this module."""

        @staticmethod
        def after(_delay, callback):
            """Record the after call on `_Root` for later assertions.

            Inputs: `_delay`, `callback`. Output: None.
            """
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
    """Verify find imaris executable prefers env override.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in find imaris executable prefers env override.
    """
    module = _load_xt_module()
    imaris_exe = r"C:\Apps\Imaris 11.0.0\Imaris.exe"
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setenv("IMARIS_EXE", imaris_exe)
    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == imaris_exe)

    assert module._find_imaris_executable() == imaris_exe


def test_imaris_version_gate_allows_11_and_future_but_rejects_older_or_unknown():
    """Confirm imaris version gate allows 11 and future but rejects older or unknown is rejected at the boundary.

    Inputs: repository fixtures. Output: fails on regressions in imaris version gate allows 11 and future but rejects older or unknown.
    """
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
    """Verify prepare imaris XT environment adds bundled paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in prepare imaris XT environment adds bundled paths.
    """
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
    """Verify collect imaris XT diagnostics reports import failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in collect imaris XT diagnostics reports import failures.
    Raises: ImportError when validation or the called operation fails.
    """
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
        """Return the raising import.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `original_import` result. Raises: ImportError when validation or
        external operations fail.
        """
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
    """Verify resolve imaris application returns direct handle result shape.

    Inputs: repository fixtures. Output: fails on regressions in resolve imaris application returns direct handle.
    """
    module = _load_xt_module()
    direct_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)

    assert module._resolve_imaris_application(direct_handle) is direct_handle
