"""Real Tk event tests; no Imaris installation or application network is used."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import select
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import tkinter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(scope="module")
def virtual_display():
    """Inputs: installed Xvfb. Output: isolated local display, released after tests."""
    executable = shutil.which("xvfb-run")
    assert executable, "Real Tk tests require the Linux xvfb package."
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            [
                executable,
                "--auto-servernum",
                "--server-args=-screen 0 1920x1200x24 -nolisten tcp",
                sys.executable,
                "-c",
                "import json, os, sys; "
                "print(json.dumps({key: os.environ[key] "
                "for key in ('DISPLAY', 'XAUTHORITY')}), flush=True); "
                "sys.stdin.read()",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 15)
            assert ready, "Xvfb did not report a ready display within 15 seconds."
            display = process.stdout.readline()
            if not display:
                errors.seek(0)
                pytest.fail(f"Xvfb failed: {errors.read().decode(errors='replace')}")
            yield json.loads(display)
        finally:
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.communicate(timeout=5)
            assert process.returncode == 0, "xvfb-run did not complete cleanly."


@pytest.fixture
def connector_ui(virtual_display, tmp_path, monkeypatch):
    """Inputs: private display/home. Output: real dialog and callback-error collector."""
    for name, value in virtual_display.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OMERO_IMARIS_EXPORT_DIR", str(tmp_path / "exports"))
    for key in (
        "OMERO_HOST",
        "OMEROHOST",
        "OMERO_WEB_HOST",
        "OMERO_WEB_PORT",
        "OMERO_WEB_PUBLIC_PORT",
        "OMERO_PORT",
        "OMERO_USER",
        "OMERO_USERNAME",
    ):
        monkeypatch.delenv(key, raising=False)
    path = Path(__file__).resolve().parents[1] / "omero_imaris_connector"
    spec = importlib.util.spec_from_file_location(
        "xt_connector_real_tk", path / "XTOmeroConnector.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv(module.ENABLE_NATIVE_IMARIS_BRIDGE_ENV, "false")
    errors = []
    monkeypatch.setattr(
        tkinter.Tk,
        "report_callback_exception",
        lambda _self, _kind, error, _traceback: errors.append(error),
    )
    dialog = module.OMEROBrowserDialog(None)
    try:
        dialog.root.update()
        yield module, dialog
        assert errors == [], f"Tk callbacks failed: {errors!r}"
    finally:
        dialog._on_close()


def _pump_until(root, predicate, timeout=2):
    """Inputs: root, condition and deadline. Output: wait with real event dispatch."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Tk state did not settle before deadline."
        root.update()
        time.sleep(0.005)
    root.update()


def _descendants(widget):
    """Inputs: Tk parent. Output: recursively enumerated live child widgets."""
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def test_nested_modals_restore_background_only_after_final_close(connector_ui):
    """Inputs: two nested modal locks. Output: neutral cursors until final close, original cursors afterward."""
    _module, dialog = connector_ui
    widget = tkinter.Label(dialog.root, text="fixture", cursor="crosshair")
    widget.pack()
    dialog.root.update()
    dialog._lock_modal_background()
    assert widget.cget("cursor") == "arrow"
    dialog._lock_modal_background()
    dialog._unlock_modal_background()
    assert widget.cget("cursor") == "arrow"
    assert dialog._modal_background_lock_depth == 1
    dialog._unlock_modal_background()
    assert widget.cget("cursor") == "crosshair"
    assert dialog._modal_background_lock_depth == 0
    assert dialog._modal_background_cursor_restore == []


@pytest.mark.parametrize("operation", ["load", "export"])
def test_busy_clear_wrappers_restore_connected_controls_without_session_reset(
    connector_ui, operation
):
    """Inputs: completed operation in a connected real window. Output: refresh restored, Stop hidden and original client and selection retained."""
    _module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    _connected_selection(dialog, client)
    dialog._set_converter_options(["OMERO"])
    getattr(dialog, f"_set_actions_busy_for_{operation}")(True)
    assert dialog.refresh_btn.cget("state") == "disabled"
    getattr(dialog, f"_clear_actions_busy_for_{operation}")()
    dialog.root.update()
    assert dialog.refresh_btn.cget("state") == "normal"
    assert not dialog.stop_btn._canvas.winfo_ismapped()
    assert dialog.client is client and client.session_id == "fixture-session"
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]


def test_load_button_completion_delegates_to_full_busy_state_cleanup(
    connector_ui, monkeypatch
):
    """Inputs: asynchronous load-button completion. Output: one full busy-state cleanup, not only a visual button change."""
    _module, dialog = connector_ui
    cleanup = Mock(wraps=dialog._set_actions_busy_for_load)
    monkeypatch.setattr(dialog, "_set_actions_busy_for_load", cleanup)
    dialog._set_actions_busy_for_load(True)
    cleanup.reset_mock()
    dialog._reenable_load_button()
    cleanup.assert_called_once_with(False)
    assert not dialog._load_in_progress
    assert dialog.connect_btn.cget("state") == "normal"


def test_explicit_disconnect_clears_local_authentication_even_if_cookie_cleanup_fails(
    connector_ui,
):
    """Inputs: user disconnect with an unavailable cookie jar. Output: local credentials and selections cleared without leaving an authenticated UI."""
    module, dialog = connector_ui
    client = SimpleNamespace(
        cookie_jar=SimpleNamespace(
            clear=Mock(side_effect=RuntimeError("fixture jar unavailable"))
        ),
        password="fixture password",
        csrf_token="fixture csrf",
        session_id="fixture-session",
        session_key="fixture-session",
        user_id=7,
    )
    _connected_selection(dialog, client)
    dialog._disconnect()
    dialog.root.update()
    assert dialog.client is None and not dialog._connected
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert (
        client.session_id
        is client.session_key
        is client.csrf_token
        is client.user_id
        is None
    )
    assert dialog.plist.size() == dialog.dlist.size() == dialog.ilist.size() == 0
    assert dialog.status.cget("text") == "Disconnected"
    client.cookie_jar.clear.assert_called_once()


def test_empty_and_idless_browser_selections_do_not_request_data(connector_ui):
    """Inputs: no selection or a dataset without an id. Output: no fetch and unchanged active dataset and client."""
    _module, dialog = connector_ui
    client = SimpleNamespace(list_datasets=Mock(), list_images=Mock())
    dialog.client = client
    dialog._pid, dialog._did = "10", "20"
    dialog._set_browser_interaction_state(True)
    dialog._sel_proj()
    dialog._sel_ds()
    dialog.datasets_data = [{"name": "Missing identity"}]
    dialog.dlist.insert("end", "Missing identity")
    dialog.dlist.selection_set(0)
    dialog._sel_ds()
    client.list_datasets.assert_not_called()
    client.list_images.assert_not_called()
    assert (dialog._pid, dialog._did) == ("10", "20")
    assert dialog.client is client


@pytest.mark.parametrize("project_selected", [False, True])
def test_refresh_without_prior_child_selection_reports_success_not_missing_data(
    connector_ui, project_selected
):
    """Inputs: valid refresh without a prior project or dataset selection. Output: accurate neutral completion, fresh lists and retained session."""
    _module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    _connected_selection(dialog, client)
    dialog._refresh_in_progress = True
    projects = [{"id": "10", "name": "Project"}]
    datasets = [{"id": "20", "name": "Dataset"}] if project_selected else []
    dialog._apply_refresh_result(
        dialog._refresh_generation,
        "10" if project_selected else None,
        None,
        projects,
        0 if project_selected else None,
        datasets,
        None,
        [],
    )
    dialog.root.update()
    assert dialog.status.cget("text") == (
        "Refresh completed" if project_selected else "Project list refreshed"
    )
    assert dialog._pid == ("10" if project_selected else None)
    assert dialog._did is None and dialog.ilist.size() == 0
    assert not dialog._refresh_in_progress
    assert dialog.client is client and dialog._connected


@pytest.mark.parametrize("missing", [True, False])
def test_unverified_selected_export_is_never_added_to_handoff_tracking(
    connector_ui, tmp_path, missing
):
    """Inputs: missing or non-TIFF export file. Output: explicit failure, no tracked handoff and no file mutation."""
    _module, dialog = connector_ui
    path = tmp_path / "export.tif"
    if not missing:
        path.write_bytes(b"not a TIFF")
    before = set(dialog._selected_image_export_files)
    with pytest.raises(
        RuntimeError,
        match="missing after download" if missing else "not a readable TIFF",
    ):
        dialog._mark_selected_image_export_file(path)
    assert dialog._selected_image_export_files == before
    assert path.exists() is not missing
    if not missing:
        assert path.read_bytes() == b"not a TIFF"


def test_consumed_folder_hint_does_not_reappear_in_a_later_chooser(
    connector_ui, tmp_path
):
    """Inputs: consumed initial folder suggestion. Output: no stale chooser hint, but a subsequent explicit selection remains preferred."""
    _module, dialog = connector_ui
    dialog._folder_export_initial_path_hint_consumed = True
    dialog._last_folder_export_selection = ""
    assert dialog._folder_export_dialog_initialdir() == ""
    dialog._last_folder_export_selection = str(tmp_path)
    assert dialog._folder_export_dialog_initialdir() == str(tmp_path)


@pytest.mark.parametrize("path", ["", "missing"])
def test_arena_checkbox_never_registers_an_invalid_or_absent_folder(
    connector_ui, monkeypatch, tmp_path, path
):
    """Inputs: enabled folder registration with no usable path. Output: no registry call or filesystem creation."""
    module, dialog = connector_ui
    dialog.append_observed_folders_var.set(True)
    dialog._set_folder_path_value("" if not path else str(tmp_path / path))
    register = Mock(side_effect=AssertionError("Unexpected folder registration"))
    monkeypatch.setattr(module, "_append_imaris_arena_observed_folder", register)
    assert not dialog._append_current_path_to_imaris_arena_if_enabled()
    register.assert_not_called()
    assert not (tmp_path / "missing").exists()


def test_duplicate_download_summary_is_bounded_without_losing_conflict_count(
    connector_ui, tmp_path
):
    """Inputs: repeated planned names and more than eight existing files. Output: deduplicated conflicts, accurate bounded preview and safe repeat policy."""
    module, dialog = connector_ui
    names = [f"image-{index}.ims" for index in range(11)]
    for name in names:
        (tmp_path / name).write_bytes(b"retained")
    conflicts = dialog._existing_download_filename_conflicts(tmp_path, names + names)
    assert conflicts == names
    text = dialog._duplicate_download_prompt_message(conflicts, [names[0]])
    assert "... and 3 more" in text
    assert names[7] in text and names[8] not in text
    assert text.count(names[0]) == 1
    seen = {names[0]}
    assert (
        dialog._per_file_duplicate_download_policy(
            names[0], module.DUPLICATE_DOWNLOAD_POLICY_REPLACE, seen
        )
        == module.DUPLICATE_DOWNLOAD_POLICY_UNIQUE
    )
    assert all((tmp_path / name).read_bytes() == b"retained" for name in names)


def test_image_cache_components_cannot_be_empty_or_reserved_device_names(connector_ui):
    """Inputs: empty and reserved image identifiers. Output: portable nonempty single-directory cache components."""
    _module, dialog = connector_ui
    assert dialog._image_cache_subdir(".") == "img_unknown"
    assert dialog._image_cache_subdir("CON") == "img__CON"


def test_window_close_cancels_all_owned_tk_timers_before_destroying_widgets(
    connector_ui,
):
    """Inputs: pending status update and delayed callback in a real window. Output: no Tcl timers survive shutdown and neither callback runs afterward."""
    _module, dialog = connector_ui
    callback = Mock()
    dialog._set_status("queued status")
    dialog.root.after(10000, callback)
    assert dialog.root.tk.call("after", "info")
    dialog._on_close()
    assert dialog.root.tk.splitlist(dialog.root.tk.call("after", "info")) == ()
    callback.assert_not_called()


def test_unavailable_settings_do_not_prevent_window_creation_or_cancel_another_windows_timers(
    connector_ui, monkeypatch
):
    """Inputs: unavailable settings storage and two independent Tk roots. Output: usable diagnostic window whose teardown leaves the other window and its timer intact."""
    module, original = connector_ui
    other_callback = Mock()
    other_timer = original.root.after(10000, other_callback)
    monkeypatch.setattr(
        module,
        "_connector_settings_env_path",
        Mock(side_effect=OSError("fixture settings unavailable")),
    )
    dialog = module.OMEROBrowserDialog(None)
    try:
        dialog.root.update()
        assert dialog.root.winfo_exists()
        assert dialog._autosave_settings_write_error == "fixture settings unavailable"
        assert dialog._saved_settings == {}
        assert not dialog._connected
        dialog.root.after(10000, Mock())
    finally:
        dialog._on_close()
    assert original.root.winfo_exists()
    assert other_timer in original.root.tk.splitlist(
        original.root.tk.call("after", "info")
    )
    other_callback.assert_not_called()
    original.root.after_cancel(other_timer)


def test_progress_rejects_nonnumeric_server_counters_without_false_completion(
    connector_ui,
):
    """Inputs: malformed remote progress counts. Output: unavailable progress rather than invented completion or a UI exception."""
    _module, dialog = connector_ui
    assert dialog._folder_export_progress_percent("invalid", 10) is None
    assert dialog._folder_export_progress_percent(1, "invalid") is None


