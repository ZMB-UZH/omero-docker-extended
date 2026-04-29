from __future__ import annotations

from iter_test_helpers import next_or_fail

import logging
import subprocess
import types
from contextlib import nullcontext
from pathlib import Path

from omeroweb_import.views import core_functions


class _DummyLock:
    """Test double for dummy lock."""

    def __init__(self, acquired=True):
        self._acquired = acquired
        self.timeout = None
        self.released = False

    def acquire(self, timeout=None):
        """Handle acquire."""
        self.timeout = timeout
        return self._acquired

    def release(self):
        """Handle release."""
        self.released = True


def _job_state(monkeypatch, job):
    """Handle job state."""
    state = {"job": job}

    def load_job(job_id):
        """Return load job."""
        assert job_id == job["job_id"]
        return state["job"]

    def save_job(job_dict):
        """Store save job."""
        state["job"] = job_dict
        return True

    monkeypatch.setattr(core_functions, "_load_job", load_job)
    monkeypatch.setattr(core_functions, "_save_job", save_job)
    return state


def _job_state_with_updates(monkeypatch, job):
    """Handle job state with updates."""
    state = _job_state(monkeypatch, job)

    def update_job(job_id, mutator):
        """Handle update job."""
        assert job_id == job["job_id"]
        state["job"] = mutator(state["job"])
        return state["job"]

    monkeypatch.setattr(core_functions, "_update_job", update_job)
    return state


def test_import_zarr_via_cli_handles_stage_exception_without_unbound_local(
    tmp_path: Path, monkeypatch
):
    """Verify test import Zarr via cli handles stage except behavior."""
    source_path = tmp_path / "image.zarr"
    source_path.mkdir()
    shared_source = tmp_path / "shared.zarr"
    shared_source.mkdir()
    transfer_parent = tmp_path / "transfer"
    transfer_parent.mkdir()
    cleanup_attempts = []

    monkeypatch.setattr(
        core_functions,
        "_prepare_server_readable_zarr_source",
        lambda path: (shared_source, transfer_parent, None),
    )

    def failing_stage(*args, **kwargs):
        """Handle failing stage."""
        raise RuntimeError("stage boom")

    def failing_cleanup(path):
        """Handle failing cleanup."""
        cleanup_attempts.append(path)
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(core_functions, "_run_zarr_managed_repo_script", failing_stage)
    monkeypatch.setattr(
        core_functions,
        "_cleanup_shared_zarr_transfer",
        failing_cleanup,
    )

    result = core_functions._import_zarr_via_cli(
        file_path=source_path,
        session_key="session",
        host="omeroserver",
        port=4064,
        dataset_id=11,
        import_name="image.zarr",
        rel_path="image.zarr",
        entry={"index": 0},
        cleanup_staged_paths=["_staged/image.zarr"],
        covered_indexes=[0],
        covered_relative_paths=["image.zarr"],
        username="alice",
        group_name="users_private",
        native_plan=core_functions._NativeZarrImportPlan(kind="ome-zarr"),
    )

    assert cleanup_attempts == [transfer_parent]
    assert result["status"] == "error"
    assert "stage boom" in result["entry_error"]


def test_import_zarr_via_cli_rejects_missing_context_invalid_plans_and_prepare_failures(
    tmp_path: Path,
    monkeypatch,
):
    """Verify test import Zarr via cli rejects missing cont behavior."""
    source_path = tmp_path / "image.zarr"
    source_path.mkdir()
    common_kwargs = dict(
        file_path=source_path,
        session_key="session",
        host="omeroserver",
        port=4064,
        dataset_id=11,
        import_name="image.zarr",
        rel_path="image.zarr",
        entry={"index": 0},
        cleanup_staged_paths=["_staged/image.zarr"],
        covered_indexes=[0],
        covered_relative_paths=["image.zarr"],
    )

    missing_context = core_functions._import_zarr_via_cli(
        username="",
        group_name="",
        native_plan=core_functions._NativeZarrImportPlan(kind="ome-zarr"),
        **common_kwargs,
    )
    assert missing_context["status"] == "error"
    assert "Missing username or group name" in missing_context["entry_error"]

    unsupported = core_functions._import_zarr_via_cli(
        username="alice",
        group_name="users_private",
        native_plan=core_functions._NativeZarrImportPlan(),
        **common_kwargs,
    )
    assert unsupported["status"] == "error"
    assert "installed omero-cli-zarr runtime" in unsupported["entry_error"]

    invalid_plan = core_functions._import_zarr_via_cli(
        username="alice",
        group_name="users_private",
        native_plan=core_functions._NativeZarrImportPlan(
            kind="ome-zarr",
            validation_error="invalid native zarr",
        ),
        **common_kwargs,
    )
    assert invalid_plan["status"] == "error"
    assert invalid_plan["entry_error"] == "invalid native zarr"

    monkeypatch.setattr(
        core_functions,
        "_prepare_server_readable_zarr_source",
        lambda path: (None, None, "prep failed"),
    )
    prepare_failed = core_functions._import_zarr_via_cli(
        username="alice",
        group_name="users_private",
        native_plan=core_functions._NativeZarrImportPlan(kind="ome-zarr"),
        **common_kwargs,
    )
    assert prepare_failed["status"] == "error"
    assert prepare_failed["entry_error"] == "prep failed"


