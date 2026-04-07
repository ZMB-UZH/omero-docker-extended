from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions


def test_core_function_small_helper_edges_cover_early_validation_paths(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("EDGE_INT_VALUE", "bad")
    assert core_functions._get_env_int("EDGE_INT_VALUE", 7, 1, 10) == 7

    assert (
        core_functions._should_start_import_plan_build(
            {"compatibility_enabled": False, "status": "done", "files": []}
        )
        is False
    )
    assert (
        core_functions._should_start_import_plan_build(
            {
                "compatibility_enabled": False,
                "status": "ready",
                "files": [{"status": "pending"}],
            }
        )
        is False
    )
    assert (
        core_functions._should_start_import_plan_build(
            {
                "compatibility_enabled": False,
                "status": "ready",
                "planned_import_units": [
                    {
                        "relative_path": "sample",
                        "dataset_relative_path": "sample",
                        "covered_relative_paths": ["sample"],
                    }
                ],
                "files": [{"status": "uploaded", "relative_path": "sample"}],
            }
        )
        is False
    )

    job = {"compatibility_thread_active": True, "status": "uploading"}
    assert core_functions._refresh_job_status(job)["status"] == "checking"

    assert core_functions._safe_relative_path("") is None
    internal_error = core_functions._managed_upload_internal_error("public")
    assert core_functions._managed_upload_error_message(internal_error) == "public"
    assert (
        core_functions._managed_upload_error_message(RuntimeError("plain")) == "plain"
    )

    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    closed_fds = []
    monkeypatch.setattr(
        core_functions,
        "_managed_parent_runtime_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core_functions,
        "_managed_parent_directory_fd",
        lambda *args, **kwargs: (123, "sample.bin"),
    )
    monkeypatch.setattr(
        core_functions,
        "_managed_child_lstat",
        lambda *args, **kwargs: SimpleNamespace(st_size=0),
    )
    monkeypatch.setattr(
        core_functions.os,
        "unlink",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(core_functions.os, "close", lambda fd: closed_fds.append(fd))
    assert core_functions._reset_staged_upload_file(upload_root, "sample.bin") is None
    assert closed_fds == [123]

    size, error = core_functions._staged_upload_size(upload_root, "../bad")
    assert size is None
    assert error is not None

    replaced_size, replace_error = core_functions._replace_staged_upload_file(
        upload_root,
        "../bad",
        object(),
    )
    assert replaced_size is None
    assert replace_error is not None

    normalized = core_functions._normalize_sem_edx_associations(
        {
            "scan.txt": ["note.txt"],
            "missing.png": ["note.txt"],
            "image.png": "not-a-list",
            "image2.png": ["missing.txt", "note.png", "note.txt"],
        },
        [
            {"relative_path": "image2.png"},
            {"relative_path": "note.txt"},
        ],
    )
    assert normalized == {"image2.png": ["note.txt"]}

    assert core_functions._normalize_sem_edx_associations([], []) == {}
    assert core_functions._build_sem_edx_associations_from_entries([]) == {}
    derived = core_functions._build_sem_edx_associations_from_entries(
        [
            "bad-entry",
            {"relative_path": None},
            {"relative_path": "../escape.txt"},
            {"relative_path": "image.png"},
            {"relative_path": "note.txt"},
        ]
    )
    assert derived == {"image.png": ["note.txt"]}

    class _BrokenValue:
        def getValue(self):
            raise RuntimeError("boom")

        def __str__(self):
            return "fallback"

    assert core_functions._get_text(_BrokenValue()) == "fallback"
    assert core_functions._external_info_text(None, "lsid", "getLsid") == ""
    external_info = SimpleNamespace(lsid=SimpleNamespace(val="managed/path"))
    assert core_functions._external_info_text(external_info, "lsid", "getLsid") == (
        "managed/path"
    )
    broken_external = SimpleNamespace(
        lsid=SimpleNamespace(val=""),
        getLsid=lambda: (_ for _ in ()).throw(RuntimeError("bad getter")),
    )
    assert (
        core_functions._external_info_text(
            broken_external,
            "lsid",
            "getLsid",
        )
        == ""
    )

    assert core_functions._query_image_external_info(None, 1) == ("", "")
    failing_conn = SimpleNamespace(
        getQueryService=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert core_functions._query_image_external_info(failing_conn, 1) == ("", "")
    assert core_functions._query_image_external_info(
        SimpleNamespace(
            getQueryService=lambda: SimpleNamespace(
                projection=lambda *args, **kwargs: []
            ),
            SERVICE_OPTS=object(),
        ),
        1,
    ) == ("", "")

    assert core_functions._native_zarr_length_from_value_unit([]) is None

    class _BrokenLength:
        val = None

        def getValue(self):
            raise RuntimeError("bad value")

    assert core_functions._native_zarr_length_signature(_BrokenLength()) is None


def test_core_function_connection_and_name_normalization_helpers_cover_remaining_paths(
    monkeypatch,
):
    monkeypatch.delenv(core_functions.JOB_SERVICE_USER_ENV, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_USER_ENV_FALLBACK, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_AUTH_ENV, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_AUTH_ENV_FALLBACK, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_GROUP_ENV, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_GROUP_ENV_FALLBACK, raising=False)
    user, passwd, group_override, secure = core_functions._get_job_service_credentials()
    assert user == core_functions.JOB_SERVICE_USERNAME_DEFAULT
    assert not passwd
    assert group_override == ""
    assert secure is True

    service_opts = SimpleNamespace(
        setOmeroGroup=lambda _value: (_ for _ in ()).throw(RuntimeError("bad group"))
    )
    exploding_conn = SimpleNamespace(
        connect=lambda: True,
        close=lambda: (_ for _ in ()).throw(RuntimeError("close exploded")),
        SERVICE_OPTS=service_opts,
    )
    monkeypatch.setattr(
        core_functions, "BlitzGateway", lambda *args, **kwargs: exploding_conn
    )
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("svc", "opaque-auth-value", "not-an-int", True),
    )
    assert (
        core_functions._open_service_connection("host", 4064, group_id=7)
        is exploding_conn
    )

    def _raising_connect():
        raise RuntimeError("connect exploded")

    cleanup_events = []
    failing_conn = SimpleNamespace(
        connect=_raising_connect,
        close=lambda: cleanup_events.append("closed"),
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=lambda value: None),
        getLastError=lambda: (_ for _ in ()).throw(RuntimeError("last error exploded")),
    )
    monkeypatch.setattr(
        core_functions, "BlitzGateway", lambda *args, **kwargs: failing_conn
    )
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("svc", "opaque-auth-value", "", True),
    )
    assert core_functions._open_service_connection("host", 4064, group_id=7) is None
    assert cleanup_events == ["closed"]
    assert core_functions._connection_has_last_error(failing_conn) is False

    opened_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(
            setOmeroGroup=lambda _value: (_ for _ in ()).throw(
                RuntimeError("group exploded")
            )
        ),
        close=lambda: (_ for _ in ()).throw(RuntimeError("close exploded")),
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda *args, **kwargs: opened_conn,
    )
    assert (
        core_functions._open_group_scoped_session_connection(
            "session-key",
            "omeroserver",
            4064,
            group_id=4,
        )
        is opened_conn
    )

    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("open exploded")),
    )
    with pytest.raises(RuntimeError, match="open exploded"):
        core_functions._open_group_scoped_session_connection(
            "session-key",
            "omeroserver",
            4064,
            group_id=4,
        )

    assert (
        core_functions._open_user_owned_background_connection(
            "alice",
            purpose="imports",
        )
        is None
    )
    switched_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(
            setOmeroGroup=lambda _value: (_ for _ in ()).throw(
                RuntimeError("set exploded")
            )
        )
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda *args, **kwargs: switched_conn,
    )
    assert (
        core_functions._open_user_owned_background_connection(
            "alice",
            session_key="session-key",
            host="omeroserver",
            port=4064,
            group_id=4,
            purpose="imports",
        )
        is switched_conn
    )

    assert core_functions._logical_import_entry_display_name({}) == ""
    assert core_functions._logical_import_entry_group_header_name({}) == ""
    entry = {
        "relative_path": "folder/sample.ome.tif",
        "staged_path": "_staged/job/folder/group-header.ome.tif",
        "covered_relative_paths": ["folder/sample.ome.tif", "folder/metadata.txt"],
    }
    assert core_functions._build_import_name_normalization_context(entry, None) is None
    context = core_functions._build_import_name_normalization_context(entry, 7)
    assert context == {
        "desired_name": "sample.ome.tif",
        "group_header_name": "group-header.ome.tif",
    }
    assert core_functions._extract_imported_image_ids("") == []
    assert core_functions._image_name_requires_normalization("", "group-header") is True
    assert (
        core_functions._apply_import_name_normalization_context(
            entry,
            context,
            [],
            "session-key",
            "omeroserver",
            4064,
            4,
        )
        == []
    )


def test_core_function_message_and_import_verification_helpers_cover_remaining_paths():
    job = {}
    core_functions._append_job_message(job, "")
    core_functions._append_job_error(job, "")
    assert job == {}

    dataset_conn = SimpleNamespace(
        getObject=lambda obj_type, dataset_id: None,
    )
    assert (
        core_functions._verify_import(dataset_conn, "sample.tif", dataset_id=1) is False
    )
    failing_dataset_conn = SimpleNamespace(
        getObject=lambda obj_type, dataset_id: SimpleNamespace(
            listChildren=lambda: (_ for _ in ()).throw(RuntimeError("dataset exploded"))
        )
    )
    assert (
        core_functions._verify_import(
            failing_dataset_conn,
            "sample.tif",
            dataset_id=1,
        )
        is False
    )
    global_failing_conn = SimpleNamespace(
        getObjects=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("global exploded")
        )
    )
    assert core_functions._verify_import(global_failing_conn, "sample.tif") is False

    default_lock = core_functions._get_import_lock("")
    assert default_lock is core_functions._get_import_lock("")
