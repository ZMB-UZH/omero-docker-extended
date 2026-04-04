from __future__ import annotations

import copy
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions


class _Lock:
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


class _ImportedImage:
    def __init__(self, image_id: int, name: str):
        self.id = image_id
        self._name = name
        self.saved = 0

    def getName(self):
        return self._name

    def setName(self, name):
        self._name = name

    def save(self):
        self.saved += 1

    def listParents(self):
        return [SimpleNamespace(getId=lambda: 77)]


def _base_job(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "username": "alice",
        "host": "omeroserver",
        "port": 4064,
        "status": "ready",
        "files": [],
        "errors": [],
        "messages": [],
    }


def _install_process_job_defaults(
    monkeypatch: pytest.MonkeyPatch,
    job: dict,
    upload_root: Path,
):
    saved_jobs: list[dict] = []
    job_state = {"job": job}

    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: _Lock())
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: job_state["job"])
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root.parent)
    monkeypatch.setattr(
        core_functions, "_resolve_job_batch_size", lambda current_job: 50
    )
    monkeypatch.setattr(
        core_functions, "_build_import_units", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda *args, **kwargs: (True, None),
    )
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_import_job_entry",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_build_sem_edx_associations_from_entries",
        lambda entries: {},
    )
    monkeypatch.setattr(
        core_functions,
        "_resolve_staged_target_path",
        lambda root, staged_path: (root / staged_path, None),
    )
    monkeypatch.setattr(core_functions, "_validate_session", lambda conn: True)
    monkeypatch.setattr(
        core_functions,
        "_dataset_name_for_path",
        lambda relative_path, orphan_dataset_name: "Dataset",
    )
    monkeypatch.setattr(
        core_functions,
        "_append_job_error",
        lambda payload, message: payload.setdefault("errors", []).append(message),
    )
    monkeypatch.setattr(
        core_functions,
        "_append_job_message",
        lambda payload, message: payload.setdefault("messages", []).append(message),
    )
    monkeypatch.setattr(
        core_functions,
        "_append_txt_attachment_message",
        lambda payload, txt_name, image_name, success: payload.setdefault(
            "messages", []
        ).append(f"{txt_name}:{image_name}:{success}"),
    )
    monkeypatch.setattr(
        core_functions,
        "_attach_txt_to_image_service",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_batch_find_images_by_name",
        lambda conn, names, dataset_id: {
            name: _ImportedImage(index + 1, name) for index, name in enumerate(names)
        },
    )
    monkeypatch.setattr(core_functions, "_get_id", lambda obj: getattr(obj, "id", None))
    monkeypatch.setattr(
        core_functions, "safe_remove_job_data", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        core_functions,
        "_mark_failed_job_for_deferred_cleanup",
        lambda *args, **kwargs: None,
    )

    def _save_job(payload):
        saved_jobs.append(copy.deepcopy(payload))
        job_state["job"] = payload
        return True

    monkeypatch.setattr(core_functions, "_save_job", _save_job)
    return job_state, saved_jobs


