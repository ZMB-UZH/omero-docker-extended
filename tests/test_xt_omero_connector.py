from __future__ import annotations

import ast
import importlib.util
import builtins
import inspect
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
    "omero_imaris_connector",
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


def _enable_native_bridge(module, monkeypatch):
    """Enable the opt-in IcePy-backed native bridge for tests that cover it.

    Inputs: `module`, `monkeypatch`. Output: None.
    """
    monkeypatch.setenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, "true")


def _test_env_flag(name):
    """Return whether a boolean test environment flag is enabled.

    Inputs: `name`. Output: bool.
    """
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_live_imaris_install(module):
    """Return detected Imaris executable or skip when this host has no Imaris.

    Inputs: `module`. Output: Imaris executable path.
    """
    imaris_executable = module._find_imaris_executable()
    if imaris_executable:
        return imaris_executable
    message = "Supported Imaris 11+ installation is not detectable on this host."
    if _test_env_flag("IMARIS_OMERO_REQUIRE_LIVE_IMARIS_TESTS"):
        raise AssertionError(message)
    raise pytest.skip.Exception(message)


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
        self.options = {}
        self.bindings = {}

    def get(self):
        """Return the stored entry value.

        Inputs: none. Output: `self.value`.
        """
        return self.value

    def delete(self, _start, _end=None):
        """Clear the stored entry value.

        Inputs: `_start`, optional `_end`. Output: None.
        """
        self.value = ""

    def config(self, **kwargs):
        """Apply widget configuration.

        Inputs: `**kwargs`. Output: None.
        """
        self.configs.append(kwargs)
        self.options.update(kwargs)

    def bind(self, sequence, callback):
        """Record a Tk binding.

        Inputs: `sequence`, `callback`. Output: None.
        """
        self.bindings[sequence] = callback


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


def _noop(*_args, **_kwargs):
    """No-op helper for tests that need an explicit callback.

    Inputs: ignored. Output: None.
    """


class _ImmediateThread:
    """Thread test double that runs the target when `start` is called."""

    def __init__(self, target, args=(), kwargs=None, daemon=None):
        """Create `_ImmediateThread` with target call details.

        Inputs: `target`, `args`, `kwargs`, `daemon`. Output: stores call details.
        """
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        """Run the target synchronously.

        Inputs: none. Output: target return value.
        """
        return self.target(*self.args, **self.kwargs)


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


def test_omero_web_client_uses_checkbox_scheme_and_rejects_scheme_in_host():
    """Verify OMERO.web URLs use the scheme and port controls only.

    Inputs: repository fixtures. Output: fails on host/scheme boundary regressions.
    """
    module = _load_xt_module()

    assert (
        module.OMEROWebClient._build_base_url("omero.example.org", 443, "https")
        == "https://omero.example.org:443"
    )
    assert (
        module.OMEROWebClient._build_base_url("2001:db8::1", "443", "https")
        == "https://[2001:db8::1]:443"
    )
    assert (
        module._omero_web_host_input_error("https://omero.example.org")
        == module.HOST_FIELD_SCHEME_ERROR_MESSAGE
    )
    assert (
        module._omero_web_host_input_error("omero.example.org:443")
        == module.HOST_FIELD_PORT_ERROR_MESSAGE
    )
    with pytest.raises(ValueError, match="without http"):
        module.OMEROWebClient._build_base_url("https://omero.example.org", 443, "https")


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
            return _FakeHTTPResponse(
                (
                    '{"omero_ims_export": true, '
                    '"omero_ims_export_capability": '
                    '"zmb_omero_imaris_connector_v1", '
                    '"converters": {"OMERO": true}}'
                ).encode("utf-8")
            )

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is True
    assert opened_urls == [
        (
            f"{client.base_url}/omero_imaris_connector/imaris-export/?capabilities=1",
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


def test_client_rejects_legacy_missing_image_capability_response(
    monkeypatch,
):
    """Verify client rejects legacy missing-image capability responses.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in client accepts endpoints without the custom capability flag.
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

    assert client.has_omero_ims_export_capability() is False


def test_client_rejects_capability_payload_without_custom_flag():
    """Verify OMERO converter capability requires the custom setup flag.

    Inputs: repository fixtures. Output: fails on regressions in strict OMERO converter detection.
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
            return _FakeHTTPResponse(
                b'{"omero_ims_export": true, "converters": {"OMERO": true}}'
            )

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is False


def test_client_rejects_capability_payload_with_false_converter_flag():
    """Verify custom flag alone does not enable the OMERO converter.

    Inputs: repository fixtures. Output: fails on regressions in converter-specific capability validation.
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
            return _FakeHTTPResponse(
                (
                    '{"omero_ims_export": true, '
                    '"omero_ims_export_capability": '
                    '"zmb_omero_imaris_connector_v1", '
                    '"converters": {"OMERO": false}}'
                ).encode("utf-8")
            )

    client.opener = _FakeOpener()

    assert client.has_omero_ims_export_capability() is False


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


def test_resolve_imaris_application_uses_imarislib_factory(monkeypatch):
    """Verify resolve imaris application uses imarislib factory.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve imaris application uses imarislib factory.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
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

    assert module._native_imaris_bridge_enabled() is False
    assert module._resolve_imaris_application(17) is expected


def test_resolve_imaris_application_retries_until_handle_available(monkeypatch):
    """Verify resolve imaris application retries until handle available.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve imaris application retries until handle available.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
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
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
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


def test_resolve_imaris_application_returns_none_when_bridge_module_is_unloaded(
    monkeypatch,
):
    """Confirm resolution does not import an unloaded native bridge module.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions that
    import Bitplane's native IcePy stack into the current Python process.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        """Reject unsafe in-process native bridge imports.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `real_import` result. Raises: AssertionError for native bridge imports.
        """
        if name == "ImarisLib":
            raise AssertionError("native Imaris bridge must run in a helper process")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    assert module._resolve_imaris_application(17) is None


def test_optional_icepy_bridge_is_disabled_by_default_without_diagnostic_import_noise(
    monkeypatch,
):
    """Verify the IcePy bridge flag is disabled by default and diagnostics are quiet.

    Inputs: pytest provides `monkeypatch`. Output: fails on opt-in bridge regressions.
    Raises: AssertionError if disabled diagnostics attempt bridge imports.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    messages = []
    monkeypatch.setattr(module, "_xt_debug", messages.append)

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        """Fail if disabled startup attempts Imaris bridge imports.

        Inputs: import call arguments. Output: imported module for non-bridge imports.
        Raises: AssertionError for disabled bridge imports.
        """
        if name in {"ImarisLib", "IcePy"}:
            raise AssertionError("disabled native bridge must not import IcePy code")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setattr(module, "_find_imaris_executable", lambda: "")
    monkeypatch.setattr(module, "_iter_imaris_install_roots", lambda: iter(()))

    assert module._native_imaris_bridge_enabled() is False
    module._log_imaris_xt_diagnostics()

    joined_messages = "\n".join(messages)
    assert "IcePy" not in joined_messages
    assert "ImarisLib_error" not in joined_messages


def test_resolve_imaris_application_hides_icepy_detail_when_optional_bridge_disabled(
    monkeypatch,
):
    """Verify disabled optional bridge does not import or leak IcePy details.

    Inputs: pytest provides `monkeypatch`. Output: fails on direct handle diagnostics regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    messages = []

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        """Reject unsafe in-process native bridge imports.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `real_import` result. Raises: AssertionError for native bridge imports.
        """
        if name == "ImarisLib":
            raise AssertionError("native Imaris bridge must run in a helper process")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    monkeypatch.setattr(module, "_xt_debug", messages.append)

    assert module._resolve_imaris_application(17) is None
    joined_messages = "\n".join(messages)
    assert "Direct in-process ImarisLib import skipped" in joined_messages
    assert "IcePy" not in joined_messages
    assert "compatible native bridge runner" not in joined_messages


def test_resolve_imaris_application_bridge_failure_message_keeps_runner_path(
    monkeypatch,
):
    """Check that optional bridge diagnostics point to the helper-runner path.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when
    direct bridge resolution hides the helper-runner path.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    messages = []

    real_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        """Reject unsafe in-process native bridge imports.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `real_import` result. Raises: AssertionError for native bridge imports.
        """
        if name == "ImarisLib":
            raise AssertionError("native Imaris bridge must run in a helper process")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
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

        def __init__(self):
            """Create `_FakeImaris` with empty current-file state.

            Inputs: none. Output: initializes state.
            """
            self.current = ""

        def FileOpen(self, path, *_args):
            """Record the file-open call on `_FakeImaris` for later assertions.

            Inputs: `path` path, `*_args`. Output: None.
            """
            opened.append(path)
            self.current = path

        def GetCurrentFileName(self):
            """Return the verified current file path.

            Inputs: none. Output: current path string.
            """
            return self.current

    imaris = _FakeImaris()

    assert module.open_file_in_imaris(ims_path, imaris) is True
    assert opened == [str(ims_path)]


def test_open_file_in_imaris_accepts_openfile_only_handles(tmp_path):
    """Verify OpenFile-only Imaris handles remain valid for same-session opening.

    Inputs: pytest provides `tmp_path`. Output: fails on OpenFile compatibility regressions.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    opened = []

    class _FakeImaris:
        """OpenFile-only Imaris API test double."""

        def __init__(self):
            """Create `_FakeImaris` with empty current-file state.

            Inputs: none. Output: initializes state.
            """
            self.current = ""

        def OpenFile(self, path, *_args):
            """Record the open call.

            Inputs: `path`, optional API args. Output: None.
            """
            opened.append(path)
            self.current = path

        def GetCurrentFileName(self):
            """Return the verified current file path.

            Inputs: none. Output: current path string.
            """
            return self.current

    imaris = _FakeImaris()

    assert module._looks_like_imaris_application(imaris) is True
    assert module.open_file_in_imaris(ims_path, imaris) is True
    assert opened == [str(ims_path)]


def test_open_file_in_imaris_accepts_legacy_loadfile_handles(tmp_path):
    """Verify legacy LoadFile-only Imaris handles remain valid after validation.

    Inputs: pytest provides `tmp_path`. Output: fails on legacy API compatibility regressions.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    opened = []

    class _FakeImaris:
        """LoadFile-only Imaris API test double."""

        def __init__(self):
            """Create `_FakeImaris` with empty current-file state.

            Inputs: none. Output: initializes state.
            """
            self.current = ""

        def LoadFile(self, path, *_args):
            """Record the open call.

            Inputs: `path`, optional API args. Output: None.
            """
            opened.append(path)
            self.current = path

        def GetCurrentFileName(self):
            """Return the verified current file path.

            Inputs: none. Output: current path string.
            """
            return self.current

    imaris = _FakeImaris()

    assert module._looks_like_imaris_application(imaris) is True
    assert module.open_file_in_imaris(ims_path, imaris) is True
    assert opened == [str(ims_path)]


def test_open_file_in_imaris_rejects_unverified_current_file(tmp_path, monkeypatch):
    """Confirm open file in imaris rejects unverified current file is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in open file in imaris rejects unverified current file.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    other_path = tmp_path / "other.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_INTERVAL", 0.01)

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


def test_open_file_in_imaris_rejects_unverified_fileopen_without_current_file(
    tmp_path,
    monkeypatch,
):
    """Confirm bare IMS FileOpen success is not treated as a verified open.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: asserts IMS open
    success is rejected without current-file or visible-dataset proof.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_INTERVAL", 0.01)
    opened = []

    class _FakeImaris:
        """Handle that reports no verifiable loaded file or dataset."""

        @staticmethod
        def FileOpen(path, *_args):
            """Record an unverified FileOpen call.

            Inputs: `path`, optional args. Output: None.
            """
            opened.append(path)

    assert module.open_file_in_imaris(ims_path, _FakeImaris()) is False
    assert opened == [str(ims_path), str(ims_path)]


def test_open_file_in_imaris_requires_visible_dataset_without_current_file(
    tmp_path,
    monkeypatch,
):
    """Verify no-current-file IMS opens require an explicit visible dataset handoff.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on unverified
    dataset handoff regressions.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_INTERVAL", 0.01)

    class _FakeDataSet:
        """Dataset test double with valid dimensions."""

        @staticmethod
        def GetSizeX():
            """Return a positive X dimension.

            Inputs: none. Output: int.
            """
            return 12

        @staticmethod
        def GetSizeY():
            """Return a positive Y dimension.

            Inputs: none. Output: int.
            """
            return 8

        @staticmethod
        def GetSizeZ():
            """Return a positive Z dimension.

            Inputs: none. Output: int.
            """
            return 1

    class _FakeImaris:
        """Handle that exposes loaded data but no current-file getter."""

        def __init__(self):
            """Create fake Imaris state.

            Inputs: none. Output: initializes state.
            """
            self.data_set = None
            self.visible_data_set = None

        def FileOpen(self, _path, *_args):
            """Load a dataset without exposing current-file metadata.

            Inputs: `_path`, optional args. Output: None.
            """
            self.data_set = _FakeDataSet()

        def GetDataSet(self):
            """Return the loaded dataset.

            Inputs: none. Output: dataset object or None.
            """
            return self.data_set

        def SetDataSet(self, data_set):
            """Record the visible dataset handoff.

            Inputs: `data_set`. Output: None.
            """
            self.visible_data_set = data_set

    imaris = _FakeImaris()

    assert module.open_file_in_imaris(ims_path, imaris) is True
    assert imaris.visible_data_set is imaris.data_set


def test_open_file_in_imaris_accepts_visible_dataset_when_current_file_stays_stale(
    tmp_path,
    monkeypatch,
):
    """Verify visible-dataset proof can override stale current-file metadata.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails when Imaris
    APIs that do not update current-file metadata cannot still verify visible data.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_INTERVAL", 0.01)

    class _FakeDataSet:
        """Dataset test double with valid dimensions."""

        @staticmethod
        def GetSizeX():
            """Return a positive X dimension.

            Inputs: none. Output: int.
            """
            return 2

        @staticmethod
        def GetSizeY():
            """Return a positive Y dimension.

            Inputs: none. Output: int.
            """
            return 2

    class _FakeImaris:
        """Handle with stale current-file metadata but visible loaded data."""

        def __init__(self):
            """Create fake Imaris state.

            Inputs: none. Output: initializes state.
            """
            self.data_set = None
            self.visible_data_set = None

        def FileOpen(self, _path, *_args):
            """Load a dataset while leaving current-file metadata stale.

            Inputs: `_path`, optional args. Output: None.
            """
            self.data_set = _FakeDataSet()

        @staticmethod
        def GetCurrentFileName():
            """Return stale current-file metadata.

            Inputs: none. Output: stale path.
            """
            return "C:\\old\\previous.ims"

        def GetDataSet(self):
            """Return the loaded dataset.

            Inputs: none. Output: dataset object or None.
            """
            return self.data_set

        def SetDataSet(self, data_set):
            """Record visible dataset handoff.

            Inputs: `data_set`. Output: None.
            """
            self.visible_data_set = data_set

    imaris = _FakeImaris()

    assert module.open_file_in_imaris(ims_path, imaris) is True
    assert imaris.visible_data_set is imaris.data_set


def test_open_file_in_imaris_rejects_dataset_without_visibility_api(
    tmp_path,
    monkeypatch,
):
    """Confirm no-current-file IMS opens are rejected without visibility API proof.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: asserts a loaded
    dataset alone is rejected as a complete same-session open.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "IMARIS_OPEN_VERIFY_INTERVAL", 0.01)

    class _FakeDataSet:
        """Dataset test double with valid dimensions."""

        @staticmethod
        def GetSizeX():
            """Return a positive X dimension.

            Inputs: none. Output: int.
            """
            return 1

    class _FakeImaris:
        """Handle that loads data but cannot make it visible."""

        def __init__(self):
            """Create fake Imaris state.

            Inputs: none. Output: initializes state.
            """
            self.data_set = None

        def FileOpen(self, _path, *_args):
            """Load a dataset without visibility APIs.

            Inputs: `_path`, optional args. Output: None.
            """
            self.data_set = _FakeDataSet()

        def GetDataSet(self):
            """Return the loaded dataset.

            Inputs: none. Output: dataset object or None.
            """
            return self.data_set

    assert module.open_file_in_imaris(ims_path, _FakeImaris()) is False


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


def test_open_file_in_imaris_rejects_original_file_when_ims_flag_is_false(tmp_path):
    """Verify require_ims False does not allow original-file handoff.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in IMS-only Imaris handoff.
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
        is False
    )
    assert opened == []


def test_open_file_in_imaris_raw_file_never_uses_submission_only_verification(
    tmp_path,
    monkeypatch,
):
    """Verify raw Imaris input cannot bypass IMS-open verification.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on raw handoff regressions.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_text("native converter input", encoding="utf-8")
    opened = []
    monkeypatch.setattr(
        module,
        "_wait_for_imaris_verified_open",
        lambda *_args, **_kwargs: True,
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
        is False
    )
    assert opened == []


def test_open_file_in_imaris_raw_file_rejects_observable_submission(
    tmp_path,
    monkeypatch,
):
    """Verify raw Imaris input is rejected even if submission would look successful.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: fails on regressions in IMS-only handoff.
    """
    module = _load_xt_module()
    original_path = tmp_path / "demo.lif"
    original_path.write_text("native converter input", encoding="utf-8")
    opened = []
    monkeypatch.setattr(
        module,
        "_wait_for_imaris_verified_open",
        lambda *_args, **_kwargs: True,
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
        is False
    )
    assert opened == []


def test_open_file_in_imaris_raw_file_rejects_before_retrying_with_options(tmp_path):
    """Verify raw Imaris input is rejected before FileOpen retry logic.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in IMS validation.
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
        is False
    )
    assert opened == []


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


def test_imaris_open_snapshot_changed_covers_observable_effects():
    """Verify Imaris open snapshot comparison covers every success signal.

    Inputs: repository fixtures. Output: fails on observable-effect comparison regressions.
    """
    module = _load_xt_module()
    before = ("", 1, None)

    assert (
        module._imaris_open_snapshot_changed(
            before,
            ("C:\\data\\demo.ims", 1, None),
            "C:\\data\\demo.ims",
        )
        is True
    )
    assert (
        module._imaris_open_snapshot_changed(before, ("other.ims", 1, None), "") is True
    )
    assert module._imaris_open_snapshot_changed(before, ("", 2, None), "") is True
    assert module._imaris_open_snapshot_changed(before, ("", 1, "present"), "") is True
    assert module._imaris_open_snapshot_changed(before, ("", 1, None), "") is False


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
    """Verify Load stays gated by connection, converter, path, and image selection.

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
    dialog.images_data = [{"id": 1, "name": "selected"}]
    dialog.ilist = _FakeListbox(["selected"], selection={0})

    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"

    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar("")
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"

    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_write_state = "unchecked"
    dialog.ilist.selection_clear(0)
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"

    dialog.ilist.selection_set(0)
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "normal"

    dialog._folder_path_write_state = "unwritable"
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"


def test_path_change_reenables_load_after_reconnect_when_converter_is_available():
    """Verify typed path changes recompute Load state after reconnect.

    Inputs: repository fixtures. Output: fails on reconnect/path state regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_var = _FakeVar("OMERO")
    dialog.load_btn = _FakeButton()
    dialog._load_in_progress = False
    dialog._folder_export_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(r"C:\valid-export")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_trace_suppressed = False
    dialog._folder_path_write_state = "empty"
    dialog.folder_path_entry = _FakeEntry()
    dialog.images_data = [{"id": 1, "name": "selected"}]
    dialog.ilist = _FakeListbox(["selected"], selection={0})

    module.OMEROBrowserDialog._on_folder_path_changed(dialog)

    assert dialog._folder_path_write_state == "unchecked"
    assert dialog.load_btn.state == "normal"


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
        module.CONNECTOR_SETTINGS_CONVERTER_KEY: "Imaris",
        module.CONNECTOR_SETTINGS_AUTOSAVE_KEY: "true",
        module.CONNECTOR_SETTINGS_SHOW_LOG_KEY: "false",
        module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY: "true",
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
    assert loaded[module.CONNECTOR_SETTINGS_CONVERTER_KEY] == "Imaris"
    assert loaded[module.CONNECTOR_SETTINGS_SHOW_LOG_KEY] == "false"
    assert loaded[module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY] == "true"
    assert (
        loaded[module.CONNECTOR_SETTINGS_VERSION_KEY] == module.CONNECTOR_INFO_VERSION
    )


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
    monkeypatch.setattr(module, "_xt_debug", logs.append)

    loaded = module._load_connector_settings(
        settings_dir / module.AUTOSAVE_SETTINGS_FILE_NAME
    )

    assert loaded == {}
    assert logs == [
        "Connector settings load skipped: "
        "Connector settings directory is not a regular directory"
    ]


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
    monkeypatch.setattr(module, "_xt_debug", logs.append)

    loaded = module._load_connector_settings(settings_path)

    assert loaded == {module.CONNECTOR_SETTINGS_PORT_KEY: "443"}
    assert logs == [
        "Connector settings parse failed: OMERO_CONNECTOR_HOST on line 1 ignored"
    ]
    assert "unterminated" not in logs[0]


