"""Connector failure contracts; native Imaris qualification remains a separate gate."""

from __future__ import annotations

import ctypes
import builtins
import contextlib
from email.message import Message
import importlib.util
import math
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("operation", ["folder", "settings"])
def test_pathlike_input_is_normalized_once_before_filesystem_mutation(
    xt, tmp_path, operation
):
    """Inputs: path protocol whose later reads change identity. Output: one normalization, operations only on the validated path and no leftover write probe."""
    target = tmp_path / "uploads"
    target.mkdir()
    if operation == "settings":
        target = xt._connector_settings_env_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture settings")

    class ChangingPath:
        """A path provider that must not be reevaluated after validation."""

        def __init__(self):
            """Inputs: none. Output: an unread path provider."""
            self.reads = 0

        def __fspath__(self):
            """Inputs: path conversion. Output: validated target once, invalid path on a second read."""
            self.reads += 1
            return str(target) if self.reads == 1 else "\x00"

    supplied = ChangingPath()
    if operation == "folder":
        assert xt._folder_path_write_error(supplied) == ""
        assert list(target.iterdir()) == []
    else:
        xt._rotate_connector_settings_backups(supplied)
        assert not target.exists()
        assert (
            xt._connector_settings_backup_path(target, 1).read_bytes()
            == b"fixture settings"
        )
    assert supplied.reads == 1


@pytest.mark.parametrize(
    "value,expected", [("0", 1), ("-100", 1), ("999", 10), ("invalid", None)]
)
def test_http_retry_count_always_permits_a_bounded_first_attempt(
    xt, monkeypatch, value, expected
):
    """Inputs: invalid or excessive configured retry count. Output: bounded nonempty attempt range, never zero attempts or an unbounded loop."""
    monkeypatch.setenv(xt.HTTP_TRANSIENT_RETRY_ATTEMPTS_ENV, value)
    actual = xt._http_retry_attempts()
    assert actual == (
        xt.DEFAULT_HTTP_TRANSIENT_RETRY_ATTEMPTS if expected is None else expected
    )
    assert 1 <= actual <= 10


@pytest.mark.parametrize(
    "visible,input_failure", [(False, False), (True, False), (True, True)]
)
def test_standalone_entrypoint_contains_fatal_startup_and_closed_console_input(
    xt, monkeypatch, capsys, visible, input_failure
):
    """Inputs: fatal startup before the normal UI error boundary. Output: visible failure only when configured, with no escaped EOF or second launch."""
    xt._XT_RUNTIME_STATE.console_output_enabled = visible
    launch = Mock(side_effect=RuntimeError("fixture-startup-failure"))
    prompt = Mock(
        side_effect=EOFError("fixture input closed") if input_failure else None,
        return_value="",
    )
    monkeypatch.setattr(xt, "XTOmeroConnector", launch)
    monkeypatch.setattr(builtins, "input", prompt)
    xt.main()
    launch.assert_called_once_with(None)
    assert prompt.call_count == int(visible)
    output = capsys.readouterr().out
    assert ("Fatal: fixture-startup-failure" in output) is visible
    assert ("Press ENTER to close" in output) is visible


def test_standalone_script_checks_platform_before_importing_or_starting_tk(
    xt, tmp_path
):
    """Inputs: actual manual invocation on Linux. Output: clear native-platform requirement, no Tk display error or interactive prompt."""
    result = subprocess.run(
        [xt.sys.executable, xt.__file__],
        input="",
        text=True,
        capture_output=True,
        timeout=15,
        env={**os.environ, "HOME": str(tmp_path)},
        check=True,
    )
    assert "Detected a non-Windows platform" in result.stdout
    assert "Press ENTER" not in result.stdout
    assert result.stderr == ""


def test_native_diagnostics_deduplicate_paths_and_report_available_imports(
    xt, tmp_path, monkeypatch
):
    """Inputs: duplicate installation paths and already-loaded optional modules. Output: truthful existence/import diagnostics with each candidate reported once."""
    root = tmp_path / "Imaris 11.0"
    root.mkdir()
    candidate = root / "XT"
    candidate.mkdir()
    monkeypatch.setattr(xt, "_iter_imaris_install_roots", lambda: iter([str(root)]))
    monkeypatch.setattr(
        xt,
        "_iter_imaris_xt_path_candidates",
        lambda _root: iter([str(candidate), str(candidate)]),
    )
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: True)
    monkeypatch.setattr(xt, "_find_imaris_executable", lambda: None)
    monkeypatch.setattr(xt, "_find_imaris_file_converter_executable", lambda: None)
    monkeypatch.setitem(xt.sys.modules, "ImarisLib", SimpleNamespace())
    monkeypatch.setitem(xt.sys.modules, "IcePy", SimpleNamespace())
    report = xt._collect_imaris_xt_diagnostics()
    assert report["xt_candidate_paths"] == [{"path": str(candidate), "exists": True}]
    assert report["imarislib_import"] == {"ok": True, "error": ""}
    assert report["icepy_import"] == {"ok": True, "error": ""}
    lines = []
    monkeypatch.setattr(xt, "_xt_debug", lines.append)
    xt._log_imaris_xt_diagnostics()
    assert sum("XT diagnostics path=" in line for line in lines) == 1
    assert any(
        "ImarisLib_ok=True" in line and "IcePy_ok=True" in line for line in lines
    )
    assert any("install_root=" + str(root) in line for line in lines)


def test_native_home_fallback_uses_homedrive_and_homepath_without_guessing(
    xt, monkeypatch
):
    """Inputs: native profile without USERPROFILE but with explicit drive/home values. Output: their exact absolute path without relying on a checkout."""
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "nt"
    platform.environ = {"HOMEDRIVE": "C:", "HOMEPATH": r"\fixture-home"}
    monkeypatch.setattr(xt, "os", platform)
    assert str(xt._connector_user_home()) == r"C:\fixture-home"


def test_windows_absolute_path_with_nonletter_drive_is_rejected(xt):
    """Inputs: absolute-looking path with invalid drive designator. Output: rejection before filesystem access."""
    assert not xt._is_structurally_valid_windows_folder_path(r"1:\images")


def test_tiff_native_open_helper_uses_converter_workflow_instead(
    xt, tmp_path, monkeypatch
):
    """Inputs: valid TIFF handed to the IMS-only native runner. Output: explicit refusal without launching an incompatible native helper."""
    path = tmp_path / "image.tif"
    path.write_bytes(b"II*\x00fixture")
    helper = Mock()
    monkeypatch.setattr(xt, "_run_native_bridge_helper", helper)
    assert not xt._run_native_bridge_open_helper(
        "fixture-python", path, 7, require_ims=False
    )
    helper.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_host_does_not_display_a_premature_syntax_error(xt, value):
    """Inputs: unfilled host field. Output: neutral syntax feedback; required-field checks belong to the connection form."""
    assert xt._omero_web_host_input_error(value) == ""


def test_invalid_backup_target_is_rejected_without_touching_existing_settings(
    xt, tmp_path
):
    """Inputs: invalid backup target beside existing settings. Output: explicit failure with all original paths and bytes retained."""
    settings = tmp_path / "settings.env"
    settings.write_bytes(b"retained settings")
    with pytest.raises(OSError, match="Connector settings path is invalid"):
        xt._rotate_connector_settings_backups(None)
    assert list(tmp_path.iterdir()) == [settings]
    assert settings.read_bytes() == b"retained settings"


def test_native_open_helper_rejects_missing_file_without_spawning(
    xt, tmp_path, monkeypatch
):
    """Inputs: deleted export before native handoff. Output: explicit refusal, no helper process and no recreated file."""
    path = tmp_path / "missing.ims"
    helper = Mock()
    monkeypatch.setattr(xt, "_run_native_bridge_helper", helper)
    assert not xt._run_native_bridge_open_helper("fixture-python", path, 7)
    helper.assert_not_called()
    assert not path.exists()


def test_permissive_api_error_boundary_does_not_misreport_expiry_as_data(xt):
    """Inputs: classified authentication error to the optional-read boundary. Output: absent result, never exception data or a credential operation."""
    error = xt._OMEROAuthenticationError("fixture expiry")
    assert xt.OMEROWebClient._api_error_result(error, raise_on_error=False) is None
    with pytest.raises(xt._OMEROAuthenticationError) as caught:
        xt.OMEROWebClient._api_error_result(error, raise_on_error=True)
    assert caught.value is error


def test_logging_rejects_a_regular_file_as_its_parent_directory(
    xt, tmp_path, monkeypatch
):
    """Inputs: configured log directory replaced by a regular file. Output: no accepted log target and unchanged file bytes."""
    parent = tmp_path / "settings"
    parent.write_bytes(b"preserved")
    monkeypatch.setattr(
        xt, "_connector_settings_env_path", lambda: parent / "settings.env"
    )
    assert xt._safe_xt_log_file(parent / xt.XT_LOG_FILE_NAME) is None
    assert parent.read_bytes() == b"preserved"


@pytest.mark.parametrize(
    "path",
    [r"\\server\bad:share\folder", r"\\server\NUL\folder", r"\\server\share.\folder"],
)
def test_unc_share_names_obey_the_same_path_safety_contract_as_folders(xt, path):
    """Inputs: invalid UNC share components. Output: rejection before any filesystem or network access."""
    assert not xt._is_structurally_valid_windows_folder_path(path)


def test_executable_discovery_does_not_accept_an_arbitrary_existing_binary(
    xt, tmp_path
):
    """Inputs: unrelated existing executable in a supported installation directory. Output: no accepted Imaris executable."""
    install = tmp_path / "Imaris 11.0"
    install.mkdir()
    executable = install / "unrelated.exe"
    executable.write_bytes(b"not Imaris")
    assert not xt._is_existing_supported_imaris_executable_path(executable)
    assert xt._ensure_connector_settings_imaris_executable(object()) == ""
    assert executable.read_bytes() == b"not Imaris"


def test_folder_inventory_fails_truthfully_when_an_entry_disappears(
    xt, tmp_path, monkeypatch
):
    """Inputs: actual file removed between enumeration and metadata read. Output: explicit inventory failure, never a partial successful upload manifest."""
    folder = tmp_path / "upload"
    folder.mkdir()
    missing = folder / "image.tif"
    missing.write_bytes(b"fixture")
    scan = xt.os.scandir

    @contextlib.contextmanager
    def disappear(path):
        """Inputs: real directory path. Output: native directory entries with one concurrent removal."""
        with scan(path) as entries:
            observed = list(entries)
        missing.unlink()
        yield iter(observed)

    monkeypatch.setattr(xt.os, "scandir", disappear)
    with pytest.raises(RuntimeError, match="Failed to inspect.*FileNotFoundError"):
        xt._collect_local_folder_entries(folder)


def test_converter_candidates_are_deduplicated_and_do_not_invent_a_sibling(
    xt, tmp_path, monkeypatch
):
    """Inputs: real installation with no converter sibling and duplicate root discovery. Output: no invented executable and one normalized candidate."""
    install = tmp_path / "Imaris 11.0"
    install.mkdir()
    executable = install / "Imaris.exe"
    executable.write_bytes(b"fixture")
    assert xt._imaris_file_converter_executable_path(executable) is None
    monkeypatch.setattr(xt, "_find_imaris_executable", lambda: str(executable))
    monkeypatch.setattr(
        xt, "_iter_imaris_install_roots", lambda: iter([str(install), str(install)])
    )
    assert list(xt._iter_imaris_file_converter_executable_candidates()) == [
        str(install / "ImarisFileConverter.exe")
    ]


@pytest.mark.parametrize("kind", ["str", "path"])
def test_single_path_input_is_not_misinterpreted_as_a_sequence(xt, tmp_path, kind):
    """Inputs: one real path as text or Path. Output: one complete regular file rather than character-wise paths."""
    image = tmp_path / "image.ims"
    image.write_bytes(b"fixture")
    assert xt._existing_regular_file_path_list(
        str(image) if kind == "str" else image
    ) == [image]


def test_python_launcher_discovery_ignores_incomplete_records_and_empty_roots(
    xt, monkeypatch
):
    """Inputs: incomplete launcher output and no operating-system roots. Output: no guessed executable or directory scan."""
    assert xt._parse_python_launcher_paths("-3.12\n-3.13 *\nnot-a-launcher") == []
    platform = SimpleNamespace(**vars(xt.os))
    platform.environ = {}
    monkeypatch.setattr(xt, "os", platform)
    assert list(xt._iter_windows_python_launchers()) == []


def test_invalid_native_application_id_never_launches_a_helper(xt, monkeypatch):
    """Inputs: invalid native application id. Output: no payload, no resolved application and no helper process."""
    launch = Mock(side_effect=AssertionError("Unexpected native helper"))
    monkeypatch.setattr(xt.subprocess, "run", launch)
    assert xt._native_bridge_payload("not-an-id", "probe") is None
    assert xt._resolve_imaris_application("not-an-id") is None
    launch.assert_not_called()