def test_core_function_remaining_helper_paths_cover_last_direct_branches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    assert (
        core_functions._has_read_write_permissions(
            SimpleNamespace(
                canEdit=lambda: False,
                canWrite=lambda: False,
                getDetails=lambda: SimpleNamespace(getPermissions=lambda: None),
            )
        )
        is False
    )

    monkeypatch.setattr(
        core_functions,
        "_should_start_import_plan_build",
        lambda job_dict: False,
    )
    monkeypatch.setattr(
        core_functions,
        "_planned_import_units_for_request",
        lambda job_dict: [],
    )
    waiting_job = {
        "job_id": "a" * 32,
        "compatibility_enabled": True,
        "status": "checking",
    }
    assert core_functions._prepare_uploaded_job_for_request_path_import(
        "a" * 32,
        waiting_job,
        conn=None,
    ) == (waiting_job, None)
    monkeypatch.setattr(
        core_functions,
        "_prepare_request_job_import_datasets",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    assert (
        core_functions._prepare_uploaded_job_for_request_path_import(
            "a" * 32,
            {
                "job_id": "a" * 32,
                "compatibility_enabled": True,
                "compatibility_thread_active": False,
                "status": "awaiting_confirmation",
            },
            conn=None,
        )[1]
        is None
    )

    images = [
        _ImportedImage(1, "Normalized [1]"),
        _ImportedImage(2, "group-header.ome.tif"),
    ]
    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda *args, **kwargs: SimpleNamespace(
            getObject=lambda object_type, image_id: images[image_id - 1],
            close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_image_name_requires_normalization",
        lambda current_name, group_header_name: True,
    )
    monkeypatch.setattr(core_functions, "_get_id", lambda obj: obj.id)
    renamed = core_functions._apply_import_name_normalization_context(
        {"relative_path": "plate.zarr"},
        {"desired_name": "Normalized", "group_header_name": "group-header.ome.tif"},
        [1, 2],
        "session",
        "omeroserver",
        4064,
        None,
    )
    assert renamed == [2]
    assert images[0].getName() == "Normalized [1]"
    assert images[1].getName() == "Normalized [2]"

    monkeypatch.setattr(
        core_functions,
        "_managed_child_lstat",
        lambda parent_fd, child_name, display_path: None,
    )
    monkeypatch.setattr(
        core_functions.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk failure")),
    )
    with pytest.raises(OSError, match="disk failure"):
        core_functions._open_managed_upload_file_fd(7, "demo.txt", 0, "demo.txt")

    assert core_functions._looks_like_directory_package_root(
        [
            "plate.zarr/.zattrs",
            "plate.zarr/OME/METADATA.ome.xml",
        ],
        "plate.zarr",
        "plate.zarr/OME/METADATA.ome.xml",
        [
            "plate.zarr/.zattrs",
            "plate.zarr/OME/METADATA.ome.xml",
        ],
    )
    assert (
        core_functions._looks_like_directory_package_root(
            [
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
            "plate.zarr",
            "plate.zarr/OME/METADATA.ome.xml",
            [
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
        )
        is True
    )
    assert (
        core_functions._looks_like_directory_package_root(
            [
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
            "plate.zarr",
            "",
            [
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
        )
        is True
    )

    compatibility_job = {
        "job_id": "b" * 32,
        "compatibility_enabled": True,
        "files": [],
    }
    job_state = {"job": compatibility_job}
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: job_state["job"])
    monkeypatch.setattr(
        core_functions, "_get_upload_root", lambda: tmp_path / "uploads"
    )
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda *args, **kwargs: [{"staged_path": "", "relative_path": ""}],
    )
    monkeypatch.setattr(
        core_functions,
        "_serialize_import_unit_plan",
        lambda unit: {"relative_path": unit.get("relative_path")},
    )
    monkeypatch.setattr(core_functions, "_refresh_job_status", lambda job_dict: None)
    monkeypatch.setattr(
        core_functions,
        "_compatibility_pending_entries",
        lambda job_dict: [],
    )
    monkeypatch.setattr(
        core_functions,
        "_should_start_compatibility_check",
        lambda job_dict: False,
    )
    monkeypatch.setattr(core_functions, "_resolve_job_batch_size", lambda job_dict: 1)

    def _update_job(job_id, mutator):
        job_state["job"] = mutator(job_state["job"])
        return job_state["job"]

    monkeypatch.setattr(core_functions, "_update_job", _update_job)
    core_functions._run_compatibility_check_inner("b" * 32)
    assert compatibility_job["planned_import_units"] == [{"relative_path": ""}]

    monkeypatch.setattr(
        core_functions,
        "_native_zarr_import_plan",
        lambda zarr_path: SimpleNamespace(
            kind="native", validation_error="broken zarr"
        ),
    )
    assert (
        core_functions._prepare_native_zarr_copy(tmp_path / "demo.zarr")
        == "broken zarr"
    )
    assert (
        core_functions.messages.job_error_with_path("demo.ome.tif", "")
        == "Import failure: demo.ome.tif"
    )


def test_process_import_job_returns_early_when_jobs_disappear_or_are_terminal(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: None)
    core_functions._process_import_job("m" * 32)

    initial_job = _base_job("n" * 32)
    load_sequence = iter([initial_job, None])
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: next(load_sequence))
    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: _Lock())
    core_functions._process_import_job("n" * 32)

    terminal_job = _base_job("o" * 32)
    load_sequence = iter([terminal_job, {**terminal_job, "status": "done"}])
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: next(load_sequence))
    monkeypatch.setattr(core_functions, "_get_import_lock", lambda username: _Lock())
    core_functions._process_import_job("o" * 32)