def test_connector_show_log_preference_defaults_enabled_and_reads_false(tmp_path):
    """Verify startup console visibility defaults on and honors saved false.

    Inputs: pytest provides `tmp_path`. Output: fails on startup show-log regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)

    assert module._load_connector_show_log_preference(settings_path) is True

    settings_path.parent.mkdir()
    settings_path.write_text(
        "\n".join(
            [
                f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="{module.CONNECTOR_INFO_VERSION}"',
                f'{module.CONNECTOR_SETTINGS_SHOW_LOG_KEY}="false"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert module._load_connector_show_log_preference(settings_path) is False

    settings_path.write_text(
        f'{module.CONNECTOR_SETTINGS_SHOW_LOG_KEY}="unterminated\n',
        encoding="utf-8",
    )
    assert module._load_connector_show_log_preference(settings_path) is True


def test_connector_settings_version_prepare_creates_new_file_with_defaults(tmp_path):
    """Verify first boot creates a current-version connector settings file.

    Inputs: pytest provides `tmp_path`. Output: fails on first-boot settings regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)

    assert module._prepare_connector_settings_for_current_version(settings_path) is True

    loaded = module._load_connector_settings(settings_path)
    assert (
        loaded[module.CONNECTOR_SETTINGS_VERSION_KEY] == module.CONNECTOR_INFO_VERSION
    )
    assert loaded[module.CONNECTOR_SETTINGS_AUTOSAVE_KEY] == "true"
    assert loaded[module.CONNECTOR_SETTINGS_SHOW_LOG_KEY] == "true"
    assert loaded[module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY] == "false"


def test_connector_settings_version_parses_info_dialog_version(monkeypatch):
    """Verify settings version is parsed from the info-dialog version value.

    Inputs: pytest provides `monkeypatch`. Output: fails on version parsing regressions.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module, "CONNECTOR_INFO_VERSION", "OMERO Connector 2.3.4")

    assert module._current_connector_settings_version() == "2.3.4"


def test_connector_settings_version_prepare_preserves_same_version_settings(tmp_path):
    """Verify same-version startup keeps user settings while refreshing version.

    Inputs: pytest provides `tmp_path`. Output: fails on same-version settings regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        "\n".join(
            [
                "# keep operator comments",
                f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="{module.CONNECTOR_INFO_VERSION}"',
                f'{module.CONNECTOR_SETTINGS_HOST_KEY}="omero.example.org"',
                f'{module.CONNECTOR_SETTINGS_SHOW_LOG_KEY}="false"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert module._prepare_connector_settings_for_current_version(settings_path) is True

    content = settings_path.read_text(encoding="utf-8")
    loaded = module._load_connector_settings(settings_path)
    assert "# keep operator comments" in content
    assert loaded[module.CONNECTOR_SETTINGS_HOST_KEY] == "omero.example.org"
    assert loaded[module.CONNECTOR_SETTINGS_SHOW_LOG_KEY] == "false"
    assert (
        loaded[module.CONNECTOR_SETTINGS_VERSION_KEY] == module.CONNECTOR_INFO_VERSION
    )
    assert not module._connector_settings_backup_path(settings_path, 1).exists()


def test_connector_settings_version_mismatch_archives_old_file(tmp_path):
    """Verify version mismatch archives old settings and creates a fresh file.

    Inputs: pytest provides `tmp_path`. Output: fails on settings migration regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        "\n".join(
            [
                "# previous settings",
                f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"',
                f'{module.CONNECTOR_SETTINGS_HOST_KEY}="old.example.org"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert module._prepare_connector_settings_for_current_version(settings_path) is True

    backup_path = module._connector_settings_backup_path(settings_path, 1)
    backup_content = backup_path.read_text(encoding="utf-8")
    loaded = module._load_connector_settings(settings_path)
    assert "# previous settings" in backup_content
    assert f'{module.CONNECTOR_SETTINGS_HOST_KEY}="old.example.org"' in backup_content
    assert (
        loaded[module.CONNECTOR_SETTINGS_VERSION_KEY] == module.CONNECTOR_INFO_VERSION
    )
    assert module.CONNECTOR_SETTINGS_HOST_KEY not in loaded


def test_connector_settings_version_mismatch_rotates_existing_backups(tmp_path):
    """Verify old, old2, old3 backup rotation is generated programmatically.

    Inputs: pytest provides `tmp_path`. Output: fails on settings backup rotation regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"\ncurrent\n',
        encoding="utf-8",
    )
    module._connector_settings_backup_path(settings_path, 1).write_text(
        "old-one\n", encoding="utf-8"
    )
    module._connector_settings_backup_path(settings_path, 2).write_text(
        "old-two\n", encoding="utf-8"
    )

    assert module._prepare_connector_settings_for_current_version(settings_path) is True

    assert (
        module._connector_settings_backup_path(settings_path, 1).read_text(
            encoding="utf-8"
        )
        == f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"\ncurrent\n'
    )
    assert (
        module._connector_settings_backup_path(settings_path, 2).read_text(
            encoding="utf-8"
        )
        == "old-one\n"
    )
    assert (
        module._connector_settings_backup_path(settings_path, 3).read_text(
            encoding="utf-8"
        )
        == "old-two\n"
    )


def test_connector_settings_version_migration_rejects_unsafe_backup_symlink(
    tmp_path, monkeypatch
):
    """Verify settings migration never follows or overwrites backup symlinks.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on symlink regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"\n',
        encoding="utf-8",
    )
    outside_path = tmp_path / "outside.env"
    outside_path.write_text("outside\n", encoding="utf-8")
    backup_path = module._connector_settings_backup_path(settings_path, 1)
    try:
        backup_path.symlink_to(outside_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    logs = []
    monkeypatch.setattr(module, "_xt_debug", logs.append)

    assert (
        module._prepare_connector_settings_for_current_version(settings_path) is False
    )

    assert backup_path.is_symlink()
    assert outside_path.read_text(encoding="utf-8") == "outside\n"
    assert settings_path.read_text(encoding="utf-8") == (
        f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"\n'
    )
    assert not module._connector_settings_backup_path(settings_path, 2).exists()
    assert logs == [
        "Connector settings version preparation failed: OSError",
    ]


def test_connector_settings_version_migration_rejects_settings_symlink(
    tmp_path, monkeypatch
):
    """Verify settings migration never follows a symlinked settings file.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on settings symlink regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    outside_path = tmp_path / "outside.env"
    outside_path.write_text(
        f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"\n',
        encoding="utf-8",
    )
    try:
        settings_path.symlink_to(outside_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    logs = []
    monkeypatch.setattr(module, "_xt_debug", logs.append)

    assert (
        module._prepare_connector_settings_for_current_version(settings_path) is False
    )

    assert settings_path.is_symlink()
    assert outside_path.read_text(encoding="utf-8") == (
        f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="0.9.0"\n'
    )
    assert not module._connector_settings_backup_path(settings_path, 1).exists()
    assert logs == [
        "Connector settings version preparation failed: OSError",
    ]


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
    dialog.show_log_var = _FakeVar(True)
    dialog.search_function_var = _FakeVar(False)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.converter_var = _FakeVar("OMERO")

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
        module.CONNECTOR_SETTINGS_CONVERTER_KEY: "OMERO",
        module.CONNECTOR_SETTINGS_AUTOSAVE_KEY: "true",
        module.CONNECTOR_SETTINGS_SHOW_LOG_KEY: "true",
        module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY: "false",
        module.CONNECTOR_SETTINGS_VERSION_KEY: module.CONNECTOR_INFO_VERSION,
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
    dialog.show_log_var = _FakeVar(True)
    dialog.search_function_var = _FakeVar(False)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.converter_var = _FakeVar("OMERO")

    module.OMEROBrowserDialog._on_autosave_settings_changed(dialog)

    content = settings_path.read_text(encoding="utf-8")
    assert module.CONNECTOR_SETTINGS_AUTOSAVE_KEY + '="false"' in content
    assert module.CONNECTOR_SETTINGS_SHOW_LOG_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY + '="false"' in content
    assert "PASSWORD" not in content
    assert "super-secret" not in content


def test_show_log_toggle_updates_settings_immediately_without_password(
    tmp_path, monkeypatch
):
    """Verify Show log toggles write and apply immediately before connection.

    Inputs: pytest provides `tmp_path` and `monkeypatch`. Output: fails on show-log persistence regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    settings_path = module._connector_settings_env_path(tmp_path)
    dialog._connected = False
    dialog._settings_file_path = settings_path
    dialog._saved_settings = {}
    dialog._autosave_settings_write_error = ""
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(True)
    dialog.show_log_var = _FakeVar(False)
    dialog.search_function_var = _FakeVar(True)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.converter_var = _FakeVar("Imaris")
    dialog._show_autosave_settings_error = _noop
    visibility_calls = []
    monkeypatch.setattr(
        module, "_configure_xt_console_visibility", visibility_calls.append
    )

    module.OMEROBrowserDialog._on_show_log_changed(dialog)

    content = settings_path.read_text(encoding="utf-8")
    assert visibility_calls == [False]
    assert module.CONNECTOR_SETTINGS_SHOW_LOG_KEY + '="false"' in content
    assert module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_CONVERTER_KEY + '="Imaris"' in content
    assert "PASSWORD" not in content
    assert "super-secret" not in content


def test_search_function_toggle_updates_settings_immediately_without_password(
    tmp_path,
):
    """Verify Search function toggles persist immediately without credentials.

    Inputs: pytest provides `tmp_path`. Output: fails on search-option persistence regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    settings_path = module._connector_settings_env_path(tmp_path)
    dialog._settings_file_path = settings_path
    dialog._saved_settings = {}
    dialog._autosave_settings_write_error = ""
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(True)
    dialog.show_log_var = _FakeVar(True)
    dialog.search_function_var = _FakeVar(True)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.converter_var = _FakeVar("Imaris")
    dialog._show_autosave_settings_error = _noop

    module.OMEROBrowserDialog._on_search_function_changed(dialog)

    content = settings_path.read_text(encoding="utf-8")
    assert module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_SHOW_LOG_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_CONVERTER_KEY + '="Imaris"' in content
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
    dialog.show_log_var = _FakeVar(True)
    dialog.search_function_var = _FakeVar(False)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.converter_var = _FakeVar("OMERO")
    logs = []
    monkeypatch.setattr(module, "_xt_debug", logs.append)

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
    monkeypatch.setattr(module.threading, "Thread", _ImmediateThread)

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

        @staticmethod
        def list_projects():
            """Return a minimal project list.

            Inputs: none. Output: project fixtures.
            """
            return [{"id": "project-1", "name": "Project One"}]

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
    dialog.show_log_var = _FakeVar(True)
    dialog.search_function_var = _FakeVar(False)
    dialog.autosave_settings_check = _FakeButton()
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.connect_btn = _FakeButton()
    dialog.root = types.SimpleNamespace(update_idletasks=lambda: None)
    dialog._set_status = lambda text, color="#ecf0f1": statuses.append((text, color))
    dialog._set_connection_indicator = lambda _state: None
    dialog._schedule_health_ping = lambda: None
    dialog._invoke_on_ui_thread = lambda callback, wait=True: callback()
    dialog.plist = _FakeListbox()
    dialog.dlist = _FakeListbox()
    dialog.ilist = _FakeListbox()
    dialog._project_list_label = lambda project: project["name"]
    dialog._detect_converter_options_after_connection = lambda client=None: ["OMERO"]
    dialog._detect_folder_export_after_connection = lambda client=None: {
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
    assert dialog.client is created_clients[0]
    assert converter_calls == [[], ["OMERO"]]
    assert export_calls[-1] == (True, "")
    assert statuses[-1] == ("Connected to OMERO", "#d4edda")
    assert module.CONNECTOR_SETTINGS_HOST_KEY + '="omero.example.org"' in content
    assert module.CONNECTOR_SETTINGS_PORT_KEY + '="443"' in content
    assert module.CONNECTOR_SETTINGS_USERNAME_KEY + '="alice"' in content
    assert module.CONNECTOR_SETTINGS_HTTPS_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_PATH_KEY + f'="{tmp_path}"' in content
    assert module.CONNECTOR_SETTINGS_SHOW_LOG_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY + '="false"' in content
    assert dialog.pass_entry.value == ""
    password_attr = "pass" + "word"
    assert getattr(created_clients[0], password_attr) == str()
    assert "PASSWORD" not in content
    assert "super-secret" not in content


def test_connect_starts_background_worker_without_blocking_ui_thread(monkeypatch):
    """Verify connect does not perform network setup directly on the Tk UI thread.

    Inputs: pytest provides `monkeypatch`. Output: fails on synchronous-connect
    regressions.
    """
    module = _load_xt_module()
    threads = []

    class RecordingThread:
        """Thread fake that records construction without running the target."""

        def __init__(self, target, args=(), kwargs=None, daemon=None):
            """Create `RecordingThread` with call details.

            Inputs: `target`, `args`, `kwargs`, `daemon`. Output: records thread.
            """
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon
            threads.append(self)

        def start(self):
            """Record that the thread would have been started.

            Inputs: none. Output: None.
            """
            self.started = True

    monkeypatch.setattr(module.threading, "Thread", RecordingThread)
    monkeypatch.setattr(
        module,
        "OMEROWebClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("client creation must happen in the worker")
        ),
    )

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = False
    dialog._connection_in_progress = False
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("typed-secret")
    dialog.https_var = _FakeVar(True)
    dialog.connect_btn = _FakeButton()
    dialog.root = types.SimpleNamespace(update_idletasks=lambda: None)
    dialog._set_converter_options = _noop
    dialog._set_folder_export_capability = _noop
    dialog._set_status = _noop
    dialog._set_connection_indicator = _noop

    module.OMEROBrowserDialog._connect(dialog)

    assert dialog._connection_in_progress is True
    assert len(threads) == 1
    assert threads[0].target == dialog._connect_worker
    assert threads[0].args == (
        "omero.example.org",
        443,
        "alice",
        "typed-secret",
        "https",
    )
    assert threads[0].daemon is True
    assert threads[0].started is True


def test_failed_connection_keeps_visible_password_for_user_retry(monkeypatch):
    """Verify failed login does not clear the typed password field.

    Inputs: pytest provides `monkeypatch`. Output: fails on password-clear regressions.
    """

    class FakeClient:
        """Test double for a failed OMERO.web client."""

        def __init__(self, *_args, **_kwargs):
            """Create fake failed client state.

            Inputs: connection fields. Output: initializes credential attributes.
            """
            setattr(self, "pass" + "word", "typed-" + "secret")
            setattr(self, "csrf_" + "token", "csrf-" + "value")
            self.session_id = "session"
            self.session_key = "session"

        @staticmethod
        def connect():
            """Return a failed login result.

            Inputs: none. Output: bool.
            """
            return False

    module = _load_xt_module()
    monkeypatch.setattr(module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(module, "OMEROWebClient", FakeClient)
    errors = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = False
    dialog._connection_in_progress = False
    dialog.client = None
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("typed-secret")
    dialog.https_var = _FakeVar(True)
    dialog.connect_btn = _FakeButton()
    dialog.autosave_settings_check = _FakeButton()
    dialog.root = types.SimpleNamespace(update_idletasks=lambda: None)
    dialog._set_converter_options = _noop
    dialog._set_folder_export_capability = _noop
    dialog._set_status = _noop
    dialog._set_connection_indicator = _noop
    dialog._invoke_on_ui_thread = lambda callback, wait=True: callback()
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )

    module.OMEROBrowserDialog._connect(dialog)

    assert dialog.pass_entry.value == "typed-secret"
    assert dialog.client is None
    assert errors == [
        (
            "Connection Failed",
            "Cannot connect to OMERO server.\nPlease check your credentials.",
        )
    ]


def test_stale_connect_success_completion_clears_new_client_without_ui_mutation():
    """Verify stale background connection success cannot revive a cancelled connect.

    Inputs: repository fixtures. Output: fails on stale connect completion regressions.
    """
    module = _load_xt_module()
    cookie_jar = types.SimpleNamespace(cleared=False)
    cookie_jar.clear = lambda: setattr(cookie_jar, "cleared", True)
    client = types.SimpleNamespace(
        password="typed-secret",
        csrf_token="csrf",
        session_id="session",
        session_key="session-key",
        cookie_jar=cookie_jar,
    )
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connection_in_progress = False
    dialog.client = "existing"
    dialog._connected = False

    module.OMEROBrowserDialog._finish_connect_success(
        dialog,
        client,
        [{"id": "project", "name": "Project"}],
        ["OMERO"],
        {"available": True, "reason": ""},
    )

    assert dialog.client == "existing"
    assert dialog._connected is False
    assert client.password == str()
    assert client.csrf_token is None
    assert client.session_id is None
    assert client.session_key is None
    assert cookie_jar.cleared is True


def test_connect_rejects_scheme_in_host_before_client_creation(monkeypatch):
    """Verify Host rejects URL schemes before any OMERO.web client is created.

    Inputs: pytest provides `monkeypatch`. Output: fails on host-field validation regressions.
    """
    module = _load_xt_module()
    errors = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = False
    dialog._connection_in_progress = False
    dialog.client = None
    dialog.host_entry = _FakeEntry("https://omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("typed-secret")
    dialog.https_var = _FakeVar(True)
    dialog.root = object()
    dialog._set_converter_options = _noop
    dialog._set_folder_export_capability = _noop
    monkeypatch.setattr(
        module,
        "OMEROWebClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid host must not create a client")
        ),
    )
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )

    module.OMEROBrowserDialog._connect(dialog)

    assert errors == [("Invalid Host", module.HOST_FIELD_SCHEME_ERROR_MESSAGE)]
    assert dialog.client is None


def test_omero_web_client_drops_password_after_connect_attempt(monkeypatch):
    """Verify the client does not retain the password after authentication.

    Inputs: pytest provides `monkeypatch`. Output: fails on retained-password regressions.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient(
        "omero.example.org",
        443,
        "alice",
        TEST_LOGIN_VALUE,
        scheme="https",
    )
    extraction_calls = []

    class _FakeOpener:
        """Fake opener for a successful login and authenticated API probe."""

        def __init__(self):
            """Create opener call recorder.

            Inputs: none. Output: initializes call state.
            """
            self.calls = []

        def open(self, request, timeout):
            """Return the next fake HTTP response.

            Inputs: `request`, `timeout`. Output: fake HTTP response.
            """
            self.calls.append((request, timeout))
            if len(self.calls) == 1:
                return _FakeHTTPResponse(b"", headers={"Content-Type": "text/html"})
            if len(self.calls) == 2:
                assert TEST_LOGIN_VALUE.encode() in request.data
                return _FakeHTTPResponse(b"", headers={"Content-Type": "text/html"})
            return _FakeHTTPResponse(
                b'{"data":[]}',
                headers={"Content-Type": "application/json"},
            )

    opener = _FakeOpener()

    def _extract_cookies_from_jar():
        """Populate authentication cookies in login order.

        Inputs: none. Output: None.
        """
        extraction_calls.append("extract")
        if len(extraction_calls) == 1:
            setattr(client, "csrf_" + "token", "csrf-" + "token")
        else:
            client.session_id = "session-id"
            client.session_key = "session-id"

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(module.urllib.request, "install_opener", lambda *_args: None)
    client._extract_cookies_from_jar = _extract_cookies_from_jar

    assert client.connect() is True
    password_attr = "pass" + "word"
    assert getattr(client, password_attr) == str()
    assert len(opener.calls) == 3


def test_password_reveal_is_timed_and_clear_cancels_pending_timer():
    """Verify the password reveal control is UI-only and automatically hidden.

    Inputs: repository fixtures. Output: fails on password reveal regressions.
    """
    module = _load_xt_module()
    scheduled = []
    cancelled = []

    class _Root:
        """Fake Tk root with after cancellation support."""

        @staticmethod
        def after(delay, callback):
            """Record scheduled callback.

            Inputs: `delay`, `callback`. Output: fake after id.
            """
            scheduled.append((delay, callback))
            return "after-1"

        @staticmethod
        def after_cancel(after_id):
            """Record cancellation.

            Inputs: `after_id`. Output: None.
            """
            cancelled.append(after_id)

    class _RevealButton:
        """Fake reveal button state sink."""

        def __init__(self):
            """Create state recorder.

            Inputs: none. Output: initializes list.
            """
            self.states = []

        def set_visible(self, visible):
            """Record visibility state.

            Inputs: `visible`. Output: None.
            """
            self.states.append(bool(visible))

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog.pass_entry = _FakeEntry("typed-secret")
    dialog.password_reveal_btn = _RevealButton()
    dialog._password_reveal_after_id = None
    dialog._password_revealed = False

    module.OMEROBrowserDialog._toggle_password_reveal(dialog)

    assert dialog.pass_entry.options["show"] == ""
    assert dialog.password_reveal_btn.states == [True]
    assert scheduled[0][0] == module.PASSWORD_REVEAL_DURATION_MS

    scheduled[0][1]()
    assert dialog.pass_entry.options["show"] == "*"
    assert dialog.password_reveal_btn.states[-1] is False

    dialog.pass_entry.value = "typed-secret"
    module.OMEROBrowserDialog._toggle_password_reveal(dialog)
    module.OMEROBrowserDialog._clear_password_entry(dialog)

    assert dialog.pass_entry.value == ""
    assert dialog.pass_entry.options["show"] == "*"
    assert "after-1" in cancelled


def test_hidden_password_copy_and_cut_are_blocked_without_blocking_paste():
    """Verify hidden password mode blocks clipboard extraction only.

    Inputs: repository fixtures. Output: fails on password clipboard regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)

    dialog._password_revealed = False
    assert module.OMEROBrowserDialog._block_hidden_password_clipboard(dialog) == "break"

    dialog._password_revealed = True
    assert module.OMEROBrowserDialog._block_hidden_password_clipboard(dialog) is None

    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    password_binding_source = source[
        source.index("self.pass_entry.bind") : source.index(
            "self.password_reveal_btn = _PasswordRevealButton("
        )
    ]
    assert "<<Copy>>" in password_binding_source
    assert "<<Cut>>" in password_binding_source
    assert "<<Paste>>" not in password_binding_source


