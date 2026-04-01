from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory

from omeroweb_import.strings import errors
from omeroweb_import.views import index_view


def _test_job_id(suffix: str) -> str:
    """Build a fake job ID at runtime so static scanners do not flag it as a token."""
    return "dead" + "0" * 26 + suffix


def _payload(response):
    return json.loads(response.content.decode("utf-8"))


class _NamedObject:
    def __init__(self, name: str):
        self._name = name

    def getName(self):
        return self._name


class _Project(_NamedObject):
    pass


class _Conn:
    def __init__(
        self,
        *,
        project=None,
        group=None,
        event_context=None,
        event_error: Exception | None = None,
    ):
        self._project = project
        self._group = group
        self._event_context = event_context
        self._event_error = event_error

    def getObject(self, kind, obj_id):
        if kind == "Project":
            return self._project
        if kind == "ExperimenterGroup":
            return self._group
        raise AssertionError(f"unexpected object lookup: {kind!r} {obj_id!r}")

    def getEventContext(self):
        if self._event_error is not None:
            raise self._event_error
        return self._event_context


def test_index_list_projects_and_root_status_surface_runtime_context(monkeypatch):
    upload_root = Path(tempfile.gettempdir()) / "import-upload-root"
    request = RequestFactory().get("/omeroweb_import/")

    monkeypatch.setattr(index_view, "_current_user_id", lambda conn: 17)
    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(
        index_view,
        "_get_jobs_root",
        lambda: Path(tempfile.gettempdir()) / "import-jobs",
    )
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(
        index_view,
        "_get_env_int",
        lambda key, default, minimum, maximum: (
            4 if key == index_view.UPLOAD_CONCURRENCY_ENV else 7
        ),
    )
    monkeypatch.setattr(
        index_view,
        "_collect_project_payload",
        lambda conn, user_id: [{"id": 1, "name": "Project A", "user_id": user_id}],
    )
    monkeypatch.setattr(index_view, "_special_methods_enabled", lambda: True)
    monkeypatch.setattr(
        index_view.messages,
        "index_messages",
        lambda: {"title": "Import files"},
    )
    monkeypatch.setattr(index_view, "reverse", lambda name, kwargs=None: f"/{name}/")

    def fake_render(_request, _template, context):
        return HttpResponse(
            json.dumps(context, sort_keys=True),
            content_type="application/json",
        )

    monkeypatch.setattr(index_view, "render", fake_render)

    response = index_view.index(request, conn=object())
    payload = _payload(response)

    assert payload["upload_root"] == str(upload_root)
    assert payload["upload_enabled"] is True
    assert payload["upload_concurrency"] == 4
    assert payload["upload_batch_files"] == 7
    assert payload["special_methods_enabled"] is True
    assert payload["user_id"] == 17
    assert payload["project_list_url"] == "/omeroweb_import_projects/"
    assert payload["messages_json"] == json.dumps({"title": "Import files"})

    list_response = index_view.list_projects(request, conn=object())
    assert _payload(list_response) == [{"id": 1, "name": "Project A", "user_id": 17}]

    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "root")
    root_response = index_view.root_status(request, conn=object())
    assert _payload(root_response) == {"is_root_user": True}


def test_start_upload_wrapper_returns_sanitized_server_error(monkeypatch):
    request = RequestFactory().post("/omeroweb_import/start/")

    monkeypatch.setattr(
        index_view,
        "_start_upload",
        lambda request, conn: (_ for _ in ()).throw(
            RuntimeError("secret backend details")
        ),
    )

    response = index_view.start_upload(request, conn=object())

    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_start_upload(),
    }