def test_import_zarr_via_cli_handles_no_objects_metadata_and_render_failures(
    tmp_path: Path, monkeypatch, caplog
):
    """Verify test import Zarr via cli handles no objects m behavior."""
    source_path = tmp_path / "image.zarr"
    source_path.mkdir()
    shared_source = tmp_path / "shared.zarr"
    shared_source.mkdir()
    transfer_parent = tmp_path / "transfer"
    transfer_parent.mkdir()
    managed_zarr = tmp_path / "managed" / "image.zarr"

    cleanup_calls = []
    imported_image_cleanup_calls = []
    verify_calls = []

    monkeypatch.setattr(
        core_functions,
        "_prepare_server_readable_zarr_source",
        lambda path: (shared_source, transfer_parent, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_cleanup_shared_zarr_transfer",
        lambda path: cleanup_calls.append(("shared", path)),
    )
    monkeypatch.setattr(
        core_functions,
        "_run_zarr_managed_repo_script",
        lambda action, host, port, **kwargs: (
            True,
            {"Managed_Path": str(managed_zarr)},
            "",
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_build_omero_cli_command",
        lambda *args, **kwargs: ["omero", "zarr", "import"],
    )
    monkeypatch.setattr(core_functions, "_build_cli_env", lambda: {"TEST": "1"})
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 30)
    monkeypatch.setattr(
        core_functions,
        "_cleanup_managed_zarr_path",
        lambda host, port, **kwargs: cleanup_calls.append(
            ("managed", kwargs.get("managed_path"))
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_cleanup_imported_images",
        lambda host, port, image_ids: imported_image_cleanup_calls.append(
            list(image_ids)
        ),
    )

    def run_case(
        *,
        returncode,
        stdout,
        stderr,
        api_ids,
        finalize_result,
        render_result,
        run_error=None,
    ):
        """Run run case."""
        cleanup_calls.clear()
        imported_image_cleanup_calls.clear()
        verify_calls.clear()

        if run_error is None:
            monkeypatch.setattr(
                core_functions.subprocess,
                "run",
                lambda *args, **kwargs: subprocess.CompletedProcess(
                    args=["omero", "zarr", "import"],
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                ),
            )
        else:
            monkeypatch.setattr(
                core_functions.subprocess,
                "run",
                lambda *args, **kwargs: (_ for _ in ()).throw(run_error),
            )
        monkeypatch.setattr(
            core_functions,
            "_extract_imported_object_ids",
            lambda output: ["101"] if "Image:101" in output else [],
        )

        def verify_api(*args, **kwargs):
            """Handle verify API."""
            verify_calls.append(kwargs)
            return list(api_ids)

        monkeypatch.setattr(
            core_functions,
            "_verify_zarr_import_via_api",
            verify_api,
        )
        monkeypatch.setattr(
            core_functions,
            "_finalize_imported_zarr_image_metadata",
            lambda *args, **kwargs: finalize_result,
        )
        monkeypatch.setattr(
            core_functions,
            "_verify_imported_zarr_images_renderable",
            lambda *args, **kwargs: render_result,
        )

        return core_functions._import_zarr_via_cli(
            file_path=source_path,
            session_key="session",
            host="omeroserver",
            port=4064,
            dataset_id=11,
            import_name="image.zarr",
            rel_path="image.zarr",
            entry={"index": 0},
            cleanup_staged_paths=["_staged/image.zarr"],
            covered_indexes=[0],
            covered_relative_paths=["image.zarr"],
            username="alice",
            group_id=7,
            group_name="users_private",
            native_plan=core_functions._NativeZarrImportPlan(
                kind="ome-zarr",
                verify_lsid_prefix=True,
            ),
        )

    with caplog.at_level(logging.INFO, logger=core_functions.logger.name):
        no_objects = run_case(
            returncode=0,
            stdout="secret zarr stdout",
            stderr="secret zarr stderr",
            api_ids=[],
            finalize_result=(True, []),
            render_result=(True, []),
        )
    assert no_objects["status"] == "error"
    assert (
        no_objects["entry_error"] == core_functions.errors.import_no_objects_created()
    )
    assert cleanup_calls[-1] == ("managed", managed_zarr)
    assert imported_image_cleanup_calls == []
    assert "stdout_lines=1 stderr_lines=1" in caplog.text
    assert "secret zarr stdout" not in caplog.text
    assert "secret zarr stderr" not in caplog.text

    metadata_failure = run_case(
        returncode=0,
        stdout="Image:101",
        stderr="",
        api_ids=[],
        finalize_result=(False, ["size mismatch"]),
        render_result=(True, []),
    )
    assert metadata_failure["status"] == "error"
    assert "metadata finalization" in metadata_failure["entry_error"]
    assert imported_image_cleanup_calls == [["101"]]
    assert cleanup_calls[-1] == ("managed", managed_zarr)

    render_failure = run_case(
        returncode=0,
        stdout="Image:101",
        stderr="",
        api_ids=[],
        finalize_result=(True, []),
        render_result=(False, ["thumbnail failed"]),
    )
    assert render_failure["status"] == "error"
    assert "render verification" in render_failure["entry_error"]
    assert imported_image_cleanup_calls == [["101"]]
    assert cleanup_calls[-1] == ("managed", managed_zarr)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=core_functions.logger.name):
        salvaged_success = run_case(
            returncode=1,
            stdout="",
            stderr="secret salvage stderr",
            api_ids=["201"],
            finalize_result=(True, []),
            render_result=(True, []),
        )
    assert salvaged_success["status"] == "imported"
    assert salvaged_success["file_path"] == managed_zarr
    assert imported_image_cleanup_calls == []
    assert verify_calls[-1]["expected_lsid"] is None
    assert verify_calls[-1]["expected_lsid_prefix"] == str(managed_zarr)
    assert "stdout_lines=0 stderr_lines=1" in caplog.text
    assert "secret salvage stderr" not in caplog.text

    timeout_failure = run_case(
        returncode=0,
        stdout="",
        stderr="",
        api_ids=[],
        finalize_result=(True, []),
        render_result=(True, []),
        run_error=core_functions.subprocess.TimeoutExpired(
            ["omero", "zarr", "import"], 30
        ),
    )
    assert timeout_failure["status"] == "error"


def test_import_zarr_via_cli_uses_api_verified_image_ids_for_name_normalization(
    tmp_path: Path,
    monkeypatch,
):
    """Verify test import Zarr via cli uses API verified im behavior."""
    source_path = tmp_path / "image.zarr"
    source_path.mkdir()
    shared_source = tmp_path / "shared.zarr"
    shared_source.mkdir()
    transfer_parent = tmp_path / "transfer"
    transfer_parent.mkdir()
    managed_zarr = tmp_path / "managed" / "image.zarr"
    captured = {}

    monkeypatch.setattr(
        core_functions,
        "_prepare_server_readable_zarr_source",
        lambda path: (shared_source, transfer_parent, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_cleanup_shared_zarr_transfer",
        lambda path: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_run_zarr_managed_repo_script",
        lambda action, host, port, **kwargs: (
            True,
            {"Managed_Path": str(managed_zarr)},
            "",
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_build_omero_cli_command",
        lambda *args, **kwargs: ["omero", "zarr", "import"],
    )
    monkeypatch.setattr(core_functions, "_build_cli_env", lambda: {"TEST": "1"})
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 30)
    monkeypatch.setattr(
        core_functions.process_utils,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["omero", "zarr", "import"],
            returncode=0,
            stdout="Fileset:10\n",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_verify_zarr_import_via_api",
        lambda *args, **kwargs: ["201", "202"],
    )
    monkeypatch.setattr(
        core_functions,
        "_finalize_imported_zarr_image_metadata",
        lambda *args, **kwargs: (True, []),
    )
    monkeypatch.setattr(
        core_functions,
        "_verify_imported_zarr_images_renderable",
        lambda *args, **kwargs: (True, []),
    )
    monkeypatch.setattr(
        core_functions,
        "_apply_import_name_normalization_context",
        lambda entry, context, imported_image_ids, *args, **kwargs: captured.setdefault(
            "image_ids", list(imported_image_ids)
        ),
    )

    result = core_functions._import_zarr_via_cli(
        file_path=source_path,
        session_key="session",
        host="omeroserver",
        port=4064,
        dataset_id=11,
        import_name="image.zarr",
        rel_path="image.zarr",
        entry={"index": 0},
        cleanup_staged_paths=["_staged/image.zarr"],
        covered_indexes=[0],
        covered_relative_paths=["image.zarr"],
        username="alice",
        group_id=7,
        group_name="users_private",
        normalization_context=core_functions._ImportNameNormalizationContext(
            cli_import_name="source.lif",
            expected_image_names=("source.lif [Series A]", "source.lif [Series B]"),
        ),
        native_plan=core_functions._NativeZarrImportPlan(
            kind="ome-zarr",
            verify_lsid_prefix=True,
        ),
    )

    assert result["status"] == "imported"
    assert captured["image_ids"] == [201, 202]


def test_import_zarr_via_cli_handles_unexpected_cli_runner_exceptions(
    tmp_path: Path,
    monkeypatch,
):
    """Verify test import Zarr via cli handles unexpected c behavior."""
    source_path = tmp_path / "image.zarr"
    source_path.mkdir()
    shared_source = tmp_path / "shared.zarr"
    shared_source.mkdir()
    transfer_parent = tmp_path / "transfer"
    transfer_parent.mkdir()
    managed_zarr = tmp_path / "managed" / "image.zarr"
    cleanup_calls = []

    monkeypatch.setattr(
        core_functions,
        "_prepare_server_readable_zarr_source",
        lambda path: (shared_source, transfer_parent, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_cleanup_shared_zarr_transfer",
        lambda path: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_run_zarr_managed_repo_script",
        lambda action, host, port, **kwargs: (
            True,
            {"Managed_Path": str(managed_zarr)},
            "",
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_cleanup_managed_zarr_path",
        lambda host, port, **kwargs: cleanup_calls.append(kwargs.get("managed_path")),
    )
    monkeypatch.setattr(
        core_functions.process_utils,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cli boom")),
    )
    monkeypatch.setattr(
        core_functions,
        "_verify_zarr_import_via_api",
        lambda *args, **kwargs: [],
    )

    result = core_functions._import_zarr_via_cli(
        file_path=source_path,
        session_key="session",
        host="omeroserver",
        port=4064,
        dataset_id=11,
        import_name="image.zarr",
        rel_path="image.zarr",
        entry={"index": 0},
        cleanup_staged_paths=["_staged/image.zarr"],
        covered_indexes=[0],
        covered_relative_paths=["image.zarr"],
        username="alice",
        group_id=7,
        group_name="users_private",
        native_plan=core_functions._NativeZarrImportPlan(kind="ome-zarr"),
    )

    assert result["status"] == "error"
    assert result["entry_error"] == core_functions.errors.import_failed()
    assert cleanup_calls == [managed_zarr]


def test_finalize_imported_zarr_image_metadata_records_reload_failures(
    tmp_path: Path, monkeypatch
):
    """Verify test finalize imported Zarr image metadata re behavior."""
    managed_zarr = tmp_path / "managed"

    class _PixelsWrapper:
        """Represent pixels wrapper."""

        def __init__(self, storage):
            self._storage = storage
            self._obj = types.SimpleNamespace(
                setPhysicalSizeX=lambda value: self._storage.__setitem__("x", value)
            )

        @staticmethod
        def getPhysicalSizeX():
            """Return get physical size x."""
            return None

    class _Image:
        """Represent image."""

        def __init__(self, storage):
            self._storage = storage

        def getPrimaryPixels(self):
            """Return get primary pixels."""
            return _PixelsWrapper(self._storage)

    storages = {1: {}, 2: {}}
    update_saves = []

    class _Conn:
        """Represent conn."""

        def __init__(self):
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=lambda value: setattr(self, "group", value)
            )
            self.closed = False
            self._calls = {}

        @staticmethod
        def getUpdateService():
            """Return get update service."""
            return types.SimpleNamespace(
                saveAndReturnObject=lambda obj: update_saves.append(obj) or obj
            )

        def getObject(self, object_type, image_id):
            """Return get object."""
            assert object_type == "Image"
            self._calls[image_id] = self._calls.get(image_id, 0) + 1
            call_number = self._calls[image_id]
            if image_id == 1:
                if call_number == 1:
                    return _Image(storages[1])
                raise RuntimeError("reload failed")
            if image_id == 2:
                if call_number == 1:
                    return _Image(storages[2])
                return types.SimpleNamespace(
                    getPrimaryPixels=lambda: (_ for _ in ()).throw(
                        RuntimeError("pixels missing")
                    )
                )
            raise AssertionError(f"Unexpected image id {image_id}")

        def close(self):
            """Handle close."""
            self.closed = True

    conn = _Conn()

    class _AdminConn:
        """Represent admin conn."""

        def __init__(self):
            self.closed = False

        @staticmethod
        def suConn(username):
            """Handle su conn."""
            assert username == "alice"
            return conn

        def close(self):
            """Handle close."""
            self.closed = True

    admin_conn = _AdminConn()

    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda host, port: admin_conn,
    )
    monkeypatch.setattr(
        core_functions,
        "_query_image_external_info",
        lambda current_conn, image_id: (
            str(managed_zarr / f"image-{image_id}.zarr"),
            None,
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_runtime_native_zarr_physical_sizes",
        lambda managed_root, image_relative_path: ({"x": image_relative_path}, None),
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
        ["1", "2", "1"],
        managed_zarr=managed_zarr,
        group_id=7,
    )

    assert ok is False
    assert any("reload failed" in message for message in errors)
    assert any("pixels missing" in message for message in errors)
    assert conn.group == "7"
    assert len(update_saves) == 2
    assert conn.closed is True
    assert admin_conn.closed is True


def test_import_job_entry_covers_staged_background_and_native_routing_failures(
    tmp_path: Path, monkeypatch
):
    """Verify test import job entry covers staged backgroun behavior."""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    staged_root = upload_root / "_staged"
    staged_root.mkdir()
    sample_file = staged_root / "sample.ome.tif"
    sample_file.write_text("image", encoding="utf-8")
    sample_zarr = staged_root / "sample.zarr"
    sample_zarr.mkdir()

    assert core_functions._import_job_entry(
        {},
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
    ) == {"skip": True}

    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (None, "staged path rejected"),
    )
    staged_error = core_functions._import_job_entry(
        {"relative_path": "sample.ome.tif", "staged_path": "_staged/sample.ome.tif"},
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
    )
    assert staged_error["status"] == "error"
    assert staged_error["entry_error"] == "staged path rejected"

    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (staged_root / "missing.ome.tif", None),
    )
    missing_file = core_functions._import_job_entry(
        {"relative_path": "missing.ome.tif", "staged_path": "_staged/missing.ome.tif"},
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
    )
    assert missing_file["status"] == "error"
    assert missing_file["entry_error"] == core_functions.errors.missing_staged_file(
        "missing.ome.tif"
    )

    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (sample_file, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_background_import_session",
        lambda *args, **kwargs: nullcontext(None),
    )
    missing_session = core_functions._import_job_entry(
        {"relative_path": "sample.ome.tif", "staged_path": "_staged/sample.ome.tif"},
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
        username="alice",
    )
    assert missing_session["status"] == "error"
    assert (
        missing_session["entry_error"]
        == core_functions.errors.missing_omero_connection_details()
    )

    monkeypatch.setattr(
        core_functions,
        "_background_import_session",
        lambda *args, **kwargs: nullcontext("bg-session"),
    )
    monkeypatch.setattr(core_functions, "_native_zarr_import_enabled", lambda: False)
    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (sample_zarr, None),
    )
    incompatible_zarr = core_functions._import_job_entry(
        {
            "relative_path": "sample.zarr",
            "staged_path": "_staged/sample.zarr",
            "compatibility": "incompatible",
            "import_backend": core_functions._ZARR_IMPORT_BACKEND_NATIVE,
        },
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
        username="alice",
        group_name="users_private",
    )
    assert incompatible_zarr["status"] == "error"
    assert "Bio-Formats did not recognize" in incompatible_zarr["entry_error"]

    monkeypatch.setattr(core_functions, "_native_zarr_import_enabled", lambda: True)
    monkeypatch.setattr(
        core_functions,
        "_deserialize_native_zarr_plan",
        lambda payload: core_functions._NativeZarrImportPlan(),
    )
    monkeypatch.setattr(
        core_functions,
        "_native_zarr_import_plan",
        lambda path: core_functions._NativeZarrImportPlan(),
    )
    missing_plan = core_functions._import_job_entry(
        {
            "relative_path": "sample.zarr",
            "staged_path": "_staged/sample.zarr",
            "compatibility": "compatible",
            "import_backend": core_functions._ZARR_IMPORT_BACKEND_NATIVE,
        },
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
        username="alice",
        group_name="users_private",
    )
    assert missing_plan["status"] == "error"
    assert "routing metadata is missing" in missing_plan["entry_error"]

    monkeypatch.setattr(
        core_functions,
        "_deserialize_native_zarr_plan",
        lambda payload: core_functions._NativeZarrImportPlan(
            kind="ome-zarr",
            recognized_zarr=True,
            validation_error="invalid native zarr",
        ),
    )
    validation_error = core_functions._import_job_entry(
        {
            "relative_path": "sample.zarr",
            "staged_path": "_staged/sample.zarr",
            "compatibility": "compatible",
            "import_backend": core_functions._ZARR_IMPORT_BACKEND_NATIVE,
            "native_zarr_plan": {"kind": "ome-zarr"},
        },
        upload_root,
        "session",
        "omeroserver",
        4064,
        {},
        "Default",
        username="alice",
        group_name="users_private",
    )
    assert validation_error["status"] == "error"
    assert validation_error["entry_error"] == "invalid native zarr"