def test_stopping_operation_with_missing_event_creates_one_and_is_idempotent(
    connector_ui,
):
    """Inputs: active operation without an event, followed by repeated Stop. Output: one cancellation signal and one generation advance without creating a new session."""
    _module, dialog = connector_ui
    dialog._load_in_progress = True
    dialog._operation_cancel_event = None
    generation = dialog._operation_generation
    dialog._request_stop_current_operation()
    event = dialog._operation_cancel_event
    assert event.is_set()
    assert dialog._operation_generation == generation + 1
    dialog._load_in_progress = True
    dialog._request_stop_current_operation()
    assert dialog._operation_cancel_event is event
    assert dialog._operation_generation == generation + 1
    assert dialog.client is None
    dialog._load_in_progress = False


@pytest.mark.parametrize("operation", ["folder", "ims"])
def test_background_cancellation_failure_does_not_discard_the_client(
    connector_ui, monkeypatch, operation
):
    """Inputs: server cancellation fails in a real background worker. Output: bounded completion, diagnostic failure and unchanged session/UI."""
    module, dialog = connector_ui
    failure = ConnectionResetError("fixture cancellation lost")
    client = SimpleNamespace(
        session_id="fixture-session",
        cancel_folder_export_job=Mock(side_effect=failure),
        cancel_active_ims_exports=Mock(side_effect=failure),
    )
    _connected_selection(dialog, client)
    log = Mock()
    monkeypatch.setattr(module, "_xt_debug", log)
    callback = (
        (
            lambda: dialog._cancel_folder_export_job_in_background(
                client, {"id": "fixture-job"}
            )
        )
        if operation == "folder"
        else (lambda: dialog._cancel_active_ims_exports_in_background(client))
    )
    _run_worker_with_mainloop(dialog, callback)
    assert "cancellation failed" in log.call_args.args[0]
    assert "ConnectionResetError" in log.call_args.args[0]
    assert dialog.client is client and client.session_id == "fixture-session"
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]


def test_optional_ui_fields_can_be_absent_without_resetting_other_state(
    connector_ui, monkeypatch
):
    """Inputs: optional fields absent during UI construction or teardown. Output: bounded layout fallbacks and no session or unrelated widget mutation."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    _connected_selection(dialog, client)
    before = dialog._browser_panel_fractions
    with monkeypatch.context() as patcher:
        patcher.setattr(dialog, "browser_frame", None)
        dialog._browser_sash_drag_index = 0
        assert dialog._browser_panel_area_width() == 1
        dialog._apply_browser_panel_layout()
        dialog._drag_browser_panel_resize(SimpleNamespace(x_root=10))
        patcher.setattr(dialog, "folder_path_var", None)
        dialog._set_folder_path_var_safely("must not replace a widget")
        patcher.setattr(dialog, "_browser_search_vars", {})
        patcher.setattr(dialog, "_browser_search_entries", {"projects": None})
        dialog._set_browser_search_var_safely("projects", "unused")
        dialog._set_browser_interaction_state(True)
    dialog._browser_sash_drag_index = None
    assert dialog._browser_panel_fractions == before
    assert dialog.client is client and dialog._connected
    partial_dialog = object.__new__(module.OMEROBrowserDialog)
    partial_dialog._enforce_window_minimum_for_current_layout()
    partial_dialog._indicator_state = "connected"
    partial_dialog._schedule_indicator_blink()
    partial_dialog._indicator_state = "busy"
    partial_dialog._schedule_indicator_blink()
    partial_dialog._reset_background_cursor_after_silent_work()
    assert module._apply_omero_window_icon(None, image="cached icon") == "cached icon"


def test_placeholder_traces_never_filter_or_validate_user_content(
    connector_ui, monkeypatch
):
    """Inputs: placeholder updates and disabled search. Output: no filtering or folder probe, while existing user query text is retained."""
    _module, dialog = connector_ui
    filtered, inspect = Mock(), Mock()
    monkeypatch.setattr(dialog, "_apply_browser_search_filter", filtered)
    monkeypatch.setattr(dialog, "_queue_folder_path_dir_check", inspect)
    dialog._folder_path_placeholder_visible = True
    dialog._folder_path_trace_suppressed = False
    dialog._on_folder_path_changed()
    inspect.assert_not_called()
    dialog._browser_search_placeholder_visible["projects"] = True
    dialog._browser_search_trace_suppressed.discard("projects")
    dialog._on_browser_search_changed("projects")
    filtered.assert_not_called()
    dialog.search_function_var.set(False)
    filtered.reset_mock()
    before = dialog._browser_search_vars["projects"].get()
    dialog._show_browser_search_placeholder("projects")
    assert dialog._browser_search_vars["projects"].get() == before
    dialog.search_function_var.set(True)
    dialog._set_browser_search_var_safely("projects", "user query")
    dialog._show_browser_search_placeholder("projects")
    assert dialog._browser_search_vars["projects"].get() == "user query"


def test_widget_api_failures_leave_selection_and_cursor_cleanup_usable(
    connector_ui, monkeypatch
):
    """Inputs: failed focus/cursor operations and invalid widget-reported indices. Output: no changed selection, fallback IDs and bounded diagnostics."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    _connected_selection(dialog, client)
    dialog.projects_data, dialog.datasets_data = [{"id": 10}], [{"id": 20}]
    monkeypatch.setattr(dialog.root, "focus_get", lambda: dialog.ilist)
    monkeypatch.setattr(
        dialog.root,
        "focus_set",
        Mock(side_effect=tkinter.TclError("fixture focus unavailable")),
    )
    dialog._clear_browser_listbox_focus()
    monkeypatch.setattr(
        dialog.root,
        "configure",
        Mock(side_effect=tkinter.TclError("fixture cursor unavailable")),
    )
    dialog._reset_background_cursor_after_silent_work()
    monkeypatch.setattr(dialog.ilist, "nearest", lambda _y: 99)
    assert (
        dialog._on_image_listbox_click(SimpleNamespace(widget=dialog.ilist, y=0))
        == "break"
    )
    assert dialog.ilist.curselection() == (0,)
    monkeypatch.setattr(dialog.plist, "curselection", lambda: ("invalid",))
    monkeypatch.setattr(dialog.dlist, "curselection", lambda: (None,))
    assert dialog._current_selected_project_id() == "10"
    assert dialog._current_selected_dataset_id() == "20"
    getter = SimpleNamespace(
        winfo_width=Mock(side_effect=ValueError("fixture invalid dimension"))
    )
    assert module._safe_widget_dimension(getter, "winfo_width") == 0
    assert dialog.client is client and dialog._connected


def test_disabled_bridge_probe_finishes_without_overwriting_an_active_probe(
    connector_ui,
):
    """Inputs: optional bridge disabled or another probe already active. Output: bounded readiness and unchanged active probe state."""
    _module, dialog = connector_ui
    assert dialog._run_native_bridge_probe_now(timeout=0) is True
    assert dialog._native_bridge_probe_done.is_set()
    dialog._native_bridge_probe_in_progress = True
    dialog._native_bridge_probe_error = "active probe evidence"
    dialog._reset_native_bridge_probe_for_converter_detection()
    assert dialog._native_bridge_probe_in_progress
    assert dialog._native_bridge_probe_error == "active probe evidence"
    dialog._native_bridge_probe_in_progress = False
    dialog._reset_native_bridge_probe_for_converter_detection()
    assert dialog._native_bridge_probe_error == ""
    assert not dialog._native_bridge_probe_done.is_set()
    assert not dialog._native_bridge_probe_started


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("_connection_in_progress", True),
        ("_folder_export_in_progress", True),
        ("_load_in_progress", True),
        ("_modal_background_lock_depth", 1),
        ("_browser_sash_drag_index", 0),
    ],
)
def test_silent_probe_cleanup_preserves_the_active_operation_cursor(
    connector_ui, monkeypatch, attribute, value
):
    """Inputs: active operation owning the real window cursor. Output: silent cleanup leaves that cursor intact; idle cleanup later restores it."""
    _module, dialog = connector_ui
    dialog.root.configure(cursor="watch")
    with monkeypatch.context() as state:
        state.setattr(dialog, attribute, value)
        dialog._reset_background_cursor_after_silent_work()
        assert dialog.root.cget("cursor") == "watch"
    dialog._reset_background_cursor_after_silent_work()
    assert dialog.root.cget("cursor") == ""


@pytest.mark.parametrize("raced", [False, True])
def test_live_native_handle_is_reused_even_when_acquired_before_queued_handoff(
    connector_ui, monkeypatch, raced
):
    """Inputs: existing handle or handle acquired before a worker callback executes. Output: same live handle reused, no redundant native acquisition."""
    module, dialog = connector_ui
    app = SimpleNamespace(FileOpen=Mock(), GetFactory=Mock(return_value=object()))
    acquire = Mock(side_effect=AssertionError("Redundant native acquisition"))
    monkeypatch.setattr(module, "_resolve_imaris_application", acquire)
    dialog.imaris_id = 7
    if raced:
        invoke = dialog._invoke_on_ui_thread

        def install_then_invoke(callback, wait=True):
            """Inputs: queued handoff callback. Output: same callback after another successful acquisition supplies the handle."""

            def installed():
                """Inputs: none. Output: handle installed on the UI thread before handoff resolution."""
                dialog.imaris = app
                return callback()

            return invoke(installed, wait=wait)

        monkeypatch.setattr(dialog, "_invoke_on_ui_thread", install_then_invoke)
        results = []
        _run_worker_with_mainloop(
            dialog,
            lambda: results.append(dialog._resolve_direct_imaris_handle_for_handoff()),
        )
        assert results == [True]
    else:
        dialog.imaris = app
        assert dialog._resolve_direct_imaris_handle_for_handoff()
    assert dialog._has_imaris_handoff_target()
    assert dialog._ensure_native_open_ready_before_export()
    assert dialog.imaris is app
    acquire.assert_not_called()


def test_folder_export_launcher_passes_the_owned_cancellation_scope_to_its_worker(
    connector_ui, tmp_path, monkeypatch
):
    """Inputs: approved real folder selection. Output: one background launch carrying the exact current event and generation, without changing source files."""
    _module, dialog = connector_ui
    folder = tmp_path / "selected-folder"
    folder.mkdir()
    (folder / "image.tif").write_bytes(b"retained")
    _connected_selection(dialog, SimpleNamespace(session_id="fixture-session"))
    dialog._folder_export_available = True
    monkeypatch.setattr(dialog, "_select_folder_for_omero_export", lambda: str(folder))
    monkeypatch.setattr(dialog, "_ask_yes_no_dialog", lambda *_args: True)
    observed = []
    done = threading.Event()

    def receive(*args):
        """Inputs: actual background launch arguments. Output: captured cancellation ownership without uploading fixture data."""
        observed.append((threading.current_thread(), args))
        done.set()

    monkeypatch.setattr(dialog, "_export_folder_worker", receive)
    dialog._export_folder_to_omero()
    assert done.wait(2)
    worker, arguments = observed[0]
    worker.join(timeout=2)
    assert not worker.is_alive() and worker.ident != dialog._ui_thread_id
    assert arguments == (
        str(folder),
        folder.name,
        dialog._operation_cancel_event,
        dialog._operation_generation,
    )
    assert dialog._folder_export_in_progress
    assert not dialog._operation_cancel_event.is_set()
    assert (folder / "image.tif").read_bytes() == b"retained"
    dialog._clear_actions_busy_for_export()


def test_stale_folder_worker_failure_cannot_overwrite_a_new_operation(
    connector_ui, tmp_path, monkeypatch
):
    """Inputs: old upload fails after a newer operation owns the UI. Output: new controls/status/session remain intact, with no stale error dialog."""
    _module, dialog = connector_ui
    folder = tmp_path / "upload"
    folder.mkdir()
    (folder / "image.tif").write_bytes(b"retained")
    dialog._set_actions_busy_for_export(True)
    event, generation = dialog._operation_cancel_event, dialog._operation_generation

    def new_operation():
        """Inputs: current UI. Output: a new operation and its visible status."""
        event.set()
        dialog._clear_actions_busy_for_export()
        dialog._set_actions_busy_for_export(True)
        dialog._set_status("New operation running")

    def old_request(*_args):
        """Inputs: old upload request. Output: network failure after the UI has moved to the next operation."""
        dialog._invoke_on_ui_thread(new_operation)
        raise ConnectionResetError("old upload failed")

    client = SimpleNamespace(
        session_id="fixture-session",
        start_folder_export_job=Mock(side_effect=old_request),
    )
    _connected_selection(dialog, client)
    errors = Mock()
    monkeypatch.setattr(dialog, "_show_error_dialog", errors)
    _run_worker_with_mainloop(
        dialog,
        lambda: dialog._export_folder_worker(
            str(folder), folder.name, event, generation
        ),
    )
    errors.assert_not_called()
    assert dialog._folder_export_in_progress
    assert dialog.status.cget("text") == "New operation running"
    assert dialog._operation_generation > generation
    assert dialog.client is client and client.session_id == "fixture-session"
    assert (folder / "image.tif").read_bytes() == b"retained"
    dialog._clear_actions_busy_for_export()


