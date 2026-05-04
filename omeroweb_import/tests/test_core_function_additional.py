from __future__ import annotations

import logging
import types
from pathlib import Path

import pytest

from omero_plugin_common import process_utils
from omeroweb_import.views import core_functions


class _State:
    """Represent state."""

    def __init__(self, image_id, *, persist_on_refresh=True):
        """Initialize the instance.

        Inputs: `image_id`, `persist_on_refresh`. Output: None.
        """
        self.image_id = image_id
        self.persist_on_refresh = persist_on_refresh
        self.values = {}


class _PixelsWrapper:
    """Represent pixels wrapper."""

    def __init__(
        self,
        state: _State,
        *,
        with_obj: bool = True,
        missing_axis: str | None = None,
        reload_error: str | None = None,
    ):
        """Initialize the instance.

        Inputs: `state`, `with_obj`, `missing_axis`, `reload_error`. Output: None.
        """
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
        """Return value.

        Inputs: `axis_name`. Output: computed value. Raises on invalid or unavailable
        state.

        state.
        """
        if self._reload_error:
            raise RuntimeError(self._reload_error)
        if not self._state.persist_on_refresh:
            return "mismatch"
        return self._state.values.get(axis_name)

    def getPhysicalSizeX(self):
        """Return Physical Size X.

        Inputs: none. Output: `self._value` result.
        """
        return self._value("x")

    def getPhysicalSizeY(self):
        """Return Physical Size Y.

        Inputs: none. Output: `self._value` result.
        """
        return self._value("y")

    def getPhysicalSizeZ(self):
        """Return Physical Size Z.

        Inputs: none. Output: `self._value` result.
        """
        return self._value("z")


class _ImageWrapper:
    """Represent image wrapper."""

    def __init__(
        self,
        state: _State,
        *,
        with_obj: bool = True,
        missing_axis: str | None = None,
        pixels_error: str | None = None,
        reload_error: str | None = None,
    ):
        """Initialize the instance.

        Inputs: `state`, `with_obj`, `missing_axis`, `pixels_error`, `reload_error`.
        Output: None.
        """
        self._state = state
        self._with_obj = with_obj
        self._missing_axis = missing_axis
        self._pixels_error = pixels_error
        self._reload_error = reload_error

    def getPrimaryPixels(self):
        """Return Primary Pixels.

        Inputs: none. Output: `_PixelsWrapper` result. Raises on invalid or unavailable
        state.
        """
        if self._pixels_error:
            raise RuntimeError(self._pixels_error)
        return _PixelsWrapper(
            self._state,
            with_obj=self._with_obj,
            missing_axis=self._missing_axis,
            reload_error=self._reload_error,
        )


def _stateful_job_updates(monkeypatch, job):
    """Stateful job updates.

    Inputs: `monkeypatch`, `job`. Output: computed value.
    """
    state = {"job": job}

    def _update_job(job_id, mutator):
        """Update job.

        Inputs: `job_id`, `mutator`. Output: `state['job']`.
        """
        assert job_id == job["job_id"]
        state["job"] = mutator(state["job"])
        return state["job"]

    monkeypatch.setattr(core_functions, "_update_job", _update_job)
    return state