def test_mark_failed_job_for_deferred_cleanup_reports_partial_failures(
    tmp_path: Path,
    monkeypatch,
):
    """Verify test mark failed job for deferred cleanup rep behavior."""
    monkeypatch.setattr(
        core_functions, "_get_failed_import_retention_seconds", lambda: 3600
    )
    monkeypatch.setattr(
        core_functions, "_get_upload_root", lambda: tmp_path / "uploads"
    )
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: tmp_path / "jobs")
    results = iter([True, False])
    monkeypatch.setattr(
        core_functions,
        "safe_mark_path_for_deferred_cleanup",
        lambda *args, **kwargs: next_or_fail(results),
    )

    assert core_functions._mark_failed_job_for_deferred_cleanup("f" * 32) is False


def test_open_service_connection_handles_group_override_and_connect_failures(
    monkeypatch,
):
    """Verify test open service connection handles group ov behavior."""

    class _Conn:
        """Represent conn."""

        def __init__(self, *, connect_result=True, connect_error=None):
            self.connect_result = connect_result
            self.connect_error = connect_error
            self.closed = False
            self.group_calls = []
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=self.group_calls.append
            )

        def connect(self):
            """Handle connect."""
            if self.connect_error is not None:
                raise self.connect_error
            return self.connect_result

        def close(self):
            """Handle close."""
            self.closed = True

        @staticmethod
        def getLastError():
            """Return get last error."""
            return "boom"

    success_conn = _Conn()
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("job-service", "secret", "not-a-number", False),
    )
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda *args, **kwargs: success_conn,
    )

    opened = core_functions._open_service_connection("omeroserver", 4064, group_id=9)

    assert opened is success_conn
    assert success_conn.group_calls == ["9"]

    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("job-service", "", "", True),
    )
    assert core_functions._open_service_connection("omeroserver", 4064) is None

    failed_conn = _Conn(connect_result=False)
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("job-service", "secret", "5", True),
    )
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda *args, **kwargs: failed_conn,
    )
    assert core_functions._open_service_connection("omeroserver", 4064) is None
    assert failed_conn.closed is True

    exploding_conn = _Conn(connect_error=RuntimeError("connect boom"))
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda *args, **kwargs: exploding_conn,
    )
    assert core_functions._open_service_connection("omeroserver", 4064) is None
    assert exploding_conn.closed is True