@pytest.mark.parametrize("mode", ["disabled", "non_native", "no_python"])
def test_unavailable_native_runner_does_not_open_or_modify_the_image(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: disabled, non-native or unavailable alternate runtime. Output: explicit no-handoff and unchanged image bytes."""
    image = tmp_path / "image.ims"
    image.write_bytes(b"\x89HDF\r\n\x1a\nretained")
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "posix" if mode == "non_native" else "nt"
    monkeypatch.setattr(xt, "os", platform)
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: mode != "disabled")
    monkeypatch.setattr(xt, "_iter_native_bridge_python_executables", lambda: iter(()))
    helper = Mock(side_effect=AssertionError("Unexpected native helper"))
    monkeypatch.setattr(xt, "_run_native_bridge_open_helper", helper)
    assert not xt._open_file_in_imaris_with_native_bridge_runner(image, 7)
    helper.assert_not_called()
    assert image.read_bytes() == b"\x89HDF\r\n\x1a\nretained"


def test_native_open_helper_rejects_a_non_ims_file_before_spawning(
    xt, tmp_path, monkeypatch
):
    """Inputs: existing TIFF presented as IMS. Output: no native helper invocation and unchanged TIFF bytes."""
    image = tmp_path / "not-ims.tif"
    image.write_bytes(b"II*\x00fixture")
    helper = Mock()
    monkeypatch.setattr(xt, "_run_native_bridge_helper", helper)
    assert not xt._run_native_bridge_open_helper("fixture-python", image, 7)
    helper.assert_not_called()
    assert image.read_bytes() == b"II*\x00fixture"


def test_native_stderr_retains_errors_and_distinguishes_only_known_benign_warning(
    xt, monkeypatch
):
    """Inputs: mixed and exclusively benign bridge diagnostics. Output: real errors retained, with explicit known-warning handling."""
    log = Mock()
    monkeypatch.setattr(xt, "_xt_debug", log)
    benign = "communicator not destroyed during global destruction"
    xt._log_native_bridge_stderr("Actual failure\n" + benign, "probe")
    assert "Actual failure" in log.call_args.args[0]
    assert benign not in log.call_args.args[0]
    xt._log_native_bridge_stderr(benign, "probe")
    assert "suppressed benign Ice shutdown warning" in log.call_args.args[0]


def test_download_uses_binary_open_flag_when_provided_without_altering_bytes(
    xt, tmp_path, monkeypatch
):
    """Inputs: platform exposing binary-mode open flag. Output: exact binary download with no newline conversion."""
    platform = SimpleNamespace(**vars(xt.os))
    platform.O_BINARY = 0
    monkeypatch.setattr(xt, "os", platform)
    payload = b"a\r\nb\x00\xff"
    with xt._open_download_target(str(tmp_path), "fixture.bin", "unique") as (
        target,
        stream,
    ):
        stream.write(payload)
    assert Path(target).read_bytes() == payload


def test_failed_log_cleanup_is_nonfatal_and_does_not_remove_other_files(
    xt, tmp_path, monkeypatch
):
    """Inputs: denied unlink for a regular diagnostic log. Output: retained log, retained neighboring data and no propagated exception."""
    log = tmp_path / "diagnostic.log"
    data = tmp_path / "image.ims"
    log.write_bytes(b"diagnostic")
    data.write_bytes(b"retained")
    original = Path.unlink

    def denied(path, *args, **kwargs):
        """Inputs: requested deletion. Output: access denial only for the diagnostic log."""
        if path == log:
            raise PermissionError("fixture log is in use")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    xt._safe_unlink_xt_log_path(log)
    assert log.read_bytes() == b"diagnostic"
    assert data.read_bytes() == b"retained"


def test_group_scope_and_item_shape_helpers_preserve_explicit_inputs(xt):
    """Inputs: explicitly scoped endpoint and direct item list. Output: no duplicate scope and unchanged list identity."""
    client = object.__new__(xt.OMEROWebClient)
    endpoint = "m/projects/?group=7&limit=20"
    assert client._with_all_groups(endpoint) == endpoint
    items = [{"id": 7}]
    assert client._extract_items(items) is items
    assert client._normalize_url("", "https://example.test") == ""


def test_invalid_sash_index_is_rejected_without_changing_layout(xt):
    """Inputs: nonexistent splitter index. Output: actionable failure, with original pane proportions retained."""
    fractions = [0.3, 0.3, 0.4]
    with pytest.raises(ValueError, match="sash_index must be 0 or 1"):
        xt._resize_browser_panel_fractions(fractions, 2, 0.5)
    assert fractions == [0.3, 0.3, 0.4]


def test_missing_environment_variable_is_not_replaced_with_a_guessed_path(
    xt, monkeypatch
):
    """Inputs: unknown percent-style environment reference. Output: unchanged explicit reference, never a working-directory fallback."""
    monkeypatch.delenv("XT_FIXTURE_MISSING_ROOT", raising=False)
    path = r"%XT_FIXTURE_MISSING_ROOT%\images"
    assert xt._expand_windows_environment_variables(path) == path


@pytest.mark.parametrize(
    "platform_name,path",
    [("posix", "/missing/fixture"), ("nt", ""), ("nt", r"C:\missing\fixture")],
)
def test_arena_registration_rejects_unsupported_or_missing_folder_without_registry_access(
    xt, monkeypatch, platform_name, path
):
    """Inputs: unavailable native platform or invalid/missing folder. Output: no registry access and explicit failure."""
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = platform_name
    monkeypatch.setattr(xt, "os", platform)
    monkeypatch.setattr(xt, "_safe_is_directory", lambda _path: False)
    registry = Mock(side_effect=AssertionError("Unexpected registry access"))
    monkeypatch.setattr(xt, "_import_winreg_module", registry)
    assert not xt._append_imaris_arena_observed_folder(path)
    registry.assert_not_called()


def test_inaccessible_existence_probe_is_not_reported_as_an_existing_file(
    xt, monkeypatch
):
    """Inputs: failed filesystem metadata lookup. Output: false existence without propagating the optional diagnostic failure."""
    platform = SimpleNamespace(**vars(xt.os))
    platform.path = SimpleNamespace(**vars(xt.os.path))
    platform.path.exists = Mock(side_effect=OSError("fixture metadata unavailable"))
    monkeypatch.setattr(xt, "os", platform)
    assert not xt._safe_path_exists("fixture-path")
    platform.path.exists.assert_called_once_with("fixture-path")


def test_available_registry_module_is_returned_without_modifying_it(xt, monkeypatch):
    """Inputs: a native registry provider made available by the interpreter. Output: the exact provider, without registration or writes."""
    registry = SimpleNamespace()
    monkeypatch.setitem(xt.sys.modules, "winreg", registry)
    assert xt._import_winreg_module() is registry
    assert vars(registry) == {}


@pytest.mark.parametrize("closing", [False, True])
@pytest.mark.parametrize("wait", [False, True])
def test_ui_scheduling_failure_is_suppressed_only_for_confirmed_window_shutdown(
    xt, closing, wait
):
    """Inputs: scheduler failure racing an optional close signal. Output: explicit normal failure or closed-window cancellation, never false callback success."""
    closed = threading.Event()
    failure = RuntimeError("fixture scheduler unavailable")

    def schedule(_delay, _callback):
        """Inputs: callback registration. Output: failed registration, optionally racing the window-close event."""
        if closing:
            closed.set()
        raise failure

    dialog = SimpleNamespace(_ui_closed=closed, root=SimpleNamespace(after=schedule))
    callback = Mock()
    if closing and not wait:
        assert xt._dispatch_ui_callback(dialog, callback, wait=wait) is None
    else:
        expected = xt._ConnectorOperationCancelled if closing else RuntimeError
        with pytest.raises(expected) as error:
            xt._dispatch_ui_callback(dialog, callback, wait=wait)
        if not closing:
            assert error.value is failure
    callback.assert_not_called()


@pytest.mark.parametrize(
    "scheme, port, message",
    [("ftp", 443, "scheme"), ("https", 0, "port"), ("http", "not-a-port", "port")],
)
def test_client_url_construction_rejects_unsupported_connection_parameters(
    xt, scheme, port, message
):
    """Inputs: invalid protocol or port before client creation. Output: explicit rejection, never a constructed network endpoint."""
    with pytest.raises(ValueError, match=message):
        xt.OMEROWebClient._build_base_url("example.test", port, scheme)


@pytest.mark.parametrize(
    "target", ["https://[invalid", "https://example.test/not-login/"]
)
def test_malformed_or_unrelated_redirect_does_not_invent_authentication_failure(
    xt, target
):
    """Inputs: malformed/unrelated redirect location. Output: no false authentication rejection and no parser exception."""
    headers = Message()
    headers["Location"] = target
    response = SimpleNamespace(
        status=302, headers=headers, geturl=lambda: "https://example.test/data/"
    )
    assert xt.OMEROWebClient._check_login_redirect(response) is False
    assert xt.OMEROWebClient._looks_like_login_page({"unexpected": "mapping"}) is False


def test_version_parser_rejects_unbounded_numeric_version_text(xt):
    """Inputs: malformed version component beyond Python's integer safety limit. Output: no accepted native installation version."""
    previous = xt.sys.get_int_max_str_digits()
    try:
        xt.sys.set_int_max_str_digits(640)
        assert xt._infer_imaris_major_version_from_path("Imaris " + "9" * 1000) is None
    finally:
        xt.sys.set_int_max_str_digits(previous)


def test_collapsed_polygon_and_empty_download_name_have_deterministic_fallbacks(xt):
    """Inputs: zero-area icon geometry and names consisting only of stripped punctuation. Output: finite unchanged centroid and safe default filename."""
    assert xt._inset_polygon([4, 5, 4, 5, 4, 5], 2) == [4, 5, 4, 5, 4, 5]
    assert xt._safe_download_filename(".", ".") == "download"
    assert xt._pluralize("invalid", "image") == "images"
    assert xt._pluralize(object(), "image") == "images"


def test_response_cancellation_during_socket_wait_closes_the_owned_socket(xt):
    """Inputs: real socket awaiting bytes when cancellation arrives. Output: bounded cancellation and closed response descriptor."""
    reader, writer = socket.socketpair()
    headers = Message()
    headers["Content-Length"] = "4"
    cancel = threading.Event()
    response = xt._CancellableHTTPResponse(
        reader, "https://example.test/file", 200, "OK", headers, b"", cancel, 2
    )
    signal = threading.Timer(0.02, cancel.set)
    signal.start()
    try:
        with pytest.raises(xt._ConnectorOperationCancelled):
            response.read(1)
        assert response.closed
        assert reader.fileno() == -1
    finally:
        signal.join(timeout=1)
        response.close()
        writer.close()
    assert not signal.is_alive()


def test_zero_size_response_read_does_not_consume_buffered_image_bytes(xt):
    """Inputs: real socket response with buffered bytes and a zero-length read. Output: empty read followed by exact unchanged data."""
    reader, writer = socket.socketpair()
    headers = Message()
    headers["Content-Length"] = "3"
    try:
        with xt._CancellableHTTPResponse(
            reader,
            "https://example.test/file",
            200,
            "OK",
            headers,
            b"abc",
            threading.Event(),
            2,
        ) as response:
            assert response.read(0) == b""
            assert response.read() == b"abc"
    finally:
        reader.close()
        writer.close()


def test_zero_byte_socket_send_fails_without_replaying_the_request(xt, monkeypatch):
    """Inputs: native transport reports closure during a non-empty send. Output: explicit failure after exactly one send attempt."""
    transport = SimpleNamespace(send=Mock(return_value=0))
    ready = Mock()
    monkeypatch.setattr(xt, "_socket_wait", ready)
    with pytest.raises(OSError, match="Socket closed while sending"):
        xt._socket_send_all(transport, b"request", threading.Event(), time.time() + 2)
    ready.assert_called_once()
    assert transport.send.call_count == 1


@pytest.mark.parametrize(
    "operation",
    ["home", "prepare", "write", "backup", "folder", "executable", "version"],
)
def test_invalid_path_input_cannot_reach_filesystem_operations(xt, tmp_path, operation):
    """Inputs: non-path object to public path boundaries. Output: explicit rejection, no settings or image writes; diagnostics remain permitted."""
    invalid = object()
    if operation == "home":
        with pytest.raises(OSError, match="home path is invalid"):
            xt._connector_settings_env_path(invalid)
    elif operation == "prepare":
        assert xt._prepare_connector_settings_for_current_version(invalid) is False
    elif operation == "write":
        with pytest.raises(OSError, match="path is invalid"):
            xt._atomic_write_connector_settings({}, invalid)
    elif operation == "backup":
        with pytest.raises(ValueError, match="target is invalid"):
            xt._connector_settings_backup_path(invalid, 1)
    elif operation == "folder":
        with pytest.raises(RuntimeError, match="folder path is invalid"):
            xt._collect_local_folder_entries(invalid)
    elif operation == "executable":
        assert not xt._is_existing_supported_imaris_executable_path(invalid)
        assert xt._imaris_file_converter_executable_path(invalid) is None
    else:
        assert xt._infer_imaris_major_version_from_path(invalid) is None
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    if operation in {"prepare", "write"}:
        log = xt._connector_settings_env_path(tmp_path).parent / xt.XT_LOG_FILE_NAME
        assert files == [log]
        assert "OSError" in log.read_text()
    else:
        assert files == []


@pytest.mark.parametrize("index", [0, -1])
def test_settings_backup_rejects_nonpositive_generation(xt, tmp_path, index):
    """Inputs: invalid backup generation. Output: no destination allocation and unchanged settings."""
    settings = tmp_path / "settings.env"
    settings.write_bytes(b"original")
    with pytest.raises(ValueError, match="index must be positive"):
        xt._connector_settings_backup_path(settings, index)
    assert settings.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [settings]


def test_failed_atomic_settings_commit_removes_only_its_temporary_file(
    xt, tmp_path, monkeypatch
):
    """Inputs: atomic replacement denied after successful private-file write. Output: original settings retained and temporary file removed."""
    target = xt._connector_settings_env_path(tmp_path)
    target.parent.mkdir()
    target.write_bytes(b"# operator-owned settings\n")
    unrelated = target.parent / "unrelated.tmp"
    unrelated.write_bytes(b"keep")
    monkeypatch.setattr(xt.os, "replace", Mock(side_effect=PermissionError("denied")))
    with pytest.raises(PermissionError, match="denied"):
        xt._atomic_write_connector_settings({}, target)
    assert target.read_bytes() == b"# operator-owned settings\n"
    assert unrelated.read_bytes() == b"keep"
    log = target.parent / xt.XT_LOG_FILE_NAME
    assert set(target.parent.iterdir()) == {target, unrelated, log}
    assert "PermissionError" in log.read_text()


@pytest.mark.parametrize("kind", ["ims", "tiff"])
def test_image_header_probe_never_accepts_missing_or_unreadable_files(
    xt, tmp_path, monkeypatch, kind
):
    """Inputs: missing file and real image header whose read is denied. Output: false format recognition, unchanged file."""
    path = tmp_path / f"image.{kind}"
    check = xt.is_ims_file if kind == "ims" else xt.is_tiff_file
    assert not check(path)
    payload = b"\x89HDF\r\n\x1a\n" if kind == "ims" else b"II*\x00"
    path.write_bytes(payload)
    with monkeypatch.context() as denied:
        denied.setattr(Path, "open", Mock(side_effect=PermissionError("denied")))
        assert not check(path)
    assert path.read_bytes() == payload


@pytest.mark.parametrize(
    "mode", ["native_absent", "no_window", "missing_api", "api_failure"]
)
def test_optional_console_controls_fail_without_changing_application_state(
    xt, monkeypatch, mode
):
    """Inputs: unsupported host or missing/failing native console APIs. Output: false capability, preserved requested visibility, no shell invocation."""
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "posix" if mode == "native_absent" else "nt"
    monkeypatch.setattr(xt, "os", platform)
    api = SimpleNamespace(
        GetConsoleWindow=Mock(return_value=0 if mode == "no_window" else 37),
        SetConsoleTitleW=Mock(side_effect=OSError("unavailable")),
    )
    if mode == "missing_api":
        del api.SetConsoleTitleW
        del api.GetConsoleWindow
    user = SimpleNamespace(ShowWindow=Mock(side_effect=OSError("unavailable")))
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=api, user32=user), raising=False
    )
    assert not xt._configure_xt_console_visibility(False)
    assert xt._XT_RUNTIME_STATE.console_output_enabled is False
    assert not xt._set_process_window_title("OMERO Connector")
    if mode in {"native_absent", "no_window", "missing_api"}:
        user.ShowWindow.assert_not_called()


@pytest.mark.parametrize(
    "setting, expected", [("", ""), ("  ", ""), ("plain value", "plain value")]
)
def test_unquoted_settings_values_are_literal_text(xt, setting, expected):
    """Inputs: empty and ordinary env values. Output: literal strings without shell evaluation."""
    assert xt._parse_connector_settings_env_value(setting) == expected
    assert xt._connector_settings_bool(True) is True
    assert xt._connector_settings_bool(False) is False


@pytest.mark.parametrize(
    "existing, added, expected",
    [
        ("a", "", "a"),
        ("/first", "/first", "/first"),
        ("/first\n/second", "/third", "/first\n/second\n/third"),
        ("/first;/second", "/third", "/first;/second;/third"),
    ],
)
def test_arena_folder_list_preserves_format_and_prevents_duplicates(
    xt, existing, added, expected
):
    """Inputs: existing newline/semicolon list and a candidate folder. Output: one appended folder without losing prior entries."""
    assert xt._append_imaris_arena_folder_list_value(existing, added) == expected
    assert not xt._imaris_arena_folder_list_has_folder(existing, "")
    assert not xt._imaris_arena_tree_state_has_observed_folder(existing, "")
    assert xt._append_imaris_arena_tree_state_observed_folder(existing, "") == existing
    assert (
        xt._append_imaris_arena_tree_state_observed_folder(
            "[Observed]/first", "/second"
        )
        == "[Observed]/first[Observed]/second"
    )


def test_absent_registry_value_is_not_a_configured_observed_folder(xt):
    """Inputs: missing native registry value. Output: empty result and a single read, never a key creation."""
    registry = SimpleNamespace(
        QueryValueEx=Mock(side_effect=FileNotFoundError("absent"))
    )
    key = object()
    assert xt._query_registry_string_value(registry, key, "FolderList") == ""
    registry.QueryValueEx.assert_called_once_with(key, "FolderList")


def test_missing_tk_dependency_reports_startup_requirement(xt, monkeypatch):
    """Inputs: unavailable Tk import. Output: actionable startup error with the original import error retained."""
    original = builtins.__import__

    def import_without_tk(name, *args, **kwargs):
        """Inputs: import request. Output: normal modules except an unavailable Tk runtime."""
        if name == "tkinter":
            raise ImportError("fixture missing Tk")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_tk)
    with pytest.raises(RuntimeError, match="Tkinter is required") as failure:
        xt._ensure_tk_loaded()
    assert isinstance(failure.value.__cause__, ImportError)


@pytest.mark.parametrize("dataset", [None, object()])
def test_native_clone_requires_a_clone_capability(xt, dataset):
    """Inputs: missing native dataset or Clone API. Output: no invented clone and no native mutation."""
    assert xt._clone_current_imaris_dataset(object()) is None
    app = SimpleNamespace(GetDataSet=Mock(return_value=dataset))
    assert xt._clone_current_imaris_dataset(app) is None
    app.GetDataSet.assert_called_once_with()


def test_unique_download_namespace_exhaustion_preserves_every_existing_file(
    xt, tmp_path, monkeypatch
):
    """Inputs: all bounded candidate filenames occupied by real files. Output: allocation fails without overwriting or deleting any file."""
    clock = xt.datetime.datetime

    class FixedTime(clock):
        """Use a stable timestamp so the complete collision namespace is deterministic."""

        @classmethod
        def now(cls, tz=None):
            """Inputs: requested timezone. Output: one fixed aware fixture instant."""
            return cls(2026, 1, 1, tzinfo=tz)

    monkeypatch.setattr(xt.datetime, "datetime", FixedTime)
    candidates = list(xt._unique_download_candidates(tmp_path, "image.tif"))
    assert len(candidates) == len(set(candidates)) == 1000
    for path in candidates:
        Path(path).write_bytes(b"preserved")
    with pytest.raises(RuntimeError, match="unique download filename"):
        xt._unique_download_path(tmp_path, "image.tif")
    with pytest.raises(RuntimeError, match="allocate a download file"):
        with xt._open_download_target(
            tmp_path, "image.tif", xt.DUPLICATE_DOWNLOAD_POLICY_UNIQUE
        ):
            pytest.fail("An occupied download namespace was reused")
    assert {str(path) for path in tmp_path.iterdir()} == set(candidates)
    assert all(Path(path).read_bytes() == b"preserved" for path in candidates)