def test_rounded_button_config_updates_only_changed_state():
    """Verify rounded button configuration avoids redundant redraws.

    Inputs: repository fixtures. Output: fails on rounded button config regressions.
    """
    module = _load_xt_module()

    class _Canvas:
        """Canvas fake that records configuration calls."""

        def __init__(self):
            """Create the fake canvas.

            Inputs: none. Output: initializes call storage.
            """
            self.configs = []

        def config(self, **kwargs):
            """Record a canvas config call.

            Inputs: `**kwargs`. Output: None.
            """
            self.configs.append(kwargs)

    button = object.__new__(module._RoundedButton)
    button._canvas = _Canvas()
    button._bg = "#ffffff"
    button._fg = "#000000"
    button._active_bg = "#eeeeee"
    button._active_fg = "#111111"
    button._font = ("Arial", 10)
    button._text = "Load"
    button._width = 120
    button._height = 42
    button._state = "normal"
    button._pressed = True
    button._hover = True
    redraws = []
    cursor_syncs = []
    button._redraw = lambda: redraws.append("redraw")
    button._sync_cursor = lambda: cursor_syncs.append("cursor")

    module._RoundedButton.config(
        button,
        background="#ffffff",
        foreground="#000000",
        text="Load",
    )
    assert redraws == []
    assert cursor_syncs == []

    module._RoundedButton.config(
        button,
        background="#101820",
        width=132,
        state="disabled",
    )
    assert button._bg == "#101820"
    assert button._width == 132
    assert button._pressed is False
    assert button._hover is False
    assert button._canvas.configs == [{"width": 132}]
    assert redraws == ["redraw"]
    assert cursor_syncs == ["cursor"]


def test_rounded_button_redraw_omits_internal_horizontal_strokes():
    """Verify rounded buttons do not draw decorative internal separator lines.

    Inputs: repository fixtures. Output: fails on rounded button style regressions.
    """
    module = _load_xt_module()

    class _Canvas:
        """Canvas fake that records draw operations."""

        def __init__(self):
            """Create the fake canvas.

            Inputs: none. Output: initializes draw-operation storage.
            """
            self.lines = []
            self.polygons = []
            self.texts = []

        @staticmethod
        def winfo_width():
            """Return fake width.

            Inputs: none. Output: int.
            """
            return 120

        @staticmethod
        def winfo_height():
            """Return fake height.

            Inputs: none. Output: int.
            """
            return 42

        @staticmethod
        def delete(_tag):
            """Accept delete calls.

            Inputs: `_tag`. Output: None.
            """

        def create_polygon(self, *args, **kwargs):
            """Record rounded-rectangle polygon calls.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.polygons.append((args, kwargs))

        def create_text(self, *args, **kwargs):
            """Record text calls.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.texts.append((args, kwargs))

        def create_line(self, *args, **kwargs):
            """Record line calls.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.lines.append((args, kwargs))

    button = object.__new__(module._RoundedButton)
    button._canvas = _Canvas()
    button._bg = "#3498db"
    button._fg = "white"
    button._active_bg = "#2f85c7"
    button._active_fg = "white"
    button._font = ("Arial", 10, "bold")
    button._text = "Connect"
    button._width = 120
    button._height = 42
    button._state = "normal"
    button._pressed = False
    button._hover = False
    button._radius = 7
    button._compact_height = False

    module._RoundedButton._redraw(button)

    assert len(button._canvas.polygons) == 2
    assert len(button._canvas.texts) == 1
    assert button._canvas.lines == []


def test_tk_system_colors_are_resolved_before_photoimage_pixels():
    """Verify Tk system colors are converted before PhotoImage pixel output.

    Inputs: repository fixtures. Output: fails on system color regressions.
    """
    module = _load_xt_module()

    class _Widget:
        """Fake Tk widget that resolves a Windows system color."""

        @staticmethod
        def winfo_rgb(value):
            """Resolve one symbolic Tk color.

            Inputs: `value`. Output: 16-bit RGB tuple. Raises: ValueError.
            """
            if value.lower() == "systembuttonface":
                return (0xF0F0, 0xF0F0, 0xF0F0)
            raise ValueError(value)

    assert module._resolve_tk_color(_Widget(), "SystemButtonFace") == "#f0f0f0"
    assert (
        module._circle_pixel_color(
            distance=100,
            radius=4,
            fill="#ffffff",
            outline="#000000",
            background=module._resolve_tk_color(_Widget(), "SystemButtonFace"),
        )
        == "#f0f0f0"
    )

    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    circle_source = source[
        source.index("def _antialiased_circle_image(") : source.index(
            "def _normalized_tk_state("
        )
    ]
    assert "_resolve_tk_color(master, _widget_background(master))" in circle_source
    assert "_resolve_tk_color(master, fill, fallback=background)" in circle_source
    assert "_resolve_tk_color(master, outline, fallback=fill)" in circle_source
    assert "bg=_resolve_tk_color(master, _widget_background(master))" in source


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
    assert 'self.path_label = self._connection_label(conn_frame, "Path:")' in source
    assert "self.path_label.grid(" in source
    assert 'FOLDER_PATH_PLACEHOLDER = "Type or select local path..."' in source
    assert (
        "self.folder_path_entry.grid(\n            row=2,\n            column=1,"
        in source
    )
    assert "columnspan=4,\n            sticky=tk.EW," in source
    assert "self.password_frame = tk.Frame(" in source
    assert (
        "self.password_frame.grid(\n            row=1, column=3, columnspan=2,"
    ) in source
    assert "self.password_frame.grid_columnconfigure(0, weight=1)" in source
    assert "self.pass_entry = tk.Entry(\n            self.password_frame," in source
    assert "PASSWORD_REVEAL_BUTTON_SIZE = 18" in source
    assert "ipady=0" in source
    assert "self.password_reveal_btn = _PasswordRevealButton(" in source
    assert "self._visible = False\n        super().__init__(*args, **kwargs)" in source
    assert "command=self._toggle_password_reveal" in source
    assert (
        'self.pass_entry.bind("<Control-c>", self._block_hidden_password_clipboard)'
        in source
    )
    assert (
        'self.pass_entry.bind("<Control-x>", self._block_hidden_password_clipboard)'
        in source
    )
    assert (
        'self.pass_entry.bind("<<Copy>>", self._block_hidden_password_clipboard)'
        in source
    )
    assert (
        'self.pass_entry.bind("<<Cut>>", self._block_hidden_password_clipboard)'
        in source
    )
    assert (
        '"<<Paste>>"'
        not in source[
            source.index("self.pass_entry.bind") : source.index(
                "self.password_reveal_btn = _PasswordRevealButton("
            )
        ]
    )
    assert "self.connect_btn.grid(row=0, column=5," in source
    assert "self.select_folder_btn.grid(row=2, column=5," in source
    assert (
        "self.autosave_settings_var = tk.BooleanVar(value=default_autosave_settings)"
        in source
    )
    assert "default_show_log = _connector_settings_bool(" in source
    assert "self.show_log_var = tk.BooleanVar(value=default_show_log)" in source
    assert "default_search_function = _connector_settings_bool(" in source
    assert (
        "self.search_function_var = tk.BooleanVar(value=default_search_function)"
        in source
    )
    assert 'text="Autosave settings"' in source
    assert 'text="Show log"' in source
    assert 'text="Search function"' in source
    assert 'text="Save settings"' not in source
    assert 'state=_tk_constant("DISABLED", "disabled")' in source
    assert "command=self._on_autosave_settings_changed" in source
    assert "command=self._on_show_log_changed" in source
    assert "command=self._on_search_function_changed" in source
    assert "bg=FOLDER_PATH_SELECT_BG" in source
    assert "activebackground=FOLDER_PATH_SELECT_ACTIVE_BG" in source
    assert "width=96" in source
    assert "height=38" in source
    assert "compact_height=True" in source
    assert "def _align_path_row_control_heights(self):" in source
    assert 'getattr(self, "folder_path_entry", None), "winfo_height"' in source
    assert (
        'getattr(self, "select_folder_btn", None),\n'
        '            getattr(self, "refresh_btn", None),\n'
        '            getattr(self, "converter_dropdown", None),' in source
    )
    assert "configure(height=entry_height)" in source
    assert 'text="Export folder to OMERO"' in source
    init_marker = source.index("def __init__(self, imaris, imaris_id=None):")
    settings_prepare = source.index(
        "_prepare_connector_settings_for_current_version(self._settings_file_path)",
        init_marker,
    )
    settings_load = source.index(
        "self._saved_settings = _load_connector_settings", init_marker
    )
    tk_load = source.index("_ensure_tk_loaded()", init_marker)
    assert settings_prepare < settings_load
    assert settings_load < tk_load
    assert 'tooltip="Interact with OMERO"' in source


def test_connection_setting_labels_are_start_aligned_without_moving_entries():
    """Verify connection labels start-align while entry grid positions stay fixed.

    Inputs: repository fixtures. Output: fails on UI alignment regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    for label in ("Port", "Username", "Password"):
        assert f'self._connection_label(conn_frame, "{label}:").grid' in source
    assert 'self.host_label = self._connection_label(conn_frame, "Host:")' in source
    assert 'self.path_label = self._connection_label(conn_frame, "Path:")' in source
    assert "self.host_label.grid(" in source
    assert "self.path_label.grid(" in source

    assert 'anchor=_tk_constant("W", "w")' in source
    assert 'justify=_tk_constant("LEFT", "left")' in source
    assert "width=CONNECTION_LABEL_WIDTH" in source
    assert source.count('sticky=_tk_constant("NSEW", "nsew"), pady=5') >= 5
    assert "self.host_entry.grid(row=0, column=1, pady=5, padx=5)" in source
    assert "self.user_entry.grid(row=1, column=1, pady=5, padx=5)" in source
    assert (
        "self.port_entry.grid(row=0, column=3, pady=5, padx=5, sticky=tk.W)" in source
    )


def test_converter_selector_remains_wired_in_connection_settings_panel():
    """Verify converter dropdown remains present in the connection settings panel.

    Inputs: repository fixtures. Output: fails on converter selector regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "CONVERTER_DROPDOWN_WIDTH = 116" in source
    assert "CONVERTER_DROPDOWN_TEXT_PAD = 10" in source
    assert "CONVERTER_DROPDOWN_ARROW_WIDTH = 24" in source
    assert "CONVERTER_SLOT_WIDTH = 619" in source
    assert "AUTOSAVE_SETTINGS_FRAME_WIDTH = 450" in source
    assert "AUTOSAVE_SETTINGS_OPTION_GAP = 34" in source
    assert "class _ConverterDropdown:" in source
    assert "self._arrow = tk.Canvas(" in source
    assert 'text="v"' not in source
    assert "self._arrow.create_line(" in source
    assert "capstyle=tk.ROUND" in source
    assert "joinstyle=tk.ROUND" in source
    assert "self.converter_slot = tk.Frame(" in source
    assert "self.converter_slot.pack_propagate(False)" in source
    assert "self.converter_frame = tk.Frame(self.converter_slot)" in source
    assert "self.converter_text_offset_spacer = tk.Frame(" in source
    assert (
        'self.converter_label = tk.Label(self.converter_frame, text="Converter:")'
        in source
    )
    assert "def _checkbutton_text_offset(widget):" in source
    assert "self.converter_dropdown = _ConverterDropdown(" in source
    assert "on_open=self._clear_browser_listbox_focus" in source
    assert "self.converter_dropdown.pack(side=tk.LEFT)" in source
    assert "self.refresh_btn.pack(side=tk.RIGHT)" in source
    assert "tk.Menubutton(" not in source
    assert "tk.Menu(" not in source
    assert 'popup.bind("<FocusOut>", lambda _event: self.close_popup())' not in source
    assert "popup.focus_force()" not in source
    assert "def _clear_browser_listbox_focus(self):" in source
    assert 'self._preferred_converter_setting = ""' in source
    assert "def _select_converter(self, value):" in source
    assert "dropdown.set_options(options)" in source
    assert (
        "self.converter_slot.grid(\n            row=2,\n            column=6," in source
    )
    assert "columnspan=3,\n            sticky=tk.W," in source
    assert "converter_slot.grid_configure(padx=(34, 0))" in source
    assert "self.converter_frame.pack_forget()" in source
    assert "self.converter_frame.grid_remove()" not in source
    assert 'f"{width}x{height}+{self._frame.winfo_rootx()}+"' in source
    assert "container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)" in source
    assert "highlighted = self._open or self._hover" in source
    assert "if _native_imaris_bridge_enabled():" in source
    assert (
        "if _native_imaris_bridge_enabled():\n"
        "            self._reset_native_bridge_probe_for_converter_detection()\n"
        "            self._start_native_bridge_probe()" in source
    )
    assert (
        "if client:\n            omero_available = client.has_omero_ims_export_capability()"
        in source
    )
    assert "if can_attempt_imaris_handoff and self.client:" not in source
    assert "def _has_imaris_handoff_target(self):" in source


def test_path_row_alignment_matches_refresh_to_entry_height():
    """Verify path-row controls adopt the rendered path-entry height.

    Inputs: repository fixtures. Output: fails on path-row height regressions.
    """
    module = _load_xt_module()

    class _Root:
        """Fake root that records idle updates."""

        def __init__(self):
            """Create fake root state.

            Inputs: none. Output: initializes call records.
            """
            self.idle_updates = 0

        def update_idletasks(self):
            """Record idle update.

            Inputs: none. Output: None.
            """
            self.idle_updates += 1

    class _Entry:
        """Fake entry exposing a rendered height."""

        @staticmethod
        def winfo_height():
            """Return rendered entry height.

            Inputs: none. Output: int.
            """
            return 31

    class _Control:
        """Fake command control that records configuration."""

        def __init__(self):
            """Create fake control state.

            Inputs: none. Output: initializes configuration records.
            """
            self.config_calls = []

        def config(self, **kwargs):
            """Record widget configuration.

            Inputs: keyword options. Output: None.
            """
            self.config_calls.append(dict(kwargs))

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog.folder_path_entry = _Entry()
    dialog.select_folder_btn = _Control()
    dialog.refresh_btn = _Control()
    dialog.converter_dropdown = _Control()
    dialog.converter_slot = _Control()

    module.OMEROBrowserDialog._align_path_row_control_heights(dialog)

    assert dialog.root.idle_updates == 1
    assert dialog.select_folder_btn.config_calls == [{"height": 31}]
    assert dialog.refresh_btn.config_calls == [{"height": 31}]
    assert dialog.converter_dropdown.config_calls == [{"height": 31}]
    assert dialog.converter_slot.config_calls == [{"height": 31}]


def test_converter_dropdown_open_clears_stale_browser_listbox_focus():
    """Verify converter popup opening does not restore browser panel focus.

    Inputs: repository fixtures. Output: fails on dropdown/listbox focus regressions.
    """
    module = _load_xt_module()

    class _Widget:
        """Simple Tk-like widget with a parent pointer."""

        def __init__(self, master=None):
            """Create fake widget.

            Inputs: optional `master`. Output: initializes parent pointer.
            """
            self.master = master

    class _Root:
        """Fake root exposing focus state."""

        def __init__(self, focused_widget):
            """Create fake root.

            Inputs: focused widget. Output: initializes focus records.
            """
            self.focused_widget = focused_widget
            self.focus_set_calls = 0

        def focus_get(self):
            """Return focused widget.

            Inputs: none. Output: widget.
            """
            return self.focused_widget

        def focus_set(self):
            """Record focus reset.

            Inputs: none. Output: None.
            """
            self.focus_set_calls += 1
            self.focused_widget = self

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.plist = _Widget()
    dialog.dlist = _Widget()
    dialog.ilist = _Widget()
    focused_child = _Widget(master=dialog.dlist)
    dialog.root = _Root(focused_child)

    module.OMEROBrowserDialog._clear_browser_listbox_focus(dialog)

    assert dialog.root.focus_set_calls == 1
    assert dialog.root.focused_widget is dialog.root


def test_converter_selection_refreshes_load_button_state():
    """Verify converter menu selection recomputes the Load button state.

    Inputs: repository fixtures. Output: fails on converter-state regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_var = _FakeVar("")
    dialog._connected = False
    refresh_calls = []

    def _set_load_button_for_converter():
        """Record Load button refresh.

        Inputs: none. Output: None.
        """
        refresh_calls.append("refresh")

    dialog._set_load_button_for_converter = _set_load_button_for_converter

    module.OMEROBrowserDialog._select_converter(dialog, "Imaris")

    assert dialog.converter_var.get() == "Imaris"
    assert dialog._preferred_converter_setting == "Imaris"
    assert refresh_calls == ["refresh"]


def test_converter_selection_autosaves_immediately_after_connection(tmp_path):
    """Verify converter dropdown changes are persisted by Autosave settings.

    Inputs: pytest provides `tmp_path`. Output: fails on converter autosave regressions.
    """
    module = _load_xt_module()
    settings_path = module._connector_settings_env_path(tmp_path)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = True
    dialog._settings_file_path = settings_path
    dialog._saved_settings = {}
    dialog._autosave_settings_write_error = ""
    dialog.host_entry = _FakeEntry("omero.example.org")
    dialog.port_entry = _FakeEntry("443")
    dialog.user_entry = _FakeEntry("alice")
    dialog.pass_entry = _FakeEntry("super-secret")
    dialog.https_var = _FakeVar(True)
    dialog.autosave_settings_var = _FakeVar(True)
    dialog.show_log_var = _FakeVar(True)
    dialog.search_function_var = _FakeVar(False)
    dialog.folder_path_var = _FakeVar(str(tmp_path))
    dialog._folder_path_placeholder_visible = False
    dialog.converter_var = _FakeVar("OMERO")
    dialog._set_load_button_for_converter = _noop
    dialog._show_autosave_settings_error = _noop

    module.OMEROBrowserDialog._select_converter(dialog, "Imaris")

    content = settings_path.read_text(encoding="utf-8")
    assert module.CONNECTOR_SETTINGS_CONVERTER_KEY + '="Imaris"' in content
    assert module.CONNECTOR_SETTINGS_SHOW_LOG_KEY + '="true"' in content
    assert module.CONNECTOR_SETTINGS_SEARCH_FUNCTION_KEY + '="false"' in content
    assert "PASSWORD" not in content
    assert "super-secret" not in content


def test_converter_detection_resets_stale_native_probe_before_waiting(monkeypatch):
    """Verify reconnect converter detection does not reuse a stale bridge failure.

    Inputs: repository fixtures. Output: fails on reconnect converter regressions.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)

    class _Done:
        """Immediate done event for converter detection."""

        @staticmethod
        def wait(timeout):
            """Record wait compatibility.

            Inputs: `timeout`. Output: bool.
            """
            assert timeout == module.NATIVE_BRIDGE_PROBE_TIMEOUT
            return True

    class _Lock:
        """Context manager compatible fake lock."""

        def __enter__(self):
            """Enter fake lock.

            Inputs: none. Output: self.
            """
            return self

        @staticmethod
        def __exit__(*_args):
            """Exit fake lock.

            Inputs: ignored. Output: bool.
            """
            return False

    class _Client:
        """OMERO client fake with available server-side conversion."""

        @staticmethod
        def has_omero_ims_export_capability():
            """Return conversion capability.

            Inputs: none. Output: bool.
            """
            return True

    dialog = object.__new__(module.OMEROBrowserDialog)
    calls = []
    dialog._native_bridge_probe_done = _Done()
    dialog._native_bridge_probe_lock = _Lock()
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog.client = _Client()

    def _reset_native_bridge_probe_for_converter_detection():
        """Record stale-probe reset.

        Inputs: none. Output: None.
        """
        calls.append("reset")

    def _start_native_bridge_probe():
        """Record native-probe start.

        Inputs: none. Output: None.
        """
        calls.append("start")

    dialog._reset_native_bridge_probe_for_converter_detection = (
        _reset_native_bridge_probe_for_converter_detection
    )
    dialog._start_native_bridge_probe = _start_native_bridge_probe

    options = module.OMEROBrowserDialog._detect_converter_options_after_connection(
        dialog
    )

    assert calls == ["reset", "start"]
    assert options == ["OMERO", "Imaris"]


def test_converter_detection_keeps_selector_when_probe_failed_but_imaris_id_exists(
    monkeypatch,
):
    """Verify a failed background probe does not hide valid converter choices.

    Inputs: repository fixtures. Output: fails on converter visibility regressions.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_available = False
    dialog._native_bridge_probe_error = "bridge unavailable"
    dialog._reset_native_bridge_probe = _noop
    dialog._start_native_bridge_probe = _noop
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: True)
    monkeypatch.setattr(
        module,
        "_find_imaris_convert_executable",
        lambda: r"C:\Imaris\ImarisConvert.exe",
    )

    assert dialog._detect_converter_options_after_connection() == ["OMERO", "Imaris"]