def test_process_import_job_handles_missing_connection_details_upload_root_and_crashes(
    tmp_path: Path, monkeypatch
):
    """Verify test process import job handles missing conne behavior."""
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 4000.0)

    job_id = "e" * 32
    missing_connection_job = {
        "job_id": job_id,
        "username": "alice",
        "files": [],
        "errors": [],
        "messages": [],
        "status": "ready",
    }
    missing_state = _job_state(monkeypatch, missing_connection_job)
    missing_lock = _DummyLock(acquired=True)
    monkeypatch.setattr(
        core_functions, "_get_import_lock", lambda username: missing_lock
    )

    core_functions._process_import_job(job_id)

    assert missing_state["job"]["status"] == "error"
    assert (
        core_functions.errors.missing_omero_connection_details()
        in missing_state["job"]["errors"]
    )
    assert missing_lock.released is True

    upload_root_job = upload_root / job_id
    if upload_root_job.exists():
        core_functions.safe_remove_job_data(job_id, upload_root)

    missing_upload_job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_name": "users_private",
        "session_key": "session",
        "files": [],
        "errors": [],
        "messages": [],
        "status": "ready",
    }
    missing_upload_state = _job_state(monkeypatch, missing_upload_job)
    missing_upload_lock = _DummyLock(acquired=True)
    monkeypatch.setattr(
        core_functions, "_get_import_lock", lambda username: missing_upload_lock
    )

    core_functions._process_import_job(job_id)

    assert missing_upload_state["job"]["status"] == "error"
    assert (
        core_functions.errors.upload_folder_missing_on_server()
        in (missing_upload_state["job"]["errors"])
    )
    assert missing_upload_lock.released is True

    crash_root = upload_root / job_id
    crash_root.mkdir(parents=True, exist_ok=True)
    crashing_job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_name": "users_private",
        "session_key": "session",
        "files": [
            {
                "relative_path": "sample.ome.tif",
                "status": "uploaded",
                "size": 5,
                "errors": [],
            }
        ],
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"Default": 11},
        "orphan_dataset_name": "Default",
        "imported_bytes": 0,
        "total_bytes": 5,
        "sem_edx_associations": {},
        "sem_edx_settings": {},
        "special_upload": "",
    }
    crashing_state = _job_state(monkeypatch, crashing_job)
    crashing_lock = _DummyLock(acquired=True)
    monkeypatch.setattr(
        core_functions, "_get_import_lock", lambda username: crashing_lock
    )
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job: 1)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("planner exploded")),
    )

    core_functions._process_import_job(job_id)

    assert crashing_state["job"]["status"] == "error"
    assert crashing_state["job"]["errors"]
    assert crashing_lock.released is True