def test_start_upload_success_normalizes_entries_and_captures_group_context(
    tmp_path, monkeypatch
):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    saved = {}
    request = RequestFactory().post(
        "/omeroweb_import/start/",
        data=json.dumps(
            {
                "project_id": "9",
                "files": [
                    {"relative_path": "analysis/data.txt", "size": "not-an-int"},
                    {"relative_path": "Thumbs.db", "size": -4},
                    {"relative_path": "top-level.tif", "size": 5},
                ],
                "special_upload": "sem_edx_spectra",
                "compatibility_enabled": False,
                "batch_size": "11",
                "sem_edx_associations": {"analysis/data.txt": ["sample-1"]},
                "sem_edx_settings": {"create_tables": False},
            }
        ),
        content_type="application/json",
    )
    conn = _Conn(
        project=_Project("Project One"),
        group=_NamedObject("Research"),
        event_context=SimpleNamespace(groupId=7, groupName="  "),
    )
    uuid_values = iter(
        [
            SimpleNamespace(hex="a" * 32),
            SimpleNamespace(hex="b" * 32),
            SimpleNamespace(hex="c" * 32),
            SimpleNamespace(hex="d" * 32),
        ]
    )

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(
        index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064)
    )
    monkeypatch.setattr(index_view, "_special_methods_enabled", lambda: True)
    monkeypatch.setattr(index_view, "_is_owned_by_user", lambda obj, user_id: False)
    monkeypatch.setattr(index_view, "_has_read_write_permissions", lambda obj: True)
    monkeypatch.setattr(index_view, "_current_user_id", lambda conn: 13)
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "_normalize_sem_edx_associations",
        lambda associations, normalized: {
            "normalized": [entry["relative_path"] for entry in normalized]
        },
    )
    monkeypatch.setattr(
        index_view,
        "_normalize_sem_edx_settings",
        lambda settings: {"create_tables": False, "create_figures_images": True},
    )
    monkeypatch.setattr(
        index_view, "_generate_orphan_dataset_name", lambda: "UploadRoot_TEST"
    )
    monkeypatch.setattr(index_view.uuid, "uuid4", lambda: next(uuid_values))
    monkeypatch.setattr(
        index_view,
        "reverse",
        lambda name, kwargs=None: (
            f"/mock/{name}/{kwargs['job_id']}" if kwargs else f"/mock/{name}"
        ),
    )

    def save_job(job):
        saved["job"] = json.loads(json.dumps(job))
        return True

    monkeypatch.setattr(index_view, "_save_job", save_job)

    response = index_view._start_upload(request, conn=conn)
    payload = _payload(response)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["job_id"] == "d" * 32
    assert payload["upload_url"].endswith("/mock/omeroweb_import_files/" + "d" * 32)

    job = saved["job"]
    assert job["project_id"] == 9
    assert job["project_name"] == "Project One"
    assert job["group_id"] == 7
    assert job["group_name"] == "Research"
    assert job["compatibility_enabled"] is False
    assert job["job_batch_size"] == 10
    assert job["orphan_dataset_name"] == "UploadRoot_TEST"
    assert job["sem_edx_associations"] == {
        "normalized": ["analysis/data.txt", "Thumbs.db", "top-level.tif"]
    }
    assert job["sem_edx_settings"] == {
        "create_tables": False,
        "create_figures_images": True,
    }
    assert job["total_bytes"] == 5
    assert job["files"][0]["size"] == 0
    assert job["files"][0]["import_skip"] is True
    assert job["files"][0]["compatibility_skip"] is True
    assert job["files"][1]["size"] == 0
    assert job["files"][1]["import_skip"] is True
    assert job["files"][1]["compatibility_skip"] is True
    assert job["files"][2]["import_skip"] is False