def test_converter_discovery_and_unconfigured_export_directory_use_explicit_boundaries(
    connector_ui, tmp_path, monkeypatch
):
    """Inputs: discovered converter and no export-directory override. Output: capability reflects discovery and cache directory stays under the system temporary root."""
    module, dialog = connector_ui
    monkeypatch.setattr(
        module,
        "_find_imaris_file_converter_executable",
        lambda: str(tmp_path / "ImarisFileConverter.exe"),
    )
    assert dialog._has_imaris_converter_handoff_target()
    monkeypatch.setattr(module, "_find_imaris_file_converter_executable", lambda: None)
    assert not dialog._has_imaris_converter_handoff_target()
    monkeypatch.delenv("OMERO_IMARIS_EXPORT_DIR", raising=False)
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))
    expected = tmp_path / "ImarisOMEROExports"
    assert Path(dialog._get_export_dir()) == expected
    assert expected.is_dir()


def test_popup_destroy_failure_still_releases_selector_state_and_root_bindings(
    connector_ui, monkeypatch
):
    """Inputs: Tk rejects destruction of a popup. Output: closed selector state and detached root bindings, with the main window still usable."""
    module, dialog = connector_ui
    variable = tkinter.StringVar(master=dialog.root, value="OMERO")
    menu = module._ConverterDropdown(dialog.root, variable)
    menu.set_options(["OMERO", "Imaris"])
    menu.pack()
    dialog.root.update()
    menu.open_popup()
    popup = menu._popup
    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(
                popup,
                "destroy",
                Mock(side_effect=tkinter.TclError("fixture popup closing")),
            )
            menu.close_popup()
        assert menu._popup is None and not menu._open
        assert menu._root_click_bind_id is menu._root_escape_bind_id is None
        assert dialog.root.winfo_exists()
    finally:
        popup.destroy()
        menu._frame.destroy()


def test_modal_walker_excludes_child_dialogs_and_survives_widget_errors(
    connector_ui, monkeypatch
):
    """Inputs: real widgets, separate toplevel and failed widget queries. Output: only reachable main-window widgets."""
    module, dialog = connector_ui
    modal = tkinter.Toplevel(dialog.root)
    nested = tkinter.Label(modal, text="modal")
    nested.pack()
    broken_parent = tkinter.Frame(dialog.root)
    broken_child = tkinter.Label(dialog.root, text="unavailable")
    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(
                broken_parent,
                "winfo_children",
                Mock(side_effect=tkinter.TclError("destroyed")),
            )
            patcher.setattr(
                broken_child,
                "winfo_toplevel",
                Mock(side_effect=tkinter.TclError("destroyed")),
            )
            widgets = list(dialog._iter_modal_background_widgets())
        assert dialog.root in widgets and broken_parent in widgets
        assert (
            modal not in widgets
            and nested not in widgets
            and broken_child not in widgets
        )
        empty = object.__new__(module.OMEROBrowserDialog)
        assert list(empty._iter_modal_background_widgets()) == []
    finally:
        modal.destroy()


@pytest.mark.parametrize("failure_phase", ["lock", "unlock"])
def test_modal_cleanup_continues_after_one_widget_failure(
    connector_ui, monkeypatch, failure_phase
):
    """Inputs: one widget rejects a cursor update. Output: remaining widgets restore and modal state clears."""
    _module, dialog = connector_ui
    broken = tkinter.Label(dialog.root, text="broken", cursor="crosshair")
    healthy = tkinter.Label(dialog.root, text="healthy", cursor="watch")
    broken.pack()
    healthy.pack()
    dialog.root.update()
    with monkeypatch.context() as patcher:
        if failure_phase == "lock":
            patcher.setattr(
                broken, "cget", Mock(side_effect=tkinter.TclError("unavailable cursor"))
            )
        dialog._lock_modal_background()
        assert healthy.cget("cursor") == "arrow"
        if failure_phase == "unlock":
            patcher.setattr(
                broken,
                "configure",
                Mock(side_effect=tkinter.TclError("destroyed widget")),
            )
        dialog._unlock_modal_background()
    assert healthy.cget("cursor") == "watch"
    assert dialog._modal_background_lock_depth == 0
    assert dialog._modal_background_cursor_restore == []


@pytest.mark.parametrize("mode", ["blank", "placeholder", "typed", "invalid"])
def test_folder_placeholder_never_becomes_an_export_destination(
    connector_ui, tmp_path, monkeypatch, mode
):
    """Inputs: displayed placeholder or user-entered path. Output: only real valid text becomes a destination."""
    module, dialog = connector_ui
    value = {
        "blank": "",
        "placeholder": module.FOLDER_PATH_PLACEHOLDER,
        "typed": str(tmp_path),
        "invalid": "bad\x00path",
    }[mode]
    checks = Mock()
    monkeypatch.setattr(dialog, "_queue_folder_path_dir_check", checks)
    dialog._folder_path_placeholder_visible = mode in {"placeholder", "typed"}
    dialog._set_folder_path_var_safely(value)
    dialog._show_folder_path_placeholder()
    if mode in {"blank", "placeholder"}:
        assert dialog._folder_path_placeholder_visible
        assert dialog.folder_path_var.get() == module.FOLDER_PATH_PLACEHOLDER
        assert dialog._current_local_folder_path() == ""
        assert dialog.folder_path_entry.cget("fg") == module.FOLDER_PATH_PLACEHOLDER_FG
        dialog._hide_folder_path_placeholder()
        assert dialog.folder_path_var.get() == ""
        assert not dialog._folder_path_placeholder_visible
        assert dialog._folder_path_write_state == "empty"
    else:
        assert not dialog._folder_path_placeholder_visible
        assert dialog.folder_path_var.get() == value
        assert dialog._folder_path_write_state == (
            "unchecked" if mode == "typed" else "invalid"
        )
        checks.assert_called_with(value)
        assert dialog.folder_path_entry.cget("fg") == module.FOLDER_PATH_TEXT_FG


@pytest.mark.parametrize(
    "failure", ["after", "lift", "focus_force", "focus_set", "icursor"]
)
def test_failed_login_focus_recovery_tolerates_window_manager_errors(
    connector_ui, monkeypatch, failure
):
    """Inputs: one destroyed/unavailable GUI operation. Output: remaining focus recovery completes and modal lock clears."""
    _module, dialog = connector_ui
    client = object()
    dialog.client = client
    dialog._modal_background_lock_depth = 2
    dialog._modal_background_window_disabled = True
    target = (
        dialog.root
        if failure in {"after", "lift", "focus_force"}
        else dialog.pass_entry
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            target,
            failure,
            Mock(side_effect=tkinter.TclError("fixture window unavailable")),
        )
        dialog._queue_connection_retry_focus()
        dialog.root.update()
    assert dialog._modal_background_lock_depth == 0
    assert dialog._modal_background_window_disabled is False
    assert dialog.client is client
    assert dialog.pass_entry.winfo_exists()


@pytest.mark.parametrize(
    "failure", ["settings_path", "write_io", "write_type", "write_value"]
)
def test_autosave_failure_retains_previous_settings_and_authenticated_client(
    connector_ui, tmp_path, monkeypatch, failure
):
    """Inputs: persistence failure. Output: truthful failure, untouched prior configuration and no session reset."""
    module, dialog = connector_ui
    target = tmp_path / "connector-settings.env"
    target.write_text("OMERO_HOST=omero.example.test\n", encoding="utf-8")
    original_bytes = target.read_bytes()
    previous = {module.CONNECTOR_SETTINGS_HOST_KEY: "omero.example.test"}
    dialog._saved_settings = previous
    dialog._settings_file_path = None if failure == "settings_path" else str(target)
    dialog.client = object()
    original_client = dialog.client
    error = {
        "settings_path": OSError,
        "write_io": OSError,
        "write_type": TypeError,
        "write_value": ValueError,
    }[failure]("fixture unavailable settings")
    if failure == "settings_path":
        monkeypatch.setattr(
            module, "_connector_settings_env_path", Mock(side_effect=error)
        )
    else:
        monkeypatch.setattr(
            module, "_atomic_write_connector_settings", Mock(side_effect=error)
        )
    assert dialog._write_autosave_settings() is False
    assert "fixture unavailable settings" in dialog._autosave_settings_write_error
    assert dialog._saved_settings is previous
    assert dialog.client is original_client
    assert target.read_bytes() == original_bytes


@pytest.mark.parametrize(
    "mode,title",
    [
        ("disconnected", "Not Connected"),
        ("missing_client", "Not Connected"),
        ("refreshing", "Refresh In Progress"),
        ("no_path", "No Path Selected"),
        ("unwritable", None),
        ("no_selection", "No Selection"),
        ("no_converter", "No Converter"),
        ("confirmation_declined", None),
        ("duplicates_declined", None),
    ],
)
def test_load_preconditions_never_start_work_or_clear_login(
    connector_ui, tmp_path, monkeypatch, mode, title
):
    """Inputs: invalid or declined load in a real dialog. Output: no background job or session reset."""
    module, dialog = connector_ui
    client = module.OMEROWebClient("localhost", 443, "fixture-user", "", "https")
    client.session_id = "fixture-session"
    client.csrf_token = secrets.token_hex(16)
    client.cookie_jar = module.http.cookiejar.CookieJar()
    dialog.client = None if mode == "missing_client" else client
    dialog._connected = mode != "disconnected"
    dialog._refresh_in_progress = mode == "refreshing"
    dialog._available_converter_options = () if mode == "no_converter" else ("OMERO",)
    dialog.converter_var.set("OMERO")
    images = [] if mode == "no_selection" else [{"id": 7, "name": "fixture.ims"}]
    monkeypatch.setattr(dialog, "_selected_images", lambda: images)
    monkeypatch.setattr(
        dialog,
        "_current_local_folder_path",
        lambda: "" if mode == "no_path" else str(tmp_path),
    )
    monkeypatch.setattr(
        dialog, "_mark_folder_path_write_state", lambda _path: mode != "unwritable"
    )
    warn = Mock()
    write_error = Mock()
    monkeypatch.setattr(dialog, "_show_warning_dialog", warn)
    monkeypatch.setattr(dialog, "_show_folder_path_write_error", write_error)
    monkeypatch.setattr(
        dialog, "_ask_yes_no_dialog", lambda *_args: mode != "confirmation_declined"
    )
    monkeypatch.setattr(
        dialog, "_resolve_duplicate_download_policy", lambda *_args: (False, None)
    )
    thread = Mock(
        side_effect=AssertionError("Invalid or declined load started a worker")
    )
    original = (client.session_id, client.csrf_token, client.cookie_jar)
    with monkeypatch.context() as boundary:
        boundary.setattr(module, "threading", SimpleNamespace(Thread=thread))
        dialog._load()
    thread.assert_not_called()
    assert dialog.client is (None if mode == "missing_client" else client)
    assert (client.session_id, client.csrf_token, client.cookie_jar) == original
    assert not dialog._load_in_progress
    assert write_error.call_count == int(mode == "unwritable")
    if title:
        assert warn.call_args.args[0] == title
    else:
        warn.assert_not_called()


@pytest.mark.parametrize(
    "mode,title",
    [
        ("busy", None),
        ("refreshing", "Refresh In Progress"),
        ("disconnected", "Not Connected"),
        ("unavailable", "Export Unavailable"),
        ("selection_cancelled", None),
        ("invalid_path", "Invalid Folder"),
        ("filesystem_root", "Invalid Folder"),
        ("missing_folder", "Invalid Folder"),
        ("confirmation_declined", None),
    ],
)
def test_folder_export_preconditions_preserve_session_and_existing_data(
    connector_ui, tmp_path, monkeypatch, mode, title
):
    """Inputs: blocked or declined upload in a real dialog. Output: no upload and no login or data mutation."""
    module, dialog = connector_ui
    client = module.OMEROWebClient("localhost", 443, "fixture-user", "", "https")
    client.session_id = "fixture-session"
    client.cookie_jar = module.http.cookiejar.CookieJar()
    dialog.client = client
    dialog._connected = mode != "disconnected"
    dialog._refresh_in_progress = mode == "refreshing"
    dialog._folder_export_in_progress = mode == "busy"
    dialog._folder_export_available = mode != "unavailable"
    dialog._folder_export_reason = ""
    folder = tmp_path / "upload"
    folder.mkdir()
    original = folder / "source.dat"
    original.write_bytes(b"retain original user bytes")
    selected = {
        "selection_cancelled": "",
        "invalid_path": "\x00",
        "filesystem_root": folder.anchor,
        "missing_folder": str(tmp_path / "missing"),
    }.get(mode, str(folder))
    monkeypatch.setattr(dialog, "_select_folder_for_omero_export", lambda: selected)
    notices = Mock()
    monkeypatch.setattr(dialog, "_show_warning_dialog", notices)
    monkeypatch.setattr(dialog, "_show_error_dialog", notices)
    monkeypatch.setattr(dialog, "_ask_yes_no_dialog", lambda *_args: False)
    thread = Mock(side_effect=AssertionError("Blocked export started a worker"))
    jar = client.cookie_jar
    with monkeypatch.context() as boundary:
        boundary.setattr(module, "threading", SimpleNamespace(Thread=thread))
        dialog._export_folder_to_omero()
    thread.assert_not_called()
    assert dialog.client is client and client.session_id == "fixture-session"
    assert client.cookie_jar is jar
    assert original.read_bytes() == b"retain original user bytes"
    assert list(folder.iterdir()) == [original]
    if title:
        assert notices.call_args.args[0] == title
    else:
        notices.assert_not_called()