def test_process_import_job_handles_group_resolution_preskips_and_cleanup_warnings(
    tmp_path: Path, monkeypatch
):
    """Verify test process import job handles group resolut behavior."""
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 4500.0)

    job_id = "g" * 32
    (upload_root / job_id).mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_id": 5,
        "group_name": "",
        "session_key": "session",
        "files": [
            {
                "relative_path": "skip.txt",
                "status": "uploaded",
                "size": 1,
                "import_skip": True,
            },
            {
                "relative_path": "bad.zarr",
                "status": "pending",
                "size": 2,
                "compatibility": "incompatible",
            },
            {
                "relative_path": "done.ome.tif",
                "status": "imported",
                "size": 3,
            },
            {
                "relative_path": "sample.ome.tif",
                "status": "uploaded",
                "size": 4,
                "errors": [],
            },
        ],
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"Default": 11},
        "orphan_dataset_name": "Default",
        "imported_bytes": 0,
        "total_bytes": 7,
        "sem_edx_associations": {},
        "sem_edx_settings": {},
        "special_upload": "sem_edx_spectra",
    }
    state = _job_state(monkeypatch, job)
    lock = _DummyLock(acquired=True)
    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: lock)
    monkeypatch.setattr(
        core_functions, "_resolve_job_batch_size", lambda current_job: 1
    )

    class _AdminConn:
        """Represent admin conn."""

        def __init__(self):
            self.closed = False

        def close(self):
            """Handle close."""
            self.closed = True

    admin_conn = _AdminConn()
    monkeypatch.setattr(
        core_functions, "_open_admin_connection", lambda host, port: admin_conn
    )
    monkeypatch.setattr(
        core_functions,
        "_resolve_group_name",
        lambda conn, group_id, group_name=None: "users_private",
    )
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda current_job, current_root: [
            {
                "relative_path": "sample.ome.tif",
                "covered_indexes": [3],
                "cleanup_staged_paths": ["bad-cleanup"],
            }
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda current_job, entries: (True, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_import_job_entry",
        lambda *args, **kwargs: {
            "status": "imported",
            "covered_indexes": [3],
            "cleanup_staged_paths": ["bad-cleanup"],
            "rel_path": "sample.ome.tif",
        },
    )
    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (None, "cleanup path rejected"),
    )
    monkeypatch.setattr(
        core_functions,
        "_build_sem_edx_associations_from_entries",
        lambda entries: {},
    )
    monkeypatch.setattr(
        core_functions,
        "safe_remove_job_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup boom")),
    )
    deferred_jobs = []
    monkeypatch.setattr(
        core_functions,
        "_mark_failed_job_for_deferred_cleanup",
        lambda target_job_id: deferred_jobs.append(target_job_id) or True,
    )

    core_functions._process_import_job(job_id)

    assert lock.released is True
    assert admin_conn.closed is True
    assert state["job"]["group_name"] == "users_private"
    assert state["job"]["status"] == "done"
    assert state["job"]["files"][0]["status"] == "skipped"
    assert state["job"]["files"][1]["status"] == "skipped"
    assert state["job"]["files"][3]["status"] == "imported"
    assert state["job"]["imported_bytes"] == 7
    assert (
        core_functions.messages.skipped_non_importable("skip.txt")
        in state["job"]["messages"]
    )
    assert (
        core_functions.messages.skipped_incompatible("bad.zarr")
        in state["job"]["messages"]
    )
    assert (
        "SEM EDX: no TXT/image associations found; skipping TXT attachments"
        in state["job"]["messages"]
    )
    assert deferred_jobs == []