def test_converter_detection_keeps_imaris_choice_without_server_converter(monkeypatch):
    """Verify local Imaris handoff remains selectable when OMERO export is absent.

    Inputs: repository fixtures. Output: fails on converter visibility regressions.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_available = False
    dialog._native_bridge_probe_error = "bridge unavailable"
    dialog._reset_native_bridge_probe = _noop
    dialog._start_native_bridge_probe = _noop
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: False)
    monkeypatch.setattr(
        module,
        "_find_imaris_convert_executable",
        lambda: r"C:\Imaris\ImarisConvert.exe",
    )

    assert dialog._detect_converter_options_after_connection() == ["Imaris"]


def test_converter_detection_reset_does_not_interrupt_active_native_probe():
    """Verify converter detection does not reset an already running bridge probe.

    Inputs: repository fixtures. Output: fails on native probe race regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_in_progress = True
    reset_calls = []

    def _reset_native_bridge_probe():
        """Record unexpected reset.

        Inputs: none. Output: None.
        """
        reset_calls.append("reset")

    dialog._reset_native_bridge_probe = _reset_native_bridge_probe

    module.OMEROBrowserDialog._reset_native_bridge_probe_for_converter_detection(dialog)

    assert reset_calls == []


def test_connection_settings_has_top_right_help_and_info_buttons():
    """Verify connection panel keeps responsive help and info icon buttons.

    Inputs: repository fixtures. Output: fails on connection panel icon regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "class _CircularIconButton(_RoundedButton):" in source
    circular_source = source[
        source.index("class _CircularIconButton(_RoundedButton):") : source.index(
            "class _PasswordRevealButton(_RoundedButton):"
        )
    ]
    assert "create_arc(" not in circular_source
    assert "create_oval(" not in circular_source
    assert (
        "_antialiased_circle_image(self._canvas, width, height, fill, outline)"
        in circular_source
    )
    password_source = source[
        source.index("class _PasswordRevealButton(_RoundedButton):") : source.index(
            "class OMEROWebClient"
        )
    ]
    assert "create_arc(" not in password_source
    assert password_source.count("create_oval(") == 1
    assert "create_polygon(" in password_source
    assert "create_text(" not in password_source
    assert "PASSWORD_REVEAL_ICON_FONT" not in source
    assert "_antialiased_circle_image(" not in password_source
    assert "self._canvas.create_image(" not in password_source
    assert "capstyle=tk.ROUND" in password_source
    assert "self.panel_icon_frame = tk.Frame(conn_frame)" in source
    assert (
        "self.panel_icon_frame.grid(\n            row=0,\n            column=8,"
        in source
    )
    assert "rowspan=2,\n            sticky=tk.NE," in source
    assert "panel_icon_frame.grid_configure(padx=(12, 0))" in source
    assert "self.help_btn = _CircularIconButton(" in source
    assert 'text="?",' in source
    assert "bg=CONNECTOR_HELP_ICON_BG" in source
    assert "fg=CONNECTOR_HELP_ICON_FG" in source
    assert "font=CONNECTOR_PANEL_ICON_FONT" in source
    assert "width=CONNECTOR_PANEL_ICON_SIZE" in source
    assert "height=CONNECTOR_PANEL_ICON_SIZE" in source
    assert "self.help_btn.pack(side=tk.LEFT, padx=(0, 6))" in source
    assert "self.info_btn = _CircularIconButton(" in source
    assert 'text="i",' in source
    assert "command=self._show_connector_info" in source
    assert "bg=CONNECTOR_INFO_ICON_BG" in source
    assert "fg=CONNECTOR_INFO_ICON_FG" in source
    assert "self.info_btn.pack(side=tk.LEFT)" in source
    assert 'CONNECTOR_INFO_VERSION = "1.0.0"' in source
    assert 'CONNECTOR_INFO_AUTHOR = "Efstratios Mitridis"' in source
    assert 'CONNECTOR_INFO_CONTACT = "mitridisefstratios@gmail.com"' in source
    assert '"contributors are not liable' not in source
    assert '"service interruption' not in source
    assert "No liability can " in source
    info_source = source[
        source.index("def _show_connector_info(self):") : source.index(
            "def _invoke_on_ui_thread", source.index("def _show_connector_info(self):")
        )
    ]
    assert "text=CONNECTOR_INFO_TITLE" not in info_source
    assert "title_label" not in info_source
    assert "pady=(0, 3)" not in info_source
    assert "pady=(0, 14)" not in info_source
    assert "disclaimer.grid(" in info_source
    assert "pady=0" in info_source
    assert '("Author(s):", CONNECTOR_INFO_AUTHOR)' in info_source
    assert '("Contact:", CONNECTOR_INFO_CONTACT)' in info_source
    assert '("Version:", CONNECTOR_INFO_VERSION)' in info_source
    assert 'metadata_label_font = ("Arial", 9, "bold")' in info_source
    assert "font=metadata_label_font" in info_source
    assert "row=4, column=2" in info_source
    assert "info_window.grab_set()" in source
    assert "self.root.wait_window(info_window)" in source


def test_blocking_messagebox_locks_background_window_and_cursors(monkeypatch):
    """Verify modal message boxes prevent background UI interaction artifacts.

    Inputs: pytest provides `monkeypatch`. Output: fails on modal background lock regressions.
    """
    module = _load_xt_module()

    class _Widget:
        """Minimal Tk-like widget for modal background locking tests."""

        def __init__(self, cursor="", root=None):
            """Create a widget with cursor and root ownership.

            Inputs: `cursor`, `root`. Output: fake widget instance.
            """
            self.cursor = cursor
            self.root = root or self
            self.children = []
            self.disabled = False

        def cget(self, key):
            """Return a fake widget option.

            Inputs: `key`. Output: configured fake value.
            """
            if key == "cursor":
                return self.cursor
            raise KeyError(key)

        def configure(self, **kwargs):
            """Configure fake widget options.

            Inputs: `kwargs`. Output: None.
            """
            if "cursor" in kwargs:
                self.cursor = kwargs["cursor"]

        def winfo_children(self):
            """Return child widgets.

            Inputs: none. Output: children list.
            """
            return list(self.children)

        def winfo_toplevel(self):
            """Return the top-level root widget.

            Inputs: none. Output: root widget.
            """
            return self.root

        @staticmethod
        def winfo_exists():
            """Return whether the fake widget still exists.

            Inputs: none. Output: bool.
            """
            return True

        def attributes(self, option, value):
            """Record fake top-level disabled state.

            Inputs: `option`, `value`. Output: None.
            """
            assert option == "-disabled"
            self.disabled = bool(value)

    root = _Widget()
    button = _Widget(cursor="hand2", root=root)
    root.children.append(button)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = root
    observed = []

    def _showwarning(title, message, parent=None):
        """Capture state while the modal warning is active.

        Inputs: messagebox arguments. Output: bool.
        """
        observed.append((title, message, parent is root, root.disabled, button.cursor))
        return True

    monkeypatch.setattr(module.messagebox, "showwarning", _showwarning, raising=False)

    assert module.OMEROBrowserDialog._show_warning_dialog(dialog, "Title", "Body")
    assert observed == [("Title", "Body", True, True, "arrow")]
    assert root.disabled is False
    assert button.cursor == "hand2"


def test_autosave_settings_is_pinned_separately_from_right_aligned_icons():
    """Verify autosave stays fixed while help/info remain right aligned.

    Inputs: repository fixtures. Output: fails on autosave alignment regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "AUTOSAVE_SETTINGS_FRAME_WIDTH = 450" in source
    assert "AUTOSAVE_SETTINGS_OPTION_GAP = 34" in source
    assert "conn_frame.grid_columnconfigure(7, weight=1)" in source
    assert "conn_frame.grid_columnconfigure(8, weight=1)" not in source
    assert "self.autosave_settings_frame = tk.Frame(" in source
    assert (
        "self.autosave_settings_frame.grid(\n            row=0,\n            column=6,"
        in source
    )
    assert "padx=(34, 0)" in source
    assert "self.autosave_settings_frame.grid_propagate(False)" in source
    assert (
        "self.autosave_settings_check = tk.Checkbutton(\n"
        "            self.autosave_settings_frame,"
    ) in source
    assert "self.autosave_settings_check.pack(side=tk.LEFT)" in source
    assert 'text="Show log"' in source
    assert "command=self._on_show_log_changed" in source
    assert 'text="Search function"' in source
    assert "command=self._on_search_function_changed" in source
    assert "padx=(AUTOSAVE_SETTINGS_OPTION_GAP, 0)" in source
    assert "self.converter_text_offset_spacer.pack(side=tk.LEFT, fill=tk.Y)" in source
    assert (
        "converter_text_spacer.config(width=_checkbutton_text_offset(autosave_check))"
        in source
    )
    assert "panel_icon_frame.grid_propagate(False)" not in source
    assert source.index("self.autosave_settings_frame.grid(") < source.index(
        "panel_icon_frame.grid("
    )


def test_status_text_aligns_with_load_button_start():
    """Verify bottom status text starts at the Load button's left edge.

    Inputs: repository fixtures. Output: fails on bottom status alignment regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "ACTION_ROW_HORIZONTAL_PAD = 10" in source
    assert "ACTION_BUTTON_PAD = 0" in source
    assert "ACTION_BUTTON_GAP = 4" in source
    assert "STATUS_TEXT_PAD = ACTION_ROW_HORIZONTAL_PAD + ACTION_BUTTON_PAD" in source
    assert "actions.pack(fill=tk.X, padx=ACTION_ROW_HORIZONTAL_PAD" in source
    assert (
        "self.load_btn.grid(row=0, column=0, sticky=tk.W, padx=ACTION_BUTTON_PAD)"
        in source
    )
    assert "padx=STATUS_TEXT_PAD,\n            pady=5," in source
    assert "BOTTOM_PROGRESS_RESERVED_HEIGHT = 12" in source
    assert "bg=_resolve_tk_color(self.root, _widget_background(self.root))" in source
    assert (
        "height=BOTTOM_PROGRESS_RESERVED_HEIGHT,\n            bg=STATUS_NEUTRAL_BG"
        not in source
    )
    assert "bottom_progress_margin.pack(fill=tk.X, side=tk.BOTTOM)" in source
    assert "bottom_progress_margin.pack_propagate(False)" in source
    assert "padx=(STATUS_TEXT_PAD, STATUS_TEXT_PAD)" in source


def test_connection_indicator_draws_single_flat_circle():
    """Verify bottom-right connection indicator has no shadow or inner highlight.

    Inputs: repository fixtures. Output: fails on status-indicator drawing regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    indicator_source = source[
        source.index("def _draw_connection_indicator(self, state):") : source.index(
            "def _set_connection_indicator",
            source.index("def _draw_connection_indicator(self, state):"),
        )
    ]

    assert indicator_source.count("canvas.create_oval(") == 1
    assert "canvas.create_oval(6, 4, 28, 26" in indicator_source
    assert "shadow" not in indicator_source
    assert "highlight" not in indicator_source


def test_non_input_click_clears_text_input_focus():
    """Verify clicking non-input UI clears blinking entry cursors.

    Inputs: repository fixtures. Output: fails on focus-clear regressions.
    """
    module = _load_xt_module()
    cleared_focus = []

    class _Widget:
        """Small widget fake with Tk class and parent chain."""

        def __init__(self, widget_class, master=None):
            """Create widget fake.

            Inputs: `widget_class`, optional `master`. Output: initialized fake.
            """
            self._widget_class = widget_class
            self.master = master

        def winfo_class(self):
            """Return fake Tk widget class.

            Inputs: none. Output: widget class string.
            """
            return self._widget_class

    class _Root:
        """Root fake for focus clearing."""

        def __init__(self, focused):
            """Create root fake.

            Inputs: `focused`. Output: initialized fake.
            """
            self._focused = focused

        def focus_get(self):
            """Return currently focused widget.

            Inputs: none. Output: widget.
            """
            return self._focused

        @staticmethod
        def focus_set():
            """Record focus clear.

            Inputs: none. Output: None.
            """
            cleared_focus.append("root")

    focused_entry = _Widget("Entry")
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root(focused_entry)

    module.OMEROBrowserDialog._clear_text_focus_on_non_input_click(
        dialog,
        types.SimpleNamespace(widget=_Widget("Button")),
    )
    assert cleared_focus == ["root"]

    module.OMEROBrowserDialog._clear_text_focus_on_non_input_click(
        dialog,
        types.SimpleNamespace(widget=_Widget("Entry")),
    )
    assert cleared_focus == ["root"]

    nested_entry_child = _Widget("Canvas", master=_Widget("Entry"))
    assert module._widget_or_ancestor_is_text_input(nested_entry_child) is True


def test_browser_panels_use_draggable_splitters_with_fraction_limits():
    """Verify browser panels use resizable splitters with bounded fractions.

    Inputs: repository fixtures. Output: fails on browser splitter regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    module = _load_xt_module()

    assert (
        "BROWSER_PANEL_DEFAULT_FRACTIONS = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)" in source
    )
    assert "BROWSER_PANEL_MIN_FRACTION = 0.5 * (1.0 / 3.0)" in source
    assert "BROWSER_PANEL_MAX_FRACTION = 1.5 * (1.0 / 3.0)" in source
    assert (
        "self._browser_panel_fractions = tuple(BROWSER_PANEL_DEFAULT_FRACTIONS)"
        in source
    )
    assert "self._browser_panel_layout_widths = None" in source
    assert "self._browser_sash_drag_index = None" in source
    assert "@staticmethod\n    def _current_window_minimum_size(root):" in source
    assert 'cursor="sb_h_double_arrow"' in source
    assert "p_frame.grid(row=0, column=0, sticky=tk.NSEW)" in source
    assert "d_frame.grid(row=0, column=2, sticky=tk.NSEW)" in source
    assert "i_frame.grid(row=0, column=4, sticky=tk.NSEW)" in source
    assert "listbox.grid(row=0, column=0, sticky=tk.NSEW)" in source
    assert "y_scroll.grid(row=0, column=1, sticky=tk.NS)" in source
    assert "x_scroll.grid(row=1, column=0, sticky=tk.EW)" in source
    assert "layout_widths = tuple(widths)" in source
    assert "p_frame.pack(side=tk.LEFT" not in source
    assert "d_frame.pack(side=tk.LEFT" not in source
    assert "i_frame.pack(side=tk.LEFT" not in source

    assert module._normalized_browser_panel_fractions((1, 1, 1)) == pytest.approx(
        (1 / 3, 1 / 3, 1 / 3)
    )
    assert module._resize_browser_panel_fractions(
        (1 / 3, 1 / 3, 1 / 3), 0, 0.01
    ) == pytest.approx((1 / 6, 1 / 2, 1 / 3))
    assert module._resize_browser_panel_fractions(
        (1 / 3, 1 / 3, 1 / 3), 1, 0.99
    ) == pytest.approx((1 / 3, 1 / 2, 1 / 6))


def test_browser_panel_layout_applies_stored_percentages_on_resize():
    """Verify stored browser panel fractions drive grid column widths.

    Inputs: repository fixtures. Output: fails on proportional resize regressions.
    """
    module = _load_xt_module()

    class _Browser:
        """Browser frame fake that records column configuration."""

        def __init__(self, width):
            """Create browser fake.

            Inputs: `width`. Output: initializes record state.
            """
            self.width = width
            self.columns = {}
            self.configure_calls = []

        def winfo_width(self):
            """Return current fake width.

            Inputs: none. Output: int.
            """
            return self.width

        def grid_columnconfigure(self, column, **kwargs):
            """Record column configuration.

            Inputs: `column`, `**kwargs`. Output: None.
            """
            self.columns[column] = kwargs
            self.configure_calls.append((column, kwargs))

    dialog = object.__new__(module.OMEROBrowserDialog)
    browser = _Browser(916)
    dialog.browser_frame = browser
    dialog._browser_panel_fractions = (0.25, 0.35, 0.40)

    module.OMEROBrowserDialog._apply_browser_panel_layout(dialog)

    assert dialog._browser_panel_fractions == pytest.approx((0.25, 0.35, 0.40))
    assert browser.columns[0] == {"minsize": 225, "weight": 0}
    assert browser.columns[2] == {"minsize": 315, "weight": 0}
    assert browser.columns[4] == {"minsize": 360, "weight": 0}
    assert browser.columns[1] == {"minsize": module.BROWSER_SPLITTER_WIDTH, "weight": 0}
    assert browser.columns[3] == {"minsize": module.BROWSER_SPLITTER_WIDTH, "weight": 0}
    assert len(browser.configure_calls) == 5

    module.OMEROBrowserDialog._apply_browser_panel_layout(dialog)
    assert len(browser.configure_calls) == 5


def test_browser_panel_drag_updates_fraction_state():
    """Verify dragging a splitter stores bounded browser panel fractions.

    Inputs: repository fixtures. Output: fails on splitter drag regressions.
    """
    module = _load_xt_module()

    class _Browser:
        """Browser frame fake for splitter drag tests."""

        @staticmethod
        def winfo_width():
            """Return fake browser width.

            Inputs: none. Output: int.
            """
            return 916

        @staticmethod
        def winfo_rootx():
            """Return fake browser root x.

            Inputs: none. Output: int.
            """
            return 100

        @staticmethod
        def grid_columnconfigure(*_args, **_kwargs):
            """Accept column configuration.

            Inputs: ignored. Output: None.
            """

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.browser_frame = _Browser()
    dialog._browser_panel_fractions = (1 / 3, 1 / 3, 1 / 3)
    dialog._browser_sash_drag_index = 0

    module.OMEROBrowserDialog._drag_browser_panel_resize(
        dialog,
        types.SimpleNamespace(x_root=620),
    )

    assert dialog._browser_panel_fractions == pytest.approx((1 / 2, 1 / 6, 1 / 3))

    module.OMEROBrowserDialog._stop_browser_panel_resize(dialog, object())
    assert dialog._browser_sash_drag_index is None


def test_action_buttons_keep_fixed_size_while_close_tracks_right_edge():
    """Verify action buttons stay fixed while only the row spacer expands.

    Inputs: repository fixtures. Output: fails on action-row resize regressions.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "actions.grid_columnconfigure(1, minsize=ACTION_BUTTON_GAP)" in source
    assert "actions.grid_columnconfigure(3, weight=1)" in source
    assert "class _NativeButton:" not in source
    assert '"takefocus": False' not in source
    assert "class _RoundedButton:" in source
    assert "self.load_btn = _RoundedButton(" in source
    assert "width=260,\n            height=52," in source
    assert (
        "self.load_btn.grid(row=0, column=0, sticky=tk.W, padx=ACTION_BUTTON_PAD)"
        in source
    )
    assert (
        "self.export_btn.grid(row=0, column=2, sticky=tk.W, padx=ACTION_BUTTON_PAD)"
        in source
    )
    assert "close_btn = _RoundedButton(" in source
    assert "width=120,\n            height=52," in source
    assert (
        "close_btn.grid(row=0, column=4, sticky=tk.E, padx=ACTION_BUTTON_PAD)" in source
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
    path_hint = tmp_path / "hint"
    path_hint.mkdir()
    selected_folder = tmp_path / "selected"
    selected_folder.mkdir()

    busy_states = []
    statuses = []
    threads = []
    dialog_calls = []
    confirm_calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._refresh_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(str(path_hint))
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_dir_check_value = str(path_hint)
    dialog._folder_path_dir_check_is_dir = True
    dialog._folder_export_initial_path_hint_consumed = False
    dialog._last_folder_export_selection = ""
    dialog._export_folder_worker = lambda *_args: None
    dialog._set_actions_busy_for_export = busy_states.append
    dialog._set_status = lambda text, color="#ecf0f1": statuses.append((text, color))

    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **kwargs: dialog_calls.append(kwargs) or str(selected_folder),
        raising=False,
    )
    monkeypatch.setattr(
        module.messagebox,
        "askyesno",
        lambda title, message: confirm_calls.append((title, message)) or True,
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

    assert dialog_calls == [
        {
            "parent": dialog.root,
            "mustexist": True,
            "title": "Select folder to export to OMERO",
            "initialdir": str(path_hint),
        }
    ]
    assert confirm_calls == [
        (
            "Confirm folder export",
            "Export the selected folder to OMERO root path as a dataset?\n\n"
            "Dataset name: selected\n"
            "\n"
            "This will upload every file inside the selected folder.",
        )
    ]
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
    dialog._refresh_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(r"C:\\")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_dir_check_value = ""
    dialog._folder_path_dir_check_is_dir = False
    dialog._folder_export_initial_path_hint_consumed = False
    dialog._last_folder_export_selection = ""
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
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: r"C:\\",
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
    dialog._refresh_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(r"C:\missing-folder")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_dir_check_value = ""
    dialog._folder_path_dir_check_is_dir = False
    dialog._folder_export_initial_path_hint_consumed = False
    dialog._last_folder_export_selection = ""
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
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: r"C:\missing-folder",
        raising=False,
    )

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert errors == [
        (
            "Invalid Folder",
            "Please select an existing folder.",
        )
    ]