def test_startup_requires_connection_and_has_usable_geometry(connector_ui):
    """Inputs: new dialog. Output: disconnected controls and in-window action bounds."""
    module, dialog = connector_ui
    assert dialog.root.title() == "OMERO Connector"
    assert dialog._native_bridge_probe_done.is_set()
    assert not dialog._native_bridge_available
    assert dialog.host_entry.get() == dialog.user_entry.get() == ""
    assert dialog.pass_entry.cget("show") == "*"
    assert dialog.pass_entry.get() == ""
    assert dialog.connect_btn.cget("state") == "normal"
    assert dialog.load_btn.cget("state") == "disabled"
    assert dialog.export_btn.cget("state") == "disabled"
    assert not dialog.stop_btn._canvas.winfo_ismapped()
    assert Path(dialog.export_dir).is_dir()
    for width, height in ((1456, 760), (1800, 1000), (1000, 700)):
        dialog.root.geometry(f"{width}x{height}")
        dialog.root.update()
        actual_width = dialog.root.winfo_width()
        actual_height = dialog.root.winfo_height()
        for button in (dialog.load_btn, dialog.export_btn, dialog.close_btn):
            canvas = button._canvas
            x = canvas.winfo_rootx() - dialog.root.winfo_rootx()
            y = canvas.winfo_rooty() - dialog.root.winfo_rooty()
            assert 0 <= x < x + canvas.winfo_width() <= actual_width
            assert 0 <= y < y + canvas.winfo_height() <= actual_height
    assert dialog.root.minsize()[0] >= module.OMERO_CONNECTOR_WINDOW_WIDTH


def test_password_clipboard_and_automatic_remasking(connector_ui, monkeypatch):
    """Inputs: harmless test text and real timers. Output: hidden copy/cut stays blocked."""
    module, dialog = connector_ui
    monkeypatch.setattr(module, "PASSWORD_REVEAL_DURATION_MS", 100)
    dialog.password_reveal_btn.invoke()
    assert not dialog._password_revealed
    dialog.pass_entry.insert(0, "fixture-only-text")
    dialog.pass_entry.selection_range(0, "end")
    dialog.root.clipboard_clear()
    dialog.root.clipboard_append("retained-clipboard")
    for event in ("<<Copy>>", "<<Cut>>"):
        dialog.pass_entry.event_generate(event)
        dialog.root.update()
        assert dialog.root.clipboard_get() == "retained-clipboard"
        assert dialog.pass_entry.get() == "fixture-only-text"
    dialog.password_reveal_btn.invoke()
    assert dialog._password_revealed
    assert dialog.pass_entry.cget("show") == ""
    assert dialog._password_reveal_after_id is not None
    _pump_until(dialog.root, lambda: not dialog._password_revealed)
    assert dialog.pass_entry.cget("show") == "*"
    assert dialog._password_reveal_after_id is None
    dialog.password_reveal_btn.invoke()
    dialog.password_reveal_btn.invoke()
    assert not dialog._password_revealed
    dialog._clear_password_entry()
    assert dialog.pass_entry.get() == ""
    assert dialog._password_reveal_after_id is None


@pytest.mark.parametrize("value", ["a", "65536", "12 3", "-1", "1.5"])
def test_real_entry_validation_rejects_invalid_port_text(connector_ui, value):
    """Inputs: invalid port characters/range. Output: Tk rejects the edit, not just submit."""
    _, dialog = connector_ui
    dialog.port_entry.insert(0, value)
    assert dialog.port_entry.get() == ""
    dialog.port_entry.insert(0, "65535")
    assert dialog.port_entry.get() == "65535"
    dialog.port_entry.delete(0, "end")
    assert dialog.port_entry.get() == ""


@pytest.mark.parametrize(
    "widget_name",
    [
        "_RoundedButton",
        "_CircularIconButton",
        "_StopSignButton",
        "_PasswordRevealButton",
    ],
)
def test_canvas_buttons_obey_actual_pointer_and_disabled_states(
    connector_ui, widget_name
):
    """Inputs: native pointer events. Output: one callback per valid release; none disabled."""
    module, dialog = connector_ui
    panel = module.tk.Toplevel(dialog.root)
    calls = []
    button = getattr(module, widget_name)(
        panel,
        text="Test",
        command=lambda: calls.append("clicked"),
        width=160,
        height=50,
    )
    button.pack()
    dialog.root.update()
    canvas = button._canvas
    assert canvas.find_all()
    for sequence in ("<Enter>", "<ButtonPress-1>", "<ButtonRelease-1>"):
        canvas.event_generate(sequence, x=20, y=20)
        dialog.root.update()
    assert calls == ["clicked"]
    canvas.event_generate("<ButtonPress-1>", x=20, y=20)
    canvas.event_generate("<ButtonRelease-1>", x=-1, y=20)
    canvas.event_generate("<Leave>")
    dialog.root.update()
    assert calls == ["clicked"]
    button.config(state="disabled")
    for sequence in ("<Enter>", "<ButtonPress-1>", "<ButtonRelease-1>", "<Leave>"):
        canvas.event_generate(sequence, x=20, y=20)
        dialog.root.update()
    assert button.invoke() is None
    assert calls == ["clicked"]
    assert canvas.cget("cursor") == "arrow"
    button.configure(state="normal", width=180, height=60, text="Changed")
    dialog.root.update()
    assert canvas.winfo_width() == 180
    assert canvas.winfo_height() == 60
    assert (
        any(
            canvas.itemcget(item, "text") == "Changed"
            for item in canvas.find_all()
            if canvas.type(item) == "text"
        )
        or widget_name == "_PasswordRevealButton"
    )
    assert canvas.cget("cursor") == "hand2"
    panel.destroy()


def test_custom_widget_configuration_roundtrips_native_options(connector_ui):
    """Inputs: real canvas/button/dropdown configuration. Output: accurate public option reads and delegated Tk options."""
    module, dialog = connector_ui
    button = module._RoundedButton(dialog.root, text="Before")
    options = {
        "background": "#123456",
        "activebackground": "#234567",
        "foreground": "#345678",
        "activeforeground": "#456789",
        "text": "After",
        "state": "disabled",
    }
    button.configure(options, highlightthickness=2)
    for key, expected in options.items():
        assert button.cget(key) == expected
    assert button.cget("bg") == options["background"]
    assert button.cget("fg") == options["foreground"]
    assert int(button.cget("highlightthickness")) == 2
    callback = Mock(return_value="invoked")
    button.configure(command=callback, state="normal")
    assert button.invoke() == "invoked"
    callback.assert_called_once_with()
    value = module.tk.StringVar(master=dialog.root, value="First")
    dropdown = module._ConverterDropdown(dialog.root, value)
    dropdown.configure({"width": 237, "height": 31}, borderwidth=3)
    assert dropdown.cget("width") == 237
    assert dropdown.cget("height") == 31
    assert int(dropdown.cget("borderwidth")) == 3
    button._canvas.destroy()
    dropdown._frame.destroy()


@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize(
    "callback",
    [
        "_on_autosave_settings_changed",
        "_on_search_function_changed",
        "_on_collaboration_projects_changed",
        "_on_append_observed_folders_changed",
    ],
)
def test_preference_callbacks_refuse_disconnected_writes_and_report_save_failures(
    connector_ui, monkeypatch, connected, callback
):
    """Inputs: preference change while disconnected or storage unavailable. Output: no unauthorized save, explicit save failure, and no session reset."""
    _module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    dialog.client = client
    dialog._connected = connected
    write = Mock(return_value=False)
    notice, refresh = Mock(), Mock()
    monkeypatch.setattr(dialog, "_write_autosave_settings", write)
    monkeypatch.setattr(dialog, "_show_autosave_settings_error", notice)
    monkeypatch.setattr(dialog, "_refresh_browser", refresh)
    getattr(dialog, callback)()
    dialog.root.update()
    assert write.call_count == int(connected)
    assert notice.call_count == int(connected)
    assert refresh.call_count == int(
        connected and callback == "_on_collaboration_projects_changed"
    )
    assert dialog.client is client
    assert dialog._connected is connected
    assert client.session_id == "fixture-session"


@pytest.mark.parametrize(
    "case,title",
    [
        ("missing_pass", "Missing Fields"),
        ("missing_host", "Missing Fields"),
        ("missing_port", "Missing Fields"),
        ("missing_user", "Missing Fields"),
        ("invalid_port", "Invalid Port"),
        ("invalid_host", "Invalid Host"),
    ],
)
def test_connection_field_validation_never_starts_an_authentication_worker(
    connector_ui, monkeypatch, case, title
):
    """Inputs: incomplete or invalid UI fields including restored invalid port text. Output: precise feedback before creating a client or worker."""
    module, dialog = connector_ui
    values = {
        "host_entry": "bad/host" if case == "invalid_host" else "example.test",
        "port_entry": "not-a-port" if case == "invalid_port" else "443",
        "user_entry": "fixture",
        "pass_entry": secrets.token_urlsafe(24),
    }
    if case.startswith("missing_"):
        values[case.removeprefix("missing_") + "_entry"] = ""
    dialog.port_entry.configure(validate="none")
    for name, text in values.items():
        entry = getattr(dialog, name)
        entry.delete(0, "end")
        entry.insert(0, text)
    error, warning = Mock(), Mock()
    monkeypatch.setattr(dialog, "_show_error_dialog", error)
    monkeypatch.setattr(dialog, "_show_warning_dialog", warning)
    worker = Mock(side_effect=AssertionError("Invalid fields started authentication"))
    with monkeypatch.context() as boundary:
        boundary.setattr(module.threading, "Thread", worker)
        dialog._connect()
    worker.assert_not_called()
    feedback = warning if case.startswith("missing_") else error
    assert feedback.call_args.args[0] == title
    assert not dialog._connection_in_progress
    assert not dialog._connected


@pytest.mark.parametrize("available", [False, True])
def test_native_converter_preflight_reports_capability_without_exporting(
    connector_ui, monkeypatch, available
):
    """Inputs: present or missing native converter. Output: exact readiness result without starting an export or clearing the selected image."""
    _module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    _connected_selection(dialog, client)
    monkeypatch.setattr(
        dialog, "_has_imaris_converter_handoff_target", lambda: available
    )
    assert dialog._ensure_imaris_converter_handoff_ready_before_export() is available
    dialog.root.update()
    assert dialog.client is client and dialog._connected
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]
    assert not dialog._load_in_progress


@pytest.mark.parametrize("width", [1, 2, 3, 641])
def test_browser_layout_preserves_positive_tracks_at_tiny_widths(
    connector_ui, monkeypatch, width
):
    """Inputs: available panel width down to one pixel. Output: every real Tk grid track stays positive and repeated layout stays stable."""
    _module, dialog = connector_ui
    monkeypatch.setattr(dialog, "_browser_panel_area_width", lambda: width)
    dialog._apply_browser_panel_layout()
    dimensions = tuple(
        dialog.browser_frame.grid_columnconfigure(column)["minsize"]
        for column in (0, 2, 4)
    )
    assert all(value >= 1 for value in dimensions)
    assert dialog._browser_panel_layout_widths == dimensions
    dialog._apply_browser_panel_layout()
    assert dialog._browser_panel_layout_widths == dimensions


def test_destroyed_listbox_helpers_do_not_clear_other_selections(
    connector_ui, monkeypatch
):
    """Inputs: a genuinely destroyed Tk listbox. Output: safe diagnostics and unchanged live selection and login."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    _connected_selection(dialog, client)
    widget = module.tk.Listbox(dialog.root)
    widget.insert("end", "gone")
    widget.destroy()
    logs = []
    monkeypatch.setattr(module, "_xt_debug", logs.append)
    assert dialog._listbox_size(widget) == 0
    assert dialog._listbox_size(None) == 0
    dialog._set_listbox_anchor(widget, 0)
    dialog._focus_listbox(widget)
    assert sum("TclError" in line for line in logs) == 3
    shell = object.__new__(module.OMEROBrowserDialog)
    shell.root = None
    shell._clear_browser_listbox_focus()
    shell.root = module.tk.Tk()
    shell.root.destroy()
    shell._clear_browser_listbox_focus()
    assert logs[-1] == "Listbox focus lookup failed: TclError"
    assert dialog.client is client and dialog._connected
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]


def test_dropdown_selection_and_outside_click_preserve_root_bindings(connector_ui):
    """Inputs: native dropdown events. Output: exact selection and temporary bindings removed."""
    module, dialog = connector_ui
    panel = module.tk.Toplevel(dialog.root)
    value = module.tk.StringVar(master=panel, value="First")
    opened = []
    dropdown = module._ConverterDropdown(
        panel, value, on_open=lambda: opened.append(True)
    )
    dropdown.pack()
    dropdown.set_options(["First", "Second"])
    dialog.root.update()
    preserved = []
    original = panel.bind(
        "<ButtonPress-1>", lambda _event: preserved.append(True), add="+"
    )
    dropdown._label.event_generate("<Button-1>")
    dialog.root.update()
    assert dropdown._open and opened == [True]
    assert dropdown._popup.winfo_width() == dropdown._frame.winfo_width()
    second = next(
        widget
        for widget in _descendants(dropdown._popup)
        if isinstance(widget, module.tk.Label) and widget.cget("text") == "Second"
    )
    second.event_generate("<Enter>")
    second.event_generate("<Leave>")
    second.event_generate("<ButtonRelease-1>")
    dialog.root.update()
    assert value.get() == "Second"
    assert dropdown._popup is None
    assert original in panel.bind("<ButtonPress-1>")
    dropdown.open_popup()
    dialog.root.update()
    panel.event_generate("<ButtonPress-1>", x=0, y=0)
    dialog.root.update()
    assert not dropdown._open
    assert preserved
    dropdown.set_options([])
    dropdown.open_popup()
    assert dropdown._popup is None
    panel.destroy()


def test_dropdown_refresh_discards_stale_choices(connector_ui):
    """Inputs: changed options while open. Output: no obsolete selectable popup survives."""
    module, dialog = connector_ui
    panel = module.tk.Toplevel(dialog.root)
    value = module.tk.StringVar(master=panel, value="First")
    dropdown = module._ConverterDropdown(panel, value)
    dropdown.pack()
    dropdown.set_options(["First", "Second"])
    dialog.root.update()
    dropdown.open_popup()
    dialog.root.update()
    previous = dropdown._popup
    dropdown.set_options(["Replacement"])
    dialog.root.update()
    assert dropdown._popup is None
    assert not previous.winfo_exists()
    dropdown.open_popup()
    dialog.root.update()
    labels = [
        widget.cget("text")
        for widget in _descendants(dropdown._popup)
        if isinstance(widget, module.tk.Label)
    ]
    assert labels == ["Replacement"]
    panel.destroy()


@pytest.mark.parametrize("kind", ["help", "info"])
def test_modal_close_releases_grab_without_closing_connector(connector_ui, kind):
    """Inputs: actual modal and its Close control. Output: released input grab, live parent."""
    module, dialog = connector_ui
    observed = []

    def close_modal():
        """Inputs: scheduled callback. Output: records modal state and invokes Close."""
        children = [
            widget
            for widget in dialog.root.winfo_children()
            if isinstance(widget, module.tk.Toplevel)
        ]
        assert len(children) == 1
        child = children[0]
        observed.append((child.title(), dialog.root.grab_current() is child))
        close = next(
            widget
            for widget in _descendants(child)
            if isinstance(widget, module.tk.Button) and widget.cget("text") == "Close"
        )
        close.invoke()

    # An independent timeout bounds wait_window even if callback assertions fail.
    def destroy_stalled_modal():
        """Inputs: deadline callback. Output: destroys only this dialog's remaining children."""
        for widget in dialog.root.winfo_children():
            if isinstance(widget, module.tk.Toplevel):
                widget.destroy()

    watchdog = dialog.root.after(2000, destroy_stalled_modal)
    dialog.root.after(100, close_modal)
    getattr(dialog, f"_show_connector_{kind}")()
    dialog.root.after_cancel(watchdog)
    assert observed == [(getattr(module, f"CONNECTOR_{kind.upper()}_TITLE"), True)]
    assert dialog.root.grab_current() is None
    assert dialog.root.winfo_exists()


