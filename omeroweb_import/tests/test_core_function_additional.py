from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from omeroweb_import.views import core_functions


class _State:
    def __init__(self, image_id, *, persist_on_refresh=True):
        self.image_id = image_id
        self.persist_on_refresh = persist_on_refresh
        self.values = {}


class _PixelsWrapper:
    def __init__(
        self,
        state: _State,
        *,
        with_obj: bool = True,
        missing_axis: str | None = None,
        reload_error: str | None = None,
    ):
        self._state = state
        self._reload_error = reload_error
        if with_obj:
            setters = {"image_id": state.image_id}
            for axis_name in ("X", "Y", "Z"):
                if axis_name == missing_axis:
                    continue
                setters[f"setPhysicalSize{axis_name}"] = (
                    lambda value, key=axis_name.lower(): self._state.values.__setitem__(
                        key, value
                    )
                )
            self._obj = types.SimpleNamespace(**setters)
        else:
            self._obj = None

    def _value(self, axis_name):
        if self._reload_error:
            raise RuntimeError(self._reload_error)
        if not self._state.persist_on_refresh:
            return "mismatch"
        return self._state.values.get(axis_name)

    def getPhysicalSizeX(self):
        return self._value("x")

    def getPhysicalSizeY(self):
        return self._value("y")

    def getPhysicalSizeZ(self):
        return self._value("z")


class _ImageWrapper:
    def __init__(
        self,
        state: _State,
        *,
        with_obj: bool = True,
        missing_axis: str | None = None,
        pixels_error: str | None = None,
        reload_error: str | None = None,
    ):
        self._state = state
        self._with_obj = with_obj
        self._missing_axis = missing_axis
        self._pixels_error = pixels_error
        self._reload_error = reload_error

    def getPrimaryPixels(self):
        if self._pixels_error:
            raise RuntimeError(self._pixels_error)
        return _PixelsWrapper(
            self._state,
            with_obj=self._with_obj,
            missing_axis=self._missing_axis,
            reload_error=self._reload_error,
        )


def _stateful_job_updates(monkeypatch, job):
    state = {"job": job}

    def _update_job(job_id, mutator):
        assert job_id == job["job_id"]
        state["job"] = mutator(state["job"])
        return state["job"]

    monkeypatch.setattr(core_functions, "_update_job", _update_job)
    return state