def test_export_folder_to_omero_rejects_malformed_selector_path(monkeypatch):
    """Verify malformed typed selector paths do not crash the export action.

    Inputs: pytest provides `monkeypatch`. Output: fails on export validation regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._refresh_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar("C:\\bad\x00path")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_dir_check_value = ""
    dialog._folder_path_dir_check_is_dir = False
    dialog._folder_export_initial_path_hint_consumed = False
    dialog._last_folder_export_selection = ""
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
    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: "C:\\bad\x00path",
        raising=False,
    )

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert errors == [
        (
            "Invalid Folder",
            "Please select an existing folder.",
        )
    ]


def test_export_folder_to_omero_cancel_stops_before_confirmation(monkeypatch):
    """Verify cancelling the export folder chooser starts no confirmation.

    Inputs: pytest provides `monkeypatch`. Output: fails on chooser-cancel regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._folder_export_in_progress = False
    dialog._refresh_in_progress = False
    dialog._connected = True
    dialog.client = object()
    dialog._folder_export_available = True
    dialog._folder_export_reason = ""
    dialog.root = object()
    dialog.folder_path_var = _FakeVar("")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_dir_check_value = ""
    dialog._folder_path_dir_check_is_dir = False
    dialog._folder_export_initial_path_hint_consumed = False
    dialog._last_folder_export_selection = ""
    dialog._set_actions_busy_for_export = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(AssertionError("busy state must not change"))
    dialog._set_status = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("status must not change")
    )
    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **_kwargs: "",
        raising=False,
    )
    monkeypatch.setattr(
        module.messagebox,
        "askyesno",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation must not open after cancel")
        ),
        raising=False,
    )

    module.OMEROBrowserDialog._export_folder_to_omero(dialog)

    assert dialog._folder_export_initial_path_hint_consumed is True


def test_export_folder_dialog_uses_last_selected_folder_after_first_hint(
    tmp_path, monkeypatch
):
    """Verify the path row is only a first-use export chooser hint.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on export chooser regressions.
    """
    module = _load_xt_module()
    path_hint = tmp_path / "hint"
    last_selected = tmp_path / "last-selected"
    new_selected = tmp_path / "new-selected"
    for folder in (path_hint, last_selected, new_selected):
        folder.mkdir()

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = object()
    dialog.folder_path_var = _FakeVar(str(path_hint))
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_dir_check_value = str(path_hint)
    dialog._folder_path_dir_check_is_dir = True
    dialog._folder_export_initial_path_hint_consumed = True
    dialog._last_folder_export_selection = str(last_selected)
    dialog_calls = []
    monkeypatch.setattr(
        module.filedialog,
        "askdirectory",
        lambda **kwargs: dialog_calls.append(kwargs) or str(new_selected),
        raising=False,
    )

    selected = module.OMEROBrowserDialog._select_folder_for_omero_export(dialog)

    assert selected == str(new_selected)
    assert dialog._last_folder_export_selection == str(new_selected)
    assert dialog_calls == [
        {
            "parent": dialog.root,
            "mustexist": True,
            "title": "Select folder to export to OMERO",
            "initialdir": str(last_selected),
        }
    ]


def test_folder_export_initialdir_requires_background_validated_path(tmp_path):
    """Verify typed path hints require the background directory check.

    Inputs: pytest provides `tmp_path`. Output: fails on initialdir validation regressions.
    """
    module = _load_xt_module()
    path_hint = tmp_path / "hint"
    path_hint.mkdir()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.folder_path_var = _FakeVar(str(path_hint))
    dialog._folder_path_placeholder_visible = False
    dialog._folder_export_initial_path_hint_consumed = False
    dialog._last_folder_export_selection = ""
    dialog._folder_path_dir_check_value = ""
    dialog._folder_path_dir_check_is_dir = False

    assert module.OMEROBrowserDialog._folder_export_dialog_initialdir(dialog) == ""

    dialog._folder_path_dir_check_value = str(path_hint)
    dialog._folder_path_dir_check_is_dir = True
    assert module.OMEROBrowserDialog._folder_export_dialog_initialdir(dialog) == str(
        path_hint
    )


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
            "The folder was exported to OMERO root path as dataset 'batch'.",
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


def test_image_selection_updates_load_button_enabled_state():
    """Verify Load enables only while at least one image is selected.

    Inputs: repository fixtures. Output: fails on image-selection load gating regressions.
    """
    module = _load_xt_module()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = True
    dialog.client = object()
    dialog.converter_var = _FakeVar("OMERO")
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
    dialog._load_in_progress = False
    dialog._folder_export_in_progress = False
    dialog.images_data = [{"id": 1}, {"id": 2}]
    dialog.ilist = _FakeListbox(items=["a", "b"], selection=set())
    dialog.load_btn = _FakeButton()
    dialog._image_selection_anchor = None

    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "disabled"

    result = dialog._on_image_listbox_click(
        types.SimpleNamespace(widget=dialog.ilist, y=1, state=0)
    )

    assert result == "break"
    assert dialog.ilist.selection == {1}
    assert dialog.load_btn.state == "normal"

    result = dialog._on_image_listbox_click(
        types.SimpleNamespace(widget=dialog.ilist, y=1, state=0x0004)
    )

    assert result == "break"
    assert dialog.ilist.selection == set()
    assert dialog.load_btn.state == "disabled"


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


def test_xt_connector_never_launches_fresh_imaris_processes():
    """Verify the XT connector never starts Imaris as a fallback.

    Inputs: repository fixtures. Output: fails on regressions that reintroduce
    fresh-session fallback launches or ImarisServerIce process spawning.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")

    assert "_launch_fresh_imaris_bridge" not in source
    assert "_launch_imaris_process" not in source
    assert "_launch_imaris_and_find_bridge_python" not in source
    assert "Opening a new Imaris session" not in source
    assert "Fresh Imaris" not in source
    assert "ImarisServerIce" not in source
    assert "subprocess.Popen(" not in source


def test_direct_imaris_resolution_does_not_import_native_bridge_in_process():
    """Verify direct handle resolution does not import Bitplane native modules.

    Inputs: repository fixtures. Output: fails on regressions that can load
    ImarisLib/IcePy into the connector's current Python process.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    tree = ast.parse(source)

    function_nodes = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    resolver = function_nodes["_resolve_imaris_application"]
    resolver_imports = [
        alias.name
        for node in ast.walk(resolver)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]

    assert "ImarisLib" not in resolver_imports
    assert "IcePy" not in resolver_imports
    assert 'sys.modules.get("ImarisLib")' in source


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


def test_native_bridge_runner_rejects_original_file_when_ims_not_required(
    tmp_path, monkeypatch
):
    """Verify native bridge runner enforces IMS even when legacy flag is false.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in native bridge IMS validation.
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
    calls = []

    def _fake_run(cmd, **kwargs):
        """Return `tests.test_xt_omero_connector`'s fake command result.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `SimpleNamespace` result.
        """
        calls.append((cmd, kwargs))
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
        is False
    )
    assert calls == []


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


def test_native_bridge_helper_rejects_unverified_ims_fileopen(tmp_path):
    """Verify the native bridge helper rejects bare IMS FileOpen success.

    Inputs: pytest provides `tmp_path`. Output: helper rejects success without
    current-file or visible-dataset proof.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
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
        "file_path": str(ims_path),
        "require_ims": True,
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

    assert completed.returncode == 4
    assert completed.stdout.strip() == "BRIDGE_RUNNER_OPEN_UNVERIFIED"
    assert calls_path.read_text(encoding="utf-8").splitlines() == ["2", "1"]


def test_native_bridge_helper_opens_ims_with_visible_dataset_without_current_file(
    tmp_path,
):
    """Verify the helper accepts no-current-file IMS only after visibility handoff.

    Inputs: pytest provides `tmp_path`. Output: asserts SetDataSet handoff is
    required and executed for no-current-file Imaris APIs.
    """
    module = _load_xt_module()
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    visible_path = tmp_path / "visible.txt"
    fake_imarislib = tmp_path / "ImarisLib.py"
    fake_imarislib.write_text(
        "\n".join(
            [
                "import os",
                "visible_path = os.environ['IMARIS_FAKE_VISIBLE']",
                "",
                "class DataSet:",
                "    def GetSizeX(self):",
                "        return 4",
                "    def GetSizeY(self):",
                "        return 3",
                "    def GetSizeZ(self):",
                "        return 1",
                "",
                "class App:",
                "    def __init__(self):",
                "        self.data_set = None",
                "    def FileOpen(self, *args):",
                "        self.data_set = DataSet()",
                "    def GetDataSet(self):",
                "        return self.data_set",
                "    def SetDataSet(self, data_set):",
                "        with open(visible_path, 'w', encoding='utf-8') as handle:",
                "            handle.write('visible')",
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
        "file_path": str(ims_path),
        "require_ims": True,
        "open_verify_timeout": 0.01,
        "open_verify_interval": 0.01,
    }
    env = dict(os.environ)
    env["IMARIS_FAKE_VISIBLE"] = str(visible_path)

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
    assert visible_path.read_text(encoding="utf-8") == "visible"


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


def test_native_bridge_runner_reports_legacy_false_flag_as_ims_open(
    tmp_path, monkeypatch
):
    """Verify legacy require_ims false payload is logged as an IMS open.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on native bridge logging regressions.
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
        "completed IMS open request in the current Imaris session" in message
        for message in messages
    )
    assert not any("original-file" in message for message in messages)


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
        "/api/v0/m/projects/<id>/datasets/?group=-1&base_url=<redacted>"
    )
    assert "omero.example.org" not in safe_url
    assert "51" not in safe_url

    safe_user_url = module._safe_url_for_log(
        f"{scheme}://omero.example.org/api/v0/m/images/7/"
        "?username=alice.smith&group=Facility%20Staff&experimenter=42"
    )
    assert safe_user_url == (
        "/api/v0/m/images/<id>/?username=alice.smith&group=Facility Staff"
        "&experimenter=<redacted>"
    )

    malicious_url = module._safe_url_for_log(
        f"{scheme}://omero.example.org/api/v0/m/images/"
        f"?username={scheme}%3A%2F%2Fleak.example%2Fapi&group=readers"
    )
    assert malicious_url == ("/api/v0/m/images/?username=<redacted>&group=readers")
    assert "leak.example" not in malicious_url

    duplicate_url = module._safe_url_for_log(
        "https://omero.example.org/api/v0/m/images/"
        "?username=alice&username=bob&unsafe%20key=secret&group=readers%0A"
    )
    assert duplicate_url == (
        "/api/v0/m/images/?username=alice&unsafe_key=<redacted>&group=<redacted>"
    )
    assert "bob" not in duplicate_url
    assert "secret" not in duplicate_url


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


def test_xt_connector_imaris_load_path_does_not_download_archived_originals():
    """Verify the Imaris load path does not download archived original files.

    Inputs: repository fixtures. Output: fails on regressions in Imaris converter source selection.
    """
    module = _load_xt_module()
    source = (
        inspect.getsource(module.OMEROBrowserDialog._load_worker)
        + inspect.getsource(module.OMEROBrowserDialog._load_multiple_worker)
        + inspect.getsource(
            module.OMEROBrowserDialog._download_selected_image_with_imaris_converter
        )
    )

    assert "download_original_file" not in source
    assert "download_selected_image_ome_tiff" in source
    assert "convert_ome_tiff_to_ims_with_local_imaris" in source


def test_client_download_selected_image_ome_tiff_uses_standard_export_endpoint(
    tmp_path,
):
    """Verify selected Image ID export uses OMERO.web OME-TIFF, not originals.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in selected-image export endpoint selection.
    """
    module = _load_xt_module()
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(request, timeout):
            """Return a small TIFF response and record the request.

            Inputs: `request`, `timeout`. Output: `_FakeHTTPResponse`.
            """
            opened_urls.append((request.full_url, timeout))
            return _FakeHTTPResponse(
                b"II*\x00selected-image",
                headers={
                    "Content-Disposition": 'attachment; filename="demo.ome.tif"',
                    "Content-Type": "image/tiff",
                    "Content-Length": "18",
                },
            )

    client.opener = _FakeOpener()

    local_path = client.download_selected_image_ome_tiff(17, tmp_path)

    assert Path(local_path).name == "demo.ome.tif"
    assert Path(local_path).read_bytes() == b"II*\x00selected-image"
    assert opened_urls == [
        (
            f"{client.base_url}/webgateway/render_ome_tiff/i/17/",
            module.EXPORT_TIMEOUT + 60,
        )
    ]
    assert "archived_files" not in opened_urls[0][0]


def test_client_download_selected_image_ome_tiff_404_never_downloads_original(
    tmp_path,
    monkeypatch,
):
    """Verify OME-TIFF export failure does not fall back to archived originals.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in Imaris source download boundaries.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.urllib.error, "HTTPError", _FakeHTTPError)
    client = module.OMEROWebClient("omero.example.org", 4090, "user", TEST_LOGIN_VALUE)
    client.session_id = "session-123"
    opened_urls = []

    class _FakeOpener:
        """Test double for fake opener."""

        @staticmethod
        def open(request, timeout=None):
            """Raise a not-found export response.

            Inputs: `request`, `timeout`. Output: None. Raises: `_FakeHTTPError`.
            """
            assert timeout == module.EXPORT_TIMEOUT + 60
            opened_urls.append(request.full_url)
            raise _FakeHTTPError(b"not found", code=404, msg="Not Found")

    client.opener = _FakeOpener()

    with pytest.raises(RuntimeError, match="No archived original file was downloaded"):
        client.download_selected_image_ome_tiff(17, tmp_path)

    assert opened_urls == [f"{client.base_url}/webgateway/render_ome_tiff/i/17/"]
    assert "archived_files" not in opened_urls[0]


def test_convert_ome_tiff_to_ims_with_local_imaris_runs_imarisconvert(
    tmp_path,
    monkeypatch,
):
    """Verify local Imaris conversion invokes ImarisConvert and validates IMS output.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in local conversion command construction.
    """
    module = _load_xt_module()
    converter = tmp_path / "ImarisConvert.exe"
    converter.write_text("fake", encoding="utf-8")
    source_file = tmp_path / "source.ome.tif"
    source_file.write_bytes(b"II*\x00selected-image")
    calls = []

    def _run(cmd, **kwargs):
        """Record subprocess invocation and create a fake IMS output.

        Inputs: `cmd`, `**kwargs`. Output: fake completed process.
        """
        calls.append((cmd, kwargs))
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x89HDF\r\n\x1a\npayload")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        module, "_find_imaris_convert_executable", lambda: str(converter)
    )
    monkeypatch.setattr(module.subprocess, "run", _run)

    ims_path = module.convert_ome_tiff_to_ims_with_local_imaris(
        source_file,
        tmp_path,
        fallback_name="converted.ims",
    )

    assert module.is_ims_file(ims_path) is True
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[:2] == [str(converter), "-i"]
    assert cmd[2] == str(source_file)
    assert cmd[3] == "-o"
    assert cmd[5:] == ["-l", "none"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == module.LOCAL_IMARIS_CONVERT_TIMEOUT


def test_convert_ome_tiff_to_ims_reports_breakpoint_exit_code(tmp_path, monkeypatch):
    """Verify local converter errors expose decimal and hexadecimal exit codes.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on breakpoint diagnostics regressions.
    """
    module = _load_xt_module()
    converter = tmp_path / "ImarisConvert.exe"
    converter.write_text("fake", encoding="utf-8")
    source_file = tmp_path / "source.ome.tif"
    source_file.write_bytes(b"II*\x00selected-image")
    monkeypatch.setattr(
        module, "_find_imaris_convert_executable", lambda: str(converter)
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: types.SimpleNamespace(
            returncode=0x80000003,
            stdout="",
            stderr="breakpoint",
        ),
    )

    with pytest.raises(RuntimeError, match="0x80000003"):
        module.convert_ome_tiff_to_ims_with_local_imaris(source_file, tmp_path)


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


def test_native_bridge_helper_source_has_no_undefined_logger_reference():
    """Verify the generated bridge helper is self-contained.

    Inputs: repository fixtures. Output: fails on helper-source regressions.
    """
    module = _load_xt_module()

    assert "logger." not in module._NATIVE_BRIDGE_OPEN_HELPER
    assert '"OpenFile"' in module._NATIVE_BRIDGE_OPEN_HELPER
    assert '"LoadFile"' in module._NATIVE_BRIDGE_OPEN_HELPER


def test_native_bridge_runner_requires_numeric_imaris_id(monkeypatch):
    """Verify native bridge runner requires numeric imaris ID.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in native bridge runner requires numeric imaris ID.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
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
    _enable_native_bridge(module, monkeypatch)
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


def test_dialog_direct_handle_reacquisition_is_not_icepy_flag_gated(monkeypatch):
    """Verify direct XT handle reacquisition works with optional IcePy probing disabled.

    Inputs: pytest provides `monkeypatch`. Output: fails on pre-download bridge readiness regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._ui_thread_id = -1
    dialog.root = types.SimpleNamespace(after=lambda _delay, callback: callback())
    status_updates = []
    ui_calls = []
    resolved_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)
    dialog._set_status = lambda text, _color="#ecf0f1": status_updates.append(text)
    dialog._invoke_on_ui_thread = lambda callback: (
        ui_calls.append("resolve") or callback()
    )
    monkeypatch.setattr(
        module,
        "_resolve_imaris_application",
        lambda imaris_id, **_kwargs: resolved_handle if imaris_id == "17" else None,
    )

    assert dialog._ensure_native_open_ready_before_export() is True
    assert dialog.imaris is resolved_handle
    assert status_updates == ["Checking Imaris same-session open support..."]
    assert ui_calls == ["resolve"]


def test_handoff_target_uses_numeric_imaris_id_without_optional_icepy(monkeypatch):
    """Verify a numeric XT id is enough to attempt final same-session handoff.

    Inputs: pytest provides `monkeypatch`. Output: fails on converter visibility regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"

    assert dialog._has_imaris_handoff_target() is True


def test_pre_export_readiness_allows_numeric_id_when_direct_handle_is_not_ready(
    monkeypatch,
):
    """Verify pre-export readiness does not block a valid delayed XT handoff.

    Inputs: pytest provides `monkeypatch`. Output: fails on premature preflight blocking.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    status_updates = []
    ui_calls = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._ui_thread_id = -1
    dialog.root = types.SimpleNamespace(after=lambda _delay, callback: callback())
    dialog._set_status = lambda text, _color="#ecf0f1": status_updates.append(text)
    dialog._invoke_on_ui_thread = lambda callback: (
        ui_calls.append("resolve") or callback()
    )
    monkeypatch.setattr(
        module, "_resolve_imaris_application", lambda *_args, **_kwargs: None
    )

    assert dialog._ensure_native_open_ready_before_export() is True
    assert dialog.imaris is None
    assert status_updates == ["Checking Imaris same-session open support..."]
    assert ui_calls == ["resolve"]