@pytest.mark.parametrize("operation", ["load", "export"])
def test_operation_controls_block_duplicate_action_and_restore_idle(
    connector_ui, operation
):
    """Inputs: busy/finished transitions. Output: disabled launchers and visible Stop only while busy."""
    _, dialog = connector_ui
    action = getattr(dialog, f"_set_actions_busy_for_{operation}")
    action(True)
    dialog.root.update()
    assert dialog.stop_btn._canvas.winfo_ismapped()
    for button in (
        dialog.connect_btn,
        dialog.load_btn,
        dialog.export_btn,
        dialog.refresh_btn,
    ):
        assert button.cget("state") == "disabled"
    dialog.stop_btn.invoke()
    assert dialog._operation_cancel_event.is_set()
    getattr(dialog, f"_finish_{operation}_workflow")(False, cancelled=True)
    dialog.root.update()
    assert not dialog.stop_btn._canvas.winfo_ismapped()
    assert dialog.connect_btn.cget("state") == "normal"
    assert dialog.load_btn.cget("state") == "disabled"
    assert dialog.export_btn.cget("state") == "disabled"


def test_browser_navigation_resets_children_and_fetches_exact_parent(connector_ui):
    """Inputs: a deterministic project tree. Output: selected IDs drive real Tk lists without stale children."""
    _, dialog = connector_ui
    calls = []
    projects = [{"id": 10, "name": "Alpha"}, {"id": 20, "name": "Beta"}]
    datasets = {
        "10": [{"id": 11, "name": "First"}],
        "20": [{"id": 21, "name": "Second"}],
    }
    images = {
        "11": [{"id": 12, "name": "First image"}],
        "21": [{"id": 22, "name": "Second image"}],
    }

    def fetch(kind, parent):
        """Inputs: parent identity. Output: the matching fixture children and an audit entry."""
        calls.append((kind, parent))
        return {"datasets": datasets, "images": images}[kind][parent]

    dialog.client = SimpleNamespace(
        list_projects=lambda **_kwargs: projects,
        list_datasets=lambda parent: fetch("datasets", parent),
        list_images=lambda parent: fetch("images", parent),
    )
    dialog._connected = True
    dialog._set_browser_interaction_state(True)
    dialog._load_projects()
    assert dialog.plist.get(0, "end") == ("Alpha", "Beta")
    for index, project_id, dataset_id, image_id in (
        (0, "10", "11", 12),
        (1, "20", "21", 22),
    ):
        dialog.plist.selection_clear(0, "end")
        dialog.plist.selection_set(index)
        dialog.plist.event_generate("<<ListboxSelect>>")
        dialog.root.update()
        assert dialog._pid == project_id
        assert dialog._did is None
        assert dialog.ilist.size() == 0
        assert dialog.datasets_data == datasets[project_id]
        dialog.dlist.selection_set(0)
        dialog.dlist.event_generate("<<ListboxSelect>>")
        dialog.root.update()
        assert dialog._did == dataset_id
        assert [row["id"] for row in dialog.images_data] == [image_id]
    assert calls == [
        ("datasets", "10"),
        ("images", "11"),
        ("datasets", "20"),
        ("images", "21"),
    ]


def test_search_and_multiselect_keep_visible_image_identity(connector_ui):
    """Inputs: real search/selection events. Output: filtering retains matching IDs, never hidden selections."""
    _, dialog = connector_ui
    dialog._connected = True
    dialog.search_function_var.set(True)
    dialog._set_browser_search_visible(True)
    images = [
        {"id": 101, "name": "Alpha one"},
        {"id": 102, "name": "Beta"},
        {"id": 103, "name": "Alpha two"},
        {"id": 104, "name": "Gamma"},
    ]
    dialog._all_images_data = images
    dialog._apply_browser_search_filter("images")
    dialog.root.update()
    dialog.ilist.focus_force()
    dialog.ilist.event_generate("<Control-a>")
    dialog.root.update()
    assert [image["id"] for image in dialog._selected_images()] == [101, 102, 103, 104]
    assert "images" in dialog._load_button_text()
    entry = dialog._browser_search_entries["images"]
    entry.event_generate("<FocusIn>")
    entry.insert(0, "ALPHA")
    dialog.root.update()
    assert [image["id"] for image in dialog.images_data] == [101, 103]
    assert [image["id"] for image in dialog._selected_images()] == [101, 103]
    assert dialog._image_selection_anchor == 0
    entry.delete(0, "end")
    entry.insert(0, "not-present")
    dialog.root.update()
    assert dialog.ilist.size() == 0
    assert dialog._selected_images() == []
    assert dialog._image_selection_anchor is None
    entry.delete(0, "end")
    entry.event_generate("<FocusOut>")
    dialog.root.update()
    assert dialog._browser_search_query("images") == ""
    assert dialog._browser_search_placeholder_visible["images"]
    assert dialog.images_data == images
    assert dialog._selected_images() == []
    dialog.search_function_var.set(False)
    dialog._set_browser_search_visible(False)
    dialog.root.update()
    assert not dialog._browser_search_frames["images"].winfo_ismapped()
    assert dialog._browser_search_query("images") == ""


def test_shift_control_selection_uses_stable_range_anchor(connector_ui):
    """Inputs: real pointer modifier events. Output: contiguous range and independent toggles."""
    _, dialog = connector_ui
    dialog._connected = True
    dialog._set_browser_interaction_state(True)
    dialog._all_images_data = [{"id": n, "name": f"Image {n}"} for n in range(5)]
    dialog._apply_browser_search_filter("images")
    dialog.root.update()
    for index, modifiers, expected in (
        (1, 0, (1,)),
        (3, 1, (1, 2, 3)),
        (2, 4, (1, 3)),
        (4, 4, (1, 3, 4)),
        (0, 0, (0,)),
    ):
        _, y, _, height = dialog.ilist.bbox(index)
        dialog.ilist.event_generate(
            "<ButtonPress-1>", x=10, y=y + height // 2, state=modifiers
        )
        dialog.root.update()
        assert dialog.ilist.curselection() == expected
    assert dialog._image_selection_anchor == 0


@pytest.mark.parametrize("busy", [False, True])
def test_health_outage_and_recovery_preserve_session_and_selection(
    connector_ui, monkeypatch, busy
):
    """Inputs: exhausted background checks. Output: retained login, selection and foreground work."""
    _, dialog = connector_ui
    client = SimpleNamespace(
        cookie_jar=None,
        session_id="fixture-session",
        session_key="fixture-session",
        csrf_token="fixture-csrf",
        user_id=7,
    )
    initial_session = vars(client).copy()
    dialog.client = client
    dialog._connected = True
    dialog._pid, dialog._did = "10", "20"
    dialog._set_browser_interaction_state(True)
    dialog.images_data = [{"id": 30, "name": "Selected image"}]
    for widget, text in (
        (dialog.plist, "Selected project"),
        (dialog.dlist, "Selected dataset"),
        (dialog.ilist, "Selected image"),
    ):
        widget.insert("end", text)
        widget.selection_set(0)
    dialog._set_status("Foreground task status")
    dialog._set_connection_indicator("busy" if busy else "connected")
    dialog.root.update()
    monkeypatch.setattr(
        dialog,
        "_show_error_dialog",
        lambda *_args: pytest.fail("Background health checks must not open a modal."),
    )
    generation = dialog._health_ping_generation
    dialog._health_ping_in_progress = True
    dialog._finish_health_ping(generation, TimeoutError("fixture-only failure"))
    dialog.root.update()

    assert dialog._connected and dialog.client is client
    assert vars(client) == initial_session
    assert (dialog._pid, dialog._did) == ("10", "20")
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]
    assert all(
        widget.curselection() == (0,)
        for widget in (dialog.plist, dialog.dlist, dialog.ilist)
    )
    assert not dialog._health_ping_in_progress
    assert dialog._health_ping_after_id is not None
    assert dialog._indicator_state == ("busy" if busy else "error")
    if busy:
        assert dialog.status.cget("text") == "Foreground task status"
        dialog._restore_idle_connection_indicator()
        assert dialog._indicator_state == "error"
    else:
        assert "retrying automatically" in dialog.status.cget("text")

    dialog._finish_health_ping(generation, None)
    dialog.root.update()
    assert dialog._indicator_state == "connected"
    assert dialog.status.cget("text") == (
        "Foreground task status" if busy else "Connection restored"
    )
    assert dialog.client is client and client.session_id == "fixture-session"
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]

    dialog._disconnect()
    dialog._finish_health_ping(generation, None)
    dialog.root.update()
    assert not dialog._connected and dialog.client is None
    assert client.session_id is None and client.csrf_token is None
    assert dialog._health_ping_after_id is None
    assert dialog.ilist.size() == 0
    assert dialog._indicator_state == "disconnected"


def test_health_recovery_does_not_replace_newer_foreground_status(
    connector_ui, monkeypatch
):
    """Inputs: operation progress after an outage warning. Output: health recovery cannot erase it."""
    _, dialog = connector_ui
    dialog.client = SimpleNamespace(cookie_jar=None)
    dialog._connected = True
    monkeypatch.setattr(
        dialog,
        "_show_error_dialog",
        lambda *_args: pytest.fail("Background health checks must not open a modal."),
    )
    generation = dialog._health_ping_generation
    dialog._finish_health_ping(generation, TimeoutError())
    dialog.root.update()
    dialog._set_status("Foreground operation completed")
    dialog.root.update()
    dialog._finish_health_ping(generation, None)
    dialog.root.update()
    assert dialog.status.cget("text") == "Foreground operation completed"
    assert dialog._indicator_state == "connected"


def test_authentication_rejection_clears_invalid_session_and_cancels_health_checks(
    connector_ui, monkeypatch
):
    """Inputs: confirmed authentication rejection. Output: explicit reconnect, cleared local state, no modal."""
    module, dialog = connector_ui
    client = SimpleNamespace(
        cookie_jar=None,
        session_id="fixture-expired-session",
        session_key="fixture-expired-session",
        csrf_token="fixture-csrf",
        user_id=7,
    )
    dialog.client = client
    dialog._connected = True
    dialog._set_browser_interaction_state(True)
    dialog.ilist.insert("end", "Previously selected image")
    dialog.ilist.selection_set(0)
    dialog._schedule_health_ping()
    generation = dialog._health_ping_generation
    monkeypatch.setattr(
        dialog,
        "_show_error_dialog",
        lambda *_args: pytest.fail(
            "Background authentication rejection must not open a modal."
        ),
    )
    dialog._finish_health_ping(generation, module._OMEROAuthenticationError())
    dialog.root.update()
    assert not dialog._connected and dialog.client is None
    assert client.session_id is None and client.csrf_token is None
    assert dialog.ilist.size() == 0
    assert dialog._health_ping_after_id is None
    assert dialog._health_ping_generation > generation
    assert dialog.status.cget("text") == "Authentication required - Please reconnect"
    assert dialog.connect_btn.cget("text") == "Connect"
    assert dialog.load_btn.cget("state") == "disabled"
    assert dialog._indicator_state == "disconnected"