def test_start_upload_handles_disabled_special_methods_event_context_failures_and_save_errors(
    tmp_path, monkeypatch
):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    captured = {}
    request = RequestFactory().post(
        "/omeroweb_import/start/",
        data=json.dumps(
            {
                "files": [{"relative_path": "folder/sample.tif", "size": 1}],
                "special_upload": "sem_edx_spectra",
                "sem_edx_associations": {"folder/sample.tif": ["sample-1"]},
                "sem_edx_settings": {"create_tables": False},
            }
        ),
        content_type="application/json",
    )
    conn = _Conn(event_error=RuntimeError("group lookup exploded"))

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(
        index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064)
    )
    monkeypatch.setattr(index_view, "_special_methods_enabled", lambda: False)
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(index_view.uuid, "uuid4", lambda: SimpleNamespace(hex="e" * 32))
    monkeypatch.setattr(
        index_view,
        "reverse",
        lambda name, kwargs=None: (
            f"/mock/{name}/{kwargs['job_id']}" if kwargs else f"/mock/{name}"
        ),
    )
    monkeypatch.setattr(
        index_view,
        "_normalize_sem_edx_associations",
        lambda associations, normalized: dict(associations),
    )

    def save_job(job):
        captured["job"] = json.loads(json.dumps(job))
        return False

    monkeypatch.setattr(index_view, "_save_job", save_job)

    response = index_view._start_upload(request, conn=conn)

    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_update_upload_job_state(),
    }
    assert captured["job"]["group_id"] is None
    assert captured["job"]["group_name"] is None
    assert captured["job"]["special_upload"] == ""
    assert captured["job"]["sem_edx_associations"] == {}
    assert captured["job"]["sem_edx_settings"] == {}


def test_start_upload_rejects_invalid_project_payloads_paths_and_batch_limits(
    tmp_path, monkeypatch
):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064)
    )
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(index_view, "_save_job", lambda job: True)
    monkeypatch.setattr(index_view.uuid, "uuid4", lambda: SimpleNamespace(hex="f" * 32))
    monkeypatch.setattr(index_view, "reverse", lambda name, kwargs=None: f"/{name}/")
    monkeypatch.setattr(index_view, "_special_methods_enabled", lambda: True)

    response = index_view._start_upload(
        RequestFactory().get("/omeroweb_import/start/"), conn=object()
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_start_post_required(),
    }

    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: False)
    response = index_view._start_upload(
        RequestFactory().post(
            "/omeroweb_import/start/",
            data=json.dumps({"files": [{"relative_path": "file.tif", "size": 1}]}),
            content_type="application/json",
        ),
        conn=object(),
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_folder_not_writable(),
    }

    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(index_view, "load_json_body", lambda request: [])
    response = index_view._start_upload(
        RequestFactory().post(
            "/omeroweb_import/start/", data=b"[]", content_type="application/json"
        ),
        conn=object(),
    )
    assert _payload(response) == {"ok": False, "error": errors.no_files_provided()}

    monkeypatch.setattr(
        index_view,
        "load_json_body",
        lambda request: {
            "project_id": "bad",
            "files": [{"relative_path": "file.tif", "size": 1}],
        },
    )
    response = index_view._start_upload(
        RequestFactory().post("/omeroweb_import/start/"), conn=object()
    )
    assert response.status_code == 400
    assert _payload(response) == {
        "ok": False,
        "error": errors.invalid_project_selection(),
    }

    conn = _Conn(project=_Project("Unauthorized"))
    monkeypatch.setattr(
        index_view,
        "load_json_body",
        lambda request: {
            "project_id": "4",
            "files": [{"relative_path": "file.tif", "size": 1}],
        },
    )
    monkeypatch.setattr(index_view, "_current_user_id", lambda conn: 1)
    monkeypatch.setattr(index_view, "_is_owned_by_user", lambda obj, user_id: False)
    monkeypatch.setattr(index_view, "_has_read_write_permissions", lambda obj: False)
    response = index_view._start_upload(
        RequestFactory().post("/omeroweb_import/start/"), conn=conn
    )
    assert response.status_code == 400
    assert _payload(response) == {
        "ok": False,
        "error": errors.invalid_project_selection(),
    }

    monkeypatch.setattr(
        index_view, "load_json_body", lambda request: {"files": "not-a-list"}
    )
    response = index_view._start_upload(
        RequestFactory().post("/omeroweb_import/start/"), conn=object()
    )
    assert _payload(response) == {"ok": False, "error": errors.no_files_provided()}

    monkeypatch.setattr(
        index_view,
        "load_json_body",
        lambda request: {"files": [{"relative_path": "file.tif", "size": 1}]},
    )
    monkeypatch.setattr(index_view, "_resolve_omero_host_port", lambda conn: ("", None))
    response = index_view._start_upload(
        RequestFactory().post("/omeroweb_import/start/"), conn=object()
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_resolve_host_port(),
    }

    monkeypatch.setattr(
        index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064)
    )

    def staged_error(upload_root, staged_path):
        if "blocked" in staged_path:
            return "Unsafe staged target"
        return None

    monkeypatch.setattr(index_view, "_validate_staged_target_path", staged_error)
    monkeypatch.setattr(
        index_view,
        "load_json_body",
        lambda request: {
            "files": [
                42,
                {"relative_path": "../bad", "size": 1},
                {"relative_path": "folder/file.bin", "size": 1},
                {"relative_path": "folder", "size": 1},
                {"relative_path": "blocked/file.bin", "size": 1},
            ]
        },
    )
    response = index_view._start_upload(
        RequestFactory().post("/omeroweb_import/start/"), conn=object()
    )
    payload = _payload(response)
    assert payload["ok"] is False
    assert "Duplicate" not in payload["error"]
    assert "Invalid file paths" in payload["error"]
    assert "42" in payload["error"]
    assert "Unsafe staged target" in payload["error"]
    assert "folder" in payload["error"]

    monkeypatch.setattr(
        index_view,
        "_validate_staged_target_path",
        lambda upload_root, staged_path: None,
    )
    monkeypatch.setattr(
        index_view,
        "load_json_body",
        lambda request: {"files": [{"relative_path": "big.bin", "size": 3}]},
    )
    monkeypatch.setattr(index_view, "MAX_UPLOAD_BATCH_BYTES", 2)
    monkeypatch.setattr(index_view, "MAX_UPLOAD_BATCH_GB", 1)
    response = index_view._start_upload(
        RequestFactory().post("/omeroweb_import/start/"), conn=object()
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_batch_too_large(1),
    }