def test_pre_export_readiness_still_rejects_missing_handoff_target(monkeypatch):
    """Verify pre-export readiness still fails when there is no handle or XT id.

    Inputs: pytest provides `monkeypatch`. Output: fails on missing-target validation regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = None
    dialog._set_status = _noop

    assert dialog._ensure_native_open_ready_before_export() is False


@pytest.mark.parametrize(
    ("converter", "filename", "expected_download"),
    [
        ("OMERO", "sample.ims", "ims"),
        ("Imaris", "sample.ims", "imaris"),
    ],
)
def test_load_worker_retries_delayed_direct_handoff_after_nonblocking_preflight(
    tmp_path,
    monkeypatch,
    converter,
    filename,
    expected_download,
):
    """Verify delayed direct XT handle resolution is retried at final handoff.

    Inputs: pytest provides fixtures and converter parameters. Output: fails on the no-bridge preflight regression.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    local_file = tmp_path / filename
    local_file.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    downloads = []
    opened = []
    errors = []

    class _FakeImaris:
        """Fake Imaris app resolved only at final handoff."""

        def __init__(self):
            """Create fake Imaris current-file state.

            Inputs: none. Output: initializes state.
            """
            self.current = ""

        def FileOpen(self, path, *_args):
            """Record the final FileOpen call.

            Inputs: `path`, `*_args`. Output: None.
            """
            opened.append(path)
            self.current = path

        def GetCurrentFileName(self):
            """Return the current file path for IMS-open verification.

            Inputs: none. Output: path string.
            """
            return self.current

    resolution_results = [None, _FakeImaris()]

    def _resolve_imaris_application(imaris_id, **_kwargs):
        """Return no handle during preflight and a handle during final open.

        Inputs: `imaris_id`, keyword arguments. Output: fake Imaris app or None.
        """
        assert imaris_id == "17"
        return resolution_results.pop(0)

    def _download_ims_export(image_id, download_dir, fallback_name):
        """Record server-side IMS export download.

        Inputs: OMERO image id, target directory, fallback name. Output: local file path.
        """
        downloads.append(("ims", image_id, Path(download_dir), fallback_name))
        return str(local_file)

    def _download_with_imaris_converter(image_id, image_name, download_dir):
        """Record selected-image local Imaris conversion.

        Inputs: OMERO image id, image name, target directory. Output: local file path.
        """
        downloads.append(("imaris", image_id, image_name, Path(download_dir)))
        return str(local_file)

    monkeypatch.setattr(
        module, "_resolve_imaris_application", _resolve_imaris_application
    )
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._ui_thread_id = -1
    dialog.root = types.SimpleNamespace(after=lambda _delay, callback: callback())
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog.client = types.SimpleNamespace(
        download_ims_export=_download_ims_export,
        download_original_file=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("archived original download must not run")
        ),
    )
    dialog._download_selected_image_with_imaris_converter = (
        _download_with_imaris_converter
    )
    dialog._set_status = _noop
    dialog._show_info = _noop
    dialog._show_error = lambda _title, message: errors.append(message)
    dialog._invoke_on_ui_thread = lambda callback, wait=True: (
        None if not wait else callback()
    )

    module.OMEROBrowserDialog._load_worker(
        dialog,
        {"id": 7, "name": filename},
        converter,
    )

    if converter == "OMERO":
        assert downloads == [(expected_download, 7, tmp_path, "img_7.ims")]
    else:
        assert downloads == [(expected_download, 7, filename, tmp_path)]
    assert opened == [str(local_file)]
    assert dialog.temp_files == [str(local_file)]
    assert dialog.imaris is not None
    assert resolution_results == []
    assert errors == []


def test_open_downloaded_file_retries_direct_handle_when_optional_bridge_disabled(
    tmp_path,
    monkeypatch,
):
    """Verify final file open reacquires direct XT handle without optional IcePy probing.

    Inputs: pytest provides `tmp_path` and `monkeypatch`. Output: fails on final handoff regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    opened = []

    class _FakeImaris:
        """Fake Imaris app returned by delayed direct resolution."""

        def __init__(self):
            """Create fake Imaris current-file state.

            Inputs: none. Output: initializes state.
            """
            self.current = ""

        def FileOpen(self, path, *_args):
            """Record the final FileOpen call.

            Inputs: `path`, `*_args`. Output: None.
            """
            opened.append(path)
            self.current = path

        def GetCurrentFileName(self):
            """Return the current file path for IMS-open verification.

            Inputs: none. Output: path string.
            """
            return self.current

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._ui_thread_id = module.threading.get_ident()
    dialog._set_status = _noop
    monkeypatch.setattr(
        module,
        "_resolve_imaris_application",
        lambda imaris_id, **_kwargs: _FakeImaris() if imaris_id == "17" else None,
    )

    assert dialog._open_downloaded_file_in_imaris(str(ims_path), require_ims=True)
    assert opened == [str(ims_path)]


def test_open_downloaded_file_uses_lazy_bridge_runner_when_probe_disabled(
    tmp_path,
    monkeypatch,
):
    """Verify final open can use a lazy bridge runner without startup probing.

    Inputs: pytest provides `tmp_path` and `monkeypatch`. Output: fails on final handoff regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    ims_path = tmp_path / "demo.ims"
    ims_path.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    attempts = []
    direct_calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._ui_thread_id = module.threading.get_ident()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_python_executable = None
    dialog._set_status = _noop
    monkeypatch.setattr(
        module, "_resolve_imaris_application", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        module,
        "open_file_in_imaris",
        lambda *args, **_kwargs: direct_calls.append(args) or False,
    )

    def _lazy_runner(
        file_path,
        imaris_id,
        preferred_python_executable=None,
        require_ims=True,
        allow_when_disabled=False,
    ):
        """Record lazy native runner handoff.

        Inputs: bridge runner arguments. Output: True.
        """
        attempts.append(
            (
                file_path,
                imaris_id,
                preferred_python_executable,
                require_ims,
                allow_when_disabled,
            )
        )
        return True

    monkeypatch.setattr(
        module,
        "_open_file_in_imaris_with_native_bridge_runner",
        _lazy_runner,
    )

    assert dialog._open_downloaded_file_in_imaris(str(ims_path), require_ims=True)
    assert direct_calls == []
    assert attempts == [(str(ims_path), "17", None, True, True)]


def test_open_downloaded_files_use_lazy_bridge_runner_when_probe_disabled(
    tmp_path,
    monkeypatch,
):
    """Verify batch final open can use lazy bridge handoff without startup probing.

    Inputs: pytest provides `tmp_path` and `monkeypatch`. Output: fails on batch final handoff regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    first = tmp_path / "first.ims"
    second = tmp_path / "second.ims"
    first.write_bytes(b"\x89HDF\r\n\x1a\nfirst")
    second.write_bytes(b"\x89HDF\r\n\x1a\nsecond")
    attempts = []
    direct_calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._ui_thread_id = module.threading.get_ident()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_python_executable = None
    dialog._set_status = _noop
    monkeypatch.setattr(
        module, "_resolve_imaris_application", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        module,
        "open_files_in_imaris",
        lambda *args, **_kwargs: direct_calls.append(args) or False,
    )

    def _lazy_runner(
        file_paths,
        imaris_id,
        preferred_python_executable=None,
        require_ims=True,
        allow_when_disabled=False,
    ):
        """Record lazy native batch runner handoff.

        Inputs: bridge runner arguments. Output: True.
        """
        attempts.append(
            (
                list(file_paths),
                imaris_id,
                preferred_python_executable,
                require_ims,
                allow_when_disabled,
            )
        )
        return True

    monkeypatch.setattr(
        module,
        "_open_files_in_imaris_with_native_bridge_runner",
        _lazy_runner,
    )

    assert dialog._open_downloaded_files_in_imaris([str(first), str(second)])
    assert direct_calls == []
    assert attempts == [([str(first), str(second)], "17", None, True, True)]


def test_dialog_native_bridge_probe_runs_before_export_and_blocks_when_unavailable(
    monkeypatch,
):
    """Confirm an unavailable native bridge blocks without launching Imaris.

    Inputs: repository fixtures. Output: fails on regressions that launch a fresh
    Imaris session instead of stopping at the same-session boundary.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
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


def test_dialog_native_bridge_probe_does_not_trust_non_opening_handle(monkeypatch):
    """Verify bridge probing does not trust a non-opening handle or launch Imaris.

    Inputs: repository fixtures. Output: fails on regressions in same-session
    bridge readiness checks.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
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
    """Verify dialog native bridge probe revalidates stale cached python.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in dialog native bridge probe revalidates stale cached python.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
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
    _enable_native_bridge(module, monkeypatch)
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
    _enable_native_bridge(module, monkeypatch)
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
    _enable_native_bridge(module, monkeypatch)
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
        lambda file_path, imaris_id, preferred_python_executable=None, require_ims=True, allow_when_disabled=False: (
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


def test_detect_converter_options_defaults_omero_when_server_supports_it(monkeypatch):
    """Verify detect converter options defaults OMERO when server supports it.

    Inputs: repository fixtures. Output: fails on regressions in detect converter options defaults OMERO when server supports it.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog._reset_native_bridge_probe = _noop
    dialog._start_native_bridge_probe = _noop
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: True)

    assert dialog._detect_converter_options_after_connection() == ["OMERO", "Imaris"]


def test_detect_converter_options_hides_omero_without_server_capability(monkeypatch):
    """Verify detect converter options hides OMERO without server capability.

    Inputs: repository fixtures. Output: fails on regressions in detect converter options hides OMERO without server capability.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog._reset_native_bridge_probe = _noop
    dialog._start_native_bridge_probe = _noop
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: False)

    assert dialog._detect_converter_options_after_connection() == ["Imaris"]


def test_detect_converter_options_hides_imaris_without_local_converter(monkeypatch):
    """Verify Imaris option requires a local Imaris conversion executable.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in Imaris converter availability detection.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog._reset_native_bridge_probe = _noop
    dialog._start_native_bridge_probe = _noop
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: True)
    monkeypatch.setattr(module, "_find_imaris_convert_executable", lambda: None)

    assert dialog._detect_converter_options_after_connection() == ["OMERO"]


def test_detect_converter_options_keeps_omero_when_native_open_unavailable(
    monkeypatch,
):
    """Verify OMERO capability is not hidden by missing native Imaris handoff.

    Inputs: repository fixtures. Output: fails on converter visibility regressions.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_started = True
    dialog._native_bridge_available = False
    dialog._native_bridge_probe_error = "bridge unavailable"
    dialog._reset_native_bridge_probe = _noop
    dialog._start_native_bridge_probe = _noop
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: True)
    monkeypatch.setattr(
        module,
        "_find_imaris_convert_executable",
        lambda: r"C:\Imaris\ImarisConvert.exe",
    )

    assert dialog._detect_converter_options_after_connection() == ["OMERO"]


def test_detect_converter_options_is_quiet_when_native_bridge_flag_is_disabled(
    monkeypatch,
):
    """Verify disabled IcePy bridge probing is silent during converter detection.

    Inputs: pytest provides `monkeypatch`. Output: fails on disabled bridge regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    logs = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = "17"
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_available = False
    dialog._native_bridge_probe_error = ""
    dialog._reset_native_bridge_probe_for_converter_detection = lambda: (
        _ for _ in ()
    ).throw(AssertionError("disabled bridge must not reset native probing"))
    dialog._start_native_bridge_probe = lambda: (_ for _ in ()).throw(
        AssertionError("disabled bridge must not start native probing")
    )
    dialog.client = types.SimpleNamespace(has_omero_ims_export_capability=lambda: True)
    monkeypatch.setattr(module, "_xt_debug", logs.append)
    monkeypatch.setattr(
        module,
        "_find_imaris_convert_executable",
        lambda: r"C:\Imaris\ImarisConvert.exe",
    )

    assert dialog._detect_converter_options_after_connection() == ["OMERO", "Imaris"]
    assert not any("bridge" in message.lower() for message in logs)


def test_set_converter_options_hides_dropdown_and_disables_load():
    """Verify set converter options hides dropdown and disables load.

    Inputs: repository fixtures. Output: fails on regressions in set converter options hides dropdown and disables load.
    """
    module = _load_xt_module()

    class DummyDropdown:
        """Test double for converter dropdown."""

        def __init__(self):
            """Create `DummyDropdown` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.options = None

        def set_options(self, options):
            """Record converter options.

            Inputs: `options`. Output: None.
            """
            self.options = list(options)

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

    dropdown = DummyDropdown()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_dropdown = dropdown
    dialog.converter_var = DummyVar()
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = DummyButton()
    dialog.refresh_btn = DummyButton()

    module.OMEROBrowserDialog._set_converter_options(dialog, [])

    assert dropdown.options == []
    assert dialog.converter_var.value == ""
    assert dialog.converter_frame.hidden is True
    assert dialog.load_btn.state == "disabled"
    assert dialog.refresh_btn.state == "disabled"


def test_set_converter_options_populates_dropdown_without_blank_entry():
    """Verify set converter options populates dropdown without blank entry.

    Inputs: repository fixtures. Output: fails on regressions in set converter options populates menu without blank entry.
    """
    module = _load_xt_module()

    class DummyDropdown:
        """Test double for converter dropdown."""

        def __init__(self):
            """Create `DummyDropdown` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.options = None

        def set_options(self, options):
            """Record converter options.

            Inputs: `options`. Output: None.
            """
            self.options = list(options)

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

    dropdown = DummyDropdown()
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_dropdown = dropdown
    dialog.converter_var = DummyVar()
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = DummyButton()
    dialog.refresh_btn = DummyButton()
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
    dialog.images_data = [{"id": 1, "name": "selected"}]
    dialog.ilist = _FakeListbox(["selected"], selection=set())

    module.OMEROBrowserDialog._set_converter_options(dialog, ["OMERO", "Imaris"])

    assert dropdown.options == ["OMERO", "Imaris"]
    assert "" not in dropdown.options
    assert "-" not in dropdown.options
    assert dialog.converter_var.value == "OMERO"
    assert dialog.converter_frame.shown is True
    assert dialog.load_btn.state == "disabled"
    assert dialog.refresh_btn.state == "normal"

    dialog.ilist.selection_set(0)
    module.OMEROBrowserDialog._set_load_button_for_converter(dialog)
    assert dialog.load_btn.state == "normal"

    module.OMEROBrowserDialog._select_converter(dialog, "Imaris")
    assert dialog.converter_var.value == "Imaris"


def test_set_converter_options_restores_saved_converter_when_available():
    """Verify saved converter selection is restored after capability detection.

    Inputs: repository fixtures. Output: fails on saved converter selection regressions.
    """
    module = _load_xt_module()

    class DummyDropdown:
        """Dropdown fake for saved converter restoration."""

        def __init__(self):
            """Create option recorder.

            Inputs: none. Output: initializes options.
            """
            self.options = None

        def set_options(self, options):
            """Record options.

            Inputs: `options`. Output: None.
            """
            self.options = list(options)

    class DummyFrame:
        """Frame fake for saved converter restoration."""

        @staticmethod
        def grid():
            """Accept frame show.

            Inputs: none. Output: None.
            """

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_dropdown = DummyDropdown()
    dialog.converter_var = _FakeVar("")
    dialog.converter_frame = DummyFrame()
    dialog.load_btn = _FakeButton()
    dialog.refresh_btn = _FakeButton()
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
    dialog._preferred_converter_setting = ""
    dialog._saved_settings = {module.CONNECTOR_SETTINGS_CONVERTER_KEY: "Imaris"}

    module.OMEROBrowserDialog._set_converter_options(dialog, ["OMERO", "Imaris"])

    assert dialog.converter_var.get() == "Imaris"
    assert dialog._preferred_converter_setting == "Imaris"


def test_set_converter_options_ignores_stale_saved_omero_when_unavailable():
    """Verify stale saved OMERO cannot select an unavailable converter option.

    Inputs: repository fixtures. Output: fails on stale converter restoration regressions.
    """
    module = _load_xt_module()

    class _Dropdown:
        """Dropdown fake for stale converter restoration."""

        def __init__(self):
            """Create option recorder.

            Inputs: none. Output: initializes options.
            """
            self.options = None

        def set_options(self, options):
            """Record options.

            Inputs: `options`. Output: None.
            """
            self.options = list(options)

    class _Frame:
        """Frame fake for converter visibility."""

        @staticmethod
        def grid():
            """Accept frame show.

            Inputs: none. Output: None.
            """

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.converter_dropdown = _Dropdown()
    dialog.converter_var = _FakeVar("")
    dialog.converter_frame = _Frame()
    dialog.load_btn = _FakeButton()
    dialog.refresh_btn = _FakeButton()
    dialog._connected = True
    dialog.client = object()
    dialog.folder_path_var = _FakeVar(r"C:\exports")
    dialog._folder_path_placeholder_visible = False
    dialog._folder_path_write_state = "unchecked"
    dialog._preferred_converter_setting = ""
    dialog._saved_settings = {module.CONNECTOR_SETTINGS_CONVERTER_KEY: "OMERO"}

    module.OMEROBrowserDialog._set_converter_options(dialog, ["Imaris"])

    assert dialog.converter_var.get() == "Imaris"
    assert dialog._preferred_converter_setting == "Imaris"
    assert dialog._available_converter_options == ("Imaris",)


def test_load_rejects_stale_converter_value_not_in_detected_options(tmp_path):
    """Verify load refuses a stale converter value from old settings.

    Inputs: pytest provides `tmp_path`. Output: fails on load-time converter validation regressions.
    """
    module = _load_xt_module()
    warnings = []
    refreshed_options = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._connected = True
    dialog.client = types.SimpleNamespace()
    dialog._refresh_in_progress = False
    dialog.converter_var = types.SimpleNamespace(get=lambda: "OMERO")
    dialog._available_converter_options = ("OMERO",)
    dialog._available_converter_options = ("Imaris",)
    dialog._current_local_folder_path = lambda: str(tmp_path)
    dialog._mark_folder_path_write_state = lambda _path: True
    dialog._selected_images = lambda: [{"id": 1, "name": "image"}]
    dialog._show_warning_dialog = lambda title, message: warnings.append(
        (title, message)
    )
    dialog._show_folder_path_write_error = lambda: (_ for _ in ()).throw(
        AssertionError("path should be valid")
    )
    dialog._set_load_button_for_converter = lambda: None
    dialog._set_converter_options = lambda options: refreshed_options.append(
        list(options)
    )
    dialog._ask_yes_no_dialog = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("confirmation must not run for stale converter")
    )

    module.OMEROBrowserDialog._load(dialog)

    assert warnings == [
        (
            "No Converter",
            "Please connect to OMERO and select an available converter.",
        )
    ]
    assert refreshed_options == [["Imaris"]]


def test_show_converter_frame_uses_reserved_slot_without_resizing_window():
    """Verify converter show does not resize the already-reserved layout.

    Inputs: repository fixtures. Output: fails on converter-slot regressions.
    """
    module = _load_xt_module()

    class _Root:
        """Fake root that exposes a larger requested width after converter show."""

        def __init__(self):
            """Create fake root state.

            Inputs: none. Output: initializes geometry records.
            """
            self.min_size = (module.OMERO_CONNECTOR_WINDOW_WIDTH, 760)
            self.geometry_calls = []

        @staticmethod
        def update_idletasks():
            """Accept idle update.

            Inputs: none. Output: None.
            """

        def minsize(self, *args):
            """Get or set minsize.

            Inputs: optional width and height. Output: current minsize or None.
            """
            if args:
                self.min_size = tuple(args)
                return None
            return self.min_size

        @staticmethod
        def winfo_width():
            """Return current width below requested width.

            Inputs: none. Output: int.
            """
            return 1000

        @staticmethod
        def winfo_height():
            """Return current height.

            Inputs: none. Output: int.
            """
            return 760

        @staticmethod
        def winfo_reqwidth():
            """Return requested width after converter controls become visible.

            Inputs: none. Output: int.
            """
            return 1483

        @staticmethod
        def winfo_reqheight():
            """Return requested height.

            Inputs: none. Output: int.
            """
            return 760

        def geometry(self, value):
            """Record geometry changes.

            Inputs: `value`. Output: None.
            """
            self.geometry_calls.append(value)

    class _Frame:
        """Fake converter frame."""

        def __init__(self):
            """Create grid recorder.

            Inputs: none. Output: initializes state.
            """
            self.grid_calls = 0

        def grid(self):
            """Record grid show.

            Inputs: none. Output: None.
            """
            self.grid_calls += 1

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog.converter_frame = _Frame()

    module.OMEROBrowserDialog._show_converter_frame(dialog)

    assert dialog.converter_frame.grid_calls == 1
    assert dialog.root.min_size == (module.OMERO_CONNECTOR_WINDOW_WIDTH, 760)
    assert dialog.root.geometry_calls == []


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

        def grid(self, **kwargs):
            """Apply grid geometry management.

            Inputs: `**_kwargs`. Output: None.
            """
            self.grid_kwargs = kwargs

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

        def grid(self, **kwargs):
            """Apply grid geometry management.

            Inputs: `**_kwargs`. Output: None.
            """
            self.grid_kwargs = kwargs

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

    class _FakeParent:
        """Parent fake that records listbox grid expansion."""

        def __init__(self):
            """Create fake parent.

            Inputs: none. Output: initializes records.
            """
            self.rows = {}
            self.columns = {}

        def grid_rowconfigure(self, row, **kwargs):
            """Record row configuration.

            Inputs: `row`, `**kwargs`. Output: None.
            """
            self.rows[row] = kwargs

        def grid_columnconfigure(self, column, **kwargs):
            """Record column configuration.

            Inputs: `column`, `**kwargs`. Output: None.
            """
            self.columns[column] = kwargs

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
            NSEW="nsew",
            NS="ns",
            EW="ew",
        ),
    )

    parent = _FakeParent()
    listbox = module.OMEROBrowserDialog._build_scrolled_listbox(parent)

    assert listbox is created["listbox"]
    assert listbox.kwargs["activestyle"] == "none"
    assert parent.rows[0] == {"weight": 1}
    assert parent.columns[0] == {"weight": 1}
    assert listbox.grid_kwargs == {"row": 0, "column": 0, "sticky": "nsew"}


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
    assert dialog.load_btn.state == "disabled"
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


def test_refresh_browser_does_not_repaint_action_buttons(monkeypatch):
    """Verify Refresh does not flicker Load or Export action buttons.

    Inputs: pytest provides `monkeypatch`. Output: fails on action-button flicker regressions.
    """
    module = _load_xt_module()
    threads = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._refresh_in_progress = False
    dialog._refresh_generation = 4
    dialog._connected = True
    dialog.client = object()
    dialog.refresh_btn = _FakeButton()
    dialog.load_btn = _FakeButton()
    dialog.export_btn = _FakeButton()
    dialog._current_selected_project_id = lambda: "project-1"
    dialog._current_selected_dataset_id = lambda: "dataset-1"
    statuses = []
    dialog._set_status = lambda *args, **_kwargs: statuses.append(args)
    dialog._set_connection_indicator = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("refresh start must not repaint the status bar indicator")
    )

    class _FakeThread:
        """Fake refresh thread recorder."""

        def __init__(self, target, args, daemon):
            """Record thread construction.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            threads.append((target, args, daemon))

        @staticmethod
        def start():
            """Do not run the background worker in this unit test.

            Inputs: none. Output: None.
            """

    monkeypatch.setattr(module.threading, "Thread", _FakeThread)

    module.OMEROBrowserDialog._refresh_browser(dialog)

    assert dialog.refresh_btn.configs == [{"state": "disabled"}]
    assert dialog.load_btn.configs == []
    assert dialog.export_btn.configs == []
    assert statuses == [("Refreshing OMERO browser...", "#fff3cd")]
    assert threads == [
        (
            dialog._refresh_worker,
            ("project-1", "dataset-1", 5),
            True,
        )
    ]


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
    dialog._available_converter_options = ("OMERO",)
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
    dialog._available_converter_options = ("Imaris",)
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