def test_process_import_job_ignores_sparse_result_payloads_and_worker_exceptions(
    tmp_path: Path, monkeypatch
):
    """Verify test process import job ignores sparse result behavior."""
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()
    (upload_root / ("h" * 32)).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 4600.0)

    job_id = "h" * 32
    job = {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "group_name": "users_private",
        "session_key": "session",
        "files": [
            {
                "relative_path": "sample.ome.tif",
                "status": "uploaded",
                "size": 5,
                "errors": [],
            }
        ],
        "errors": [],
        "messages": [],
        "status": "ready",
        "dataset_map": {"Default": 11},
        "orphan_dataset_name": "Default",
        "imported_bytes": 0,
        "total_bytes": 5,
        "sem_edx_associations": {},
        "sem_edx_settings": {},
        "special_upload": "",
    }
    state = _job_state(monkeypatch, job)
    lock = _DummyLock(acquired=True)
    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: lock)
    monkeypatch.setattr(
        core_functions, "_resolve_job_batch_size", lambda current_job: 4
    )
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda current_job, current_root: [
            {"relative_path": "raises.ome.tif"},
            {"relative_path": "skip.ome.tif"},
            {"relative_path": "empty.ome.tif"},
            {"relative_path": "out-of-range.ome.tif"},
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda current_job, entries: (True, None),
    )

    def _fake_import_job_entry(entry, *args, **kwargs):
        """Handle fake import job entry."""
        rel_path = entry["relative_path"]
        if rel_path == "raises.ome.tif":
            raise RuntimeError("worker exploded")
        if rel_path == "skip.ome.tif":
            return {"skip": True}
        if rel_path == "empty.ome.tif":
            return {"status": "imported", "covered_indexes": []}
        return {"status": "imported", "covered_indexes": [99]}

    monkeypatch.setattr(core_functions, "_import_job_entry", _fake_import_job_entry)
    monkeypatch.setattr(
        core_functions, "safe_remove_job_data", lambda *_args, **_kwargs: None
    )
    deferred_jobs = []
    monkeypatch.setattr(
        core_functions,
        "_mark_failed_job_for_deferred_cleanup",
        lambda target_job_id: deferred_jobs.append(target_job_id) or True,
    )

    core_functions._process_import_job(job_id)

    assert lock.released is True
    assert state["job"]["status"] == "done"
    assert state["job"]["imported_bytes"] == 0
    assert state["job"]["messages"] == []
    assert deferred_jobs == []