@pytest.mark.parametrize("error", [None, TimeoutError("stale check")])
def test_stale_health_result_cannot_change_a_newer_session(connector_ui, error):
    """Inputs: an obsolete generation. Output: no status, indicator or timer mutation."""
    _, dialog = connector_ui
    dialog.client = SimpleNamespace(cookie_jar=None, session_id="fixture-new-session")
    dialog._connected = True
    dialog._health_ping_generation = 9
    dialog._set_status("New session")
    dialog._set_connection_indicator("busy")
    dialog._finish_health_ping(8, error)
    dialog.root.update()
    assert dialog.client.session_id == "fixture-new-session"
    assert dialog.status.cget("text") == "New session"
    assert dialog._indicator_state == "busy"
    assert dialog._health_ping_after_id is None


def _run_worker_with_mainloop(dialog, callback, timeout=5):
    """Inputs: bounded worker. Output: real cross-thread Tk dispatch and joined worker."""
    errors = []
    timed_out = []

    def work():
        """Inputs: callback closure. Output: retained worker errors for the test thread."""
        try:
            callback()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=work)

    def finished():
        """Inputs: worker state. Output: quit only after worker and queued Tk callbacks finish."""
        if worker.is_alive():
            dialog.root.after(5, finished)
        else:
            dialog.root.after_idle(dialog.root.quit)

    def deadline():
        """Inputs: expired test deadline. Output: cancel owned operation and stop waiting."""
        timed_out.append(True)
        dialog._operation_cancel_event.set()
        dialog.root.quit()

    watchdog = dialog.root.after(int(timeout * 1000), deadline)
    dialog.root.after(0, worker.start)
    dialog.root.after(5, finished)
    try:
        dialog.root.mainloop()
    finally:
        dialog.root.after_cancel(watchdog)
        worker.join(timeout=2)
    assert not timed_out and not worker.is_alive(), (
        "Connector worker exceeded its deadline"
    )
    assert errors == [], f"Worker raised outside its error boundary: {errors!r}"
    dialog.root.update()


def _connected_selection(dialog, client):
    """Inputs: client fixture. Output: connected UI with deterministic selected project/dataset/image."""
    dialog.client = client
    dialog._connected = True
    dialog._pid, dialog._did = "10", "20"
    dialog._set_browser_interaction_state(True)
    dialog.images_data = [{"id": 30, "name": "Selected image"}]
    for widget, text in (
        (dialog.plist, "Selected project"),
        (dialog.dlist, "Selected dataset"),
        (dialog.ilist, "Selected image"),
    ):
        widget.insert("end", text)
        widget.selection_set(0)


def test_folder_worker_finishing_after_window_close_never_calls_destroyed_tk(
    connector_ui, tmp_path, monkeypatch
):
    """Inputs: real folder worker completes after its Tk window closes. Output: worker exits without a Tcl call, exception or stale result."""
    module, dialog = connector_ui
    entered, release = threading.Event(), threading.Event()
    errors = []
    inspect = module._safe_is_directory

    def delayed_inspection(path):
        """Inputs: selected directory. Output: real filesystem result released only after window teardown."""
        entered.set()
        assert release.wait(3)
        return inspect(path)

    def work():
        """Inputs: owned folder-check worker. Output: retained failure for the main test thread."""
        try:
            dialog._folder_path_dir_check_worker(0, str(tmp_path))
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(module, "_safe_is_directory", delayed_inspection)
    worker = threading.Thread(target=work)
    worker.start()
    try:
        assert entered.wait(2)
        dialog._on_close()
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert errors == []
    assert dialog._folder_path_dir_check_value == ""
    dialog._on_close()


def test_window_close_releases_worker_waiting_for_a_discarded_ui_callback(
    connector_ui, monkeypatch
):
    """Inputs: synchronous worker callback queued behind window teardown. Output: bounded cancellation, never a callback on destroyed widgets."""
    module, dialog = connector_ui
    original_after = dialog.root.after
    queued = []
    outcome = []
    callback = Mock(return_value="must not execute")

    def deferred_after(delay, function=None, *args):
        """Inputs: worker callback scheduling. Output: real delayed Tk event that will be discarded by window destruction."""
        if threading.get_ident() != dialog._ui_thread_id:
            queued.append(function)
            return original_after(10000, function, *args)
        return original_after(delay, function, *args)

    def work():
        """Inputs: synchronous UI request. Output: its value or cancellation captured without a leaked test thread."""
        try:
            outcome.append(dialog._invoke_on_ui_thread(callback))
        except Exception as exc:
            outcome.append(exc)

    def close_after_queue():
        """Inputs: observed queued callback. Output: deterministic real window teardown after scheduling."""
        if queued:
            dialog._on_close()
        else:
            original_after(5, close_after_queue)

    monkeypatch.setattr(dialog.root, "after", deferred_after)
    worker = threading.Thread(target=work)
    original_after(0, worker.start)
    original_after(5, close_after_queue)
    original_after(3000, dialog.root.quit)
    try:
        dialog.root.mainloop()
        worker.join(timeout=2)
        assert not worker.is_alive(), "UI teardown left a worker waiting indefinitely"
        assert len(outcome) == 1 and isinstance(
            outcome[0], module._ConnectorOperationCancelled
        )
        callback.assert_not_called()
        queued[0]()
        callback.assert_not_called()
    finally:
        if worker.is_alive() and queued:
            queued[0]()
            worker.join(timeout=2)


@pytest.mark.parametrize("wait", [False, True])
def test_ui_callback_requested_after_close_is_cancelled_before_touching_tk(
    connector_ui, monkeypatch, wait
):
    """Inputs: callback submitted after real window teardown. Output: synchronous cancellation or asynchronous discard without Tk access."""
    module, dialog = connector_ui
    dialog._on_close()
    schedule = Mock(side_effect=AssertionError("Closed window contacted Tk"))
    monkeypatch.setattr(dialog.root, "after", schedule)
    callback = Mock()
    if wait:
        with pytest.raises(
            module._ConnectorOperationCancelled, match="window is closed"
        ):
            dialog._invoke_on_ui_thread(callback)
    else:
        assert dialog._invoke_on_ui_thread(callback, wait=False) is None
        dialog._set_status("late status")
        dialog._show_error("late", "error")
        dialog._show_info("late", "info")
    schedule.assert_not_called()
    callback.assert_not_called()


def test_ui_owner_can_request_a_synchronous_result_without_waiting_on_itself(
    connector_ui,
):
    """Inputs: synchronous request from Tk's owner thread. Output: immediate value or original exception, without event-loop deadlock."""
    _module, dialog = connector_ui
    callback = Mock(return_value="result")
    assert dialog._invoke_on_ui_thread(callback) == "result"
    callback.assert_called_once_with()
    error = ValueError("fixture callback failure")
    with pytest.raises(ValueError) as caught:
        dialog._invoke_on_ui_thread(Mock(side_effect=error))
    assert caught.value is error


def test_async_ui_callback_error_is_reported_by_tk_instead_of_silently_discarded(
    connector_ui, monkeypatch
):
    """Inputs: asynchronous callback failure. Output: original error reaches Tk's callback-error handler exactly once."""
    _module, dialog = connector_ui
    reported = []
    monkeypatch.setattr(
        dialog.root,
        "report_callback_exception",
        lambda kind, error, tb: reported.append((kind, error, tb)),
    )
    error = ValueError("fixture callback failure")
    dialog._invoke_on_ui_thread(Mock(side_effect=error), wait=False)
    dialog.root.update()
    assert len(reported) == 1
    assert reported[0][0] is ValueError and reported[0][1] is error
    assert reported[0][2] is not None


def test_event_loop_exit_runs_idempotent_connector_shutdown(connector_ui):
    """Inputs: real event loop exits through quit instead of the window-close button. Output: closed window and released shutdown state."""
    _module, dialog = connector_ui
    dialog.root.after(0, dialog.root.quit)
    dialog.show()
    assert dialog._ui_closed.is_set()
    assert dialog._health_ping_after_id is None
    assert dialog._indicator_after_id is None
    dialog._on_close()