def test_load_worker_imaris_converter_exports_selected_image_then_converts_locally(
    tmp_path,
    monkeypatch,
):
    """Verify Imaris converter exports one selected Image ID and converts locally.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in Imaris converter load flow.
    """
    module = _load_xt_module()
    ome_tiff_file = tmp_path / "img_7.ome.tif"
    ome_tiff_file.write_bytes(b"II*\x00selected-image")
    ims_file = tmp_path / "img_7.ims"
    ims_file.write_bytes(b"\x89HDF\r\n\x1a\npayload")
    calls = []
    opened = []
    statuses = []
    info_messages = []

    def _convert_ome_tiff_to_ims(source_file, download_dir, fallback_name):
        """Record local Imaris conversion.

        Inputs: `source_file`, `download_dir`, `fallback_name`. Output: IMS path.
        """
        calls.append(("convert", Path(source_file), Path(download_dir), fallback_name))
        return str(ims_file)

    monkeypatch.setattr(
        module,
        "convert_ome_tiff_to_ims_with_local_imaris",
        _convert_ome_tiff_to_ims,
    )

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_selected_image_ome_tiff=lambda image_id, download_dir, fallback_name: (
            calls.append(("ome-tiff", image_id, Path(download_dir), fallback_name))
            or str(ome_tiff_file)
        ),
        download_original_file=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("archived original download must not run")
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

    assert calls == [
        ("ome-tiff", 7, tmp_path, "img_7.ome.tif"),
        ("convert", ome_tiff_file, tmp_path, "img_7.ims"),
    ]
    assert opened == [(str(ims_file), True)]
    assert dialog.temp_files == [str(ome_tiff_file), str(ims_file)]
    assert not (tmp_path / "img_7").exists()
    assert statuses[-1][0] == "Opened IMS in current Imaris session"
    assert info_messages == [
        ("Success", "IMS file opened in the current Imaris session.")
    ]
    assert all("original" not in status[0].lower() for status in statuses)


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
            calls.append(("ims", image_id, Path(download_dir), fallback_name))
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

    assert calls == [("ims", 8, tmp_path, "img_8.ims")]
    assert opened == [(str(ims_file), True)]
    assert dialog.temp_files == [str(ims_file)]
    assert not (tmp_path / "img_8").exists()


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
        events.append(("download", image_id, Path(download_dir), fallback_name))
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
        ("download", 11, tmp_path, "img_11.ims"),
        ("download", 12, tmp_path, "img_12.ims"),
        ("open", (str(first_ims), str(second_ims)), True),
    ]
    assert dialog.temp_files == [str(first_ims), str(second_ims)]
    assert "after every download completed" in info_messages[0]


def test_load_multiple_worker_imaris_converts_selected_images_before_opening(
    tmp_path,
):
    """Verify multi-image Imaris conversion completes before opening any IMS file.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in multi-image Imaris converter flow.
    """
    module = _load_xt_module()
    first_ims = tmp_path / "first.ims"
    second_ims = tmp_path / "second.ims"
    first_ims.write_bytes(b"\x89HDF\r\n\x1a\nfirst")
    second_ims.write_bytes(b"\x89HDF\r\n\x1a\nsecond")
    files_by_id = {21: str(first_ims), 22: str(second_ims)}
    events = []
    opened = []
    statuses = []
    info_messages = []

    def _download_with_imaris_converter(image_id, image_name, download_dir):
        """Convert one selected image through the local Imaris converter.

        Inputs: `image_id`, `image_name`, `download_dir`. Output: IMS path.
        """
        assert not opened
        events.append(("convert", image_id, image_name, Path(download_dir)))
        return files_by_id[image_id]

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.export_dir = str(tmp_path)
    dialog.temp_files = []
    dialog.client = types.SimpleNamespace(
        download_original_file=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("archived original download must not run")
        ),
        download_ims_export=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("IMS export must not run")
        ),
    )
    dialog._download_selected_image_with_imaris_converter = (
        _download_with_imaris_converter
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
        ("convert", 21, "first.lif", tmp_path),
        ("convert", 22, "second.czi", tmp_path),
    ]
    assert opened == [([str(first_ims), str(second_ims)], True)]
    assert dialog.temp_files == [str(first_ims), str(second_ims)]
    assert statuses[-1][0] == "Opened selected IMS files in current Imaris session"
    assert info_messages[0][0] == "Success"
    assert "opened in Imaris" in info_messages[0][1]


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
    assert "Download/conversion was not started" in errors[0]


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
    tmp_path,
    monkeypatch,
    capsys,
):
    """Verify unsupported platforms block before any GUI or Imaris startup work.

    Inputs: pytest provides `monkeypatch`, `capsys`. Output: fails on startup ordering regressions.
    """
    module = _load_xt_module()
    log_calls = []
    monkeypatch.setenv("HOME", str(tmp_path))
    expected_log_path = str(
        tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME / module.XT_LOG_FILE_NAME
    )
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
            expected_log_path,
            "XTOmeroConnector startup blocked: " + unsupported.message,
        )
    ]