def test_has_import_candidates_in_output_matches_directory_groups(tmp_path: Path):
    """Verify test has import candidates in output matches behavior."""
    package_root = tmp_path / "plate.zarr"
    package_root.mkdir()
    member = package_root / ".zattrs"
    member.write_text("{}", encoding="utf-8")
    other_root = tmp_path / "other.zarr"
    other_root.mkdir()
    other_member = other_root / ".zattrs"
    other_member.write_text("{}", encoding="utf-8")

    output = (
        "1 file(s) parsed into 1 group(s) with 1 call(s) to setId\n"
        f"# Group: {package_root} SPW: false\n"
        f"{member}\n"
    )

    assert core_functions._has_import_candidates_in_output(output) is True
    assert (
        core_functions._has_import_candidates_in_output(
            output,
            expected_file_path=package_root,
        )
        is True
    )
    assert (
        core_functions._has_import_candidates_in_output(
            output,
            expected_file_path=other_root,
        )
        is False
    )


def test_reconnect_session_closes_stale_connections_and_rejects_invalid_sessions(
    monkeypatch,
):
    """Verify test reconnect session closes stale connectio behavior."""
    events = []

    class _OldConn:
        """Represent old conn."""

        @staticmethod
        def close():
            """Handle close."""
            events.append("old-close")

    class _NewConn:
        """Represent new conn."""

        def __init__(self):
            self.closed = False
            self.groups = []
            self.SERVICE_OPTS = types.SimpleNamespace(setOmeroGroup=self.groups.append)

        def close(self):
            """Handle close."""
            self.closed = True
            events.append("new-close")

    new_conn = _NewConn()
    monkeypatch.setattr(
        core_functions.omero,
        "client",
        lambda host, port: types.SimpleNamespace(host=host, port=port),
        raising=False,
    )
    monkeypatch.setattr(
        core_functions,
        "_join_detached_session",
        lambda client, session_key: events.append(("join", session_key)),
    )
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda client_obj: new_conn,
    )
    monkeypatch.setattr(core_functions, "_validate_session", lambda conn: False)

    invalid = core_functions._reconnect_session(
        "session",
        "omeroserver",
        4064,
        old_conn=_OldConn(),
    )

    assert invalid is None
    assert events[:2] == ["old-close", ("join", "session")]
    assert new_conn.groups == ["-1"]
    assert new_conn.closed is True

    valid_conn = _NewConn()
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda client_obj: valid_conn,
    )
    monkeypatch.setattr(core_functions, "_validate_session", lambda conn: True)

    reopened = core_functions._reconnect_session("session", "omeroserver", 4064)

    assert reopened is valid_conn
    assert valid_conn.groups == ["-1"]

    monkeypatch.setattr(
        core_functions.omero,
        "client",
        lambda host, port: (_ for _ in ()).throw(RuntimeError("connect failed")),
        raising=False,
    )
    assert core_functions._reconnect_session("session", "omeroserver", 4064) is None

    class _ExplodingOldConn:
        """Represent exploding old conn."""

        @staticmethod
        def close():
            """Handle close."""
            raise RuntimeError("stale close exploded")

    class _ExplodingInvalidConn(_NewConn):
        """Represent exploding invalid conn."""

        def close(self):
            """Handle close."""
            self.closed = True
            raise RuntimeError("invalid close exploded")

    exploding_invalid_conn = _ExplodingInvalidConn()
    monkeypatch.setattr(
        core_functions.omero,
        "client",
        lambda host, port: types.SimpleNamespace(host=host, port=port),
        raising=False,
    )
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda client_obj: exploding_invalid_conn,
    )
    monkeypatch.setattr(core_functions, "_validate_session", lambda conn: False)
    assert (
        core_functions._reconnect_session(
            "session",
            "omeroserver",
            4064,
            old_conn=_ExplodingOldConn(),
        )
        is None
    )
    assert exploding_invalid_conn.groups == ["-1"]
    assert exploding_invalid_conn.closed is True


def test_session_helpers_cover_validation_open_and_detached_join_paths(monkeypatch):
    """Verify test session helpers cover validation open an behavior."""

    def _event_context():
        """Handle event context."""
        return object()

    def _expired_event_context():
        """Handle expired event context."""
        raise RuntimeError("expired")

    assert (
        core_functions._validate_session(
            types.SimpleNamespace(getEventContext=_event_context)
        )
        is True
    )
    assert (
        core_functions._validate_session(
            types.SimpleNamespace(getEventContext=_expired_event_context)
        )
        is False
    )

    detached_calls = []
    joined_session = types.SimpleNamespace(
        detachOnDestroy=lambda: detached_calls.append("detach")
    )
    client = types.SimpleNamespace(joinSession=lambda session_key: joined_session)
    assert core_functions._join_detached_session(client, "session") is joined_session
    assert detached_calls == ["detach"]

    plain_session = object()
    plain_client = types.SimpleNamespace(joinSession=lambda session_key: plain_session)
    assert (
        core_functions._join_detached_session(plain_client, "session") is plain_session
    )

    groups = []
    session_client = types.SimpleNamespace(
        joinSession=lambda session_key: plain_session
    )
    monkeypatch.setattr(
        core_functions.omero,
        "client",
        lambda host, port: session_client,
        raising=False,
    )
    monkeypatch.setattr(
        core_functions,
        "BlitzGateway",
        lambda client_obj: types.SimpleNamespace(
            SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=groups.append)
        ),
    )

    opened = core_functions._open_session_connection("session", "omeroserver", 4064)

    assert groups == ["-1"]
    assert opened.SERVICE_OPTS is not None