@pytest.mark.parametrize("boundary", ["verified", "observable"])
def test_native_open_verification_expires_without_claiming_a_changed_dataset(
    xt, tmp_path, boundary
):
    """Inputs: native API exposes no observable open effect and a failed filename read. Output: bounded false result, never an invented handoff."""
    app = SimpleNamespace(GetDataSet=lambda: None)
    before = xt._imaris_app_snapshot(app)
    started = time.monotonic()
    if boundary == "verified":
        getter = Mock(side_effect=OSError("native filename unavailable"))
        result = xt._wait_for_imaris_verified_open(
            app,
            getter,
            before,
            str(tmp_path / "expected.ims"),
            timeout=0.02,
            interval=0.001,
        )
        assert getter.called
    else:
        result = xt._wait_for_imaris_open_observable_effect(
            app, before, str(tmp_path / "expected.ims"), timeout=0.02, interval=0.001
        )
    assert result is False
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("enabled", [False, True])
def test_native_environment_setup_never_fails_the_connector_for_a_missing_dll_api(
    xt, tmp_path, monkeypatch, enabled
):
    """Inputs: existing native library directory with optional failing DLL registration. Output: deterministic path setup, no invented DLL handle or global interpreter mutation."""
    root = tmp_path / "Imaris 11.0"
    root.mkdir()
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "nt" if enabled else "posix"
    platform.environ = {"PATH": str(root)}
    platform.add_dll_directory = Mock(
        side_effect=OSError("DLL registration unavailable")
    )
    interpreter = SimpleNamespace(**vars(xt.sys))
    interpreter.path = [str(root)]
    monkeypatch.setattr(xt, "os", platform)
    monkeypatch.setattr(xt, "sys", interpreter)
    monkeypatch.setattr(xt, "_iter_imaris_install_roots", lambda: iter((str(root),)))
    monkeypatch.setattr(
        xt, "_iter_imaris_xt_path_candidates", lambda _root: iter((str(root),))
    )
    handles = list(xt._XT_DLL_DIR_HANDLES)
    assert xt._prepare_imaris_xt_environment() == {"paths": [], "dll_dirs": []}
    assert interpreter.path == [str(root)]
    assert platform.environ["PATH"] == str(root)
    assert xt._XT_DLL_DIR_HANDLES == handles
    assert platform.add_dll_directory.call_count == int(enabled)


@pytest.mark.parametrize("kind", ["project", "dataset", "image"])
def test_browser_entity_labels_use_safe_fallbacks_for_missing_metadata(xt, kind):
    """Inputs: absent entity or entity without an ID. Output: truthful fallback labels and no fabricated identifier."""
    dialog = xt.OMEROBrowserDialog
    label = getattr(dialog, f"_{kind}_list_label")
    assert label(None) == kind.title()
    assert dialog._entity_id(None) is None
    assert dialog._entity_id({}) is None
    assert dialog._entity_id({"@id": 17}) == "17"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("relative", False),
        ("/rooted", True),
        (r"\\?\UNC\server\share\folder", True),
        (r"\root-without-drive", False),
    ],
)
def test_folder_syntax_accepts_absolute_unc_and_rejects_ambiguous_roots(
    xt, value, expected
):
    """Inputs: absolute, extended UNC and ambiguous folder names. Output: structural validation independent of the machine's filesystem."""
    assert xt._is_structurally_valid_folder_path(value) is expected


@pytest.mark.parametrize("boundary", ["install", "restore"])
def test_console_interrupt_guard_handles_unavailable_signal_api(
    xt, monkeypatch, boundary
):
    """Inputs: signal registration disallowed by the runtime. Output: bounded diagnostics without aborting startup or teardown."""
    signal_api = Mock(side_effect=ValueError("not the main interpreter thread"))
    monkeypatch.setattr(xt.signal, "signal", signal_api)
    if boundary == "install":
        assert xt._install_xt_console_interrupt_guard() == []
    else:
        xt._restore_xt_console_interrupt_guard([(xt.signal.SIGINT, xt.signal.SIG_DFL)])
    assert signal_api.called
    xt._ignore_xt_console_interrupt(xt.signal.SIGINT, None)


def test_download_progress_unknown_size_reports_only_meaningful_byte_or_time_steps(
    xt, monkeypatch
):
    """Inputs: unknown total and increasing byte counts. Output: throttled reports at configured byte/time thresholds, without a false percentage."""
    now = [100.0]
    monkeypatch.setattr(xt.time, "monotonic", lambda: now[0])
    messages = []
    monkeypatch.setattr(
        xt, "_xt_console_log", lambda message, **_kwargs: messages.append(message)
    )
    reporter = xt._DownloadProgressReporter(0)
    reporter.report(1)
    assert len(messages) == 1
    reporter.report(2)
    assert len(messages) == 1
    reporter.report(1 + xt.UNKNOWN_DOWNLOAD_PROGRESS_STEP_BYTES)
    assert len(messages) == 2
    now[0] += xt.DOWNLOAD_PROGRESS_SECONDS_STEP
    reporter.report(2 + xt.UNKNOWN_DOWNLOAD_PROGRESS_STEP_BYTES)
    assert len(messages) == 3
    assert all("%" not in message for message in messages)


def test_install_discovery_uses_configured_vendor_roots_and_supported_versions(
    xt, tmp_path, monkeypatch
):
    """Inputs: separate configured program roots and mixed installations. Output: deterministic candidates only from supported vendor entries."""
    expected_roots = []
    expected_executables = []
    for index, variable in enumerate(
        ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
    ):
        base = tmp_path / f"program-root-{index}"
        monkeypatch.setenv(variable, str(base))
        for vendor in ("Bitplane", "Oxford Instruments"):
            root = base / vendor
            root.mkdir(parents=True)
            expected_roots.append(str(root))
            for entry in ("Imaris 10.0", "Imaris 11.0", "Imaris 12.0", "unrelated"):
                installation = root / entry
                installation.mkdir()
                (installation / "Imaris.exe").write_bytes(b"fixture, never executed")
            expected_executables.extend(
                str(root / version / "Imaris.exe")
                for version in ("Imaris 12.0", "Imaris 11.0")
            )
    assert list(xt._iter_imaris_vendor_roots()) == expected_roots
    assert list(xt._iter_imaris_vendor_executable_candidates()) == expected_executables
    assert xt._safe_sorted_directory_entries(tmp_path / "missing") == ()
    assert xt._safe_sorted_directory_entries(expected_roots[0]) == (
        "Imaris 10.0",
        "Imaris 11.0",
        "Imaris 12.0",
        "unrelated",
    )


@pytest.mark.parametrize("same_installation", [False, True])
def test_native_module_roots_follow_discovered_executable_without_duplicate_roots(
    xt, tmp_path, monkeypatch, same_installation
):
    """Inputs: explicit and discovered supported installations. Output: distinct roots in preference order without duplicate native search paths."""
    configured = tmp_path / "Imaris 11.0"
    discovered = configured if same_installation else tmp_path / "Imaris 12.0"
    monkeypatch.setenv("IMARIS_HOME", str(configured))
    monkeypatch.setattr(
        xt, "_find_imaris_executable", lambda: str(discovered / "Imaris.exe")
    )
    assert list(xt._iter_imaris_install_roots()) == (
        [str(configured)] if same_installation else [str(configured), str(discovered)]
    )


def test_python_candidate_requires_supported_regular_file_and_resolvable_path(
    xt, tmp_path, monkeypatch
):
    """Inputs: absent, wrongly named, or resolution-denied interpreters. Output: no executable candidate and unchanged file contents."""
    wrong = tmp_path / "not-python.exe"
    candidate = tmp_path / "python.exe"
    for path in (wrong, candidate):
        path.write_bytes(b"fixture, never executed")
    assert xt._resolve_python_executable_candidate(tmp_path / "missing") is None
    assert xt._resolve_python_executable_candidate(wrong) is None
    assert xt._resolve_python_executable_candidate(candidate) == str(
        candidate.resolve()
    )
    with monkeypatch.context() as boundary:
        boundary.setattr(Path, "resolve", Mock(side_effect=PermissionError("denied")))
        assert xt._resolve_python_executable_candidate(candidate) is None
    assert candidate.read_bytes() == b"fixture, never executed"


def test_native_interpreter_discovery_skips_failed_launchers_current_process_and_duplicates(
    xt, tmp_path, monkeypatch
):
    """Inputs: timeout, nonzero launcher exit and duplicate/current interpreter paths. Output: one verified alternate and bounded launcher calls."""
    current, alternate = (
        tmp_path / "current" / "python.exe",
        tmp_path / "alternate" / "pythonw.exe",
    )
    for path in (current, alternate):
        path.parent.mkdir()
        path.write_bytes(b"fixture, never executed")
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "nt"
    interpreter = SimpleNamespace(**vars(xt.sys))
    interpreter.executable = str(current)
    monkeypatch.setattr(xt, "os", platform)
    monkeypatch.setattr(xt, "sys", interpreter)
    launchers = [
        str(tmp_path / name / "py.exe") for name in ("timeout", "failed", "working")
    ]
    monkeypatch.setattr(xt, "_iter_windows_python_launchers", lambda: iter(launchers))
    output = "\n".join(
        f"-3.12 {path}"
        for path in (current, tmp_path / "absent.exe", alternate, alternate)
    )
    runner = Mock(
        side_effect=[
            subprocess.TimeoutExpired(launchers[0], 10),
            subprocess.CompletedProcess([], 2, "", "launcher failure"),
            subprocess.CompletedProcess([], 0, output, ""),
        ]
    )
    monkeypatch.setattr(xt.subprocess, "run", runner)
    assert list(xt._iter_native_bridge_python_executables()) == [str(alternate)]
    assert len(runner.call_args_list) == 3
    for call, launcher in zip(runner.call_args_list, launchers, strict=True):
        assert call.args == ([launcher, "-0p"],)
        assert call.kwargs["timeout"] == 10
        assert call.kwargs["stdin"] is subprocess.DEVNULL
        assert "shell" not in call.kwargs


@pytest.mark.parametrize("mode", ["disabled", "invalid_id", "none", "second"])
def test_bridge_selection_requires_an_enabled_valid_and_successfully_probed_session(
    xt, monkeypatch, mode
):
    """Inputs: disabled bridge, invalid identity, or probe failures. Output: only a verified interpreter, without probing forbidden modes."""
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: mode != "disabled")
    candidates = Mock(return_value=iter(("first-python", "second-python")))
    monkeypatch.setattr(xt, "_iter_native_bridge_python_executables", candidates)
    probe = Mock(side_effect=[False, mode == "second"])
    monkeypatch.setattr(xt, "_run_native_bridge_probe_helper", probe)
    assert xt._find_compatible_native_bridge_python(
        "invalid" if mode == "invalid_id" else "17"
    ) == ("second-python" if mode == "second" else None)
    if mode in {"disabled", "invalid_id"}:
        candidates.assert_not_called()
        probe.assert_not_called()
    else:
        assert [call.args for call in probe.call_args_list] == [
            ("first-python", "17"),
            ("second-python", "17"),
        ]


@pytest.mark.parametrize(
    "selection", ["empty", "single", "batch", "untracked", "removed"]
)
def test_selected_tiff_handoff_requires_every_file_to_be_tracked_and_present(
    xt, tmp_path, monkeypatch, selection
):
    """Inputs: real TIFFs and empty/partial/stale export tracking. Output: one appropriate native submission only when every selected file is trusted."""
    from PIL import Image

    paths = [tmp_path / "first.tif", tmp_path / "second.tif"]
    for path in paths:
        Image.new("L", (4, 4), color=37).save(path)
    dialog = object.__new__(xt.OMEROBrowserDialog)
    dialog._set_status = Mock()
    client = object()
    dialog.client = client
    dialog._selected_image_export_files = set()
    dialog._mark_selected_image_export_file(paths[0])
    if selection != "untracked":
        dialog._mark_selected_image_export_file(paths[1])
    if selection == "removed":
        paths[1].unlink()
    single = Mock(return_value=True)
    batch = Mock(return_value=True)
    monkeypatch.setattr(xt, "submit_selected_image_export_to_imaris_converter", single)
    monkeypatch.setattr(xt, "submit_selected_image_exports_to_imaris_converter", batch)
    selected = (
        []
        if selection == "empty"
        else [str(paths[0])]
        if selection == "single"
        else list(map(str, paths))
    )
    result = dialog._open_downloaded_files_in_imaris(
        selected, require_ims=False, selected_image_export=True
    )
    assert result is (selection in {"single", "batch"})
    assert single.call_count == int(selection == "single")
    assert batch.call_count == int(selection == "batch")
    if single.called:
        single.assert_called_once_with(str(paths[0]))
    if batch.called:
        batch.assert_called_once_with(list(map(str, paths)))
    assert dialog.client is client
    for path in paths:
        if path.exists():
            with Image.open(path) as image:
                assert image.size == (4, 4)
                assert image.getpixel((0, 0)) == 37


@pytest.mark.parametrize(
    "entity,identity,label",
    [
        (None, None, "selected image"),
        ({}, None, "selected image"),
        ({"id": 0}, "0", "Image 0"),
        ({"@id": 7}, "7", "selected image"),
        ({"id": 7, "name": "Measurement"}, "7", "Measurement"),
    ],
)
def test_image_identity_and_label_fallbacks_preserve_zero_ids(
    xt, entity, identity, label
):
    """Inputs: partial API entities, including ID zero. Output: exact ID and deterministic display fallback without a fabricated ID."""
    assert xt.OMEROBrowserDialog._entity_id(entity) == identity
    assert xt.OMEROBrowserDialog._image_display_name(entity) == label


def test_path_comparison_remains_bounded_when_current_directory_disappears(
    xt, tmp_path, monkeypatch
):
    """Inputs: a genuinely removed process working directory. Output: normalized fallback keys without creation, network access, or failed cleanup."""
    folder = tmp_path / "vanishing-cwd"
    folder.mkdir()
    with monkeypatch.context() as boundary:
        boundary.chdir(folder)
        folder.rmdir()
        assert (
            xt.OMEROBrowserDialog._selected_image_export_key("relative.tif")
            == "relative.tif"
        )
        assert xt._normalize_imaris_compare_path("relative.ims") == "relative.ims"
    assert not folder.exists()
    assert xt.OMEROBrowserDialog._selected_image_export_key(None) == ""


@pytest.mark.parametrize("kind", ["missing", "directory", "file", "symlink", "denied"])
def test_diagnostic_directory_setup_never_replaces_files_or_follows_links(
    xt, tmp_path, monkeypatch, kind
):
    """Inputs: real log target kinds and mkdir denial. Output: private directory only where appropriate, preserving unrelated file bytes."""
    target = tmp_path / "log-directory"
    retained = tmp_path / "user-data"
    retained.write_bytes(b"retained")
    if kind == "directory":
        target.mkdir(mode=0o755)
    elif kind == "file":
        target.write_bytes(b"not a directory")
    elif kind == "symlink":
        target.symlink_to(retained)
    elif kind == "denied":
        monkeypatch.setattr(Path, "mkdir", Mock(side_effect=PermissionError("denied")))
    expected = kind in {"missing", "directory"}
    assert xt._ensure_xt_log_directory(target) is expected
    assert retained.read_bytes() == b"retained"
    if expected:
        assert target.is_dir() and target.stat().st_mode & 0o777 == 0o700
    elif kind == "file":
        assert target.read_bytes() == b"not a directory"
    elif kind == "symlink":
        assert target.is_symlink()
    else:
        assert not target.exists()


@pytest.mark.parametrize("failed", ["console", "file", "both"])
def test_diagnostic_sink_failures_never_abort_runtime_or_skip_the_other_sink(
    xt, tmp_path, monkeypatch, failed
):
    """Inputs: failed console/file diagnostic sinks. Output: both sinks attempted exactly once, no exception propagated or alternate file created."""
    path = tmp_path / "existing.log"
    path.write_bytes(b"original log")
    xt._XT_RUNTIME_STATE.console_output_enabled = True
    xt._XT_RUNTIME_STATE.log_path = str(path)
    console = Mock(
        side_effect=OSError("closed stream") if failed in {"console", "both"} else None
    )
    file_log = Mock(
        side_effect=PermissionError("denied") if failed in {"file", "both"} else None
    )
    monkeypatch.setattr(xt, "print", console, raising=False)
    monkeypatch.setattr(xt, "_xt_write_log", file_log)
    xt._xt_console_log("fixture diagnostic", end="", flush=True)
    console.assert_called_once_with("fixture diagnostic", end="", flush=True)
    file_log.assert_called_once_with(str(path), "fixture diagnostic")
    assert path.read_bytes() == b"original log"