def test_finalize_imported_zarr_image_metadata_covers_prerequisites_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed_zarr = tmp_path / "managed"

    assert core_functions._finalize_imported_zarr_image_metadata(
        "",
        "omeroserver",
        4064,
        ["101"],
        managed_zarr=managed_zarr,
    ) == (
        False,
        ["Missing importing username for native Zarr metadata finalization."],
    )

    assert core_functions._finalize_imported_zarr_image_metadata(
        "alice",
        "omeroserver",
        4064,
        ["", "  ", ""],
        managed_zarr=managed_zarr,
    ) == (
        False,
        ["No imported Image IDs were available for native Zarr metadata finalization."],
    )

    monkeypatch.setattr(core_functions, "_open_admin_connection", lambda *_args: None)
    assert core_functions._finalize_imported_zarr_image_metadata(
        "alice",
        "omeroserver",
        4064,
        ["101"],
        managed_zarr=managed_zarr,
    ) == (
        False,
        ["Failed to open an admin connection for native Zarr metadata finalization."],
    )

    class _Conn:
        def __init__(self):
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=lambda value: setattr(self, "group", value)
            )
            self.states = {
                9: _State(9),
                10: _State(10),
                11: _State(11),
                12: _State(12),
                13: _State(13, persist_on_refresh=False),
                14: _State(14),
                15: _State(15),
            }
            self.calls = {}
            self.closed = False

        def getUpdateService(self):
            def _save(obj):
                if getattr(obj, "image_id", None) == 10:
                    raise RuntimeError("save exploded")
                return obj

            return types.SimpleNamespace(saveAndReturnObject=_save)

        def getObject(self, object_type, image_id):
            assert object_type == "Image"
            image_id = int(image_id)
            self.calls[image_id] = self.calls.get(image_id, 0) + 1
            call_number = self.calls[image_id]
            if image_id == 1:
                raise RuntimeError("lookup exploded")
            if image_id == 2:
                return None
            if image_id in {3, 4, 5, 6}:
                return _ImageWrapper(_State(image_id))
            if image_id == 7:
                return _ImageWrapper(_State(7), pixels_error="primary exploded")
            if image_id == 8:
                return _ImageWrapper(_State(8), with_obj=False)
            if image_id == 9:
                return _ImageWrapper(self.states[9], missing_axis="Y")
            if image_id == 10:
                return _ImageWrapper(self.states[10])
            if image_id == 11:
                if call_number == 1:
                    return _ImageWrapper(self.states[11])
                return None
            if image_id == 12:
                if call_number == 1:
                    return _ImageWrapper(self.states[12])
                return _ImageWrapper(
                    self.states[12], pixels_error="reload pixels exploded"
                )
            if image_id == 13:
                return _ImageWrapper(self.states[13])
            if image_id == 14:
                return _ImageWrapper(self.states[14])
            if image_id == 15:
                return _ImageWrapper(self.states[15])
            raise AssertionError(f"Unexpected image id {image_id}")

        def close(self):
            self.closed = True
            raise RuntimeError("conn close exploded")

    conn = _Conn()

    class _AdminConn:
        def __init__(self):
            self.closed = False

        def suConn(self, username):
            assert username == "alice"
            return conn

        def close(self):
            self.closed = True
            raise RuntimeError("admin close exploded")

    admin_conn = _AdminConn()
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: admin_conn,
    )
    monkeypatch.setattr(
        core_functions,
        "_query_image_external_info",
        lambda _conn, image_id: {
            3: ("", None),
            4: ("unexpected-lsid", None),
            5: ("meta-error", None),
            6: ("no-sizes", None),
            7: ("pixels-error", None),
            8: ("missing-pixels-obj", None),
            9: ("missing-setter", None),
            10: ("save-error", None),
            11: ("reload-none", None),
            12: ("reload-pixels-error", None),
            13: ("mismatch", None),
            14: ("persisted", None),
            15: ("already-matching", None),
        }[image_id],
    )
    monkeypatch.setattr(
        core_functions,
        "_native_zarr_image_relative_path_from_lsid",
        lambda _managed_root, lsid: (
            (_ for _ in ()).throw(ValueError("bad lsid"))
            if lsid == "unexpected-lsid"
            else lsid
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_runtime_native_zarr_physical_sizes",
        lambda _managed_root, relative_path: {
            "meta-error": ({}, "metadata exploded"),
            "no-sizes": ({}, None),
            "pixels-error": ({"x": "pixels-x"}, None),
            "missing-pixels-obj": ({"x": "pixels-x"}, None),
            "missing-setter": ({"y": "pixels-y"}, None),
            "save-error": ({"x": "pixels-x"}, None),
            "reload-none": ({"x": "pixels-x"}, None),
            "reload-pixels-error": ({"x": "pixels-x"}, None),
            "mismatch": ({"x": "expected"}, None),
            "persisted": ({"x": "expected"}, None),
            "already-matching": ({"x": None}, None),
        }[relative_path],
    )
    monkeypatch.setattr(
        core_functions,
        "_native_zarr_length_signature",
        lambda value: value,
    )

    ok, errors = core_functions._finalize_imported_zarr_image_metadata(
        "alice",
        "omeroserver",
        4064,
        [
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11",
            "12",
            "13",
            "14",
            "15",
        ],
        managed_zarr=managed_zarr,
        group_name="users-private",
    )

    assert ok is False
    assert conn.group == "users-private"
    assert conn.closed is True
    assert admin_conn.closed is True
    assert any("lookup exploded" in message for message in errors)
    assert any(
        "could not be loaded during native Zarr metadata finalization" in message
        for message in errors
    )
    assert any("missing externalInfo.lsid" in message for message in errors)
    assert any("unexpected externalInfo.lsid" in message for message in errors)
    assert any("metadata exploded" in message for message in errors)
    assert any("primary Pixels lookup failed" in message for message in errors)
    assert any("primary Pixels object was unavailable" in message for message in errors)
    assert any(
        "missing a physical-size setter for axis Y" in message for message in errors
    )
    assert any("physical pixel-size save failed" in message for message in errors)
    assert any(
        "could not be reloaded after native Zarr metadata finalization" in message
        for message in errors
    )
    assert any("primary Pixels reload failed" in message for message in errors)
    assert any("did not persist" in message for message in errors)
    assert conn.states[14].values["x"] == "expected"


def test_check_import_compatibility_covers_timeout_cli_errors_and_native_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.ome.tif"
    missing_response = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        missing,
        7,
        "missing.ome.tif",
    )
    assert missing_response == {
        "status": "error",
        "relative_path": "missing.ome.tif",
        "stdout": "",
        "stderr": "Missing staged file: missing.ome.tif",
        "details": "Missing staged file: missing.ome.tif",
    }

    zarr_dir = tmp_path / "image.ome.zarr"
    zarr_dir.mkdir()
    monkeypatch.setattr(core_functions, "_native_zarr_import_enabled", lambda: True)
    monkeypatch.setattr(
        core_functions,
        "_serialize_native_zarr_plan",
        lambda plan: {
            "kind": plan.kind,
            "recognized_zarr": plan.recognized_zarr,
            "validation_error": plan.validation_error,
            "compatibility_details": plan.compatibility_details,
        },
    )

    timeout_plan = core_functions._NativeZarrImportPlan(kind="native-kind")
    monkeypatch.setattr(
        core_functions, "_native_zarr_import_plan", lambda _path: timeout_plan
    )
    monkeypatch.setattr(
        core_functions,
        "_get_local_import_scan_timeout_seconds",
        lambda: 321,
    )
    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda _path: (_ for _ in ()).throw(subprocess.TimeoutExpired(["omero"], 321)),
    )
    timeout_response = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert (
        timeout_response["details"] == "Compatibility check timeout after 321 seconds"
    )
    assert (
        timeout_response["import_backend"]
        == core_functions._ZARR_IMPORT_BACKEND_BIOFORMATS
    )
    assert timeout_response["native_zarr_plan"]["kind"] == "native-kind"

    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda _path: (_ for _ in ()).throw(FileNotFoundError("omero missing")),
    )
    cli_missing = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert cli_missing["details"] == "OMERO CLI not found: omero missing"
    assert (
        cli_missing["import_backend"] == core_functions._ZARR_IMPORT_BACKEND_BIOFORMATS
    )

    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda _path: (_ for _ in ()).throw(RuntimeError("scan exploded")),
    )
    scan_error = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert (
        scan_error["details"]
        == "Unexpected error during compatibility check: scan exploded"
    )
    assert (
        scan_error["import_backend"] == core_functions._ZARR_IMPORT_BACKEND_BIOFORMATS
    )

    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda _path: types.SimpleNamespace(
            returncode=0, stdout="stdout", stderr="stderr"
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_classify_compatibility_output",
        lambda *args, **kwargs: ("compatible", "ready"),
    )
    compatible = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert compatible["status"] == "compatible"
    assert (
        compatible["import_backend"] == core_functions._ZARR_IMPORT_BACKEND_BIOFORMATS
    )

    native_plan = core_functions._NativeZarrImportPlan(
        kind="native-kind",
        compatibility_details="native-ready",
    )
    monkeypatch.setattr(
        core_functions, "_native_zarr_import_plan", lambda _path: native_plan
    )
    monkeypatch.setattr(
        core_functions,
        "_classify_compatibility_output",
        lambda *args, **kwargs: ("incompatible", "bioformats-no"),
    )
    native_compatible = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert native_compatible["status"] == "compatible"
    assert (
        native_compatible["import_backend"]
        == core_functions._ZARR_IMPORT_BACKEND_NATIVE
    )
    assert native_compatible["details"] == "native-ready"

    invalid_native_plan = core_functions._NativeZarrImportPlan(
        recognized_zarr=True,
        validation_error="layout invalid",
    )
    monkeypatch.setattr(
        core_functions, "_native_zarr_import_plan", lambda _path: invalid_native_plan
    )
    native_error = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert native_error["status"] == "error"
    assert native_error["details"] == "layout invalid"
    assert native_error["import_backend"] == core_functions._ZARR_IMPORT_BACKEND_NATIVE

    incompatible_plan = core_functions._NativeZarrImportPlan(recognized_zarr=False)
    monkeypatch.setattr(
        core_functions, "_native_zarr_import_plan", lambda _path: incompatible_plan
    )
    incompatible = core_functions._check_import_compatibility(
        "session",
        "omeroserver",
        4064,
        zarr_dir,
        None,
        "image.ome.zarr",
    )
    assert incompatible["status"] == "incompatible"
    assert (
        incompatible["import_backend"] == core_functions._ZARR_IMPORT_BACKEND_BIOFORMATS
    )