def test_prepare_job_import_datasets_handles_missing_upload_roots_and_save_failures(
    tmp_path: Path, monkeypatch
):
    """Verify test prepare job import datasets handles miss behavior."""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 5000.0)

    missing_job = {"job_id": "f" * 32, "status": "ready", "errors": []}
    missing_state = _job_state_with_updates(monkeypatch, missing_job)

    updated_job, error = core_functions._prepare_job_import_datasets(
        missing_job["job_id"], missing_job
    )

    assert updated_job["status"] == "error"
    assert error == core_functions.errors.upload_folder_missing_on_server()
    assert error in missing_state["job"]["errors"]

    existing_root = upload_root / ("f" * 32)
    existing_root.mkdir(parents=True, exist_ok=True)
    dataset_failure_job = {
        "job_id": "f" * 32,
        "status": "ready",
        "errors": [],
    }
    dataset_failure_state = _job_state_with_updates(monkeypatch, dataset_failure_job)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda current_job, current_root: [{"relative_path": "sample.ome.tif"}],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job_dict, entries, conn=None: (False, "dataset failure"),
    )

    updated_job, error = core_functions._prepare_job_import_datasets(
        dataset_failure_job["job_id"], dataset_failure_job
    )

    assert updated_job["status"] == "error"
    assert error == "dataset failure"
    assert "dataset failure" in dataset_failure_state["job"]["errors"]

    save_failure_job = {
        "job_id": "f" * 32,
        "status": "ready",
        "errors": [],
    }
    _job_state_with_updates(monkeypatch, save_failure_job)
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job_dict, entries, conn=None: (True, None),
    )
    monkeypatch.setattr(core_functions, "_save_job", lambda job_dict: False)

    updated_job, error = core_functions._prepare_job_import_datasets(
        save_failure_job["job_id"], save_failure_job
    )

    assert updated_job is None
    assert error == core_functions.errors.unable_update_upload_job_state()


def test_run_compatibility_check_inner_handles_staged_path_errors_and_future_failures(
    tmp_path: Path, monkeypatch
):
    """Verify test run compatibility check inner handles st behavior."""
    upload_root = tmp_path / "uploads"
    job_id = "a" * 32
    job_root = upload_root / job_id
    job_root.mkdir(parents=True)
    valid_file = job_root / "_staged" / "sample.ome.tif"
    valid_file.parent.mkdir(parents=True, exist_ok=True)
    valid_file.write_text("x", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions.time, "time", lambda: 6000.0)

    job = {
        "job_id": job_id,
        "host": "omeroserver",
        "port": 4064,
        "session_key": "session",
        "compatibility_enabled": True,
        "compatibility_thread_active": True,
        "compatibility_status": "checking",
        "files": [
            {"relative_path": "broken.ome.tif", "status": "uploaded"},
            {"relative_path": "sample.ome.tif", "status": "uploaded"},
        ],
    }
    state = _job_state_with_updates(monkeypatch, job)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda current_job, current_root, for_compatibility=False: [
            {
                "relative_path": "broken.ome.tif",
                "covered_indexes": [0],
                "covered_relative_paths": ["broken.ome.tif"],
                "staged_path": "_staged/broken.ome.tif",
            },
            {
                "relative_path": "sample.ome.tif",
                "covered_indexes": [1],
                "covered_relative_paths": ["sample.ome.tif"],
                "staged_path": "_staged/sample.ome.tif",
            },
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_serialize_import_unit_plan",
        lambda unit: {"relative_path": unit["relative_path"]},
    )
    monkeypatch.setattr(
        core_functions, "_resolve_job_batch_size", lambda current_job: 2
    )

    def resolve_path(current_root, staged_path):
        """Return resolve path."""
        if "broken" in staged_path:
            return None, "staged path rejected"
        return valid_file, None

    monkeypatch.setattr(core_functions, "_resolve_staged_target_path", resolve_path)
    monkeypatch.setattr(
        core_functions,
        "_dataset_name_for_import_entry",
        lambda unit, orphan_name: "Default",
    )
    monkeypatch.setattr(
        core_functions,
        "_check_import_compatibility",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("scan boom")),
    )
    monkeypatch.setattr(
        core_functions,
        "_compatibility_pending_entries",
        lambda current_job: [],
    )
    monkeypatch.setattr(
        core_functions,
        "_refresh_job_status",
        lambda current_job: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_should_start_compatibility_check",
        lambda current_job: False,
    )

    core_functions._run_compatibility_check_inner(job_id)

    assert state["job"]["planned_import_units"] == [
        {"relative_path": "broken.ome.tif"},
        {"relative_path": "sample.ome.tif"},
    ]
    assert state["job"]["files"][0]["compatibility"] == "error"
    assert state["job"]["files"][0]["compatibility_details"] == "staged path rejected"
    assert state["job"]["files"][1]["compatibility"] == "error"
    assert state["job"]["files"][1]["compatibility_details"] == "scan boom"
    assert state["job"]["compatibility_status"] == "error"
    assert state["job"]["compatibility_thread_active"] is False


def test_start_import_thread_requires_ready_state_and_persistence(monkeypatch):
    """Verify test start import thread requires ready state behavior."""
    events = []
    thread_targets = []

    class _Thread:
        """Represent thread."""

        def __init__(self, *, target, args, daemon):
            thread_targets.append((target, args, daemon))

        @staticmethod
        def start():
            """Run start."""
            events.append("thread-started")

    job = {"job_id": "a" * 32, "status": "checking"}
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: job)
    monkeypatch.setattr(core_functions, "_save_job", lambda payload: True)
    monkeypatch.setattr(core_functions.threading, "Thread", _Thread)

    core_functions._start_import_thread("a" * 32)
    assert thread_targets == []

    job["status"] = "ready"
    job["import_thread_started"] = True
    core_functions._start_import_thread("a" * 32)
    assert thread_targets == []

    job["import_thread_started"] = False
    monkeypatch.setattr(core_functions, "_save_job", lambda payload: False)
    core_functions._start_import_thread("a" * 32)
    assert thread_targets == []

    monkeypatch.setattr(core_functions, "_save_job", lambda payload: True)
    core_functions._start_import_thread("a" * 32)

    assert events == ["thread-started"]
    assert thread_targets[0][1] == ("a" * 32,)
    assert thread_targets[0][2] is True