def test_temporary_download_cleanup_preserves_link_targets_and_failed_removals(
    xt, tmp_path, monkeypatch
):
    """Inputs: partial-file symlink and denied owned-file removal. Output: only link removed, failed file retained, no user-data deletion."""
    user_data = tmp_path / "user-data"
    user_data.write_bytes(b"retained")
    link = tmp_path / "partial-link"
    link.symlink_to(user_data)
    xt._safe_remove_partial_download(None)
    xt._safe_remove_partial_download(link)
    assert not link.is_symlink()
    assert user_data.read_bytes() == b"retained"
    partial = tmp_path / "partial-file"
    partial.write_bytes(b"partial bytes")
    logs = []
    monkeypatch.setattr(xt, "_xt_debug", logs.append)
    with monkeypatch.context() as boundary:
        boundary.setattr(Path, "unlink", Mock(side_effect=PermissionError("denied")))
        xt._safe_remove_partial_download(partial)
    assert partial.read_bytes() == b"partial bytes"
    assert logs == ["Could not remove partial stopped download."]
    assert user_data.read_bytes() == b"retained"


def test_native_helper_cleanup_failure_does_not_fall_back_to_another_file(
    xt, tmp_path, monkeypatch
):
    """Inputs: unavailable permission to remove one owned helper. Output: that failure is recorded without removing a different helper or user file."""
    helper = tmp_path / "owned-helper.py"
    helper.write_bytes(b"fixture")
    unlink = Mock(side_effect=PermissionError("denied"))
    logs = []
    monkeypatch.setattr(xt, "_xt_debug", logs.append)
    with monkeypatch.context() as boundary:
        boundary.setattr(xt.os, "unlink", unlink)
        xt._cleanup_native_bridge_helper_file(None)
        xt._cleanup_native_bridge_helper_file(str(helper))
    unlink.assert_called_once_with(str(helper))
    assert helper.read_bytes() == b"fixture"
    assert logs == ["Native bridge helper cleanup failed: PermissionError: denied"]


@pytest.mark.parametrize("invalid", [b"settings", "", "bad\x00path", object()])
def test_invalid_settings_targets_are_never_read_or_created(xt, monkeypatch, invalid):
    """Inputs: invalid settings path objects. Output: empty/default preferences without reading files."""
    opener = Mock(side_effect=AssertionError("Invalid settings target was opened"))
    monkeypatch.setattr(Path, "open", opener)
    assert (
        xt._connector_settings_target_safety_error(invalid)
        == "Connector settings path is invalid"
    )
    assert xt._load_connector_settings(invalid) == {}
    assert xt._load_connector_show_log_preference(invalid) is True
    opener.assert_not_called()


@pytest.mark.parametrize(
    "contents", [b"\xff\xfe\x00", b'OMERO_SHOW_LOG="unterminated', b""]
)
def test_unreadable_or_malformed_settings_keep_safe_defaults_and_original_bytes(
    xt, tmp_path, monkeypatch, contents
):
    """Inputs: malformed or non-UTF8 settings. Output: safe defaults, bounded diagnostics and unchanged original file."""
    target = xt._connector_settings_env_path(tmp_path)
    target.parent.mkdir()
    body = contents.replace(
        b"OMERO_SHOW_LOG", xt.CONNECTOR_SETTINGS_SHOW_LOG_KEY.encode()
    )
    target.write_bytes(body)
    messages = []
    monkeypatch.setattr(xt, "_log_connector_settings_event", messages.append)
    assert xt._load_connector_settings(target) == {}
    assert xt._load_connector_show_log_preference(target) is True
    assert target.read_bytes() == body
    assert all(
        str(target) not in message and "unterminated" not in message
        for message in messages
    )


@pytest.mark.parametrize("denied", ["open", "stat"])
def test_settings_access_failure_reports_type_without_sensitive_diagnostic(
    xt, tmp_path, monkeypatch, denied
):
    """Inputs: denied access to a regular settings file. Output: defaults, unchanged bytes and no exception-detail disclosure."""
    target = xt._connector_settings_env_path(tmp_path)
    target.parent.mkdir()
    body = b"OMERO_HOST=example.test\n"
    target.write_bytes(body)
    messages = []
    monkeypatch.setattr(xt, "_log_connector_settings_event", messages.append)
    with monkeypatch.context() as boundary:
        boundary.setattr(
            Path, denied, Mock(side_effect=PermissionError("private diagnostic marker"))
        )
        assert xt._load_connector_settings(target) == {}
        assert xt._load_connector_show_log_preference(target) is True
    assert target.read_bytes() == body
    assert bool(messages) is (denied == "open")
    assert all("private diagnostic marker" not in message for message in messages)


@pytest.mark.parametrize("existing", [False, True])
def test_settings_backup_rotation_refuses_a_concurrently_created_destination(
    xt, tmp_path, monkeypatch, existing
):
    """Inputs: a backup destination created after enumeration. Output: no overwrite of current settings or competing backup."""
    target = xt._connector_settings_env_path(tmp_path)
    target.parent.mkdir()
    target.write_bytes(b"current settings")
    first = xt._connector_settings_backup_path(target, 1)
    if existing:
        first.write_bytes(b"older settings")
    collision = xt._connector_settings_backup_path(target, 2 if existing else 1)
    enumerate_backups = xt._existing_connector_settings_backup_indexes

    def create_after_enumeration(path):
        """Inputs: current backup inventory. Output: concurrent backup creation before the caller renames anything."""
        result = enumerate_backups(path)
        collision.write_bytes(b"competing backup")
        return result

    monkeypatch.setattr(
        xt, "_existing_connector_settings_backup_indexes", create_after_enumeration
    )
    with pytest.raises(OSError, match="destination already exists"):
        xt._rotate_connector_settings_backups(target)
    assert target.read_bytes() == b"current settings"
    assert collision.read_bytes() == b"competing backup"
    if existing:
        assert first.read_bytes() == b"older settings"


def test_backup_rotation_refuses_an_outside_settings_target(xt, tmp_path):
    """Inputs: a regular file outside the settings contract. Output: no rename or backup of unrelated user data."""
    target = tmp_path / "unrelated-data"
    target.write_bytes(b"preserved")
    with pytest.raises(OSError, match="unexpected file name"):
        xt._rotate_connector_settings_backups(target)
    assert target.read_bytes() == b"preserved"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize(
    "dimensions,expected_signature,has_content",
    [
        ({}, "present", False),
        ({"GetSizeX": 16}, (16, None, None, None, None), True),
        ({"GetSizeX": 0}, (0, None, None, None, None), False),
        ({"GetSizeX": -1}, (-1, None, None, None, None), False),
        ({"GetSizeX": "invalid"}, "present", False),
        ({"GetSizeX": OSError("lost handle")}, "present", False),
        (
            {"GetSizeX": 16, "GetSizeY": OSError("lost handle")},
            (16, None, None, None, None),
            False,
        ),
    ],
)
def test_imaris_dimension_probes_do_not_infer_success_from_failed_metadata(
    xt, dimensions, expected_signature, has_content
):
    """Inputs: partial, empty, or failed native metadata. Output: content requires positive readable dimensions, never a failed getter."""
    methods = {
        name: Mock(side_effect=value)
        if isinstance(value, Exception)
        else Mock(return_value=value)
        for name, value in dimensions.items()
    }
    dataset = SimpleNamespace(**methods)
    assert xt._imaris_data_set_signature(dataset) == expected_signature
    assert xt._imaris_data_set_has_content(dataset) is has_content
    assert xt._imaris_data_set_has_content(None) is False
    assert xt._current_imaris_data_set(object()) is None
    failed = Mock(side_effect=ConnectionResetError("native handle lost"))
    assert xt._current_imaris_data_set(SimpleNamespace(GetDataSet=failed)) is None
    failed.assert_called_once_with()


def test_native_handle_failure_does_not_try_other_methods_as_false_proof_of_liveness(
    xt,
):
    """Inputs: a failed cheap native probe and another callable method. Output: rejected stale handle without calling a second probe or file opener."""
    failed = Mock(side_effect=ConnectionResetError("native handle lost"))
    second, opener = Mock(return_value=1), Mock()
    app = SimpleNamespace(
        FileOpen=opener, GetCurrentFileName=failed, GetNumberOfImages=second
    )
    assert xt._imaris_application_handle_is_live(app) is False
    failed.assert_called_once_with()
    second.assert_not_called()
    opener.assert_not_called()


@pytest.mark.parametrize("failure", ["missing_api", "open", "clone"])
def test_multi_image_handoff_does_not_install_partial_slots_after_native_failure(
    xt, tmp_path, monkeypatch, failure
):
    """Inputs: native slot API/open/clone failure. Output: no partial SetImage calls and original image bytes retained."""
    image = tmp_path / "source.ims"
    payload = b"\x89HDF\r\n\x1a\nfixture"
    image.write_bytes(payload)
    install = Mock()
    app = (
        SimpleNamespace()
        if failure == "missing_api"
        else SimpleNamespace(SetImage=install)
    )
    opener = Mock(return_value=failure != "open")
    clone = Mock(return_value=None)
    monkeypatch.setattr(xt, "_open_file_in_imaris_with_mode", opener)
    monkeypatch.setattr(xt, "_clone_current_imaris_dataset", clone)
    assert xt.open_files_as_imaris_image_slots([str(image)], app) is False
    install.assert_not_called()
    assert opener.call_count == int(failure != "missing_api")
    assert clone.call_count == int(failure == "clone")
    assert image.read_bytes() == payload


@pytest.mark.parametrize(
    "response,expected",
    [
        ("", None),
        ("BRIDGE_RUNNER_PROBE_OK", "resolved the current Imaris session"),
        ("BRIDGE_RUNNER_OPENED", "completed IMS open request"),
        ("BRIDGE_RUNNER_OPENED_MANY", "completed IMS open request"),
        ("BRIDGE_RUNNER_HANDLE_UNAVAILABLE", "could not resolve"),
        ("BRIDGE_RUNNER_OPEN_METHOD_UNAVAILABLE", "file-open API is unavailable"),
        ("BRIDGE_RUNNER_INVALID_FILE_LIST", "result: BRIDGE_RUNNER_INVALID_FILE_LIST"),
        ("BRIDGE_RUNNER_MISSING_FILE", "result: BRIDGE_RUNNER_MISSING_FILE"),
        ("BRIDGE_RUNNER_INVALID_IMS", "result: BRIDGE_RUNNER_INVALID_IMS"),
        ("BRIDGE_RUNNER_OPEN_FAILED", "result: BRIDGE_RUNNER_OPEN_FAILED"),
        ("BRIDGE_RUNNER_OPEN_UNVERIFIED", "result: BRIDGE_RUNNER_OPEN_UNVERIFIED"),
        ("BRIDGE_RUNNER_EXCEPTION:" + "x" * 5000, "result: BRIDGE_RUNNER_EXCEPTION:"),
        ("unexpected " + "x" * 5000, "stdout: unexpected"),
    ],
)
def test_native_bridge_diagnostics_distinguish_verified_open_from_failures(
    xt, monkeypatch, response, expected
):
    """Inputs: native helper outcome or oversized output. Output: bounded, distinct diagnostics without false success."""
    messages = []
    monkeypatch.setattr(xt, "_xt_debug", messages.append)
    xt._log_native_bridge_stdout(response, "fixture")
    if expected is None:
        assert messages == []
    else:
        assert len(messages) == 1
        assert expected in messages[0]
        assert len(messages[0]) <= 4050
        assert ("completed IMS open request" in messages[0]) is response.startswith(
            "BRIDGE_RUNNER_OPENED"
        )


def test_import_probe_reports_real_missing_module_without_loading_native_bridges(xt):
    """Inputs: a standard module and an absent optional module. Output: accurate import diagnostics without native bridge initialization."""
    assert xt._probe_module_import("math") == {"ok": True, "error": ""}
    absent = "omero_fixture_optional_module_that_does_not_exist"
    result = xt._probe_module_import(absent)
    assert result["ok"] is False
    assert absent in result["error"]
    assert absent not in xt.sys.modules
    assert xt._probe_loaded_bridge_module_import("math") == {"ok": True, "error": ""}
    assert xt._probe_loaded_bridge_module_import(absent) == {
        "ok": False,
        "error": "not loaded; in-process import skipped",
    }


@pytest.mark.parametrize("value", [None, b"folder", "", "   ", object()])
def test_arena_folder_identity_rejects_nontext_and_empty_values(xt, value):
    """Inputs: invalid folder identities. Output: no matching identity or environment expansion."""
    assert xt._folder_path_identity(value) == ""
    assert xt._expand_windows_environment_variables(value) == ""


def test_folder_identity_normalization_errors_do_not_match_a_real_folder(
    xt, monkeypatch
):
    """Inputs: a native path normalizer failure. Output: an empty identity, not a partial path."""
    native = SimpleNamespace(**vars(xt.ntpath))
    native.normpath = Mock(side_effect=ValueError("invalid native path"))
    monkeypatch.setattr(xt, "ntpath", native)
    assert xt._folder_path_identity(r"C:\sample") == ""
    native.normpath.assert_called_once_with(r"C:\sample")


def test_arena_registry_enumeration_closes_keys_and_skips_unavailable_versions(xt):
    """Inputs: mixed vendor keys with one missing Arena subkey. Output: only existing versioned keys, all handles closed."""
    root, arena = SimpleNamespace(Close=Mock()), SimpleNamespace(Close=Mock())
    registry = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_READ=1,
        OpenKey=Mock(side_effect=[root, OSError("Arena not installed"), arena]),
        EnumKey=Mock(
            side_effect=["unrelated", "Imaris 10", "Imaris x64 11.0", OSError("end")]
        ),
    )
    expected_path = (
        xt.IMARIS_ARENA_VENDOR_REGISTRY_ROOT
        + "\\Imaris x64 11.0\\"
        + xt.IMARIS_ARENA_DATA_MANAGEMENT_SUBKEY
    )
    assert list(xt._iter_existing_imaris_arena_registry_key_paths(registry)) == [
        ((11, 0), expected_path)
    ]
    assert registry.OpenKey.call_count == 3
    assert all(
        call.args[0] is registry.HKEY_CURRENT_USER
        for call in registry.OpenKey.call_args_list
    )
    root.Close.assert_called_once_with()
    arena.Close.assert_called_once_with()


def test_registry_enumeration_unavailable_root_and_early_stop_release_resources(xt):
    """Inputs: missing provider, denied root, and a consumer stopping early. Output: no fabricated entries or leaked root handles."""
    assert list(xt._iter_existing_imaris_arena_registry_key_paths(None)) == []
    root, arena = SimpleNamespace(Close=Mock()), SimpleNamespace(Close=Mock())
    registry = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        OpenKey=Mock(side_effect=PermissionError("denied")),
        EnumKey=Mock(side_effect=["Imaris 11"]),
    )
    assert list(xt._iter_existing_imaris_arena_registry_key_paths(registry)) == []
    registry.EnumKey.assert_not_called()
    registry.OpenKey.side_effect = [root, arena]
    iterator = xt._iter_existing_imaris_arena_registry_key_paths(registry)
    assert next(iterator)[0] == (11, 0)
    arena.Close.assert_called_once_with()
    iterator.close()
    root.Close.assert_called_once_with()


@pytest.mark.parametrize(
    "failure", [OSError("missing key"), ValueError("bad value"), None]
)
def test_registry_executable_lookup_falls_through_without_creating_keys(xt, failure):
    """Inputs: an absent, invalid, or empty first registry value. Output: second installation is found and opened handles close."""
    from unittest.mock import MagicMock

    first, second = MagicMock(), MagicMock()
    first.__enter__.return_value = first
    second.__enter__.return_value = second
    first_result = failure if failure is not None else ("", 1)
    registry = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=Mock(side_effect=[first, second]),
        QueryValueEx=Mock(side_effect=[first_result, (r"C:\Imaris 11\Imaris.exe", 1)]),
    )
    assert list(xt._iter_imaris_registry_executable_candidates(None)) == []
    assert list(xt._iter_imaris_registry_executable_candidates(registry)) == [
        r"C:\Imaris 11\Imaris.exe"
    ]
    assert [call.args for call in registry.OpenKey.call_args_list] == list(
        xt._imaris_registry_locations(registry)
    )
    first.__exit__.assert_called_once()
    second.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize(
    "failure", [OSError("registry unavailable"), RuntimeError("provider failure")]
)
def test_optional_arena_registration_failure_preserves_downloaded_image(
    xt, tmp_path, monkeypatch, failure
):
    """Inputs: a registry-discovery failure after successful download. Output: explicit failure without touching image bytes."""
    image_path = tmp_path / "image.ims"
    image_path.write_bytes(b"\x89HDF\r\n\x1a\nretained")
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "nt"
    monkeypatch.setattr(xt, "os", platform)
    monkeypatch.setattr(xt, "_safe_is_directory", lambda path: path == r"C:\fixture")
    monkeypatch.setattr(
        xt, "_imaris_arena_registry_key_candidates", Mock(side_effect=failure)
    )
    logs = []
    monkeypatch.setattr(xt, "_xt_debug", logs.append)
    registry = SimpleNamespace(OpenKey=Mock(), SetValueEx=Mock())
    assert (
        xt._append_imaris_arena_observed_folder(
            r"C:\fixture",
            imaris_executable="fixture-installation",
            winreg_module=registry,
        )
        is False
    )
    assert logs and type(failure).__name__ in logs[-1]
    registry.OpenKey.assert_not_called()
    registry.SetValueEx.assert_not_called()
    assert image_path.read_bytes() == b"\x89HDF\r\n\x1a\nretained"