def test_process_import_job_handles_group_lookup_close_warning_and_missing_upload_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    job = _base_job("p" * 32)
    job["group_id"] = 17
    upload_root = tmp_path / "uploads" / job["job_id"]
    _, saved_jobs = _install_process_job_defaults(monkeypatch, job, upload_root)
    monkeypatch.setattr(
        core_functions,
        "_open_admin_connection",
        lambda *args, **kwargs: SimpleNamespace(
            close=lambda: (_ for _ in ()).throw(RuntimeError("close failed"))
        ),
    )
    monkeypatch.setattr(
        core_functions,
        "_resolve_group_name",
        lambda conn, group_id, group_name=None: "scientists",
    )

    core_functions._process_import_job(job["job_id"])

    assert saved_jobs[-1]["status"] == "error"
    assert job["group_name"] == "scientists"


def test_process_import_job_marks_jobs_error_when_dataset_preparation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    job = _base_job("q" * 32)
    upload_root = tmp_path / "uploads" / job["job_id"]
    upload_root.mkdir(parents=True)
    _, saved_jobs = _install_process_job_defaults(monkeypatch, job, upload_root)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda *args, **kwargs: [{"relative_path": "demo.ome.tif"}],
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda *args, **kwargs: (False, "dataset creation failed"),
    )

    core_functions._process_import_job(job["job_id"])

    assert saved_jobs[-1]["status"] == "error"
    assert saved_jobs[-1]["errors"][-1] == "dataset creation failed"


def test_process_import_job_cleans_up_import_payloads_and_unlinks_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    job = _base_job("r" * 32)
    job["files"] = [{"relative_path": "demo.ome.tif", "size": 3, "status": "uploaded"}]
    upload_root = tmp_path / "uploads" / job["job_id"]
    cleanup_dir = upload_root / "_staged" / "folder"
    cleanup_file = upload_root / "_staged" / "demo.ome.tif"
    cleanup_dir.mkdir(parents=True)
    cleanup_file.parent.mkdir(parents=True, exist_ok=True)
    cleanup_file.write_text("payload", encoding="utf-8")
    _, saved_jobs = _install_process_job_defaults(monkeypatch, job, upload_root)
    monkeypatch.setattr(
        core_functions,
        "_build_import_units",
        lambda *args, **kwargs: [
            {"covered_indexes": [0], "relative_path": "demo.ome.tif"}
        ],
    )
    monkeypatch.setattr(
        core_functions,
        "_import_job_entry",
        lambda *args, **kwargs: {
            "status": "imported",
            "covered_indexes": [0],
            "rel_path": "demo.ome.tif",
            "cleanup_staged_paths": [
                "_staged/folder",
                "_staged/demo.ome.tif",
            ],
        },
    )
    monkeypatch.setattr(
        core_functions.shutil,
        "rmtree",
        lambda target, ignore_errors=False: (_ for _ in ()).throw(
            OSError("cannot remove directory")
        ),
    )

    core_functions._process_import_job(job["job_id"])

    assert cleanup_file.exists() is False
    assert saved_jobs[-1]["status"] == "done"
    assert any(
        "Import success: demo.ome.tif" in message
        for message in saved_jobs[-1]["messages"]
    )


def test_process_import_job_reports_sem_edx_service_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    job = _base_job("s" * 32)
    job["special_upload"] = "sem_edx_spectra"
    job["sem_edx_associations"] = {"image-1.ome.tif": ["spectra.txt"]}
    upload_root = tmp_path / "uploads" / job["job_id"]
    upload_root.mkdir(parents=True)
    _, saved_jobs = _install_process_job_defaults(monkeypatch, job, upload_root)

    core_functions._process_import_job(job["job_id"])

    assert saved_jobs[-1]["status"] == "done"
    assert any(
        "failed to open service connection" in message
        for message in saved_jobs[-1]["messages"]
    )