def test_finalize_imported_zarr_image_metadata_covers_prerequisites_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify finalize imported Zarr image metadata covers prerequisites and errors.

    Inputs: `tmp_path`, `monkeypatch`. Output: None. Raises on invalid or unavailable
    state.

    state.
    """
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
        """Represent conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
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

        @staticmethod
        def getUpdateService():
            """Return Update Service.

            Inputs: none. Output: computed value. Raises on invalid or unavailable
            state.
            """

            def _save(obj):
                """Save.

                Inputs: `obj`. Output: `obj`. Raises on invalid or unavailable state.
                """
                if getattr(obj, "image_id", None) == 10:
                    raise RuntimeError("save exploded")
                return obj

            return types.SimpleNamespace(saveAndReturnObject=_save)

        def getObject(self, object_type, image_id):
            """Return Object.

            Inputs: `object_type`, `image_id`. Output: `_ImageWrapper` result or None.
            Raises on invalid or unavailable state.
            """
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
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            self.closed = True
            raise RuntimeError("conn close exploded")

    conn = _Conn()

    class _AdminConn:
        """Represent admin conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.closed = False

        @staticmethod
        def suConn(username):
            """Su conn.

            Inputs: `username`. Output: `conn`.
            """
            assert username == "alice"
            return conn

        def close(self):
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
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
    """Verify check import compatibility covers timeout cli errors and native routes.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
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
        lambda _path: (_ for _ in ()).throw(
            process_utils.TimeoutExpired(["omero"], 321)
        ),
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify import file covers fast path timeout and progress tracking edges.

    Inputs: `tmp_path`, `monkeypatch`, `caplog`. Output: None.
    """
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
            process_utils.TimeoutExpired(["omero", "import"], 5)
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

    monkeypatch.setattr(
        core_functions, "_build_cli_env", lambda: {"HOME": str(tmp_path)}
    )
    monkeypatch.setattr(core_functions, "_get_path_total_size", lambda _path: 9)
    rchar_values = iter((5, 12))

    def _fake_read_proc_rchar(pid):
        """Fake read proc rchar.

        Inputs: `pid`. Output: computed value.
        """
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
        """Fake time.

        Inputs: none. Output: computed value.
        """
        try:
            return next(time_values)
        except StopIteration:
            return 10.0

    monkeypatch.setattr(core_functions.time, "time", _fake_time)
    monkeypatch.setattr(
        core_functions,
        "_run_omero_cli_streaming",
        lambda cmd, *, env, timeout, on_tick=None: (
            (on_tick(999, 0.0) if on_tick is not None else None)
            or (on_tick(999, 10.0) if on_tick is not None else None)
            or process_utils.CompletedProcess(
                args=tuple(cmd),
                returncode=3,
                stdout="secret stdout line\n",
                stderr="secret stderr line\n",
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger=core_functions.logger.name):
        success, stdout, stderr = core_functions._import_file(
            None,
            "session",
            "omeroserver",
            4064,
            source,
            progress_job={"imported_bytes": 2},
        )

    assert success is False
    assert stdout == "secret stdout line\n"
    assert stderr == "secret stderr line\n"
    assert saved_jobs[0]["import_progress_bytes"] == 9
    assert "Import CLI failed for image.ome.tif" in caplog.text
    assert "stdout_lines=1 stderr_lines=1" in caplog.text
    assert "secret stdout line" not in caplog.text
    assert "secret stderr line" not in caplog.text


def test_import_file_progress_loop_covers_timeout_and_unexpected_cleanup_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify import file progress loop covers timeout and unexpected cleanup paths.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    source = tmp_path / "image.ome.tif"
    source.write_text("payload", encoding="utf-8")
    monkeypatch.setattr(
        core_functions,
        "_build_omero_cli_command",
        lambda args, session_key, host, port: ["omero", *args],
    )
    monkeypatch.setattr(
        core_functions, "_build_cli_env", lambda: {"HOME": str(tmp_path)}
    )
    monkeypatch.setattr(core_functions, "_get_path_total_size", lambda _path: 10)
    monkeypatch.setattr(core_functions, "_read_proc_rchar", lambda _pid: 0)

    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 1)
    monkeypatch.setattr(
        core_functions,
        "_run_omero_cli_streaming",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            process_utils.TimeoutExpired(["omero", "import"], 1)
        ),
    )

    timed_out = core_functions._import_file(
        None,
        "session",
        "omeroserver",
        4064,
        source,
        progress_job={"imported_bytes": 0},
    )

    assert timed_out == (False, "", "Import timed out after 1 seconds")
    monkeypatch.setattr(core_functions, "_get_path_total_size", lambda _path: 0)
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 30)
    monkeypatch.setattr(
        core_functions,
        "_run_omero_cli_streaming",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stream exploded")),
    )

    with pytest.raises(RuntimeError, match="stream exploded"):
        core_functions._import_file(
            None,
            "session",
            "omeroserver",
            4064,
            source,
            progress_job={"imported_bytes": 0},
        )


def test_start_compatibility_check_thread_marks_job_and_skips_when_already_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify start compatibility check thread marks job and skips when already active.

    Inputs: `monkeypatch`. Output: None.
    """
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
        """Represent thread."""

        def __init__(self, target, args=(), daemon=None):
            """Initialize the instance.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self._target = target
            self._args = args
            self.daemon = daemon

        def start(self):
            """Start the operation.

            Inputs: none. Output: None.
            """
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
    """Verify prepare server readable Zarr source cleans failed transfer parent.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
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