def test_optional_arena_registration_requires_an_available_registry(
    xt, tmp_path, monkeypatch
):
    """Inputs: no registry provider on an otherwise valid native folder. Output: explicit refusal and unchanged folder contents."""
    platform = SimpleNamespace(**vars(xt.os))
    platform.name = "nt"
    monkeypatch.setattr(xt, "os", platform)
    monkeypatch.setattr(xt, "_safe_is_directory", lambda path: path == r"C:\fixture")
    monkeypatch.setattr(xt, "_import_winreg_module", lambda: None)
    logs = []
    monkeypatch.setattr(xt, "_xt_debug", logs.append)
    before = list(tmp_path.iterdir())
    assert xt._append_imaris_arena_observed_folder(r"C:\fixture") is False
    assert logs[-1].endswith("winreg unavailable")
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    "name,extension,expected",
    [
        ("a." + "x" * 220, None, "a." + "x" * 178),
        ("CON" + " " * 190 + ".ims", None, "_CON.ims"),
        ("NUL" + " " * 190 + ".tiff", ".tiff", "_NUL.tiff"),
        ("CON.measurement.ims", None, "_CON.measurement.ims"),
        ("nul.data.ome.tif", ".tif", "_nul.data.ome.tif"),
        ("sample " + "x" * 200 + ".ims", ".ims", None),
    ],
)
def test_download_filename_truncation_preserves_safe_filesystem_names(
    xt, tmp_path, name, extension, expected
):
    """Inputs: overlong names and extensions. Output: bounded, writable, nonreserved filenames."""
    result = xt._safe_download_filename(name, "download", extension)
    assert len(result.encode("ascii")) <= 180
    assert Path(result).stem.upper() not in xt._WINDOWS_RESERVED_FILENAMES
    assert xt._is_valid_windows_path_component(result)
    if expected is not None:
        assert result == expected
    if extension:
        assert result.endswith(extension)
    target = tmp_path / result
    with target.open("xb") as stream:
        stream.write(b"image-content")
    assert target.read_bytes() == b"image-content"
    assert target.resolve().parent == tmp_path.resolve()


@pytest.mark.parametrize(
    "header,expected",
    [
        ("attachment; filename*=UTF-8''measurement%20one.ims", "measurement one.ims"),
        ('attachment; filename="measurement one.ims"', "measurement one.ims"),
        ("attachment; filename=measurement.ims; size=3", "measurement.ims"),
        ("inline", None),
        (None, None),
    ],
)
def test_download_header_filename_decoding_is_separate_from_path_validation(
    xt, header, expected
):
    """Inputs: standard disposition forms. Output: exact decoded filename or absence."""
    assert xt._extract_content_disposition_filename(header) == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("# comment", (None, None)),
        ('OMERO_HOST="example.test"', ("OMERO_HOST", "example.test")),
    ],
)
def test_settings_line_parser_preserves_values_and_ignores_comments(xt, line, expected):
    """Inputs: ordinary settings and comments. Output: exact key/value pair without execution."""
    assert xt._parse_connector_settings_env_line(line) == expected


@pytest.mark.parametrize("kind", ["file", "dir", "symlink", "missing", "fifo"])
def test_settings_path_classification_does_not_follow_links(xt, tmp_path, kind):
    """Inputs: real filesystem object kinds. Output: lstat identity without following a link."""
    target = tmp_path / "candidate"
    if kind == "file":
        target.write_bytes(b"preserved")
    elif kind == "dir":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(tmp_path / "absent-target")
    elif kind == "fifo":
        os.mkfifo(target)
    assert xt._path_kind_without_follow(target) == ("other" if kind == "fifo" else kind)


@pytest.mark.parametrize("value", [None, "bad\x00path"])
def test_invalid_settings_paths_are_reported_as_errors(xt, value):
    """Inputs: absent or invalid path values. Output: explicit classification failure."""
    assert xt._path_kind_without_follow(value) == "error"


def test_inaccessible_settings_path_is_not_misreported_as_missing(
    xt, monkeypatch, tmp_path
):
    """Inputs: permission-denied lstat. Output: error rather than a safe-to-create result."""
    denied = Mock(side_effect=PermissionError("denied"))
    monkeypatch.setattr(Path, "lstat", denied)
    assert xt._path_kind_without_follow(tmp_path / "settings") == "error"
    denied.assert_called_once()


def test_log_open_wrapper_failure_closes_its_allocated_descriptor(
    xt, tmp_path, monkeypatch
):
    """Inputs: fdopen failure after a real open. Output: descriptor closed, no log message written."""
    target = Path(xt._xt_log_path())
    assert target.is_relative_to(tmp_path)
    descriptors = []
    original = os.open

    def opened(*args, **kwargs):
        """Inputs: native open arguments. Output: real descriptor retained for leak verification."""
        descriptor = original(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(xt.os, "open", opened)
    monkeypatch.setattr(
        xt.os, "fdopen", Mock(side_effect=OSError("wrapper unavailable"))
    )
    xt._xt_write_log(str(target), "must not be written")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert target.read_bytes() == b""


def test_log_directory_failure_does_not_attempt_to_open_a_file(
    xt, monkeypatch, tmp_path
):
    """Inputs: unavailable private log directory. Output: no open call or escaped file."""
    target = Path(xt._xt_log_path())
    assert target.is_relative_to(tmp_path)
    monkeypatch.setattr(xt, "_ensure_xt_log_directory", Mock(return_value=False))
    opened = Mock(side_effect=AssertionError("no log file may be opened"))
    monkeypatch.setattr(xt.os, "open", opened)
    xt._xt_write_log(str(target), "message")
    opened.assert_not_called()
    assert not target.exists()


def test_log_rotation_never_moves_or_modifies_a_symlink_target(
    xt, tmp_path, monkeypatch
):
    """Inputs: oversized log and linked backup. Output: normal rotation, external content unchanged."""
    target = tmp_path / "connector.log"
    target.write_bytes(b"current")
    external = tmp_path / "unrelated"
    external.write_bytes(b"untouched")
    backup = xt._xt_log_backup_path(target, 1)
    backup.symlink_to(external)
    monkeypatch.setattr(xt, "XT_LOG_MAX_BYTES", 2)
    monkeypatch.setattr(xt, "XT_LOG_BACKUP_COUNT", 2)
    xt._rotate_xt_log_if_needed(target, 1)
    assert not target.exists()
    assert not backup.is_symlink() and backup.read_bytes() == b"current"
    assert external.read_bytes() == b"untouched"


def test_failed_log_rotation_preserves_the_original_file(xt, tmp_path, monkeypatch):
    """Inputs: denied replacement of an oversized log. Output: original content remains readable."""
    target = tmp_path / "connector.log"
    target.write_bytes(b"current")
    monkeypatch.setattr(xt, "XT_LOG_MAX_BYTES", 2)
    replace = Mock(side_effect=PermissionError("denied"))
    monkeypatch.setattr(xt.os, "replace", replace)
    xt._rotate_xt_log_if_needed(target, 1)
    assert target.read_bytes() == b"current"
    replace.assert_called_once()


def test_fatal_gui_error_uses_console_when_tk_is_unavailable(xt, monkeypatch):
    """Inputs: failed message box. Output: the same diagnostic reaches the console once."""
    monkeypatch.setattr(
        xt,
        "messagebox",
        SimpleNamespace(showerror=Mock(side_effect=RuntimeError("no display"))),
    )
    console = Mock()
    monkeypatch.setattr(xt, "_xt_console_log", console)
    xt._xt_show_fatal("Startup failed", "Display unavailable")
    console.assert_called_once_with("Startup failed: Display unavailable")


@pytest.mark.parametrize(
    "busy,connected", [(True, False), (True, True), (False, True), (False, False)]
)
def test_connection_toggle_dispatches_one_explicit_action(xt, busy, connected):
    """Inputs: current connection state. Output: no competing action during login, otherwise one connect/disconnect."""
    dialog = object.__new__(xt.OMEROBrowserDialog)
    dialog._connection_in_progress = busy
    dialog._connected = connected
    dialog._connect, dialog._disconnect = Mock(), Mock()
    dialog._toggle_connection()
    assert dialog._connect.call_count == int(not busy and not connected)
    assert dialog._disconnect.call_count == int(not busy and connected)


@pytest.mark.parametrize("selected", ["none", "current", "explicit"])
def test_folder_capability_uses_only_the_selected_client(xt, selected):
    """Inputs: absent, current or explicit client. Output: exact capability without cross-client queries."""
    dialog = object.__new__(xt.OMEROBrowserDialog)
    current = SimpleNamespace(
        get_folder_export_capability=Mock(
            return_value={"available": False, "reason": "unsupported"}
        )
    )
    explicit = SimpleNamespace(
        get_folder_export_capability=Mock(return_value={"available": True})
    )
    dialog.client = None if selected == "none" else current
    result = dialog._detect_folder_export_after_connection(
        explicit if selected == "explicit" else None
    )
    if selected == "none":
        assert result == {
            "available": False,
            "reason": "No OMERO.web client is available.",
        }
    else:
        assert result == (
            {"available": True}
            if selected == "explicit"
            else {"available": False, "reason": "unsupported"}
        )
    assert current.get_folder_export_capability.call_count == int(selected == "current")
    assert explicit.get_folder_export_capability.call_count == int(
        selected == "explicit"
    )


def test_messagebox_legacy_signature_fallback_preserves_result_and_arguments(xt):
    """Inputs: legacy two-argument dialog function. Output: one invocation after signature negotiation."""
    calls = []

    def legacy(title, message):
        """Inputs: dialog text. Output: caller's affirmative result with exact received text."""
        calls.append((title, message))
        return True

    assert (
        xt.OMEROBrowserDialog._call_messagebox_function(
            legacy, "Title", "Message", object(), icon="warning"
        )
        is True
    )
    assert calls == [("Title", "Message")]


@pytest.mark.parametrize("fail_at", ["initial", "fallback"])
def test_messagebox_does_not_replay_internal_type_errors(xt, fail_at):
    """Inputs: TypeError unrelated to signature compatibility. Output: original exception, bounded invocation count."""
    failure = TypeError("dialog conversion failed")
    function = Mock(
        side_effect=(
            [TypeError("unexpected keyword parent"), failure]
            if fail_at == "fallback"
            else failure
        )
    )
    with pytest.raises(TypeError) as caught:
        xt.OMEROBrowserDialog._call_messagebox_function(
            function, "Title", "Message", object(), icon="warning"
        )
    assert caught.value is failure
    assert function.call_count == (2 if fail_at == "fallback" else 1)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://[invalid/path", "<url>"),
        ("https://example.test/items/17/?&", "/items/<id>/"),
        (
            "https://example.test/items/17/?key=one&key=two&group=1&group=2",
            "/items/<id>/?key=<redacted>&group=1",
        ),
    ],
)
def test_diagnostic_urls_remove_authority_ids_and_repeated_private_values(
    xt, url, expected
):
    """Inputs: malformed or repeated-query URLs. Output: stable diagnostic shape without private values."""
    assert xt._safe_url_for_log(url) == expected


@pytest.mark.parametrize(
    "component",
    [".", "..", "", "name.", "name ", "NUL", "COM1.txt", "bad:name", "line\nfeed"],
)
def test_invalid_native_folder_components_are_rejected(xt, component):
    """Inputs: invalid native path component. Output: refusal before any filesystem write."""
    assert xt._is_valid_windows_path_component(component) is False


@pytest.mark.parametrize(
    "path",
    [
        r"relative\path",
        r"\rooted-without-drive",
        r"\\server\bad:share\folder",
        r"\\server",
        r"C:\NUL\folder",
    ],
)
def test_incomplete_or_reserved_native_paths_are_rejected(xt, path):
    """Inputs: ambiguous or reserved native folder path. Output: invalid result without path creation."""
    assert xt._is_structurally_valid_windows_folder_path(path) is False


@pytest.mark.parametrize(
    "error", [OSError("unavailable"), TypeError("invalid"), ValueError("invalid")]
)
def test_directory_probe_failures_are_non_writable(xt, tmp_path, monkeypatch, error):
    """Inputs: failing native directory probe. Output: safe false result instead of a write attempt."""
    probe = Mock(side_effect=error)
    monkeypatch.setattr(xt.os.path, "isdir", probe)
    assert xt._safe_is_directory(tmp_path) is False
    probe.assert_called_once_with(tmp_path)


def test_log_path_failure_does_not_fall_back_to_working_directory(xt, monkeypatch):
    """Inputs: unavailable user settings root. Output: no log path and no unsafe alternate file."""
    monkeypatch.setattr(
        xt,
        "_connector_settings_env_path",
        Mock(side_effect=OSError("home unavailable")),
    )
    assert xt._xt_log_path() == ""


def test_log_target_metadata_failure_is_rejected(xt, monkeypatch, tmp_path):
    """Inputs: denied metadata for an otherwise allowed log path. Output: rejected target without opening it."""
    target = Path(xt._xt_log_path())
    assert target.is_relative_to(tmp_path)
    monkeypatch.setattr(Path, "is_symlink", Mock(side_effect=PermissionError("denied")))
    assert xt._safe_xt_log_file(target) is None


def test_settings_home_unavailability_is_explicit(xt, monkeypatch):
    """Inputs: no usable absolute home candidate. Output: diagnostic error instead of writing under the working directory."""
    monkeypatch.setattr(
        xt._NATIVE_PATH_CLASS, "home", Mock(side_effect=OSError("no user home"))
    )
    monkeypatch.delenv("HOME", raising=False)
    with pytest.raises(OSError, match="absolute user home"):
        xt._connector_user_home()