def test_process_import_job_reuses_plot_cache_and_handles_reconnect_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    job = _base_job("t" * 32)
    job["special_upload"] = "sem_edx_spectra"
    job["dataset_map"] = {"Dataset": 77}
    job["sem_edx_settings"] = {
        "create_tables": True,
        "create_figures_attachments": True,
        "create_figures_images": False,
    }
    job["files"] = [
        {
            "relative_path": "spectra.txt",
            "staged_path": "_staged/spectra.txt",
            "size": 1,
            "status": "uploaded",
        }
    ]
    job["sem_edx_associations"] = {"broken.ome.tif": "not-a-list"}
    for index in range(11):
        job["sem_edx_associations"][f"image-{index}.ome.tif"] = ["spectra.txt"]

    upload_root = tmp_path / "uploads" / job["job_id"]
    upload_root.mkdir(parents=True)
    txt_path = upload_root / "_staged" / "spectra.txt"
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("spectrum", encoding="utf-8")
    plot_path = tmp_path / "plot.png"
    plot_path.write_text("plot", encoding="utf-8")

    _, saved_jobs = _install_process_job_defaults(monkeypatch, job, upload_root)

    open_calls = {"count": 0}

    class _Conn:
        def close(self):
            raise RuntimeError("expired connection")

    def _open_service_connection(*args, **kwargs):
        open_calls["count"] += 1
        if open_calls["count"] == 1:
            return _Conn()
        raise RuntimeError("reopen failed")

    fake_parser = types.ModuleType("omeroweb_import.services.omero.sem_edx_parser")
    fake_parser.create_edx_spectrum_plot = lambda current_txt_path: plot_path
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.services.omero.sem_edx_parser",
        fake_parser,
    )
    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        _open_service_connection,
    )
    monkeypatch.setattr(core_functions, "_validate_session", lambda conn: False)

    core_functions._process_import_job(job["job_id"])

    assert saved_jobs[-1]["status"] == "done"
    assert any(
        message.startswith("spectra.txt:image-0.ome.tif:True")
        for message in saved_jobs[-1]["messages"]
    )


def test_process_import_job_logs_sem_edx_outer_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    job = _base_job("u" * 32)
    job["special_upload"] = "sem_edx_spectra"
    job["dataset_map"] = {"Dataset": 77}
    job["sem_edx_settings"] = {
        "create_tables": True,
        "create_figures_attachments": False,
        "create_figures_images": False,
    }
    job["sem_edx_associations"] = {"image-1.ome.tif": ["spectra.txt"]}
    upload_root = tmp_path / "uploads" / job["job_id"]
    upload_root.mkdir(parents=True)
    _, saved_jobs = _install_process_job_defaults(monkeypatch, job, upload_root)
    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda *args, **kwargs: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(
        core_functions,
        "_batch_find_images_by_name",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("cache load failed")
        ),
    )
    caplog.set_level(logging.ERROR, logger=core_functions.logger.name)

    core_functions._process_import_job(job["job_id"])

    assert saved_jobs[-1]["status"] == "done"
    assert any(
        "SEM EDX txt attachment failed" in record.message for record in caplog.records
    )


def test_start_import_thread_covers_missing_job_and_thread_start_failures(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: None)
    core_functions._start_import_thread("v" * 32)

    job = {"job_id": "w" * 32, "status": "ready", "import_thread_started": False}
    saved = []
    monkeypatch.setattr(core_functions, "_load_job", lambda job_id: job)
    monkeypatch.setattr(
        core_functions,
        "_save_job",
        lambda payload: saved.append(copy.deepcopy(payload)) or True,
    )

    class _BrokenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(core_functions.threading, "Thread", _BrokenThread)
    core_functions._start_import_thread("w" * 32)
    assert saved[-1]["import_thread_started"] is False