def test_import_file_covers_fast_path_timeout_and_progress_tracking_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "image.ome.tif"
    source.write_text("payload", encoding="utf-8")
    monkeypatch.setattr(
        core_functions,
        "_build_omero_cli_command",
        lambda args, session_key, host, port: ["omero", *args],
    )
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 5)
    monkeypatch.setattr(
        core_functions,
        "_run_omero_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["omero", "import"], 5)
        ),
    )

    timed_out = core_functions._import_file(
        None,
        "session",
        "omeroserver",
        4064,
        source,
        dataset_id=7,
        import_name="renamed-image",
    )
    assert timed_out == (False, "", "Import timed out after 5 seconds")

    class _Pipe:
        def __init__(self, lines):
            self._lines = list(lines)
            self.closed = False

        def __iter__(self):
            for line in self._lines:
                yield line

        def close(self):
            self.closed = True
            raise RuntimeError("close exploded")

    class _Proc:
        def __init__(self):
            self.pid = 999
            self.returncode = 3
            self.stdout = _Pipe(["one\n"])
            self.stderr = _Pipe(["warn\n"])
            self._poll_calls = 0
            self.killed = False

        def poll(self):
            self._poll_calls += 1
            if self._poll_calls == 1:
                return None
            self.returncode = 3
            return 3

        def kill(self):
            self.killed = True

    proc = _Proc()
    monkeypatch.setattr(
        core_functions, "_build_cli_env", lambda: {"HOME": str(tmp_path)}
    )
    monkeypatch.setattr(core_functions, "_get_path_total_size", lambda _path: 9)
    monkeypatch.setattr(
        core_functions.subprocess, "Popen", lambda *args, **kwargs: proc
    )
    rchar_values = iter((5, 12))

    def _fake_read_proc_rchar(pid):
        assert pid == 999
        try:
            return next(rchar_values)
        except StopIteration:
            return 12

    monkeypatch.setattr(core_functions, "_read_proc_rchar", _fake_read_proc_rchar)
    saved_jobs = []
    monkeypatch.setattr(
        core_functions,
        "_save_job",
        lambda job_dict: (
            saved_jobs.append(dict(job_dict))
            or (_ for _ in ()).throw(RuntimeError("save exploded"))
        ),
    )
    time_values = iter((0.0, 0.0, 10.0, 10.0))

    def _fake_time():
        try:
            return next(time_values)
        except StopIteration:
            return 10.0

    monkeypatch.setattr(core_functions.time, "time", _fake_time)
    monkeypatch.setattr(core_functions.time, "sleep", lambda _seconds: None)

    success, stdout, stderr = core_functions._import_file(
        None,
        "session",
        "omeroserver",
        4064,
        source,
        progress_job={"imported_bytes": 2},
    )

    assert success is False
    assert stdout == "one\n"
    assert stderr == "warn\n"
    assert proc.killed is False
    assert saved_jobs[0]["import_progress_bytes"] == 9