def test_xt_entrypoint_applies_saved_show_log_before_startup_work(
    tmp_path,
    monkeypatch,
):
    """Verify saved Show log state is applied before GUI/startup diagnostics.

    Inputs: pytest provides `tmp_path` and `monkeypatch`. Output: fails on startup Show log ordering regressions.
    """
    module = _load_xt_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    settings_path = module._connector_settings_env_path(tmp_path)
    settings_path.parent.mkdir()
    settings_path.write_text(
        "\n".join(
            [
                f'{module.CONNECTOR_SETTINGS_VERSION_KEY}="{module.CONNECTOR_INFO_VERSION}"',
                f'{module.CONNECTOR_SETTINGS_SHOW_LOG_KEY}="false"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    supported = module._WindowsPlatformStatus(
        supported=True,
        message="OMERO Connector running on supported Windows 10.0.22631 via test.",
    )
    events = []

    class _FakeDialog:
        """Fake browser dialog for entrypoint ordering."""

        def __init__(self, *_args, **_kwargs):
            """Record dialog construction.

            Inputs: ignored. Output: None.
            """
            events.append(("dialog", None))

        @staticmethod
        def show():
            """Record dialog show.

            Inputs: none. Output: None.
            """
            events.append(("show", None))

    monkeypatch.setattr(module, "_windows_platform_status", lambda: supported)
    monkeypatch.setattr(
        module,
        "_configure_xt_console_visibility",
        lambda enabled: events.append(("visibility", enabled)),
    )
    monkeypatch.setattr(
        module,
        "_set_process_window_title",
        lambda title: events.append(("title", title)) or True,
    )
    monkeypatch.setattr(
        module,
        "_xt_write_log",
        lambda _path, message: events.append(("log", message)),
    )
    monkeypatch.setattr(
        module,
        "_ensure_tk_loaded",
        lambda: events.append(("tk", None)),
    )
    monkeypatch.setattr(
        module,
        "_log_imaris_xt_diagnostics",
        lambda: events.append(("diagnostics", None)),
    )
    monkeypatch.setattr(
        module, "_resolve_imaris_application", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(module, "OMEROBrowserDialog", _FakeDialog)

    module.XTOmeroConnector(None)

    assert events[:2] == [("visibility", False), ("title", "OMERO Connector")]
    assert ("tk", None) in events
    assert ("dialog", None) in events
    assert ("show", None) in events


def test_xt_entrypoint_resolves_direct_imaris_handle_when_optional_bridge_disabled(
    tmp_path,
    monkeypatch,
):
    """Verify normal Imaris-launched handle resolution is independent of IcePy probing.

    Inputs: pytest provides `tmp_path` and `monkeypatch`. Output: fails on startup bridge regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)
    supported = module._WindowsPlatformStatus(
        supported=True,
        message="OMERO Connector running on supported Windows 10.0.22631 via test.",
    )
    resolved_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)
    captured = {}

    class _FakeImarisLibFactory:
        """Fake ImarisLib factory for entrypoint handle resolution."""

        @staticmethod
        def GetApplication(app_id):
            """Return the fake current Imaris application.

            Inputs: `app_id`. Output: `resolved_handle`.
            """
            assert app_id == 17
            return resolved_handle

    class _FakeDialog:
        """Fake browser dialog capturing constructor arguments."""

        def __init__(self, imaris, imaris_id=None):
            """Capture the Imaris handle and id passed to the dialog.

            Inputs: `imaris`, `imaris_id`. Output: None.
            """
            captured["imaris"] = imaris
            captured["imaris_id"] = imaris_id

        @staticmethod
        def show():
            """Do not open Tk during this entrypoint contract test.

            Inputs: none. Output: None.
            """

    monkeypatch.setitem(
        sys.modules,
        "ImarisLib",
        types.SimpleNamespace(ImarisLib=_FakeImarisLibFactory),
    )
    monkeypatch.setattr(module, "_windows_platform_status", lambda: supported)
    monkeypatch.setattr(module, "_xt_log_path", lambda: str(tmp_path / "xt.log"))
    monkeypatch.setattr(module, "_install_xt_console_interrupt_guard", lambda: None)
    monkeypatch.setattr(module, "_restore_xt_console_interrupt_guard", _noop)
    monkeypatch.setattr(
        module, "_connector_settings_env_path", lambda: tmp_path / "settings.env"
    )
    monkeypatch.setattr(
        module, "_prepare_connector_settings_for_current_version", _noop
    )
    monkeypatch.setattr(
        module, "_load_connector_show_log_preference", lambda _path: True
    )
    monkeypatch.setattr(module, "_configure_xt_console_visibility", _noop)
    monkeypatch.setattr(module, "_set_process_window_title", _noop)
    monkeypatch.setattr(module, "_xt_write_log", _noop)
    monkeypatch.setattr(module, "_ensure_tk_loaded", _noop)
    monkeypatch.setattr(module, "_log_imaris_xt_diagnostics", _noop)
    monkeypatch.setattr(
        module,
        "_prepare_imaris_xt_environment",
        lambda: {"paths": [], "dll_dirs": []},
    )
    monkeypatch.setattr(module, "OMEROBrowserDialog", _FakeDialog)

    module.XTOmeroConnector("17")

    assert module._native_imaris_bridge_enabled() is False
    assert captured == {"imaris": resolved_handle, "imaris_id": "17"}


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


def test_xt_write_log_uses_settings_directory_and_rejects_unsafe_paths(
    tmp_path,
    monkeypatch,
):
    """Verify XT write log stays in the connector settings directory.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on unsafe log path regressions.
    """
    module = _load_xt_module()
    monkeypatch.setenv("HOME", str(tmp_path))

    log_path = Path(module._xt_log_path())
    settings_dir = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME
    assert log_path == settings_dir / module.XT_LOG_FILE_NAME

    module._xt_write_log(str(log_path), "first line")
    assert log_path.read_text(encoding="utf-8") == "first line\n"
    assert settings_dir.exists()

    outside_path = tmp_path / module.XT_LOG_FILE_NAME
    module._xt_write_log(str(outside_path), "outside")
    assert not outside_path.exists()

    wrong_name = settings_dir / "unrelated.log"
    module._xt_write_log(str(wrong_name), "wrong name")
    assert not wrong_name.exists()

    log_path.unlink()
    symlink_path = settings_dir / module.XT_LOG_FILE_NAME
    symlink_target = tmp_path.parent / "connector-link-target.log"
    symlink_path.symlink_to(symlink_target)
    module._xt_write_log(str(symlink_path), "through symlink")
    assert not symlink_target.exists()


def test_xt_console_log_mirrors_command_window_output_to_settings_log(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Verify visible command-window output is mirrored to the rolling settings log.

    Inputs: pytest provides `tmp_path`, `monkeypatch`, and `capsys`. Output: fails on console/log mirroring regressions.
    """
    module = _load_xt_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    module._XT_RUNTIME_STATE.log_path = None

    module._xt_console_log("visible connector message")

    captured = capsys.readouterr()
    log_path = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME / module.XT_LOG_FILE_NAME
    assert "visible connector message" in captured.out
    assert module._XT_RUNTIME_STATE.log_path == str(log_path)
    assert "visible connector message" in log_path.read_text(encoding="utf-8")

    monkeypatch.setattr(builtins, "input", lambda: "")
    module._xt_wait_for_enter_to_close()
    captured = capsys.readouterr()
    log_text = log_path.read_text(encoding="utf-8")
    assert "Press ENTER to close..." in captured.out
    assert "Press ENTER to close..." in log_text


def test_xt_console_log_hidden_mode_writes_file_without_stdout(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Verify hidden command-window mode still writes the rolling log.

    Inputs: pytest provides `tmp_path`, `monkeypatch`, and `capsys`. Output: fails on Show log suppression regressions.
    """
    module = _load_xt_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    module._XT_RUNTIME_STATE.log_path = None
    module._XT_RUNTIME_STATE.console_output_enabled = False

    module._xt_console_log("hidden connector message")

    captured = capsys.readouterr()
    log_path = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME / module.XT_LOG_FILE_NAME
    assert "hidden connector message" not in captured.out
    assert module._XT_RUNTIME_STATE.log_path == str(log_path)
    assert "hidden connector message" in log_path.read_text(encoding="utf-8")


def test_configure_xt_console_visibility_uses_windows_show_window(monkeypatch):
    """Verify Show log uses the Windows console API without shelling out.

    Inputs: pytest provides `monkeypatch`. Output: fails on Windows console visibility regressions.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)

    class _FakeKernel32:
        """Fake kernel32 console lookup."""

        @staticmethod
        def GetConsoleWindow():
            """Return fake console handle.

            Inputs: none. Output: int handle.
            """
            return 1234

    class _FakeUser32:
        """Fake user32 visibility API."""

        calls = []

        @classmethod
        def ShowWindow(cls, handle, command):
            """Record ShowWindow calls.

            Inputs: `handle`, `command`. Output: int success.
            """
            cls.calls.append((handle, command))
            return 1

    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=_FakeKernel32, user32=_FakeUser32)
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert module._configure_xt_console_visibility(False) is True
    assert module._XT_RUNTIME_STATE.console_output_enabled is False
    assert module._configure_xt_console_visibility(True) is True
    assert module._XT_RUNTIME_STATE.console_output_enabled is True
    assert _FakeUser32.calls == [(1234, 0), (1234, 5)]


def test_xt_console_interrupt_guard_installs_and_restores_handlers(monkeypatch):
    """Verify command-window Ctrl+C is scoped and cannot abort the connector.

    Inputs: pytest provides `monkeypatch`. Output: fails on console interrupt
    guard regressions.
    """
    module = _load_xt_module()
    events = []
    handlers = {module.signal.SIGINT: "old-int", 98: "old-break"}
    monkeypatch.setattr(module.signal, "SIGBREAK", 98, raising=False)
    monkeypatch.setattr(module.signal, "getsignal", lambda signum: handlers[signum])

    def signal_handler(signum, handler):
        """Record signal handler updates.

        Inputs: `signum`, `handler`. Output: None.
        """
        events.append((signum, handler))
        handlers[signum] = handler

    monkeypatch.setattr(module.signal, "signal", signal_handler)

    previous = module._install_xt_console_interrupt_guard()
    assert previous == [(module.signal.SIGINT, "old-int"), (98, "old-break")]
    assert handlers[module.signal.SIGINT] == module._ignore_xt_console_interrupt
    assert handlers[98] == module._ignore_xt_console_interrupt

    module._restore_xt_console_interrupt_guard(previous)

    assert events[-2:] == [(98, "old-break"), (module.signal.SIGINT, "old-int")]
    assert handlers[module.signal.SIGINT] == "old-int"
    assert handlers[98] == "old-break"


def test_xt_entrypoint_restores_console_interrupt_guard_after_ctrl_c(monkeypatch):
    """Verify entrypoint cleanup runs when Ctrl+C escapes fallback handling.

    Inputs: pytest provides `monkeypatch`. Output: fails on Ctrl+C cleanup regressions.
    """
    module = _load_xt_module()
    events = []

    class _Status:
        """Supported Windows platform fake."""

        supported = True
        message = "supported"

    class _Dialog:
        """Dialog fake that simulates Ctrl+C escaping Tk."""

        def __init__(self, *_args, **_kwargs):
            """Record dialog construction.

            Inputs: ignored. Output: None.
            """
            events.append("dialog")

        @staticmethod
        def show():
            """Simulate Ctrl+C during the blocking dialog loop.

            Inputs: none. Output: raises KeyboardInterrupt.
            """
            raise KeyboardInterrupt

    monkeypatch.setattr(module, "_windows_platform_status", lambda: _Status())
    monkeypatch.setattr(module, "_xt_log_path", lambda: "xt.log")
    monkeypatch.setattr(module, "_install_xt_console_interrupt_guard", lambda: "guard")
    monkeypatch.setattr(
        module,
        "_restore_xt_console_interrupt_guard",
        lambda guard: events.append(("restore", guard)),
    )
    monkeypatch.setattr(module, "_connector_settings_env_path", lambda: "settings.env")
    monkeypatch.setattr(
        module, "_prepare_connector_settings_for_current_version", _noop
    )
    monkeypatch.setattr(
        module, "_load_connector_show_log_preference", lambda _path: True
    )
    monkeypatch.setattr(module, "_configure_xt_console_visibility", _noop)
    monkeypatch.setattr(module, "_set_process_window_title", _noop)
    monkeypatch.setattr(module, "_xt_write_log", lambda *_args: events.append("write"))
    monkeypatch.setattr(
        module,
        "_xt_console_log",
        lambda *_args, **_kwargs: events.append("console"),
    )
    monkeypatch.setattr(module, "_ensure_tk_loaded", _noop)
    monkeypatch.setattr(module, "_log_imaris_xt_diagnostics", _noop)
    monkeypatch.setattr(
        module,
        "_resolve_imaris_application",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(module, "OMEROBrowserDialog", _Dialog)

    module.XTOmeroConnector(None)

    assert "dialog" in events
    assert ("restore", "guard") in events
    assert "console" in events


def test_xt_console_output_is_centralized_for_file_mirroring():
    """Verify direct command-window prints stay centralized through `_xt_console_log`.

    Inputs: repository source text. Output: raw print call locations that would bypass log mirroring.
    """
    source = Path(_XT_SCRIPT).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []

    class _PrintVisitor(ast.NodeVisitor):
        """Collect print calls outside the XT console/log mirror helper."""

        def __init__(self):
            """Create `_PrintVisitor`.

            Inputs: none. Output: None.
            """
            self.function_stack = []

        def visit_FunctionDef(self, node):
            """Visit a function definition.

            Inputs: `node`. Output: None.
            """
            self.function_stack.append(node.name)
            self.generic_visit(node)
            self.function_stack.pop()

        def visit_Call(self, node):
            """Visit a call expression.

            Inputs: `node`. Output: None.
            """
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "print"
                and self.function_stack[-1:] != ["_xt_console_log"]
            ):
                offenders.append(node.lineno)
            self.generic_visit(node)

    _PrintVisitor().visit(tree)

    assert offenders == []


def test_xt_debug_initializes_settings_directory_log_and_rotates(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Verify XT debug writes a bounded rolling log beside settings.env.

    Inputs: pytest provides `tmp_path`, `monkeypatch`, and `capsys`. Output: fails on rolling log regressions.
    """
    module = _load_xt_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(module, "XT_LOG_MAX_BYTES", 64)
    monkeypatch.setattr(module, "XT_LOG_BACKUP_COUNT", 2)
    module._XT_RUNTIME_STATE.log_path = None

    module._xt_debug("a" * 20)
    capsys.readouterr()
    log_path = tmp_path / module.AUTOSAVE_SETTINGS_DIR_NAME / module.XT_LOG_FILE_NAME
    assert module._XT_RUNTIME_STATE.log_path == str(log_path)
    assert log_path.exists()

    module._xt_write_log(str(log_path), "b" * 50)
    module._xt_write_log(str(log_path), "c" * 50)

    current = log_path.read_text(encoding="utf-8")
    first_backup = log_path.with_name(f"{log_path.name}.1").read_text(encoding="utf-8")
    second_backup = log_path.with_name(f"{log_path.name}.2").read_text(encoding="utf-8")
    assert "c" * 50 in current
    assert "b" * 50 in first_backup
    assert "a" * 20 in second_backup
    assert not log_path.with_name(f"{log_path.name}.3").exists()


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
    assert dialog.root.geometry_value == "1180x760"
    assert dialog.root.minimum_size == (1180, 760)
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


def test_health_ping_schedules_periodic_check_only_when_connected(monkeypatch):
    """Verify connected dialogs schedule silent periodic OMERO health checks.

    Inputs: pytest provides `monkeypatch`. Output: fails on health timer regressions.
    """
    module = _load_xt_module()
    scheduled = []

    class _Root:
        """Root fake that records scheduled callbacks."""

        @staticmethod
        def after(delay, callback):
            """Record delayed callback registration.

            Inputs: `delay`, `callback`. Output: timer id.
            """
            scheduled.append((delay, callback))
            return "timer-1"

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog._connected = True
    dialog.client = object()
    dialog._health_ping_after_id = None

    dialog._start_health_ping = _noop
    monkeypatch.setattr(module, "_health_ping_interval_seconds", lambda: 17)

    module.OMEROBrowserDialog._schedule_health_ping(dialog)

    assert dialog._health_ping_after_id == "timer-1"
    assert scheduled == [(17000, dialog._start_health_ping)]

    scheduled.clear()
    dialog._connected = False
    dialog._health_ping_after_id = None
    module.OMEROBrowserDialog._schedule_health_ping(dialog)
    assert scheduled == []


def test_health_ping_start_resets_background_cursor(monkeypatch):
    """Verify silent health checks do not leave a busy cursor on free window space.

    Inputs: pytest provides `monkeypatch`. Output: fails on background cursor regressions.
    """
    module = _load_xt_module()
    cursor_updates = []
    thread_starts = []

    class _Root:
        """Root fake that records cursor updates."""

        @staticmethod
        def configure(**kwargs):
            """Record configure calls.

            Inputs: keyword options. Output: None.
            """
            cursor_updates.append(kwargs)

        config = configure

    class _Thread:
        """Thread fake that records starts without running work."""

        def __init__(self, target, args, daemon):
            """Create thread fake.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            """Record thread start.

            Inputs: none. Output: None.
            """
            thread_starts.append((self.target, self.args, self.daemon))

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog._connected = True
    dialog.client = object()
    dialog._health_ping_after_id = None
    dialog._health_ping_in_progress = False
    dialog._health_ping_generation = 0
    dialog._load_in_progress = False
    dialog._folder_export_in_progress = False
    dialog._connection_in_progress = False
    dialog._browser_sash_drag_index = None
    dialog._modal_background_lock_depth = 0
    monkeypatch.setattr(module.threading, "Thread", _Thread)

    module.OMEROBrowserDialog._start_health_ping(dialog)

    assert cursor_updates == [{"cursor": ""}]
    assert thread_starts == [(dialog._health_ping_worker, (1,), True)]


def test_status_update_does_not_force_idle_redraw():
    """Verify status text changes are scheduled without synchronous redraw.

    Inputs: repository fixtures. Output: asserts background status updates avoid
    Tk idle flushes that can surface as busy cursors.
    """
    module = _load_xt_module()
    configs = []

    class _Root:
        """Root fake that executes scheduled callbacks immediately."""

        @staticmethod
        def after(_delay, callback):
            """Run the scheduled callback.

            Inputs: `_delay`, `callback`. Output: callback result.
            """
            return callback()

        @staticmethod
        def update_idletasks():
            """Reject forced idle redraws from status updates.

            Inputs: none. Output: none. Raises: AssertionError.
            """
            raise AssertionError("status update must not force idle redraw")

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog.status = types.SimpleNamespace(
        config=lambda **kwargs: configs.append(kwargs)
    )

    module.OMEROBrowserDialog._set_status(dialog, "Ready", "#d4edda")

    assert configs == [{"text": "Ready", "bg": "#d4edda"}]


def test_connect_button_update_does_not_force_idle_redraw():
    """Verify connect-button state changes avoid synchronous Tk redraws.

    Inputs: repository fixtures. Output: asserts button state changes avoid Tk
    idle flushes from non-layout code.
    """
    module = _load_xt_module()
    configs = []

    class _Root:
        """Root fake that rejects idle redraw calls."""

        @staticmethod
        def update_idletasks():
            """Reject forced idle redraws.

            Inputs: none. Output: none. Raises: AssertionError.
            """
            raise AssertionError("connect button update must not force idle redraw")

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.root = _Root()
    dialog.connect_btn = types.SimpleNamespace(
        config=lambda **kwargs: configs.append(kwargs)
    )

    module.OMEROBrowserDialog._set_connect_button(
        dialog,
        "Connect",
        "normal",
        "#3498db",
        "#2f85c7",
    )

    assert configs == [
        {
            "text": "Connect",
            "state": "normal",
            "bg": "#3498db",
            "activebackground": "#2f85c7",
            "fg": "white",
            "activeforeground": "white",
        }
    ]


def test_native_bridge_probe_worker_resets_background_cursor(monkeypatch):
    """Verify native bridge probes cannot leave a busy cursor behind.

    Inputs: pytest provides `monkeypatch`. Output: asserts probe completion runs
    the UI-thread cursor reset.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
    resets = []
    ui_calls = []

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.imaris = None
    dialog.imaris_id = None
    dialog._native_bridge_probe_lock = module.threading.Lock()
    dialog._native_bridge_probe_done = module.threading.Event()
    dialog._native_bridge_python_executable = "stale-python"
    dialog._native_bridge_available = True
    dialog._native_bridge_probe_error = ""
    dialog._native_bridge_last_verified_at = 1.0
    dialog._native_bridge_probe_in_progress = True
    dialog._invoke_on_ui_thread = lambda callback, wait=False: (
        ui_calls.append(wait) or callback()
    )
    dialog._reset_background_cursor_after_silent_work = lambda: resets.append("reset")

    module.OMEROBrowserDialog._native_bridge_probe_worker(dialog)

    assert dialog._native_bridge_probe_done.is_set()
    assert dialog._native_bridge_python_executable is None
    assert dialog._native_bridge_available is False
    assert dialog._native_bridge_last_verified_at == 0.0
    assert ui_calls == [False]
    assert resets == ["reset"]


def test_health_ping_worker_retries_before_reporting_failure(monkeypatch):
    """Verify transient health failures are retried before UI failure handling.

    Inputs: pytest provides `monkeypatch`. Output: fails on health retry regressions.
    """
    module = _load_xt_module()

    class _Client:
        """Client fake that fails twice, then answers."""

        def __init__(self):
            """Create client fake.

            Inputs: none. Output: initializes call counter.
            """
            self.calls = 0

        def ping(self, timeout):
            """Fail twice before succeeding.

            Inputs: `timeout`. Output: bool. Raises: TimeoutError.
            """
            assert timeout == 4
            self.calls += 1
            if self.calls < 3:
                raise TimeoutError("temporary outage")
            return True

    finishes = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.client = _Client()
    dialog._health_ping_generation = 9

    def _invoke_on_ui_thread(callback, wait=False):
        """Run callback immediately.

        Inputs: `callback`, `wait`. Output: callback result.
        """
        return callback()

    def _finish_health_ping(generation, error):
        """Record health ping completion.

        Inputs: `generation`, `error`. Output: None.
        """
        finishes.append((generation, error))

    dialog._invoke_on_ui_thread = _invoke_on_ui_thread
    dialog._finish_health_ping = _finish_health_ping
    monkeypatch.setattr(module, "_health_ping_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_health_ping_retry_delay_seconds", lambda: 0)
    monkeypatch.setattr(module, "_health_ping_timeout_seconds", lambda: 4)

    module.OMEROBrowserDialog._health_ping_worker(dialog, 9)

    assert dialog.client.calls == 3
    assert finishes == [(9, None)]


def test_health_ping_worker_reports_last_error_after_retry_exhaustion(monkeypatch):
    """Verify exhausted health retries report the final ping error.

    Inputs: pytest provides `monkeypatch`. Output: fails on retry exhaustion bugs.
    """
    module = _load_xt_module()

    class _Client:
        """Client fake that always times out."""

        def __init__(self):
            """Create client fake.

            Inputs: none. Output: initializes state.
            """
            self.calls = 0

        def ping(self, timeout):
            """Raise a timeout for every health check attempt.

            Inputs: `timeout`. Output: none. Raises: TimeoutError.
            """
            assert timeout == 4
            self.calls += 1
            raise TimeoutError(f"outage-{self.calls}")

    finishes = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.client = _Client()
    dialog._health_ping_generation = 9
    dialog._invoke_on_ui_thread = lambda callback, wait=False: callback()
    dialog._finish_health_ping = lambda generation, error: finishes.append(
        (generation, error)
    )
    monkeypatch.setattr(module, "_health_ping_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_health_ping_retry_delay_seconds", lambda: 0)
    monkeypatch.setattr(module, "_health_ping_timeout_seconds", lambda: 4)

    module.OMEROBrowserDialog._health_ping_worker(dialog, 9)

    assert dialog.client.calls == 3
    assert len(finishes) == 1
    assert finishes[0][0] == 9
    assert isinstance(finishes[0][1], TimeoutError)
    assert str(finishes[0][1]) == "outage-3"


def test_health_ping_worker_stops_when_generation_changes(monkeypatch):
    """Verify stale health workers do not report after disconnect cancellation.

    Inputs: pytest provides `monkeypatch`. Output: fails on stale worker bugs.
    """
    module = _load_xt_module()

    class _Client:
        """Client fake that simulates disconnect during a ping."""

        def __init__(self, dialog):
            """Create client fake.

            Inputs: `dialog`. Output: initializes state.
            """
            self.dialog = dialog
            self.calls = 0

        def ping(self, timeout):
            """Invalidate the health generation and raise.

            Inputs: `timeout`. Output: none. Raises: TimeoutError.
            """
            assert timeout == 4
            self.calls += 1
            self.dialog._health_ping_generation += 1
            raise TimeoutError("stale worker")

    finishes = []
    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog._health_ping_generation = 9
    dialog.client = _Client(dialog)
    dialog._invoke_on_ui_thread = lambda callback, wait=False: finishes.append(
        callback()
    )
    monkeypatch.setattr(module, "_health_ping_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_health_ping_retry_delay_seconds", lambda: 0)
    monkeypatch.setattr(module, "_health_ping_timeout_seconds", lambda: 4)

    module.OMEROBrowserDialog._health_ping_worker(dialog, 9)

    assert dialog.client.calls == 1
    assert finishes == []


def test_health_ping_failure_returns_interface_to_connect_ready(monkeypatch):
    """Verify repeated health-check failures reset the UI to connect-ready state.

    Inputs: pytest provides `monkeypatch`. Output: fails on health failure regressions.
    """
    module = _load_xt_module()
    disconnect_calls = []
    errors = []
    logs = []
    dialog = object.__new__(module.OMEROBrowserDialog)

    def _disconnect(**kwargs):
        """Record disconnect arguments.

        Inputs: `**kwargs`. Output: None.
        """
        disconnect_calls.append(kwargs)

    dialog._disconnect = _disconnect
    monkeypatch.setattr(module, "_xt_debug", logs.append)
    monkeypatch.setattr(
        module.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
        raising=False,
    )

    module.OMEROBrowserDialog._handle_health_ping_failure(dialog, TimeoutError())

    clear_password_key = "clear_" + "password"
    assert disconnect_calls == [
        {
            "status_text": "Connection lost - Ready to connect",
            "status_color": "#f8d7da",
            clear_password_key: False,
        }
    ]
    assert errors == [
        (
            "Connection Lost",
            "The OMERO connection was lost. Please reconnect to continue.",
        )
    ]
    assert logs == ["Read-only OMERO health check failed after retries: TimeoutError"]


def test_disconnect_preserves_password_only_when_requested():
    """Verify lost-connection reset can preserve typed credentials in memory only.

    Inputs: repository fixtures. Output: fails on disconnect-state regressions.
    """
    module = _load_xt_module()

    class _CookieJar:
        """Cookie-jar fake that supports clearing."""

        @staticmethod
        def clear():
            """Clear fake cookie jar.

            Inputs: none. Output: None.
            """

    dialog = object.__new__(module.OMEROBrowserDialog)
    dialog.client = types.SimpleNamespace(
        cookie_jar=_CookieJar(),
        password="secret",
        csrf_token="csrf",
        session_id="session",
        session_key="key",
    )
    dialog._connected = True
    dialog._pid = "project"
    dialog._did = "dataset"
    dialog._refresh_generation = 3
    dialog._refresh_in_progress = True
    dialog.projects_data = [{"id": "project"}]
    dialog.datasets_data = [{"id": "dataset"}]
    dialog.images_data = [{"id": "image"}]
    dialog._image_selection_anchor = 0
    dialog.plist = _FakeListbox(["project"], selection={0})
    dialog.dlist = _FakeListbox(["dataset"], selection={0})
    dialog.ilist = _FakeListbox(["image"], selection={0})
    dialog.pass_entry = _FakeEntry("typed-password")
    calls = {
        "cancel": 0,
        "converters": [],
        "connect": [],
        "autosave": [],
        "status": [],
        "indicator": [],
        "folder_export": [],
    }

    def _cancel_health_ping():
        """Record health cancellation.

        Inputs: none. Output: None.
        """
        calls["cancel"] += 1

    def _set_folder_export_capability(available, reason=""):
        """Record folder-export capability state.

        Inputs: `available`, `reason`. Output: None.
        """
        calls["folder_export"].append((available, reason))

    def _set_converter_options(options):
        """Record converter options.

        Inputs: `options`. Output: None.
        """
        calls["converters"].append(list(options))

    def _set_connect_button(*args, **kwargs):
        """Record connect button state.

        Inputs: `*args`, `**kwargs`. Output: None.
        """
        calls["connect"].append((args, kwargs))

    def _set_autosave_settings_control_state(enabled):
        """Record autosave control state.

        Inputs: `enabled`. Output: None.
        """
        calls["autosave"].append(enabled)

    def _set_status(text, color=module.STATUS_NEUTRAL_BG):
        """Record status text.

        Inputs: `text`, `color`. Output: None.
        """
        calls["status"].append((text, color))

    def _set_connection_indicator(state):
        """Record connection indicator state.

        Inputs: `state`. Output: None.
        """
        calls["indicator"].append(state)

    dialog._cancel_health_ping = _cancel_health_ping
    dialog._set_folder_export_capability = _set_folder_export_capability
    dialog._set_converter_options = _set_converter_options
    dialog._set_connect_button = _set_connect_button
    dialog._set_autosave_settings_control_state = _set_autosave_settings_control_state
    dialog._set_status = _set_status
    dialog._set_connection_indicator = _set_connection_indicator

    module.OMEROBrowserDialog._disconnect(
        dialog,
        status_text="Connection lost - Ready to connect",
        status_color="#f8d7da",
        clear_password=False,
    )

    assert dialog.client is None
    assert dialog._connected is False
    assert dialog.pass_entry.value == "typed-password"
    assert dialog.projects_data == []
    assert dialog.datasets_data == []
    assert dialog.images_data == []
    assert calls["cancel"] == 1
    assert calls["converters"] == [[]]
    assert calls["autosave"] == [False]
    assert calls["status"] == [("Connection lost - Ready to connect", "#f8d7da")]
    assert calls["indicator"] == ["disconnected"]
    assert calls["folder_export"] == [(False, "Connect to OMERO first.")]

    dialog.pass_entry.value = "typed-password"
    dialog.client = None
    module.OMEROBrowserDialog._disconnect(dialog)
    assert dialog.pass_entry.value == ""


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


def test_collect_imaris_xt_diagnostics_skips_unloaded_native_bridge_imports(
    monkeypatch,
):
    """Verify diagnostics do not import unloaded native bridge modules.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions that load
    Bitplane's native IcePy stack during diagnostics.
    """
    module = _load_xt_module()
    _enable_native_bridge(module, monkeypatch)
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

    def _guarded_import(name, *args, **kwargs):
        """Reject unsafe native bridge imports during diagnostics.

        Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: `original_import` result. Raises: AssertionError for native imports.
        """
        if name in {"ImarisLib", "IcePy"}:
            raise AssertionError("diagnostics must not import native bridge modules")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

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
    assert "in-process import skipped" in diagnostics["imarislib_import"]["error"]
    assert diagnostics["icepy_import"]["ok"] is False
    assert "in-process import skipped" in diagnostics["icepy_import"]["error"]


def test_no_imaris_install_detection_is_non_blocking_when_absent(monkeypatch):
    """Verify missing Imaris is a non-blocking detection result.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions that make
    ordinary non-Imaris test hosts hang or fail during local capability detection.
    """
    module = _load_xt_module()
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.delenv("IMARIS_EXE", raising=False)
    monkeypatch.delenv("IMARIS_HOME", raising=False)
    monkeypatch.delenv("IMARIS_CONVERT_EXE", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(
        module,
        "_iter_imaris_registry_executable_candidates",
        lambda _winreg: iter(()),
    )
    monkeypatch.setattr(
        module,
        "_iter_imaris_vendor_executable_candidates",
        lambda: iter(()),
    )

    assert module._find_imaris_executable() is None
    assert list(module._iter_imaris_install_roots()) == []
    assert module._find_imaris_convert_executable() is None


def test_live_imaris_install_detection_is_mandatory_when_present(monkeypatch):
    """Verify a host Imaris install is detected without native bridge imports.

    Inputs: pytest provides `monkeypatch`. Output: skips when no supported Imaris
    exists, otherwise fails on local install detection regressions.
    """
    module = _load_xt_module()
    monkeypatch.delenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, raising=False)

    imaris_executable = _require_live_imaris_install(module)
    executable_path = Path(imaris_executable)
    install_root = executable_path.parent
    install_root_key = module.os.path.normcase(
        module.os.path.normpath(str(install_root))
    )
    detected_roots = {
        module.os.path.normcase(module.os.path.normpath(str(root)))
        for root in module._iter_imaris_install_roots()
    }

    assert executable_path.is_file()
    assert executable_path.name.lower() == "imaris.exe"
    assert module._is_supported_imaris_install_path(imaris_executable)
    assert install_root_key in detected_roots

    diagnostics = module._collect_imaris_xt_diagnostics()
    assert diagnostics["imaris_executable_exists"] is True
    assert module.os.path.normcase(
        module.os.path.normpath(diagnostics["imaris_executable"])
    ) == (module.os.path.normcase(module.os.path.normpath(imaris_executable)))
    assert diagnostics["native_bridge_enabled"] is False
    assert diagnostics["imarislib_import"] == {"ok": False, "error": ""}
    assert diagnostics["icepy_import"] == {"ok": False, "error": ""}


def test_live_imaris_converter_detection_is_mandatory_when_imaris_present():
    """Verify Imaris converter executable discovery on hosts with Imaris.

    Inputs: repository and host fixtures. Output: skips when no supported Imaris
    exists, otherwise fails if the local Imaris conversion executable is missing.
    """
    module = _load_xt_module()
    _require_live_imaris_install(module)

    converter_executable = module._find_imaris_convert_executable()

    assert converter_executable, "Imaris is installed but ImarisConvert was not found."
    converter_path = Path(converter_executable)
    assert converter_path.is_file()
    assert converter_path.name.lower() in {"imarisconvert.exe", "imarisconvert"}


def test_resolve_imaris_application_returns_direct_handle():
    """Verify resolve imaris application returns direct handle result shape.

    Inputs: repository fixtures. Output: fails on regressions in resolve imaris application returns direct handle.
    """
    module = _load_xt_module()
    direct_handle = types.SimpleNamespace(FileOpen=lambda *_args: None)

    assert module._resolve_imaris_application(direct_handle) is direct_handle