@pytest.mark.parametrize(
    "options,folder", [([], False), (["OMERO"], False), (["Imaris"], True)]
)
def test_verified_connection_success_exposes_only_supported_workflows(
    connector_ui, options, folder
):
    """Inputs: completed login and verified capability set. Output: connected real GUI with accurate workflow choices, cleared password and scheduled read-only health checks."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="new-session", password="discarded credential")
    dialog._connection_in_progress = True
    dialog._finish_connect_success(
        client,
        [{"id": 17, "name": "Project"}],
        options,
        {"available": folder, "reason": "" if folder else "unavailable"},
    )
    dialog.root.update()
    assert dialog.client is client and dialog._connected
    assert not dialog._connection_in_progress
    assert client.password == module.CLEARED_CREDENTIAL_TEXT
    assert dialog._available_converter_options == tuple(options)
    assert dialog.converter_var.get() == (options[0] if options else "")
    assert dialog._folder_export_available is folder
    assert dialog.plist.get(0) == "Project"
    assert dialog.status.cget("text") == (
        "Connected to OMERO"
        if options or folder
        else "Connected, but no supported connector workflow is available"
    )
    assert dialog._health_ping_after_id is not None
    dialog._cancel_health_ping()


def test_custom_controls_preserve_geometry_popup_lifecycle_and_selection_callback(
    connector_ui,
):
    """Inputs: real canvas button/dropdown through geometry, hover, popup and selection APIs. Output: stable dimensions, correct popup dismissal and one selected value."""
    module, dialog = connector_ui
    area = tkinter.Toplevel(dialog.root)
    try:
        button = module._RoundedButton(area, text="Action", width=100, height=30)
        button.place(x=0, y=0)
        assert button._canvas.winfo_manager() == "place"
        assert button._set_dimension_option("width", 100) is False
        button.pack()
        button.pack_forget()
        assert button._canvas.winfo_manager() == ""
        variable = tkinter.StringVar(master=area, value="first")
        selected = Mock(return_value="selected")
        menu = module._ConverterDropdown(area, variable, command=selected)
        menu.set_options(["first", "second"])
        menu.grid()
        assert menu._frame.winfo_manager() == "grid"
        menu._frame.grid_remove()
        menu.pack()
        area.update()
        menu._on_enter(None)
        assert menu._hover
        menu._on_leave(None)
        assert not menu._hover
        menu.open_popup()
        popup = menu._popup
        assert popup is not None and popup.winfo_exists()
        menu._close_on_root_click_outside(SimpleNamespace(widget=menu._frame))
        menu._close_on_root_click_outside(SimpleNamespace(widget=popup))
        assert menu._popup is popup
        assert menu._toggle_popup() == "break"
        assert menu._popup is None and not popup.winfo_exists()
        assert menu._choose("second") == "selected"
        selected.assert_called_once_with("second")
        menu.pack_forget()
        assert menu._frame.winfo_manager() == ""
        module._ensure_tk_loaded()
        assert dialog.root.winfo_exists()
    finally:
        area.destroy()


@pytest.mark.parametrize("failure", ["constructor", "projects", "capabilities"])
def test_connection_worker_failure_restores_retry_controls_and_clears_new_credentials(
    connector_ui, monkeypatch, failure
):
    """Inputs: failed client creation, project lookup or capability lookup on real Tk worker. Output: retry-ready UI, cleared new credentials and no partially connected state."""
    module, dialog = connector_ui
    client = SimpleNamespace(
        connect=Mock(return_value=True),
        list_projects=Mock(
            return_value=[],
            side_effect=OSError("fixture projects unavailable")
            if failure == "projects"
            else None,
        ),
        password="fixture credential",
        session_id="new-session",
        csrf_token="new-csrf",
        session_key="new-key",
        cookie_jar=[],
    )
    factory = Mock(
        return_value=client,
        side_effect=OSError("fixture constructor failure")
        if failure == "constructor"
        else None,
    )
    monkeypatch.setattr(module, "OMEROWebClient", factory)
    monkeypatch.setattr(
        dialog,
        "_detect_converter_options_after_connection",
        Mock(side_effect=OSError("fixture capabilities unavailable")),
    )
    error = Mock()
    monkeypatch.setattr(dialog, "_show_error_dialog", error)
    dialog._connection_in_progress = True
    _run_worker_with_mainloop(
        dialog,
        lambda: dialog._connect_worker(
            "example.test", 443, "fixture", "secret", "https"
        ),
    )
    assert not dialog._connected and not dialog._connection_in_progress
    assert dialog.client is None
    assert dialog.status.cget("text") == "Connection failed"
    assert dialog._indicator_state == "error"
    assert str(dialog.pass_entry.cget("state")) == "normal"
    error.assert_called_once()
    if failure != "constructor":
        assert (
            not client.session_id and not client.csrf_token and not client.session_key
        )
        assert client.password == module.CLEARED_CREDENTIAL_TEXT
    factory.assert_called_once_with(
        "example.test", 443, "fixture", "secret", scheme="https"
    )


@pytest.mark.parametrize(
    "operation, field",
    [
        ("_cancel_password_reveal_timer", "_password_reveal_after_id"),
        ("_cancel_indicator_blink", "_indicator_after_id"),
        ("_cancel_health_ping", "_health_ping_after_id"),
        ("indicator", "_indicator_after_id"),
        ("_schedule_health_ping", "_health_ping_after_id"),
    ],
)
def test_timer_cancellation_failure_does_not_block_ui_cleanup(
    connector_ui, monkeypatch, operation, field
):
    """Inputs: Tcl refuses a stale timer cancellation. Output: cleanup finishes or a fresh timer replaces the stale handle, preserving the session."""
    _module, dialog = connector_ui
    client = SimpleNamespace(session_id="existing-session")
    dialog.client = client
    dialog._connected = True
    setattr(dialog, field, "stale-timer")
    with monkeypatch.context() as failure:
        cancel = Mock(side_effect=tkinter.TclError("timer command unavailable"))
        failure.setattr(dialog.root, "after_cancel", cancel)
        if operation == "indicator":
            dialog._set_connection_indicator("connected")
        else:
            getattr(dialog, operation)()
        cancel.assert_called_once_with("stale-timer")
    remaining = getattr(dialog, field)
    if operation == "_schedule_health_ping":
        assert remaining and remaining != "stale-timer"
        assert dialog.root.tk.call("after", "info", remaining)
        dialog._cancel_health_ping()
    else:
        assert remaining is None
    assert client.session_id == "existing-session"
    assert dialog.client is client


def test_indicator_worker_updates_only_through_the_real_tk_event_loop(connector_ui):
    """Inputs: background-worker indicator update. Output: queued main-thread repaint with the requested stable state."""
    _module, dialog = connector_ui
    _run_worker_with_mainloop(dialog, lambda: dialog._set_connection_indicator("error"))
    assert dialog._indicator_state == "error"
    assert (
        dialog.connection_indicator.itemcget(
            dialog.connection_indicator.find_all()[0], "fill"
        )
        == "#d64545"
    )


@pytest.mark.parametrize("selection", [None, 0])
def test_shift_selection_without_anchor_uses_current_selection_or_clicked_row(
    connector_ui, selection
):
    """Inputs: real image list with no explicit selection anchor. Output: deterministic Shift range, leaving other browser lists untouched."""
    _module, dialog = connector_ui
    dialog._set_browser_interaction_state(True)
    dialog.images_data = [
        {"id": index + 1, "name": f"Image {index}"} for index in range(4)
    ]
    dialog.ilist.delete(0, "end")
    for image in dialog.images_data:
        dialog.ilist.insert("end", image["name"])
    dialog.root.update()
    dialog._image_selection_anchor = None
    if selection is not None:
        dialog.ilist.selection_set(selection)
    bounds = dialog.ilist.bbox(2)
    assert bounds
    result = dialog._on_image_listbox_click(
        SimpleNamespace(widget=dialog.ilist, y=bounds[1] + 1, state=1)
    )
    assert result == "break"
    assert dialog.ilist.curselection() == ((2,) if selection is None else (0, 1, 2))
    assert dialog.plist.curselection() == dialog.dlist.curselection() == ()


def test_image_selection_handlers_ignore_other_widgets_and_empty_lists(connector_ui):
    """Inputs: events for another list or an empty Images list. Output: no invented row selection or modification to project selection."""
    _module, dialog = connector_ui
    dialog._set_browser_interaction_state(True)
    dialog.plist.insert("end", "Project")
    dialog.plist.selection_set(0)
    other = SimpleNamespace(widget=dialog.plist, y=0, state=0)
    empty = SimpleNamespace(widget=dialog.ilist, y=0, state=0)
    assert dialog._on_images_select_all(other) is None
    assert dialog._on_image_listbox_click(other) is None
    assert dialog._on_images_select_all(empty) == "break"
    assert dialog._on_image_listbox_click(empty) == "break"
    assert dialog.ilist.curselection() == ()
    assert dialog.plist.curselection() == (0,)


def test_browser_splitter_drag_resizes_second_boundary_without_losing_columns(
    connector_ui,
):
    """Inputs: real second splitter drag. Output: positive stable column widths, normalized fractions and cleared drag state on release."""
    _module, dialog = connector_ui
    dialog._start_browser_panel_resize(1, None)
    assert dialog._browser_sash_drag_index == 1
    dialog._drag_browser_panel_resize(
        SimpleNamespace(x_root=dialog.browser_frame.winfo_rootx() + 400)
    )
    dialog.root.update()
    assert sum(dialog._browser_panel_fractions) == pytest.approx(1)
    assert all(value > 0 for value in dialog._browser_panel_layout_widths)
    dialog._stop_browser_panel_resize(None)
    assert dialog._browser_sash_drag_index is None
    fractions = dialog._browser_panel_fractions
    dialog._drag_browser_panel_resize(SimpleNamespace(x_root=-100))
    assert dialog._browser_panel_fractions == fractions


def test_folder_existence_worker_and_stale_result_do_not_change_current_selection(
    connector_ui, tmp_path
):
    """Inputs: real background directory check and a late result from an older request. Output: latest valid path remains authoritative."""
    _module, dialog = connector_ui
    selected = tmp_path / "selected"
    selected.mkdir()
    dialog._folder_path_dir_check_generation = 7
    _run_worker_with_mainloop(
        dialog, lambda: dialog._folder_path_dir_check_worker(7, str(selected))
    )
    assert dialog._folder_path_dir_check_value == str(selected)
    assert dialog._folder_path_dir_check_is_dir is True
    dialog._finish_folder_path_dir_check(6, str(tmp_path / "old"), False)
    assert dialog._folder_path_dir_check_value == str(selected)
    assert dialog._folder_path_dir_check_is_dir is True


@pytest.mark.parametrize(
    "action", ["converter", "show_log", "enable_autosave", "folder"]
)
def test_autosave_failure_keeps_live_settings_and_warns_without_disconnecting(
    connector_ui, tmp_path, monkeypatch, action
):
    """Inputs: a settings commit denied during an authenticated user action. Output: warning, unchanged disk configuration and retained live session."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="retained-session")
    dialog.client = client
    dialog._connected = True
    dialog.autosave_settings_var.set(True)
    configuration = Path(dialog._settings_file_path)
    original = configuration.read_bytes()
    warning = Mock()
    monkeypatch.setattr(dialog, "_show_warning_dialog", warning)
    writer = Mock(side_effect=PermissionError("fixture settings read-only"))
    monkeypatch.setattr(module, "_atomic_write_connector_settings", writer)
    if action == "converter":
        dialog._select_converter("OMERO")
        assert dialog.converter_var.get() == "OMERO"
    elif action == "show_log":
        dialog._on_show_log_changed()
    elif action == "enable_autosave":
        dialog._enable_autosave_after_verified_connection()
    else:
        selected = tmp_path / "selected-folder"
        selected.mkdir()
        monkeypatch.setattr(
            module.filedialog, "askdirectory", lambda **_kwargs: str(selected)
        )
        dialog._select_local_folder()
        assert dialog._current_local_folder_path() == str(selected)
        assert dialog._folder_path_write_state == "writable"
        assert list(selected.iterdir()) == []
    dialog.root.update()
    warning.assert_called_once()
    assert "fixture settings read-only" == dialog._autosave_settings_write_error
    writer.assert_called_once()
    assert configuration.read_bytes() == original
    assert dialog.client is client and client.session_id == "retained-session"
    assert dialog._connected


@pytest.mark.parametrize(
    "kind, result",
    [
        ("showinfo", "ok"),
        ("askyesnocancel", None),
        ("askyesnocancel", False),
        ("askyesnocancel", True),
    ],
)
def test_information_and_cancel_dialogs_restore_modal_state_and_preserve_answer(
    connector_ui, monkeypatch, kind, result
):
    """Inputs: native messagebox answer while real main-window modal lock is held. Output: exact tri-state answer and restored interaction afterward."""
    module, dialog = connector_ui

    def answer(title, message, **kwargs):
        """Inputs: messagebox call. Output: selected answer with verified parent and active modal lock."""
        assert (title, message) == ("Title", "Question")
        assert kwargs["parent"] is dialog.root
        assert dialog._modal_background_lock_depth > 0
        if kind == "askyesnocancel":
            assert kwargs["default"] == "yes"
        return result

    monkeypatch.setattr(module.messagebox, kind, answer)
    method = (
        dialog._show_info_dialog
        if kind == "showinfo"
        else dialog._ask_yes_no_cancel_dialog
    )
    assert method("Title", "Question") == result
    assert dialog._modal_background_lock_depth == 0
    assert not dialog._modal_background_window_disabled


def test_disconnected_or_running_refresh_does_not_start_another_request(
    connector_ui, monkeypatch
):
    """Inputs: refresh while disconnected or already active. Output: one connection warning and no duplicate worker."""
    _module, dialog = connector_ui
    warning = Mock()
    monkeypatch.setattr(dialog, "_show_warning_dialog", warning)
    dialog._refresh_browser()
    warning.assert_called_once_with("Not Connected", "Please connect to OMERO first.")
    dialog._refresh_in_progress = True
    dialog._refresh_browser()
    assert warning.call_count == 1
    assert dialog.client is None
    assert dialog._refresh_in_progress
    dialog._refresh_in_progress = False


def test_destroyed_optional_widgets_do_not_break_folder_or_style_cleanup(connector_ui):
    """Inputs: real Tk widget destroyed before a deferred presentation update. Output: safe defaults and no callback exception."""
    module, dialog = connector_ui
    widget = tkinter.Label(dialog.root, text="fixture")
    widget.destroy()
    assert module._widget_background(widget) == "#f0f0f0"
    assert not module._widget_or_ancestor_is_text_input(widget)
    assert module._checkbutton_text_offset(widget) == 0
    assert not module._widget_is_or_descendant(None, dialog.root)
    dialog.folder_path_entry.destroy()
    dialog._set_folder_path_entry_fg("black")


@pytest.mark.parametrize("connected", [False, True])
def test_stopped_health_check_updates_no_disconnected_session_and_retries_transient_reads(
    connector_ui, monkeypatch, connected
):
    """Inputs: disconnected completion or one transient health-read failure. Output: correct indicator with no credential replay and bounded read retries."""
    module, dialog = connector_ui
    dialog._connected = connected
    if not connected:
        dialog._start_health_ping()
        dialog._finish_health_ping(dialog._health_ping_generation, None)
        assert dialog._indicator_state == "disconnected"
        assert not dialog._health_ping_in_progress
        return
    client = SimpleNamespace(
        session_id="retained-session", ping=Mock(side_effect=[OSError("offline"), True])
    )
    dialog.client = client
    monkeypatch.setattr(module, "_health_ping_retry_attempts", lambda: 2)
    monkeypatch.setattr(module, "_health_ping_retry_delay_seconds", lambda: 0.001)
    _run_worker_with_mainloop(
        dialog, lambda: dialog._health_ping_worker(dialog._health_ping_generation)
    )
    assert client.ping.call_count == 2
    assert client.session_id == "retained-session"
    assert dialog._connected and dialog._indicator_state == "connected"
    dialog._cancel_health_ping()


@pytest.mark.parametrize(
    "failure,converter,expected",
    [
        ("missing_id", "OMERO", "missing an OMERO image id"),
        ("unsupported", "Unknown", "Unsupported converter"),
        ("missing_file", "OMERO", "Failed to download"),
        ("invalid_ims", "OMERO", "not a valid IMS"),
        ("untracked_tiff", "Imaris", "not a readable TIFF"),
        ("handoff", "OMERO", "Failed to open IMS"),
        ("cancelled", "OMERO", None),
        ("stale_failure", "OMERO", None),
    ],
)
def test_load_worker_failures_preserve_login_files_and_current_ui(
    connector_ui, tmp_path, monkeypatch, failure, converter, expected
):
    """Inputs: real Tk worker and failed native/export boundaries. Output: no false handoff or logout, and no stale-worker UI mutation."""
    _module, dialog = connector_ui
    path = tmp_path / "image.ims"
    payload = b"invalid" if failure == "invalid_ims" else b"\x89HDF\r\n\x1a\nfixture"
    path.write_bytes(payload)
    client = SimpleNamespace(
        session_id="fixture-session",
        session_key="fixture-session",
        download_ims_export=Mock(return_value=str(path)),
    )
    _connected_selection(dialog, client)
    dialog.export_dir = str(tmp_path)
    dialog._set_actions_busy_for_load(True)
    event, generation = dialog._operation_cancel_event, dialog._operation_generation
    monkeypatch.setattr(dialog, "_ensure_native_open_ready_before_export", lambda: True)
    monkeypatch.setattr(
        dialog, "_ensure_imaris_converter_handoff_ready_before_export", lambda: True
    )
    monkeypatch.setattr(
        dialog,
        "_download_selected_image_with_imaris_converter",
        Mock(return_value=str(path)),
    )
    handoff = Mock(return_value=False)
    monkeypatch.setattr(dialog, "_open_downloaded_file_in_imaris", handoff)
    errors, information = Mock(), Mock()
    monkeypatch.setattr(dialog, "_show_error_dialog", errors)
    monkeypatch.setattr(dialog, "_show_info_dialog", information)
    if failure == "missing_file":
        client.download_ims_export.return_value = str(tmp_path / "absent.ims")
    if failure == "cancelled":
        event.set()
    if failure == "stale_failure":

        def replace_current_operation():
            """Inputs: an older in-flight download. Output: a newly owned operation, with the old event cancelled."""
            event.set()
            dialog._set_actions_busy_for_load(False)
            dialog._set_actions_busy_for_load(True)
            dialog._set_status("Current operation")

        def fail_after_new_operation(*_args, **_kwargs):
            """Inputs: an outstanding download request. Output: old request fails after the UI has moved to a new operation."""
            dialog._invoke_on_ui_thread(replace_current_operation)
            raise ConnectionResetError("stale transport")

        client.download_ims_export.side_effect = fail_after_new_operation
    dialog._set_status("Current operation")
    image = {} if failure == "missing_id" else {"id": 30, "name": "Selected image"}
    _run_worker_with_mainloop(
        dialog, lambda: dialog._load_worker(image, converter, None, event, generation)
    )
    assert dialog.client is client and dialog._connected
    assert client.session_id == client.session_key == "fixture-session"
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]
    assert path.read_bytes() == payload
    information.assert_not_called()
    assert errors.call_count == int(expected is not None)
    if expected:
        assert expected in errors.call_args.args[1]
    assert handoff.call_count == int(failure == "handoff")
    if failure == "stale_failure":
        assert dialog._load_in_progress
        assert dialog.status.cget("text") == "Current operation"
        dialog._set_actions_busy_for_load(False)
    else:
        assert not dialog._load_in_progress
        assert not dialog.stop_btn._canvas.winfo_ismapped()