def test_start_compatibility_check_thread_marks_job_and_skips_when_already_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inactive_job = {
        "job_id": "a" * 32,
        "compatibility_status": "incompatible",
        "compatibility_thread_active": False,
    }
    state = _stateful_job_updates(monkeypatch, inactive_job)
    refreshed = []
    started = []
    monkeypatch.setattr(
        core_functions,
        "_refresh_job_status",
        lambda job_dict: refreshed.append(job_dict.copy()),
    )
    monkeypatch.setattr(core_functions.time, "time", lambda: 1234.5)

    class _Thread:
        def __init__(self, target, args=(), daemon=None):
            self._target = target
            self._args = args
            self.daemon = daemon

        def start(self):
            started.append(self._args)

    monkeypatch.setattr(core_functions.threading, "Thread", _Thread)

    core_functions._start_compatibility_check_thread(inactive_job["job_id"])

    assert state["job"]["compatibility_thread_active"] is True
    assert state["job"]["compatibility_status"] == "incompatible"
    assert state["job"]["updated"] == 1234.5
    assert refreshed
    assert started == [("a" * 32,)]

    active_job = {
        "job_id": "b" * 32,
        "compatibility_status": "checking",
        "compatibility_thread_active": True,
    }
    _stateful_job_updates(monkeypatch, active_job)
    started.clear()
    core_functions._start_compatibility_check_thread(active_job["job_id"])
    assert started == []

    monkeypatch.setattr(core_functions, "_update_job", lambda *_args: None)
    core_functions._start_compatibility_check_thread("c" * 32)


def test_prepare_server_readable_zarr_source_cleans_failed_transfer_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.ome.zarr"
    source.mkdir()
    (source / "0").mkdir()
    transfer_root = tmp_path / "transfer"
    transfer_root.mkdir()
    monkeypatch.setattr(
        core_functions, "_shared_zarr_transfer_root", lambda: transfer_root
    )
    monkeypatch.setattr(
        core_functions,
        "_prepare_native_zarr_copy",
        lambda _path: "normalize exploded",
    )

    shared_source, transfer_parent, error = (
        core_functions._prepare_server_readable_zarr_source(source)
    )

    assert shared_source is None
    assert transfer_parent is None
    assert "normalize exploded" in (error or "")
    assert list(transfer_root.iterdir()) == []