@pytest.fixture
def xt(tmp_path, monkeypatch):
    """Inputs: private home. Output: an isolated connector module with no live connection."""
    monkeypatch.setenv("HOME", str(tmp_path))
    source = (
        Path(__file__).resolve().parents[1]
        / "omero_imaris_connector"
        / "XTOmeroConnector.py"
    )
    spec = importlib.util.spec_from_file_location("xt_boundary_contracts", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("buffered", [False, True])
@pytest.mark.parametrize("kind", ["extension", "trailer", "total_trailers"])
def test_chunk_framing_limits_reject_excess_without_consuming_image_data(
    xt, monkeypatch, buffered, kind
):
    """Inputs: excessive framing over a real socket. Output: bounded rejection and socket cleanup."""
    monkeypatch.setattr(xt, "CANCELLABLE_HTTP_MAX_HEADER_BYTES", 1024)
    line_limit = 64 * 1024
    if kind == "extension":
        wire = b"1;" + b"x" * line_limit + b"\r\na\r\n0\r\n\r\n"
    elif kind == "trailer":
        wire = b"0\r\nX-Long: " + b"x" * line_limit + b"\r\n\r\n"
    else:
        wire = b"0\r\n" + (b"X-Part: " + b"x" * 350 + b"\r\n") * 3 + b"\r\n"
    reader, writer = socket.socketpair()
    headers = Message()
    headers["Transfer-Encoding"] = "chunked"
    try:
        if not buffered:
            writer.sendall(wire)
        writer.shutdown(socket.SHUT_WR)
        with xt._CancellableHTTPResponse(
            reader,
            "https://omero.example.test/download/",
            200,
            "OK",
            headers,
            wire if buffered else b"",
            threading.Event(),
            5,
        ) as response:
            with pytest.raises(xt.http.client.HTTPException, match="too large"):
                response.read()
        assert response.closed and reader.fileno() == -1
    finally:
        reader.close()
        writer.close()


@pytest.mark.parametrize("prefix_bytes", [0, 1, 9, 32, 33])
def test_chunk_reader_preserves_coalesced_data_at_exact_framing_limit(
    xt, monkeypatch, prefix_bytes
):
    """Inputs: exact-limit extension split across socket/buffer. Output: byte-exact image and trailers consumed once."""
    monkeypatch.setattr(xt, "CANCELLABLE_HTTP_MAX_LINE_BYTES", 32)
    monkeypatch.setattr(xt, "CANCELLABLE_HTTP_MAX_HEADER_BYTES", 32)
    wire = b"3;" + b"x" * 28 + b"\r\nabc\r\n0\r\nX: " + b"y" * 25 + b"\r\n\r\n"
    reader, writer = socket.socketpair()
    headers = Message()
    headers["Transfer-Encoding"] = "chunked"
    try:
        writer.sendall(wire[prefix_bytes:])
        writer.shutdown(socket.SHUT_WR)
        with xt._CancellableHTTPResponse(
            reader,
            "https://omero.example.test/download/",
            200,
            "OK",
            headers,
            wire[:prefix_bytes],
            threading.Event(),
            5,
        ) as response:
            assert response.read(0) == b""
            assert response.read(2) == b"ab"
            assert response.read() == b"c"
            assert response.read(1) == b""
            assert response.geturl() == "https://omero.example.test/download/"
        response.close()
        assert response.closed and reader.fileno() == -1
    finally:
        reader.close()
        writer.close()


@pytest.mark.parametrize("retained_password", [False, True])
@pytest.mark.parametrize("authenticated", [False, True])
def test_explicit_reauthentication_never_invents_credentials_or_success(
    xt, retained_password, authenticated
):
    """Inputs: explicit reauthentication with/without credentials. Output: one attempt at most and truthful session state."""
    client = xt.OMEROWebClient(
        "localhost",
        443,
        "fixture",
        "fixture-password" if retained_password else "",
        "https",
    )
    client.session_id, client.csrf_token, client.session_key = "old", "csrf", "key"

    def connect():
        """Inputs: cleared rejected session. Output: replacement credentials only after acceptance."""
        assert (client.session_id, client.csrf_token, client.session_key) == (
            None,
            None,
            None,
        )
        if authenticated:
            client.session_id, client.csrf_token, client.session_key = (
                "new",
                "new-csrf",
                "new-key",
            )
        return authenticated

    client.connect = Mock(side_effect=connect)
    assert client.reauthenticate("explicit test login") is (
        retained_password and authenticated
    )
    assert client.connect.call_count == int(retained_password)
    if not retained_password:
        assert (client.session_id, client.csrf_token, client.session_key) == (
            "old",
            "csrf",
            "key",
        )
    elif authenticated:
        assert (client.session_id, client.csrf_token, client.session_key) == (
            "new",
            "new-csrf",
            "new-key",
        )
    else:
        assert (client.session_id, client.csrf_token, client.session_key) == (
            None,
            None,
            None,
        )


@pytest.mark.parametrize(
    "mode",
    [
        "settings_failure",
        "handle_failure",
        "gui_failure",
        "console_failure",
        "quiet_failure",
        "interrupt",
    ],
)
def test_entrypoint_failure_always_restores_interrupt_guard_and_reports_truthfully(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: startup/UI boundary failures. Output: restored console handlers, bounded operator notification, no real native launch."""
    monkeypatch.setattr(
        xt,
        "_windows_platform_status",
        lambda: SimpleNamespace(supported=True, message="fixture platform"),
    )
    monkeypatch.setattr(xt, "_xt_log_path", lambda: str(tmp_path / "connector.log"))
    handlers = object()
    monkeypatch.setattr(xt, "_install_xt_console_interrupt_guard", lambda: handlers)
    restored = Mock()
    monkeypatch.setattr(xt, "_restore_xt_console_interrupt_guard", restored)
    monkeypatch.setattr(
        xt, "_connector_settings_env_path", lambda: str(tmp_path / "settings.env")
    )
    monkeypatch.setattr(
        xt,
        "_prepare_connector_settings_for_current_version",
        Mock(
            side_effect=PermissionError("fixture settings")
            if mode == "settings_failure"
            else None
        ),
    )
    monkeypatch.setattr(xt, "_ensure_connector_settings_imaris_executable", Mock())
    monkeypatch.setattr(
        xt, "_load_connector_show_log_preference", lambda _path: mode != "quiet_failure"
    )
    monkeypatch.setattr(
        xt,
        "_configure_xt_console_visibility",
        lambda enabled: setattr(
            xt._XT_RUNTIME_STATE, "console_output_enabled", enabled
        ),
    )
    monkeypatch.setattr(xt, "_set_process_window_title", Mock())
    monkeypatch.setattr(xt, "_ensure_tk_loaded", Mock())
    monkeypatch.setattr(xt, "_log_imaris_xt_diagnostics", Mock())
    native = SimpleNamespace(FileOpen=Mock(), GetVersion=Mock(return_value="fixture"))
    monkeypatch.setattr(
        xt, "_looks_like_imaris_application", lambda value: value is native
    )
    monkeypatch.setattr(
        xt,
        "_resolve_imaris_application",
        Mock(
            side_effect=OSError("bridge failed") if mode == "handle_failure" else None,
            return_value=native,
        ),
    )
    show = Mock(
        side_effect=KeyboardInterrupt()
        if mode == "interrupt"
        else RuntimeError("fixture GUI failure")
        if mode.endswith("failure")
        and mode not in {"settings_failure", "handle_failure"}
        else None
    )
    dialog = Mock(return_value=SimpleNamespace(show=show))
    monkeypatch.setattr(xt, "OMEROBrowserDialog", dialog)
    fatal, wait = (
        Mock(),
        Mock(
            side_effect=EOFError("closed console")
            if mode == "console_failure"
            else None
        ),
    )
    monkeypatch.setattr(xt, "_xt_show_fatal", fatal)
    monkeypatch.setattr(xt, "_xt_wait_for_enter_to_close", wait)
    xt.XTOmeroConnector(native)
    restored.assert_called_once_with(handlers)
    dialog.assert_called_once_with(native, imaris_id=native)
    show.assert_called_once_with()
    failed = mode in {"gui_failure", "console_failure", "quiet_failure"}
    assert fatal.call_count == int(failed)
    assert wait.call_count == int(failed and mode != "quiet_failure")
    if failed:
        assert "fixture GUI failure" in fatal.call_args.args[1]
    assert not native.FileOpen.called


@pytest.mark.parametrize("operation", ["send", "receive"])
@pytest.mark.parametrize(
    "error_type", [BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError]
)
def test_tls_io_retries_wait_for_the_direction_requested_by_openssl(
    xt, monkeypatch, operation, error_type
):
    """Inputs: nonblocking TLS retry signals. Output: correct readiness wait, exact bytes, no replay of a partial send."""
    payload = b"verified bytes"
    sock = Mock()
    waits = []
    cancel = threading.Event()
    deadline = time.time() + 5

    def wait(
        value,
        *,
        readable=False,
        writable=False,
        buffered_read=False,
        cancel_event=None,
        deadline=0,
    ):
        """Inputs: requested readiness direction. Output: record the state-machine transition."""
        assert value is sock and cancel_event is cancel
        assert deadline > time.time()
        assert buffered_read is (operation == "receive")
        waits.append((readable, writable))

    monkeypatch.setattr(xt, "_socket_wait", wait)
    if operation == "send":
        sock.send.side_effect = [2, error_type(), len(payload) - 2]
        xt._socket_send_all(sock, payload, cancel, deadline)
        assert [bytes(call.args[0]) for call in sock.send.call_args_list] == [
            payload,
            payload[2:],
            payload[2:],
        ]
        expected = (
            (True, False) if error_type is ssl.SSLWantReadError else (False, True)
        )
        assert waits == [(False, True), (False, True), expected]
    else:
        sock.recv.side_effect = [error_type(), payload]
        assert xt._socket_recv(sock, len(payload), cancel, deadline) == payload
        expected = (
            (False, True) if error_type is ssl.SSLWantWriteError else (True, False)
        )
        assert waits == [(True, False), expected]
        assert all(call.args == (len(payload),) for call in sock.recv.call_args_list)


@pytest.mark.parametrize("mode", ["cancelled", "expired", "pending"])
def test_tls_pending_bytes_cannot_bypass_cancellation_or_deadline(
    xt, monkeypatch, mode
):
    """Inputs: buffered TLS data and cancellation/deadline state. Output: safety checks win before immediate readiness."""
    sock = Mock(spec=ssl.SSLSocket)
    sock.pending.return_value = 7
    cancel = threading.Event()
    if mode == "cancelled":
        cancel.set()
    deadline = time.time() + (-1 if mode == "expired" else 5)
    select = Mock(
        side_effect=AssertionError("Buffered TLS must not wait on the OS socket")
    )
    monkeypatch.setattr(xt.select, "select", select)
    if mode == "pending":
        xt._socket_wait(
            sock,
            readable=True,
            buffered_read=True,
            cancel_event=cancel,
            deadline=deadline,
        )
    else:
        expected = (
            xt._ConnectorOperationCancelled if mode == "cancelled" else socket.timeout
        )
        with pytest.raises(expected):
            xt._socket_wait(
                sock,
                readable=True,
                buffered_read=True,
                cancel_event=cancel,
                deadline=deadline,
            )
    assert sock.pending.call_count == int(mode == "pending")
    select.assert_not_called()


def test_tls_write_wait_requires_wire_readiness_not_unrelated_buffered_body(
    xt, monkeypatch
):
    """Inputs: TLS write needs incoming protocol data while application bytes are buffered. Output: no busy loop on those bytes."""
    sock = Mock(spec=ssl.SSLSocket)
    sock.pending.return_value = 7
    select = Mock(return_value=([sock], [], []))
    monkeypatch.setattr(xt.select, "select", select)
    xt._socket_wait(sock, readable=True, deadline=time.time() + 5)
    select.assert_called_once()
    sock.pending.assert_not_called()


@pytest.mark.parametrize(
    "fractions",
    [
        None,
        [1, 2],
        [1, "invalid", 2],
        [0, 1, 1],
        [-1, 2, 2],
        [100, 1, 1],
        [float("nan"), 1, 1],
        [float("inf"), 1, 1],
        [1e308, 1e308, 1e308],
        [10**400, 1, 1],
    ],
)
def test_invalid_panel_sizes_cannot_propagate_nonfinite_geometry(xt, fractions):
    """Inputs: malformed or extreme panel proportions. Output: finite usable default geometry, not NaN or overflow."""
    result = xt._normalized_browser_panel_fractions(fractions)
    assert result == xt.BROWSER_PANEL_DEFAULT_FRACTIONS
    assert all(math.isfinite(value) and 0 < value < 1 for value in result)
    assert sum(result) == pytest.approx(1)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (7, 7),
        (" 7 ", 7),
        ("bad", None),
        ("9" * 5000, None),
        ("\u00b2", None),
        ("-7", -7),
    ],
)
def test_native_application_identifiers_are_converted_without_incidental_errors(
    xt, value, expected
):
    """Inputs: native callback ID variants. Output: exact numeric identity or no identity, never a parsing crash."""
    assert xt._coerce_imaris_id(value) == expected


@pytest.mark.parametrize("integer_available", [False, True])
def test_native_identifier_with_unprintable_wrapper_uses_only_explicit_integer_conversion(
    xt, integer_available
):
    """Inputs: native wrapper whose string conversion fails. Output: its integer ID only when the wrapper supplies one."""

    class Wrapped:
        """Controlled boundary double for a native callback value."""

        def __str__(self):
            """Inputs: self. Output: native conversion failure."""
            raise TypeError("native value unavailable as text")

        def __int__(self):
            """Inputs: self. Output: exact native identity or declared failure."""
            if integer_available:
                return 17
            raise TypeError("native identity unavailable")

    assert xt._coerce_imaris_id(Wrapped()) == (17 if integer_available else None)


@pytest.mark.parametrize(
    "mode",
    ["module_api", "retry_then_ready", "unavailable", "factory_error", "api_error"],
)
@pytest.mark.parametrize("bridge_enabled", [False, True])
def test_native_application_resolution_is_bounded_and_uses_only_loaded_api(
    xt, monkeypatch, mode, bridge_enabled
):
    """Inputs: already-loaded native API outcomes. Output: truthful handle, bounded retries, no import of an incompatible bridge."""
    app = object()
    get = Mock(
        side_effect=OSError("fixture native failure")
        if mode == "api_error"
        else [None, app]
        if mode == "retry_then_ready"
        else None,
        return_value=None if mode == "unavailable" else app,
    )
    factory = Mock(
        side_effect=OSError("fixture factory failure")
        if mode == "factory_error"
        else None,
        return_value=SimpleNamespace(),
    )
    library = SimpleNamespace(GetApplication=get, ImarisLib=factory)
    monkeypatch.setitem(xt.sys.modules, "ImarisLib", library)
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: bridge_enabled)
    delays, diagnostics = Mock(), Mock()
    monkeypatch.setattr(xt.time, "sleep", delays)
    monkeypatch.setattr(xt, "_xt_debug", diagnostics)
    result = xt._resolve_imaris_application("17", retries=2, retry_interval=0)
    assert result is (app if mode in {"module_api", "retry_then_ready"} else None)
    assert get.call_count == (
        0
        if mode == "factory_error"
        else 2
        if mode in {"retry_then_ready", "unavailable"}
        else 1
    )
    assert all(call.args == (17,) for call in get.call_args_list)
    assert delays.call_count == int(mode in {"retry_then_ready", "unavailable"})
    if mode.endswith("error"):
        diagnostics.assert_called_once()
        assert "unavailable" in diagnostics.call_args.args[0]


@pytest.mark.parametrize("mode", ["absent", "ready", "failure", "delayed", "timeout"])
def test_native_image_count_verification_never_reports_an_unobserved_count(
    xt, monkeypatch, mode
):
    """Inputs: native count API capability and responses. Output: explicit completion only when the supported count reaches the target."""
    count = Mock(
        side_effect=ValueError("invalid native count")
        if mode == "failure"
        else [1, 2]
        if mode == "delayed"
        else None,
        return_value=1 if mode == "timeout" else 2,
    )
    app = (
        SimpleNamespace()
        if mode == "absent"
        else SimpleNamespace(GetNumberOfImages=count)
    )
    ticks = iter([0, 0, 1, 2])
    monkeypatch.setattr(xt.time, "time", lambda: next(ticks))
    monkeypatch.setattr(xt.time, "sleep", Mock())
    assert xt._wait_for_imaris_image_count(app, 2, timeout=1, interval=0) is (
        mode in {"absent", "ready", "delayed"}
    )
    if mode == "absent":
        count.assert_not_called()


@pytest.mark.parametrize(
    "mode",
    [
        "missing_file",
        "invalid_ims",
        "missing_method",
        "rejected",
        "accepted",
        "unobserved",
        "verified",
    ],
)
def test_direct_native_handoff_does_not_invent_success_or_modify_source_file(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: native file-open outcomes. Output: accepted/verified handoff only, with the downloaded bytes untouched."""
    path = tmp_path / "fixture.ims"
    data = b"invalid" if mode == "invalid_ims" else b"\x89HDF\r\n\x1a\nfixture"
    if mode != "missing_file":
        path.write_bytes(data)
    open_file = Mock(return_value=mode != "rejected")
    app = (
        SimpleNamespace()
        if mode == "missing_method"
        else SimpleNamespace(FileOpen=open_file)
    )
    monkeypatch.setattr(
        xt,
        "_file_open_call_candidates",
        lambda *_args, **_kwargs: [("FileOpen", (str(path), ""))],
    )
    monkeypatch.setattr(xt, "_imaris_app_snapshot", lambda _app: {})
    monkeypatch.setattr(xt, "_current_imaris_data_set", lambda _app: None)
    visible = Mock()
    monkeypatch.setattr(xt, "_ensure_imaris_current_dataset_visible", visible)
    monkeypatch.setattr(
        xt, "_wait_for_imaris_open_observable_effect", lambda *_args: mode == "verified"
    )
    verification = (
        "submission_only"
        if mode == "accepted"
        else "current_file"
        if mode == "invalid_ims"
        else "observable_effect"
    )
    assert xt._open_file_in_imaris_with_mode(path, app, verification) is (
        mode in {"accepted", "verified"}
    )
    assert open_file.call_count == int(
        mode not in {"missing_file", "invalid_ims", "missing_method"}
    )
    assert visible.call_count == int(mode == "verified")
    if mode != "missing_file":
        assert path.read_bytes() == data


@pytest.mark.parametrize(
    "payload,expected",
    [
        (None, "OMERO reported that the folder export failed."),
        ({}, "OMERO reported that the folder export failed."),
        ({"errors": ["", " specific failure ", "later"]}, "specific failure"),
        (
            {"errors": [], "messages": ["started", "", " final diagnostic "]},
            "final diagnostic",
        ),
    ],
)
def test_folder_failure_keeps_the_actionable_server_diagnostic(xt, payload, expected):
    """Inputs: documented folder error payloads. Output: first concrete error, final status or safe fallback."""
    assert xt.OMEROBrowserDialog._folder_export_failure_message(payload) == expected


@pytest.mark.parametrize(
    "mode", ["done", "error", "confirm", "decline", "cancel_before_confirm", "timeout"]
)
def test_folder_completion_wait_preserves_session_and_honors_confirmation(
    xt, monkeypatch, mode
):
    """Inputs: job lifecycle outcomes. Output: bounded polling, explicit confirmation, no success on rejection/cancellation."""
    dialog = object.__new__(xt.OMEROBrowserDialog)
    final = {"ok": True, "status": "done", "image_count": 2}
    initial = {"ok": True, "status": "pending", "confirmation_required": True}
    responses = (
        [initial, final]
        if mode in {"confirm", "decline", "cancel_before_confirm"}
        else [{"ok": True, "status": "error", "errors": ["fixture rejected"]}]
        if mode == "error"
        else [{"ok": True, "status": "pending"}]
        if mode == "timeout"
        else [final]
    )
    client = SimpleNamespace(
        session_id="original-session",
        get_folder_export_status=Mock(side_effect=responses),
        confirm_folder_export=Mock(),
    )
    dialog.client = client
    dialog._set_status = Mock()
    cancel = threading.Event()

    def confirm(_status):
        """Inputs: reported incompatible files. Output: explicit operator choice or intervening cancellation."""
        if mode == "cancel_before_confirm":
            cancel.set()
        return mode != "decline"

    dialog._confirm_folder_export_with_incompatible_files = Mock(side_effect=confirm)
    clock = {"now": 0}
    monkeypatch.setattr(xt, "time", SimpleNamespace(time=lambda: clock["now"]))
    monkeypatch.setattr(xt, "FOLDER_EXPORT_TIMEOUT", 1)
    monkeypatch.setattr(
        xt,
        "_wait_for_cancel_or_timeout",
        lambda *_args: clock.update(now=2 if mode == "timeout" else 0),
    )
    if mode in {"done", "confirm"}:
        assert (
            dialog._wait_for_folder_export_completion(
                "fixture", "/status/", "/confirm/", cancel
            )
            is final
        )
    else:
        expected = (
            xt._ConnectorOperationCancelled
            if mode == "cancel_before_confirm"
            else RuntimeError
        )
        with pytest.raises(expected):
            dialog._wait_for_folder_export_completion(
                "fixture", "/status/", "/confirm/", cancel
            )
    assert client.confirm_folder_export.call_count == int(mode == "confirm")
    if mode == "confirm":
        client.confirm_folder_export.assert_called_once_with("/confirm/")
    assert client.session_id == "original-session" and dialog.client is client


@pytest.mark.parametrize(
    "mode", ["already_running", "already_done", "live_handle", "needs_probe"]
)
def test_native_probe_is_single_flight_and_keeps_the_omero_session(
    xt, monkeypatch, mode
):
    """Inputs: cached/in-flight native probe states. Output: no duplicate worker and no mutation of authenticated client."""
    dialog = object.__new__(xt.OMEROBrowserDialog)
    client, app = object(), object()
    dialog.client, dialog.imaris = client, app
    dialog._native_bridge_probe_lock = threading.Lock()
    dialog._native_bridge_probe_done = threading.Event()
    dialog._native_bridge_probe_started = mode in {"already_running", "already_done"}
    dialog._native_bridge_probe_in_progress = mode == "already_running"
    if mode == "already_done":
        dialog._native_bridge_probe_done.set()
    dialog._native_bridge_probe_worker = Mock()
    thread = Mock()
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: True)
    monkeypatch.setattr(
        xt,
        "_imaris_application_handle_is_live",
        lambda value: value is app and mode == "live_handle",
    )
    monkeypatch.setattr(xt, "threading", SimpleNamespace(Thread=thread))
    dialog._start_native_bridge_probe()
    assert dialog.client is client
    assert thread.call_count == int(mode == "needs_probe")
    if mode == "needs_probe":
        thread.assert_called_once_with(
            target=dialog._native_bridge_probe_worker, daemon=True
        )
        thread.return_value.start.assert_called_once_with()
        assert dialog.imaris is None and dialog._native_bridge_probe_in_progress
    elif mode == "live_handle":
        assert dialog._native_bridge_available
        assert dialog._native_bridge_last_verified_at > 0
        assert dialog._native_bridge_probe_done.is_set()
        assert not dialog._native_bridge_probe_in_progress


@pytest.mark.parametrize(
    "value,parsed,editable",
    [
        (None, None, True),
        ("", None, True),
        (" ", None, False),
        ("invalid", None, False),
        ("0", None, True),
        ("-1", None, False),
        ("1", 1, True),
        ("65535", 65535, True),
        ("65536", None, False),
        ("100000", None, False),
        ("\u00b2", None, False),
        ("9" * 5000, None, False),
    ],
)
def test_port_validation_separates_incomplete_input_from_connectable_values(
    xt, value, parsed, editable
):
    """Inputs: typed and submitted port boundaries. Output: only valid ports can reach a connection."""
    assert xt._parse_port(value) == parsed
    assert xt._valid_port_entry_text(value) is editable


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://[::1]/", "[::1]"),
        (
            "http://[::1]/",  # DevSkim: ignore DS137138 -- loopback parser fixture; no connection
            "[::1]",
        ),
        ("https://[2001:db8::1]:443/", "[2001:db8::1]"),
        ("https://[2001:db8::1]:8443/", "[2001:db8::1]:8443"),
        (
            "http://[::1]:8080/",  # DevSkim: ignore DS137138 -- loopback parser fixture; no connection
            "[::1]:8080",
        ),
        ("https://omero.example.test:443/", "omero.example.test"),
        ("http://127.0.0.1:80/", "127.0.0.1"),
    ],
)
def test_host_header_uses_bracketed_ipv6_and_only_nondefault_ports(xt, url, expected):
    """Inputs: valid URL authorities. Output: unambiguous Host syntax for IP and DNS endpoints."""
    assert (
        xt.OMEROWebClient._host_header_for_url(urllib.parse.urlsplit(url)) == expected
    )