@pytest.mark.parametrize("failure", ["transport", "permission", "authentication"])
def test_refresh_errors_never_replay_credentials_and_preserve_valid_sessions(
    connector_ui, monkeypatch, failure
):
    """Inputs: actual Tk refresh worker failures. Output: no login replay; only proven expiry clears state."""
    module, dialog = connector_ui
    client = SimpleNamespace(
        session_id="fixture-session",
        session_key="fixture-session",
        csrf_token="fixture-csrf",
        cookie_jar=None,
        user_id=7,
        reauthenticate=Mock(return_value=False),
    )
    _connected_selection(dialog, client)
    dialog._refresh_in_progress = True
    generation = dialog._refresh_generation
    error = {
        "transport": TimeoutError("fixture connection interruption"),
        "permission": RuntimeError("OMERO.web API request failed: HTTP 403."),
        "authentication": module._OMEROAuthenticationError("Not authenticated"),
    }[failure]
    fetch = Mock(side_effect=error)
    monkeypatch.setattr(dialog, "_fetch_browser_state_for_refresh", fetch)
    monkeypatch.setattr(module, "_refresh_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_refresh_retry_delay_seconds", lambda: 0)
    shown = Mock()
    monkeypatch.setattr(dialog, "_show_error_dialog", shown)
    _run_worker_with_mainloop(
        dialog, lambda: dialog._refresh_worker("10", "20", generation)
    )

    client.reauthenticate.assert_not_called()
    assert not dialog._refresh_in_progress
    if failure == "authentication":
        assert fetch.call_count == 1
        assert not dialog._connected and dialog.client is None
        assert dialog.ilist.size() == dialog.dlist.size() == dialog.plist.size() == 0
        assert "Authentication required" in dialog.status.cget("text")
    else:
        assert fetch.call_count == 3
        assert dialog._connected and dialog.client is client
        assert client.session_id == client.session_key == "fixture-session"
        assert (dialog._pid, dialog._did) == ("10", "20")
        assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]
        assert dialog.status.cget("text") == "Refresh failed"
        shown.assert_called_once()


def test_refresh_recovers_in_original_session_without_credential_replay(
    connector_ui, monkeypatch
):
    """Inputs: one failed read followed by data. Output: original client reused and refresh restored."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session", reauthenticate=Mock())
    _connected_selection(dialog, client)
    dialog._refresh_in_progress = True
    projects = [{"id": "10", "name": "Selected project"}]
    datasets = [{"id": "20", "name": "Selected dataset"}]
    images = [{"id": 30, "name": "Selected image"}]
    fetch = Mock(
        side_effect=[
            ConnectionResetError("fixture reset"),
            (projects, 0, datasets, 0, images),
        ]
    )
    monkeypatch.setattr(dialog, "_fetch_browser_state_for_refresh", fetch)
    monkeypatch.setattr(module, "_refresh_retry_attempts", lambda: 3)
    monkeypatch.setattr(module, "_refresh_retry_delay_seconds", lambda: 0)
    _run_worker_with_mainloop(
        dialog, lambda: dialog._refresh_worker("10", "20", dialog._refresh_generation)
    )
    client.reauthenticate.assert_not_called()
    assert fetch.call_count == 2
    assert dialog.client is client and client.session_id == "fixture-session"
    assert dialog._connected and not dialog._refresh_in_progress
    assert (dialog._pid, dialog._did) == ("10", "20")
    assert dialog.status.cget("text") == "OMERO browser refreshed"


def test_stale_refresh_worker_and_error_cannot_clear_new_session(
    connector_ui, monkeypatch
):
    """Inputs: stale work and an expired-session callback. Output: newer session and UI untouched."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="new-session")
    _connected_selection(dialog, client)
    dialog._refresh_generation = 3
    dialog._set_status("New session ready")
    fetch = Mock(
        side_effect=AssertionError("stale work must not query a newer session")
    )
    monkeypatch.setattr(dialog, "_fetch_browser_state_for_refresh", fetch)
    dialog._refresh_worker("10", "20", 2)
    dialog._finish_refresh_error(
        2, module._OMEROAuthenticationError("old session expired")
    )
    dialog.root.update()
    fetch.assert_not_called()
    assert dialog.client is client and dialog._connected
    assert dialog.status.cget("text") == "New session ready"
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]


@pytest.mark.parametrize(
    "outcome",
    ["done", "empty", "skips", "job", "entry", "truncated", "upload", "cancel"],
)
def test_folder_export_worker_preserves_session_and_finishes_actual_ui(
    connector_ui, tmp_path, monkeypatch, outcome
):
    """Inputs: real files and export boundary failures. Output: verified bytes, restored controls, retained login."""
    module, dialog = connector_ui
    folder = tmp_path / "selected-folder"
    folder.mkdir()
    payload = b"" if outcome == "empty" else b"123456789"
    source = folder / "data.bin"
    source.write_bytes(payload)
    job = {
        key: f"https://omero.example.test/{key}/"
        for key in (
            "upload_url",
            "import_step_url",
            "status_url",
            "confirm_url",
            "prune_url",
        )
    }
    dialog._set_actions_busy_for_export(True)
    event, generation = dialog._operation_cancel_event, dialog._operation_generation

    def upload(*_args):
        """Inputs: one upload chunk. Output: injected cancellation or a bounded transport failure."""
        if outcome == "cancel":
            event.set()
        if outcome == "upload":
            raise ConnectionResetError("fixture upload interruption")
        return {}

    client = SimpleNamespace(
        session_id="fixture-session",
        session_key="fixture-session",
        start_folder_export_job=Mock(return_value={} if outcome == "job" else job),
        upload_folder_chunk=Mock(side_effect=upload),
        trigger_folder_export=Mock(),
        get_folder_export_status=Mock(
            return_value={
                "status": "done",
                "incompatible_files": ["skipped.bin"] if outcome == "skips" else [],
            }
        ),
        cancel_folder_export_job=Mock(),
    )
    _connected_selection(dialog, client)
    if outcome in {"entry", "truncated"}:
        monkeypatch.setattr(
            module,
            "_collect_local_folder_entries",
            lambda _folder: [
                {
                    "absolute_path": None if outcome == "entry" else str(source),
                    "relative_path": source.name,
                    "size": len(payload) + 1,
                }
            ],
        )
    monkeypatch.setattr(module, "_upload_chunk_size_bytes", lambda: 4)
    information, errors = Mock(), Mock()
    monkeypatch.setattr(dialog, "_show_info_dialog", information)
    monkeypatch.setattr(dialog, "_show_error_dialog", errors)
    _run_worker_with_mainloop(
        dialog,
        lambda: dialog._export_folder_worker(
            str(folder), "Fixture folder", event, generation
        ),
    )

    successful = outcome in {"done", "empty", "skips"}
    assert dialog.client is client and dialog._connected
    assert client.session_id == client.session_key == "fixture-session"
    assert dialog._selected_images() == [{"id": 30, "name": "Selected image"}]
    assert not dialog._folder_export_in_progress
    assert not dialog.stop_btn._canvas.winfo_ismapped()
    assert dialog.connect_btn.cget("state") == "normal"
    assert source.read_bytes() == payload
    assert information.call_count == int(successful)
    assert errors.call_count == int(not successful and outcome != "cancel")
    assert client.trigger_folder_export.call_count == int(successful)
    assert client.cancel_folder_export_job.call_count == int(outcome == "cancel")
    if successful:
        chunks = [call.args for call in client.upload_folder_chunk.call_args_list]
        assert b"".join(chunk[4] for chunk in chunks) == payload
        assert [chunk[3] for chunk in chunks] == list(range(0, max(1, len(payload)), 4))
        assert all(chunk[2] == len(payload) for chunk in chunks)
        assert [chunk[5] for chunk in chunks] == [False] * (len(chunks) - 1) + [True]
    if outcome == "truncated":
        assert "size verification failed" in errors.call_args.args[1]
    if outcome == "cancel":
        assert dialog.status.cget("text") == "Folder export stopped by user"


@pytest.mark.parametrize(
    ("status", "fields", "expected"),
    [
        ("uploading", {}, "Uploading folder 'Fixture' to OMERO..."),
        (
            "uploading",
            {"uploaded_bytes": 3, "total_bytes": 4},
            "Uploading folder to OMERO... 75.0%",
        ),
        ("checking", {}, "Checking folder export compatibility in OMERO..."),
        (
            "awaiting_confirmation",
            {},
            "Waiting for confirmation to continue the OMERO folder export...",
        ),
        ("ready", {}, "Starting OMERO folder export..."),
        ("importing", {}, "Exporting folder 'Fixture' to OMERO..."),
        (
            "importing",
            {"import_progress_bytes": 4, "total_bytes": 3},
            "Exporting folder to OMERO... 100.0%",
        ),
        ("done", {}, "Folder export completed in OMERO"),
        ("error", {}, "Folder export failed"),
        ("QUEUED", {}, "Folder export status: queued"),
        ("", {}, "Exporting folder 'Fixture' to OMERO..."),
    ],
)
def test_folder_status_uses_truthful_phase_and_bounded_progress(
    connector_ui, status, fields, expected
):
    """Inputs: phase payloads. Output: operator-visible phase and bounded percentage, never fake progress."""
    _, dialog = connector_ui
    assert (
        dialog._folder_export_status_text("Fixture", dict(fields, status=status))
        == expected
    )


@pytest.mark.parametrize("accepted", [False, True])
def test_folder_confirmation_is_bounded_and_honors_user_choice(
    connector_ui, monkeypatch, accepted
):
    """Inputs: many incompatible files and an explicit answer. Output: bounded preview and exact decision."""
    module, dialog = connector_ui
    files = [
        f"file-{index}.bin"
        for index in range(module.FOLDER_EXPORT_CONFIRM_PREVIEW_LIMIT + 2)
    ]
    prompt = Mock(return_value=accepted)
    monkeypatch.setattr(dialog, "_ask_yes_no_dialog", prompt)
    result = []
    _run_worker_with_mainloop(
        dialog,
        lambda: result.append(
            dialog._confirm_folder_export_with_incompatible_files(
                {"incompatible_files": files}
            )
        ),
    )
    assert result == [accepted]
    title, text = prompt.call_args.args
    assert title == "Confirm Compatible OMERO Export"
    assert files[0] in text and files[-1] not in text
    assert "and 2 more" in text


@pytest.mark.parametrize(
    "state",
    ["live", "disabled", "missing-id", "cached", "rediscovered", "absent", "error"],
)
def test_native_bridge_revalidation_clears_stale_capability_without_touching_login(
    connector_ui, monkeypatch, state
):
    """Inputs: bridge state changes. Output: truthful capability/cache, no authenticated-client mutation."""
    module, dialog = connector_ui
    client = SimpleNamespace(session_id="fixture-session")
    dialog.client = client
    stale_handle = object()
    dialog.imaris = stale_handle
    dialog.imaris_id = None if state == "missing-id" else 17
    dialog._native_bridge_python_executable = "cached-interpreter"
    dialog._native_bridge_probe_error = "stale error"
    monkeypatch.setattr(
        module,
        "_imaris_application_handle_is_live",
        lambda handle: state == "live" and handle is stale_handle,
    )
    monkeypatch.setattr(
        module, "_native_imaris_bridge_enabled", lambda: state != "disabled"
    )
    probe = Mock(return_value=state == "cached")
    discovery = Mock(
        return_value="new-interpreter" if state == "rediscovered" else None,
        side_effect=OSError("fixture bridge failure") if state == "error" else None,
    )
    monkeypatch.setattr(module, "_run_native_bridge_probe_helper", probe)
    monkeypatch.setattr(module, "_find_compatible_native_bridge_python", discovery)
    ready = state in {"live", "cached", "rediscovered"}
    assert dialog._revalidate_native_bridge() == ready
    assert dialog._native_bridge_available == ready
    assert bool(dialog._native_bridge_last_verified_at) == ready
    assert dialog.client is client and client.session_id == "fixture-session"
    assert (dialog.imaris is stale_handle) == (state == "live")
    if state in {"live", "disabled", "missing-id"}:
        probe.assert_not_called()
        discovery.assert_not_called()
    elif state == "cached":
        discovery.assert_not_called()
        assert dialog._native_bridge_python_executable == "cached-interpreter"
    else:
        assert dialog._native_bridge_python_executable == (
            "new-interpreter" if ready else None
        )
        assert bool(dialog._native_bridge_probe_error) != ready