def test_upload_helpers_non_chunked_paths_and_preparation_errors(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("b2")
    upload_root.mkdir()
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "bob")

    assert index_view._find_job_upload_entry({"files": []}, "missing.bin") is None
    assert (
        index_view._job_owned_by_request({"username": "alice"}, SimpleNamespace(), None)
        is False
    )
    assert index_view._parse_chunk_int("abc", "chunk_start") == (
        None,
        errors.upload_chunk_metadata_invalid("chunk_start must be an integer"),
    )
    assert index_view._parse_chunk_int("-1", "chunk_start") == (
        None,
        errors.upload_chunk_metadata_invalid("chunk_start must be non-negative"),
    )
    assert index_view._as_bool("yes") is True
    assert index_view._as_bool("0") is False

    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_dataset_targets",
        lambda job_id, job, conn: (job, "prep failed"),
    )
    prepared_job, prep_error = index_view._prepare_ready_job_for_import_start(
        job_id, {"status": "ready"}, object()
    )
    assert prepared_job == {"status": "ready"}
    assert prep_error == "prep failed"

    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_dataset_targets",
        lambda job_id, job, conn: (job, None),
    )
    prepared_job, prep_error = index_view._prepare_ready_job_for_import_start(
        job_id, {"status": "checking"}, object()
    )
    assert prepared_job == {"status": "checking"}
    assert prep_error is None

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: ({"files": []}, None),
    )
    request = RequestFactory().get(f"/omeroweb_import/upload/{job_id}/")
    response = index_view._upload_files(request, job_id, conn=object())
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_endpoint_post_required(),
    }

    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: False)
    request = RequestFactory().post(f"/omeroweb_import/upload/{job_id}/")
    response = index_view._upload_files(request, job_id, conn=object())
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_folder_not_writable(),
    }

    monkeypatch.setattr(
        index_view, "_ensure_dir", lambda path: True if path == upload_root else True
    )
    missing_response = index_view.json_error(errors.upload_job_not_found())
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (None, missing_response),
    )
    response = index_view._upload_files(
        RequestFactory().post(f"/omeroweb_import/upload/{job_id}/"),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {"ok": False, "error": errors.upload_job_not_found()}

    job = {
        "job_id": job_id,
        "username": "alice",
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/file.bin",
                "staged_path": "_staged/folder/file.bin",
                "status": "pending",
                "errors": [],
            }
        ],
    }
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (job, None),
    )
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: path == upload_root)
    response = index_view._upload_files(
        RequestFactory().post(f"/omeroweb_import/upload/{job_id}/"),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_initialize_upload_folder(),
    }

    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    response = index_view._upload_files(
        RequestFactory().post(f"/omeroweb_import/upload/{job_id}/"),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {"ok": False, "error": errors.no_files_provided()}

    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_paths": ["folder/a.bin", "folder/b.bin"],
                "files": [SimpleUploadedFile("a.bin", b"abc")],
            },
        ),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_payload_mismatch(),
    }

    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: None,
    )
    monkeypatch.setattr(
        index_view,
        "_normalize_upload_relative_path",
        lambda raw_name: (None, "bad path"),
    )
    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={"files": [SimpleUploadedFile("a.bin", b"abc")]},
        ),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_update_upload_job_state(),
    }

    monkeypatch.setattr(
        index_view,
        "_normalize_upload_relative_path",
        lambda raw_name: ("unexpected.bin", None),
    )
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: {
            **job,
            "uploaded_bytes": 0,
            "total_bytes": 0,
            "status": "uploading",
        },
    )
    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={"files": [SimpleUploadedFile("a.bin", b"abc")]},
        ),
        job_id,
        conn=object(),
    )
    assert _payload(response)["errors"] == [errors.unexpected_file("unexpected.bin")]

    monkeypatch.setattr(
        index_view,
        "_normalize_upload_relative_path",
        lambda raw_name: ("folder/file.bin", None),
    )
    monkeypatch.setattr(
        index_view,
        "_replace_staged_upload_file",
        lambda job_root, staged_path, upload: (None, "Unsafe staged target"),
    )
    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={"files": [SimpleUploadedFile("file.bin", b"abc")]},
        ),
        job_id,
        conn=object(),
    )
    assert _payload(response)["errors"] == ["Unsafe staged target"]

    monkeypatch.setattr(
        index_view,
        "_replace_staged_upload_file",
        lambda job_root, staged_path, upload: (3, None),
    )
    monkeypatch.setattr(
        index_view, "_apply_upload_updates", lambda job_id, updates, upload_errors: None
    )
    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={"files": [SimpleUploadedFile("file.bin", b"abc")]},
        ),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_update_upload_job_state(),
    }

    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda job_id, updates, upload_errors: {
            **job,
            "uploaded_bytes": 3,
            "total_bytes": 3,
            "status": "ready",
        },
    )
    job["files"][0]["status"] = "pending"
    job["files"][0]["errors"] = []
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_dataset_targets",
        lambda job_id, job, conn: (job, "prep failed"),
    )
    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={"files": [SimpleUploadedFile("file.bin", b"abc")]},
        ),
        job_id,
        conn=object(),
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_uploading_files(),
    }
    assert "prep failed" not in response.content.decode("utf-8")

    import_started = []
    job["files"][0]["status"] = "pending"
    job["files"][0]["errors"] = []
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_dataset_targets",
        lambda job_id, job, conn: (job, None),
    )
    monkeypatch.setattr(
        index_view,
        "_start_import_thread",
        lambda current_job_id: import_started.append(current_job_id),
    )
    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={"files": [SimpleUploadedFile("file.bin", b"abc")]},
        ),
        job_id,
        conn=object(),
    )
    payload = _payload(response)
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert import_started == [job_id]