@pytest.mark.parametrize("kind", ["int", "float"])
@pytest.mark.parametrize(
    "raw,expected", [("", 3), ("invalid", 3), ("-5", 1), ("99", 10), ("7", 7)]
)
def test_numeric_environment_bounds_have_safe_defaults(
    xt, monkeypatch, kind, raw, expected
):
    """Inputs: operator numeric settings. Output: bounded values without changing the environment."""
    name = "XT_TEST_BOUNDARY_VALUE"
    monkeypatch.setenv(name, raw)
    function = getattr(xt, "_bounded_env_" + kind)
    assert function(name, 3, 1, 10) == expected
    assert os.environ[name] == raw


@pytest.mark.parametrize("raw", ["", "invalid", "-1", "1", "999999999999"])
def test_upload_buffers_are_bounded_by_the_declared_contract(xt, monkeypatch, raw):
    """Inputs: configured buffer size. Output: safe defaults or bounded allocations."""
    monkeypatch.setenv(xt.UPLOAD_CHUNK_SIZE_ENV, raw)
    expected = (
        xt.DEFAULT_UPLOAD_CHUNK_SIZE_BYTES
        if raw in {"", "invalid"}
        else max(
            xt.MIN_UPLOAD_CHUNK_SIZE_BYTES,
            min(int(raw), xt.MAX_UPLOAD_CHUNK_SIZE_BYTES),
        )
    )
    assert xt._upload_chunk_size_bytes() == expected


@pytest.mark.parametrize(
    "function,key,default,minimum,maximum",
    [
        (
            "_health_ping_timeout_seconds",
            "HEALTH_PING_TIMEOUT_ENV",
            "DEFAULT_HEALTH_PING_TIMEOUT_SECONDS",
            2,
            120,
        ),
        (
            "_health_ping_retry_attempts",
            "HEALTH_PING_RETRY_ATTEMPTS_ENV",
            "DEFAULT_HEALTH_PING_RETRY_ATTEMPTS",
            1,
            10,
        ),
        (
            "_health_ping_retry_delay_seconds",
            "HEALTH_PING_RETRY_DELAY_ENV",
            "DEFAULT_HEALTH_PING_RETRY_DELAY_SECONDS",
            0,
            30,
        ),
    ],
)
def test_health_settings_use_the_correct_key_and_bounds(
    xt, monkeypatch, function, key, default, minimum, maximum
):
    """Inputs: each health setting independently. Output: defaults and clamps without unbounded retries."""
    getter = getattr(xt, function)
    name = getattr(xt, key)
    monkeypatch.delenv(name, raising=False)
    assert getter() == getattr(xt, default)
    monkeypatch.setenv(name, "-1")
    assert getter() == minimum
    monkeypatch.setenv(name, "100000")
    assert getter() == maximum


@pytest.mark.parametrize(
    "reason,transient",
    [
        (ConnectionResetError("fixture reset"), True),
        ("service temporarily unavailable", True),
        ("fixture certificate validation failed", False),
    ],
)
def test_url_errors_retry_only_transient_failure_classes(xt, reason, transient):
    """Inputs: transport failures. Output: retry classification never masks permanent validation errors."""
    assert xt._is_transient_network_error(urllib.error.URLError(reason)) is transient
    assert not xt._is_transient_network_error(ValueError("invalid endpoint"))


@pytest.mark.parametrize(
    "payload,expected",
    [
        ([], None),
        ({}, None),
        ({"eventContext": []}, None),
        ({"eventContext": {}}, None),
        ({"eventContext": {"userId": "invalid"}}, None),
        ({"eventContext": {"userId": "17"}}, 17),
    ],
)
def test_current_user_identity_requires_a_parseable_api_value(xt, payload, expected):
    """Inputs: login metadata. Output: no manufactured user identity on missing or invalid fields."""
    assert xt.OMEROWebClient._extract_event_context_user_id(payload) == expected


@pytest.mark.parametrize(
    "payload,expected",
    [
        (None, []),
        ({}, []),
        ({"data": {"items": []}, "results": [1]}, [1]),
        ({"data": {"items": [2]}}, [2]),
    ],
)
def test_collection_wrappers_keep_real_rows_without_inventing_empty_objects(
    xt, payload, expected
):
    """Inputs: nested API result shapes. Output: actual collection or empty list."""
    client = xt.OMEROWebClient("localhost", 443, "fixture-user", "", "https")
    assert client._extract_items(payload) == expected


@pytest.mark.parametrize("mode", ["absent", "raises", "no_cookie"])
def test_cookie_lookup_failure_never_fabricates_authentication(xt, mode):
    """Inputs: unavailable cookie store. Output: empty header without exposing or replacing state."""
    client = xt.OMEROWebClient("localhost", 443, "fixture-user", "", "https")
    lookup = Mock(
        side_effect=ValueError("fixture store unavailable")
        if mode == "raises"
        else None
    )
    jar = None if mode == "absent" else SimpleNamespace(add_cookie_header=lookup)
    client.cookie_jar = jar
    assert client._cookie_header_for_url(client.base_url) == ""
    assert client.cookie_jar is jar
    assert lookup.call_count == int(mode != "absent")


@pytest.mark.parametrize("value", [None, "", "\x00"])
def test_invalid_local_path_never_produces_a_display_or_root(xt, value):
    """Inputs: unusable path values. Output: no accepted directory or misleading root label."""
    assert xt._folder_display_name(value) == ""
    assert xt._display_local_path(value) == ""
    assert not xt._is_filesystem_root(value)


@pytest.mark.parametrize(
    "kind", ["missing", "file", "empty", "symlink", "fifo", "unreadable"]
)
def test_folder_inventory_rejects_incomplete_or_unsafe_sources(
    xt, tmp_path, monkeypatch, kind
):
    """Inputs: real local source boundaries. Output: no partial inventory and unchanged source bytes."""
    root = tmp_path / "upload"
    expected = {
        "missing": "no longer exists",
        "file": "not a folder",
        "empty": "does not contain any files",
        "symlink": "symbolic links",
        "fifo": "only regular files",
        "unreadable": "Failed to read",
    }[kind]
    if kind == "file":
        root.write_bytes(b"keep")
    elif kind != "missing":
        root.mkdir()
    if kind == "symlink":
        original = tmp_path / "outside"
        original.write_bytes(b"keep")
        (root / "link").symlink_to(original)
    elif kind == "fifo":
        os.mkfifo(root / "pipe", mode=0o600)
    elif kind == "unreadable":
        monkeypatch.setattr(
            xt.os, "scandir", Mock(side_effect=PermissionError("private diagnostic"))
        )
    with pytest.raises(RuntimeError, match=expected) as error:
        xt._collect_local_folder_entries(root)
    assert "private diagnostic" not in str(error.value)
    if kind == "file":
        assert root.read_bytes() == b"keep"
    elif kind == "symlink":
        assert original.read_bytes() == b"keep"


@pytest.mark.parametrize("failed", ["open", "close", "unlink"])
def test_write_probe_cleans_only_its_own_file_after_io_failure(
    xt, tmp_path, monkeypatch, failed
):
    """Inputs: interrupted writability probe. Output: failure, no leaked handle or file, prior data intact."""
    prior = tmp_path / "user-data"
    prior.write_bytes(b"retain")
    native = getattr(xt.os, failed)
    calls = []

    def fail_once(*args, **kwargs):
        """Inputs: native I/O boundary. Output: one injected failure followed by real cleanup."""
        calls.append(args)
        if len(calls) == 1:
            raise PermissionError("fixture probe failure")
        return native(*args, **kwargs)

    monkeypatch.setattr(xt.os, failed, fail_once)
    assert xt._folder_path_write_error(tmp_path) == xt.LOCAL_PATH_WRITE_ERROR_MESSAGE
    assert prior.read_bytes() == b"retain"
    assert list(tmp_path.iterdir()) == [prior]
    assert len(calls) == (1 if failed == "open" else 2)


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("mode", ["missing", "invalid", "empty", "none", "valid"])
def test_converter_handoff_rejects_unusable_files_before_launch(
    xt, tmp_path, monkeypatch, batch, mode
):
    """Inputs: selected-file boundaries. Output: no launch for absent or non-TIFF data."""
    path = tmp_path / "selected.tif"
    if mode in {"valid", "invalid"}:
        path.write_bytes(b"II*\x00fixture" if mode == "valid" else b"invalid")
    value = {"none": None, "empty": [] if batch else ""}.get(mode, path)
    submit = Mock(return_value=True)
    monkeypatch.setattr(xt, "_submit_files_to_imaris_file_converter", submit)
    function = (
        xt.submit_selected_image_exports_to_imaris_converter
        if batch
        else xt.submit_selected_image_export_to_imaris_converter
    )
    assert function(value) is (mode == "valid")
    assert submit.call_count == int(mode == "valid")
    if mode in {"valid", "invalid"}:
        assert path.read_bytes() == (
            b"II*\x00fixture" if mode == "valid" else b"invalid"
        )


@pytest.mark.parametrize(
    "mode", ["empty", "none", "missing", "no_converter", "launch_error"]
)
def test_converter_process_failure_never_reports_success(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: file discovery or process-creation failure. Output: truthful failure and intact input."""
    path = tmp_path / "source.tif"
    path.write_bytes(b"II*\x00fixture")
    converter = tmp_path / "ImarisFileConverter.exe"
    monkeypatch.setattr(
        xt,
        "_find_imaris_file_converter_executable",
        lambda: None if mode == "no_converter" else str(converter),
    )
    launch = Mock(side_effect=OSError("fixture launch refused"))
    monkeypatch.setattr(xt.subprocess, "Popen", launch)
    inputs = {"empty": [], "none": None, "missing": [tmp_path / "absent"]}.get(
        mode, [path]
    )
    assert not xt._submit_files_to_imaris_file_converter(inputs)
    assert launch.call_count == int(mode == "launch_error")
    assert path.read_bytes() == b"II*\x00fixture"


@pytest.mark.parametrize("mode", ["missing", "invalid", "non_ims", "valid"])
def test_native_batch_bridge_validates_every_file_before_start(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: native batch payload. Output: no helper process for a partial or unsupported selection."""
    path = tmp_path / "source.ims"
    path.write_bytes(b"invalid" if mode == "invalid" else b"\x89HDF\r\n\x1a\nfixture")
    inputs = [path, tmp_path / "absent"] if mode == "missing" else [path]
    monkeypatch.setattr(xt, "_iter_imaris_install_roots", lambda: iter(()))
    launch = Mock(return_value=True)
    monkeypatch.setattr(xt, "_run_native_bridge_helper", launch)
    assert xt._run_native_bridge_open_many_helper(
        "fixture-python", inputs, 7, require_ims=mode != "non_ims"
    ) is (mode == "valid")
    assert launch.call_count == int(mode == "valid")
    if mode == "valid":
        args = launch.call_args.args
        assert args[1]["app_id"] == 7
        assert args[1]["file_paths"] == [str(path)]
        assert args[1]["require_ims"] is True
        assert args[2:] == ("open_many", xt.NATIVE_BRIDGE_RUNNER_TIMEOUT)


@pytest.mark.parametrize(
    "mode", ["no_payload", "missing_python", "timeout", "failure", "success"]
)
def test_native_helper_failure_releases_only_its_private_script(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: process-boundary outcomes. Output: accurate status, bounded invocation and helper cleanup."""
    executable = tmp_path / "python.exe"
    if mode != "missing_python":
        executable.write_bytes(b"not executed")
    helper = tmp_path / "helper.py"
    helper.write_text(xt._NATIVE_BRIDGE_OPEN_HELPER)
    writer = Mock(return_value=str(helper))
    monkeypatch.setattr(xt, "_write_native_bridge_helper_file", writer)
    payload = {"mode": "probe", "app_id": 7}
    process = Mock(
        return_value=subprocess.CompletedProcess([], 0, "BRIDGE_RUNNER_PROBE_OK", "")
    )
    if mode == "timeout":
        process.side_effect = subprocess.TimeoutExpired("fixture-python", 2)
    elif mode == "failure":
        process.side_effect = OSError("fixture process unavailable")
    monkeypatch.setattr(xt.subprocess, "run", process)
    assert xt._run_native_bridge_helper(
        executable, None if mode == "no_payload" else payload, "probe", 2
    ) is (mode == "success")
    started = mode not in {"no_payload", "missing_python"}
    assert process.call_count == int(started)
    assert writer.call_count == int(started)
    assert helper.exists() is not started
    if started:
        args, kwargs = process.call_args
        assert args[0] == [str(executable.resolve()), str(helper)]
        assert kwargs["timeout"] == 2
        assert kwargs["check"] is False
        assert kwargs.get("shell", False) is False
    if executable.exists():
        assert executable.read_bytes() == b"not executed"


@pytest.mark.parametrize(
    "mode", ["disabled", "missing_id", "unavailable", "failure", "success"]
)
def test_native_probe_worker_always_publishes_completion(xt, monkeypatch, mode):
    """Inputs: native discovery outcomes. Output: waiters released without manufacturing bridge availability."""
    dialog = object.__new__(xt.OMEROBrowserDialog)
    dialog.imaris_id = None if mode == "missing_id" else 7
    dialog.imaris = None
    dialog._native_bridge_probe_lock = threading.Lock()
    dialog._native_bridge_probe_done = threading.Event()
    dialog._native_bridge_probe_in_progress = True
    original_client = object()
    dialog.client = original_client
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: mode != "disabled")
    finder = Mock(return_value="fixture-python" if mode == "success" else None)
    if mode == "failure":
        finder.side_effect = OSError("fixture bridge unavailable")
    monkeypatch.setattr(xt, "_find_compatible_native_bridge_python", finder)
    dialog._native_bridge_probe_worker()
    assert dialog._native_bridge_probe_done.is_set()
    assert not dialog._native_bridge_probe_in_progress
    assert dialog._native_bridge_available is (mode == "success")
    assert bool(dialog._native_bridge_last_verified_at) is (mode == "success")
    assert dialog._native_bridge_python_executable == (
        "fixture-python" if mode == "success" else None
    )
    assert bool(dialog._native_bridge_probe_error) is (
        mode not in {"success", "disabled"}
    )
    assert finder.call_count == int(mode not in {"disabled", "missing_id"})
    assert dialog.client is original_client


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("fresh", True),
        ("revalidated", True),
        ("lost", False),
        ("probe_fresh", True),
        ("probe_stale", True),
        ("probe_timeout", False),
        ("probe_empty", False),
    ],
)
def test_export_readiness_does_not_trust_stale_bridge_state(
    xt, monkeypatch, mode, expected
):
    """Inputs: fresh, stale or unavailable native bridge. Output: verify before export without touching login."""
    dialog = object.__new__(xt.OMEROBrowserDialog)
    dialog.imaris = None
    dialog._native_bridge_probe_lock = threading.Lock()
    dialog._native_bridge_available = not mode.startswith("probe_")
    dialog._native_bridge_last_verified_at = 1000 if mode == "fresh" else 0
    dialog._native_bridge_probe_error = "fixture unavailable"
    dialog._set_status = Mock()
    dialog._resolve_direct_imaris_handle_for_handoff = Mock(return_value=False)
    dialog._revalidate_native_bridge = Mock(
        return_value=mode in {"revalidated", "probe_stale"}
    )
    client = object()
    dialog.client = client
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: True)
    monkeypatch.setattr(xt, "time", SimpleNamespace(time=lambda: 1000))

    def probe(*, timeout):
        """Inputs: bounded probe request. Output: fixture discovery state, not an actual Imaris qualification."""
        assert timeout == xt.NATIVE_BRIDGE_REVALIDATION_TIMEOUT
        dialog._native_bridge_available = mode in {"probe_fresh", "probe_stale"}
        dialog._native_bridge_last_verified_at = 1000 if mode == "probe_fresh" else 0
        return mode != "probe_timeout"

    dialog._run_native_bridge_probe_now = Mock(side_effect=probe)
    assert dialog._ensure_native_open_ready_before_export() is expected
    assert dialog.client is client
    assert dialog._run_native_bridge_probe_now.call_count == int(
        mode.startswith("probe_")
    )
    assert dialog._revalidate_native_bridge.call_count == int(
        mode in {"revalidated", "lost", "probe_stale"}
    )
    if mode == "probe_timeout":
        assert not dialog._native_bridge_available
        assert dialog._native_bridge_last_verified_at == 0
        assert dialog._native_bridge_probe_error == "probe timed out"


def test_deferred_tk_attributes_follow_the_loaded_module(xt):
    """Inputs: pre-load and post-load assignments. Output: one authoritative module state."""
    proxy = xt._DeferredTkImport("fixture_tk")
    proxy.before = 1
    del proxy.before
    with pytest.raises(AttributeError):
        getattr(proxy, "before")
    module = SimpleNamespace(value=2)
    proxy.load(module)
    proxy.value = 3
    assert module.value == proxy.value == 3
    del proxy.value
    assert not hasattr(module, "value")


@pytest.mark.parametrize("value", [None, 1, "#zzzzzz", "invalid"])
def test_color_failure_uses_declared_fallback(xt, value):
    """Inputs: invalid UI colors and unavailable Tk lookup. Output: valid deterministic fallback."""
    widget = SimpleNamespace(winfo_rgb=Mock(side_effect=ValueError("unknown color")))
    assert xt._hex_to_rgb(value, (1, 2, 3)) == (1, 2, 3)
    assert xt._resolve_tk_color(widget, value, "#010203") == "#010203"


@pytest.mark.parametrize("error", [OSError, TypeError, ValueError, RuntimeError])
def test_path_constructor_failure_cannot_become_a_usable_path(xt, monkeypatch, error):
    """Inputs: path implementation refusing an input. Output: no path handed to an I/O sink."""
    construct = Mock(side_effect=error("fixture path unavailable"))
    monkeypatch.setattr(xt, "_NATIVE_PATH_CLASS", construct)
    assert xt._coerce_path("fixture") is None
    assert xt._existing_regular_file_path("fixture") is None
    assert construct.call_count == 2


def test_file_metadata_failure_is_not_an_existing_file(xt, monkeypatch):
    """Inputs: inaccessible file metadata. Output: false existence without opening the file."""
    path = SimpleNamespace(is_file=Mock(side_effect=PermissionError("fixture denied")))
    monkeypatch.setattr(xt, "_coerce_path", lambda _value: path)
    assert xt._existing_regular_file_path("fixture") is None
    path.is_file.assert_called_once_with()


@pytest.mark.parametrize("boundary", ["settings", "metadata"])
def test_uninspectable_log_destination_is_rejected(xt, tmp_path, monkeypatch, boundary):
    """Inputs: unavailable settings location or target metadata. Output: no accepted log destination."""
    path = tmp_path / xt.XT_LOG_FILE_NAME
    if boundary == "settings":
        monkeypatch.setattr(
            xt,
            "_connector_settings_env_path",
            Mock(side_effect=OSError("fixture settings unavailable")),
        )
    else:
        monkeypatch.setattr(
            xt, "_connector_settings_env_path", lambda: tmp_path / "settings.env"
        )
        path = SimpleNamespace(
            name=xt.XT_LOG_FILE_NAME,
            parent=tmp_path,
            is_absolute=lambda: True,
            is_symlink=Mock(side_effect=OSError("fixture metadata unavailable")),
        )
        monkeypatch.setattr(xt, "_coerce_path", lambda _value: path)
    assert xt._safe_xt_log_file(path) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failed", ["file", "count", "dataset", "invalid_count", "all"])
def test_bridge_snapshot_keeps_independent_evidence_when_one_getter_fails(
    xt, tmp_path, monkeypatch, failed
):
    """Inputs: independently failing bridge getters. Output: unavailable fields, never fabricated success."""
    path = tmp_path / "current.ims"
    dataset = object()
    getters = {
        "file": Mock(return_value=str(path)),
        "count": Mock(return_value="2"),
        "dataset": Mock(return_value=dataset),
    }
    for name, getter in getters.items():
        if failed in (name, "all"):
            getter.side_effect = OSError("fixture bridge unavailable")
    if failed == "invalid_count":
        getters["count"].return_value = "invalid"
    signature = Mock(return_value=(1, 2, 3))
    monkeypatch.setattr(xt, "_imaris_data_set_signature", signature)
    app = SimpleNamespace(
        GetCurrentFileName=getters["file"],
        GetNumberOfImages=getters["count"],
        GetDataSet=getters["dataset"],
    )
    assert xt._imaris_app_snapshot(app) == (
        "" if failed in ("file", "all") else str(path),
        None if failed in ("count", "invalid_count", "all") else 2,
        None if failed in ("dataset", "all") else (1, 2, 3),
    )
    assert all(getter.call_count == 1 for getter in getters.values())
    if failed not in ("dataset", "all"):
        signature.assert_called_once_with(dataset)
    else:
        signature.assert_not_called()


@pytest.mark.parametrize(
    "primary,fallback,expected,calls",
    [
        (True, "error", True, 0),
        (False, True, True, 1),
        ("error", True, True, 1),
        ("error", "error", False, 1),
        (False, False, False, 1),
    ],
)
def test_visibility_fallback_never_claims_success_after_both_setters_fail(
    xt, monkeypatch, primary, fallback, expected, calls
):
    """Inputs: independent native setter outcomes. Output: ordered fallback and truthful success."""
    dataset = object()
    monkeypatch.setattr(
        xt, "_imaris_data_set_has_content", lambda value: value is dataset
    )
    first, second = Mock(return_value=primary), Mock(return_value=fallback)
    if primary == "error":
        first.side_effect = OSError("fixture setter unavailable")
    if fallback == "error":
        second.side_effect = OSError("fixture fallback unavailable")
    app = SimpleNamespace(SetDataSet=first, SetImage=second)
    assert xt._ensure_imaris_current_dataset_visible(app, dataset) is expected
    first.assert_called_once_with(dataset)
    assert second.call_count == calls
    if calls:
        second.assert_called_once_with(0, dataset)


@pytest.mark.parametrize(
    "mode", ["not_windows", "missing", "failure", "exception", "success"]
)
def test_native_version_boundary_handles_unavailable_or_failed_api(
    xt, monkeypatch, mode
):
    """Inputs: platform API availability and return status. Output: verified fields or no version claim."""
    monkeypatch.setattr(
        xt, "os", SimpleNamespace(name="posix" if mode == "not_windows" else "nt")
    )
    calls = []

    def get_version(pointer):
        """Inputs: actual ctypes structure pointer. Output: populated fixture version or failure."""
        calls.append(pointer)
        if mode == "exception":
            raise OSError("fixture platform API unavailable")
        value = pointer._obj
        assert value.dwOSVersionInfoSize == ctypes.sizeof(value)
        value.dwMajorVersion = 10
        value.dwMinorVersion = 0
        value.dwBuildNumber = 19045
        return 1 if mode == "failure" else 0

    api = (
        SimpleNamespace()
        if mode == "missing"
        else SimpleNamespace(RtlGetVersion=get_version)
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(ntdll=api), raising=False)
    version = xt._read_windows_version_via_rtl_get_version()
    if mode == "success":
        assert (version.major, version.minor, version.build, version.source) == (
            10,
            0,
            19045,
            "RtlGetVersion",
        )
    else:
        assert version is None
    assert len(calls) == int(mode in {"failure", "exception", "success"})


@pytest.mark.parametrize(
    "mode", ["missing", "duplicate", "distinct", "resolution_failure"]
)
def test_python_launcher_discovery_is_unique_and_rejects_unusable_paths(
    xt, tmp_path, monkeypatch, mode
):
    """Inputs: controlled launcher files. Output: unique resolved existing paths; no process launch."""
    first = tmp_path / "system"
    second = tmp_path / "alternate"
    first.mkdir()
    second.mkdir()
    launchers = [first / "py.exe", second / "py.exe"]
    if mode != "missing":
        for path in launchers:
            path.write_bytes(b"fixture file, never executed")
    monkeypatch.setenv("SystemRoot", str(first))
    monkeypatch.setenv("WINDIR", str(first if mode == "duplicate" else second))
    if mode == "resolution_failure":
        actual_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            """Inputs: candidate path. Output: controlled inaccessible launcher, preserving unrelated paths."""
            if path in launchers:
                raise PermissionError("fixture resolution denied")
            return actual_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
    expected = (
        []
        if mode in {"missing", "resolution_failure"}
        else [str(launchers[0])]
        if mode == "duplicate"
        else [str(path) for path in launchers]
    )
    assert list(xt._iter_windows_python_launchers()) == expected
    if mode != "missing":
        assert all(
            path.read_bytes() == b"fixture file, never executed" for path in launchers
        )


@pytest.mark.parametrize("total", ["invalid", {}, [], -1, None])
def test_invalid_progress_total_does_not_report_a_false_completion(
    xt, monkeypatch, total
):
    """Inputs: malformed or unavailable length. Output: bounded progress without a percentage claim."""
    lines = []
    monkeypatch.setattr(
        xt, "_xt_console_log", lambda *args, **kwargs: lines.append(args)
    )
    reporter = xt._DownloadProgressReporter(total)
    reporter.report(0)
    assert lines == []
    reporter.report(1)
    reporter.finish(1)
    assert reporter.total_size == 0
    assert reporter._last_bytes == 1
    assert not any("100.0%" in str(line) for line in lines)


@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize(
    "origin,enabled,direct_ok,bridge_ok,expected_direct,expected_bridge,expected",
    [
        ("direct", True, True, False, 1, 0, True),
        ("direct", True, False, True, 1, 1, True),
        ("direct", True, False, False, 1, 1, False),
        ("direct", False, False, True, 1, 0, False),
        ("reacquired", True, True, False, 1, 0, True),
        ("reacquired", True, False, True, 1, 1, True),
        ("preferred", True, False, True, 0, 1, True),
        ("preferred", True, False, False, 0, 1, False),
        ("unavailable", True, False, True, 0, 1, True),
        ("unavailable", True, False, False, 0, 1, False),
        ("unavailable", False, False, True, 0, 1, True),
        ("unavailable", False, False, False, 0, 1, False),
        ("idless", True, False, False, 0, 0, False),
        ("idless", False, False, False, 0, 0, False),
    ],
)
def test_handoff_uses_each_strategy_once_without_replaying_failed_open(
    xt,
    tmp_path,
    monkeypatch,
    multiple,
    origin,
    enabled,
    direct_ok,
    bridge_ok,
    expected_direct,
    expected_bridge,
    expected,
):
    """Inputs: direct/bridge availability and outcomes. Output: preserved files/session and at most one bridge handoff."""
    paths = [tmp_path / "first.ims", tmp_path / "second.ims"]
    for path in paths:
        path.write_bytes(b"\x89HDF\r\n\x1a\nfixture")
    app = object()
    client = object()
    dialog = object.__new__(xt.OMEROBrowserDialog)
    dialog.client = client
    dialog.imaris = app if origin == "direct" else None
    dialog.imaris_id = None if origin == "idless" else "17"
    dialog._set_status = Mock()
    dialog._get_native_bridge_python_executable = Mock(
        return_value="fixture-python" if origin == "preferred" else None
    )

    def acquire():
        """Inputs: existing XT session. Output: its handle only when reacquisition succeeds."""
        if origin == "reacquired":
            dialog.imaris = app
        return dialog.imaris is app

    acquisition = Mock(side_effect=acquire)
    dialog._resolve_direct_imaris_handle_for_handoff = acquisition
    monkeypatch.setattr(xt, "_native_imaris_bridge_enabled", lambda: enabled)
    monkeypatch.setattr(
        xt, "_imaris_application_handle_is_live", lambda value: value is app
    )
    direct, bridge = Mock(return_value=direct_ok), Mock(return_value=bridge_ok)
    method = "open_files_in_imaris" if multiple else "open_file_in_imaris"
    monkeypatch.setattr(xt, method, direct)
    bridge_method = (
        "_open_files_with_native_bridge_runner"
        if multiple
        else "_open_with_native_bridge_runner"
    )
    setattr(dialog, bridge_method, bridge)
    selected = [str(path) for path in paths] if multiple else str(paths[0])
    handoff = (
        dialog._open_downloaded_files_in_imaris
        if multiple
        else dialog._open_downloaded_file_in_imaris
    )
    assert handoff(selected, require_ims=True) is expected
    assert direct.call_count == expected_direct
    assert bridge.call_count == expected_bridge
    if direct.called:
        direct.assert_called_once_with(selected, app, require_ims=True)
    if bridge.called:
        assert bridge.call_args.args == (selected,)
        assert bridge.call_args.kwargs["require_ims"] is True
        assert bridge.call_args.kwargs.get("allow_when_disabled", False) is (
            not enabled
        )
    assert acquisition.call_count == int(origin not in {"direct", "preferred"})
    assert dialog.client is client
    assert all(path.read_bytes() == b"\x89HDF\r\n\x1a\nfixture" for path in paths)