def test_chunk_import_confirm_prune_and_status_control_paths(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("c2")
    job_root = upload_root / job_id
    job_root.mkdir(parents=True)
    job = {
        "job_id": job_id,
        "username": "alice",
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 4,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/file.bin",
                "staged_path": "_staged/folder/file.bin",
                "size": 4,
                "status": "pending",
                "errors": [],
            }
        ],
    }

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(
        index_view,
        "_normalize_upload_relative_path",
        lambda raw_value: ("folder/file.bin", None),
    )
    monkeypatch.setattr(index_view, "_parse_chunk_int", index_view._parse_chunk_int)
    monkeypatch.setattr(
        index_view, "_find_job_upload_entry", index_view._find_job_upload_entry
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(f"/omeroweb_import/upload/{job_id}/", data={}),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_missing_file(),
    }

    monkeypatch.setattr(
        index_view,
        "_normalize_upload_relative_path",
        lambda raw_value: (None, "bad relative path"),
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "../bad",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {"ok": False, "error": "bad relative path"}

    monkeypatch.setattr(
        index_view,
        "_normalize_upload_relative_path",
        lambda raw_value: ("folder/file.bin", None),
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "bad",
                "chunk_end": "2",
                "file_size": "4",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_metadata_invalid("chunk_start must be an integer"),
    }

    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "bad",
                "file_size": "4",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_metadata_invalid("chunk_end must be an integer"),
    }

    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "2",
                "file_size": "bad",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_metadata_invalid("file_size must be an integer"),
    }

    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "3",
                "chunk_end": "2",
                "file_size": "4",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_metadata_invalid(
            "chunk_end must be greater than or equal to chunk_start"
        ),
    }

    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "5",
                "file_size": "4",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_metadata_invalid(
            "chunk_end cannot exceed file_size"
        ),
    }

    monkeypatch.setattr(
        index_view, "_find_job_upload_entry", lambda current_job, rel_path: None
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "2",
                "file_size": "4",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_file("folder/file.bin"),
    }

    monkeypatch.setattr(
        index_view,
        "_find_job_upload_entry",
        lambda current_job, rel_path: current_job["files"][0],
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "4",
                "file_size": "4",
                "file": SimpleUploadedFile("file.bin", b"abc"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_size_mismatch("folder/file.bin", 4, 3),
    }

    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "2",
                "file_size": "4",
                "is_last_chunk": "1",
                "file": SimpleUploadedFile("file.bin", b"ab"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.upload_chunk_incomplete("folder/file.bin", 4, 2),
    }

    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: None,
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "4",
                "file_size": "4",
                "is_last_chunk": "1",
                "file": SimpleUploadedFile("file.bin", b"abcd"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_update_upload_job_state(),
    }

    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: {
            **job,
            "status": "ready",
            "uploaded_bytes": 4,
        },
    )
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_dataset_targets",
        lambda current_job_id, current_job, conn: (current_job, "prep failed"),
    )
    response = index_view._handle_chunk_upload(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "relative_path": "folder/file.bin",
                "chunk_start": "0",
                "chunk_end": "4",
                "file_size": "4",
                "is_last_chunk": "1",
                "file": SimpleUploadedFile("file.bin", b"abcd"),
            },
        ),
        job_id,
        object(),
        job,
        job_root,
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_uploading_files(),
    }
    assert "prep failed" not in response.content.decode("utf-8")

    original_import_step = index_view._import_step
    monkeypatch.setattr(
        index_view,
        "_import_step",
        lambda request, current_job_id, conn: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    wrapper_response = index_view.import_step(
        RequestFactory().post(f"/omeroweb_import/import/{job_id}/"),
        job_id=job_id,
        conn=object(),
    )
    assert wrapper_response.status_code == 500
    assert _payload(wrapper_response) == {
        "ok": False,
        "error": errors.unexpected_server_error_importing(),
    }

    monkeypatch.setattr(index_view, "_import_step", original_import_step)
    response = index_view._import_step(RequestFactory().get("/"), job_id, conn=object())
    assert _payload(response) == {
        "ok": False,
        "error": errors.import_endpoint_post_required(),
    }

    missing_response = index_view.json_error(errors.import_job_not_found())
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (None, missing_response),
    )
    response = index_view._import_step(
        RequestFactory().post(f"/omeroweb_import/import/{job_id}/"),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {"ok": False, "error": errors.import_job_not_found()}

    ready_job = {
        "status": "ready",
        "imported_bytes": 0,
        "total_bytes": 1,
        "messages": [],
    }
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (ready_job, None),
    )
    monkeypatch.setattr(
        index_view,
        "_prepare_ready_job_for_import_start",
        lambda current_job_id, current_job, conn: (current_job, "prep failed"),
    )
    response = index_view._import_step(
        RequestFactory().post(f"/omeroweb_import/import/{job_id}/"),
        job_id,
        conn=object(),
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_importing(),
    }
    assert "prep failed" not in response.content.decode("utf-8")

    started = []
    monkeypatch.setattr(
        index_view,
        "_prepare_ready_job_for_import_start",
        lambda current_job_id, current_job, conn: (current_job, None),
    )
    monkeypatch.setattr(
        index_view,
        "_start_import_thread",
        lambda current_job_id: started.append(current_job_id),
    )
    monkeypatch.setattr(
        index_view,
        "_load_job",
        lambda current_job_id: {
            "status": "importing",
            "imported_bytes": 1,
            "total_bytes": 1,
            "messages": ["started"],
        },
    )
    response = index_view._import_step(
        RequestFactory().post(f"/omeroweb_import/import/{job_id}/"),
        job_id,
        conn=object(),
    )
    assert _payload(response) == {
        "ok": True,
        "done": False,
        "status": "importing",
        "imported_bytes": 1,
        "total_bytes": 1,
        "messages": ["started"],
    }
    assert started == [job_id]

    response = index_view.confirm_import(
        RequestFactory().get("/"), job_id=job_id, conn=object()
    )
    assert _payload(response) == {"ok": False, "error": errors.method_post_required()}

    missing_response = index_view.json_error(errors.upload_job_not_found())
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (None, missing_response),
    )
    response = index_view.confirm_import(
        RequestFactory().post("/"), job_id=job_id, conn=object()
    )
    assert _payload(response) == {"ok": False, "error": errors.upload_job_not_found()}

    idle_job = {"status": "checking"}
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (idle_job, None),
    )
    response = index_view.confirm_import(
        RequestFactory().post("/"), job_id=job_id, conn=object()
    )
    assert _payload(response) == {"ok": True, "status": "checking"}

    confirm_job = {
        "status": "awaiting_confirmation",
        "compatibility_thread_active": True,
        "compatibility_confirmed": False,
    }
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (confirm_job, None),
    )
    monkeypatch.setattr(index_view, "_save_job", lambda job: False)
    response = index_view.confirm_import(
        RequestFactory().post("/"), job_id=job_id, conn=object()
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unable_update_upload_job_state(),
    }

    confirm_job["status"] = "awaiting_confirmation"
    confirm_job["compatibility_thread_active"] = True
    confirm_job["compatibility_confirmed"] = False
    monkeypatch.setattr(index_view, "_save_job", lambda job: True)
    monkeypatch.setattr(
        index_view,
        "_prepare_ready_job_for_import_start",
        lambda current_job_id, current_job, conn: (current_job, "prep failed"),
    )
    response = index_view.confirm_import(
        RequestFactory().post("/"), job_id=job_id, conn=object()
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_importing(),
    }

    response = index_view.prune_upload(
        RequestFactory().get("/"), job_id=job_id, conn=object()
    )
    assert _payload(response) == {"ok": False, "error": errors.method_post_required()}

    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (None, missing_response),
    )
    response = index_view.prune_upload(
        RequestFactory().post("/"), job_id=job_id, conn=object()
    )
    assert _payload(response) == {"ok": False, "error": errors.upload_job_not_found()}

    keep_job = {
        "job_id": job_id,
        "status": "checking",
        "files": [
            {
                "relative_path": "keep/file1.tif",
                "staged_path": "_staged/keep/file1.tif",
                "size": 5,
                "status": "uploaded",
                "compatibility": "compatible",
            },
            {
                "relative_path": "drop/file2.tif",
                "staged_path": "_staged/drop/file2.tif",
                "size": 3,
                "status": "uploaded",
                "compatibility": "incompatible",
            },
            {
                "relative_path": "bad/file3.tif",
                "staged_path": "../escape",
                "size": 1,
                "status": "uploaded",
                "compatibility": "compatible",
            },
        ],
        "incompatible_files": ["drop/file2.tif"],
        "compatibility_status": "incompatible",
        "uploaded_bytes": 9,
        "total_bytes": 9,
    }
    kept_path = upload_root / job_id / "_staged" / "keep" / "file1.tif"
    drop_path = upload_root / job_id / "_staged" / "drop" / "file2.tif"
    kept_path.parent.mkdir(parents=True, exist_ok=True)
    drop_path.parent.mkdir(parents=True, exist_ok=True)
    kept_path.write_bytes(b"keep")
    drop_path.write_bytes(b"drop")

    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (keep_job, None),
    )
    monkeypatch.setattr(
        index_view,
        "_prepare_ready_job_for_import_start",
        lambda current_job_id, current_job, conn: (current_job, None),
    )
    import_started = []
    monkeypatch.setattr(
        index_view,
        "_start_import_thread",
        lambda current_job_id: import_started.append(current_job_id),
    )

    def update_job(current_job_id, updater):
        assert current_job_id == job_id
        return updater(keep_job)

    monkeypatch.setattr(index_view, "_update_job", update_job)
    response = index_view.prune_upload(
        RequestFactory().post(
            "/",
            data=json.dumps({"keep_paths": ["keep/file1.tif", "../escape"]}),
            content_type="application/json",
        ),
        job_id=job_id,
        conn=object(),
    )
    assert _payload(response) == {"ok": True, "status": "ready"}
    assert import_started == [job_id]
    assert kept_path.exists()
    assert not drop_path.exists()
    assert keep_job["total_bytes"] == 5
    assert keep_job["uploaded_bytes"] == 5
    assert keep_job["compatibility_status"] == "compatible"

    monkeypatch.setattr(
        index_view,
        "_prepare_ready_job_for_import_start",
        lambda current_job_id, current_job, conn: (current_job, "prep failed"),
    )
    response = index_view.prune_upload(
        RequestFactory().post(
            "/",
            data=json.dumps({"keep_paths": ["keep/file1.tif"]}),
            content_type="application/json",
        ),
        job_id=job_id,
        conn=object(),
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_importing(),
    }

    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (None, missing_response),
    )
    response = index_view.job_status(
        RequestFactory().get("/"), job_id=job_id, conn=object()
    )
    assert _payload(response) == {"ok": False, "error": errors.upload_job_not_found()}

    status_job = {
        "status": "ready",
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "import_progress_bytes": 0,
        "total_bytes": 1,
        "errors": [],
        "messages": [],
        "compatibility_status": "compatible",
        "compatibility_enabled": True,
        "files": [],
    }
    monkeypatch.setattr(
        index_view,
        "_load_owned_job",
        lambda request, conn, current_job_id, missing_error: (status_job, None),
    )
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_dataset_targets",
        lambda current_job_id, current_job, conn: (current_job, "prep failed"),
    )
    response = index_view.job_status(
        RequestFactory().get("/"), job_id=job_id, conn=object()
    )
    assert response.status_code == 500
    assert _payload(response) == {
        "ok": False,
        "error": errors.unexpected_server_error_importing(),
    }
