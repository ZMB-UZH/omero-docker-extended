"""Regression tests for chunked upload handling."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import django
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key",
        DEFAULT_CHARSET="utf-8",
        ALLOWED_HOSTS=["testserver", "localhost"],
        USE_I18N=False,
        USE_TZ=True,
        INSTALLED_APPS=[],
    )
    django.setup()

from omeroweb_upload.strings import errors
from omeroweb_upload.views import index_view
from omeroweb_upload.views import utils as view_utils


def _ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return True


def _mark_job_owned(monkeypatch, job):
    job["username"] = "alice"
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")


def test_upload_files_accepts_chunked_upload_and_marks_file_uploaded(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = "b0aa2d2266f8466c8eea6b26477693b2"
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 10,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/u1/big.bin",
                "size": 10,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(index_view, "_load_job", lambda value: job if value == job_id else None)
    monkeypatch.setattr(index_view, "_should_start_compatibility_check", lambda updated_job: False)

    import_started = []

    def fake_apply_upload_updates(current_job_id, updates, upload_errors):
        assert current_job_id == job_id
        assert upload_errors == []
        assert updates == [{"upload_id": "u1", "status": "uploaded"}]
        job["files"][0]["status"] = "uploaded"
        job["uploaded_bytes"] = 10
        job["status"] = "ready"
        return job

    monkeypatch.setattr(index_view, "_apply_upload_updates", fake_apply_upload_updates)
    monkeypatch.setattr(index_view, "_start_import_thread", lambda current_job_id: import_started.append(current_job_id))

    factory = RequestFactory()

    first_request = factory.post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "upload_mode": "chunked",
            "relative_path": "folder/big.bin",
            "chunk_start": "0",
            "chunk_end": "5",
            "file_size": "10",
            "is_last_chunk": "0",
            "file": SimpleUploadedFile("big.bin", b"hello"),
        },
    )
    first_response = index_view._upload_files(first_request, job_id, None)
    first_payload = json.loads(first_response.content)

    assert first_response.status_code == 200
    assert first_payload["ok"] is True
    assert first_payload["complete"] is False

    staged_target = upload_root / job_id / "_staged/u1/big.bin"
    assert staged_target.read_bytes() == b"hello"
    assert import_started == []

    second_request = factory.post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "upload_mode": "chunked",
            "relative_path": "folder/big.bin",
            "chunk_start": "5",
            "chunk_end": "10",
            "file_size": "10",
            "is_last_chunk": "1",
            "file": SimpleUploadedFile("big.bin", b"world"),
        },
    )
    second_response = index_view._upload_files(second_request, job_id, None)
    second_payload = json.loads(second_response.content)

    assert second_response.status_code == 200
    assert second_payload["ok"] is True
    assert second_payload["complete"] is True
    assert second_payload["saved"] == ["folder/big.bin"]
    assert second_payload["ready"] is True
    assert staged_target.read_bytes() == b"helloworld"
    assert job["files"][0]["status"] == "uploaded"
    assert import_started == [job_id]


def test_upload_files_resets_existing_staged_file_when_chunk_restarts(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = "c3c9bf8e3f0846d3b719f7874707dbba"
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 5,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/u1/big.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(index_view, "_load_job", lambda value: job if value == job_id else None)
    monkeypatch.setattr(index_view, "_should_start_compatibility_check", lambda updated_job: False)
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: {**job, "status": "ready", "uploaded_bytes": 5},
    )
    monkeypatch.setattr(index_view, "_start_import_thread", lambda current_job_id: None)

    staged_target = upload_root / job_id / "_staged/u1/big.bin"
    staged_target.parent.mkdir(parents=True, exist_ok=True)
    staged_target.write_bytes(b"stale-data")

    request = RequestFactory().post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "upload_mode": "chunked",
            "relative_path": "folder/big.bin",
            "chunk_start": "0",
            "chunk_end": "5",
            "file_size": "5",
            "is_last_chunk": "1",
            "file": SimpleUploadedFile("big.bin", b"fresh"),
        },
    )

    response = index_view._upload_files(request, job_id, None)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert staged_target.read_bytes() == b"fresh"


def test_upload_files_rejects_chunk_offset_mismatch(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = "e8706ee910b147a8b428d44ced0d68dd"
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/u1/big.bin",
                "size": 10,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(index_view, "_load_job", lambda value: job if value == job_id else None)

    staged_target = upload_root / job_id / "_staged/u1/big.bin"
    staged_target.parent.mkdir(parents=True, exist_ok=True)
    staged_target.write_bytes(b"abc")

    factory = RequestFactory()
    request = factory.post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "upload_mode": "chunked",
            "relative_path": "folder/big.bin",
            "chunk_start": "5",
            "chunk_end": "8",
            "file_size": "10",
            "is_last_chunk": "0",
            "file": SimpleUploadedFile("big.bin", b"def"),
        },
    )

    response = index_view._upload_files(request, job_id, None)
    payload = json.loads(response.content)

    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == errors.upload_chunk_offset_mismatch("folder/big.bin", 3, 5)
    assert staged_target.read_bytes() == b"abc"


def test_upload_files_rejects_unsafe_staged_path(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = "6c5e44cf71ab4836962b0fe2665783f4"
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "../escape.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(index_view, "_load_job", lambda value: job if value == job_id else None)

    apply_upload_updates_called = []
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda *args, **kwargs: apply_upload_updates_called.append((args, kwargs)),
    )

    factory = RequestFactory()
    request = factory.post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "upload_mode": "chunked",
            "relative_path": "folder/big.bin",
            "chunk_start": "0",
            "chunk_end": "5",
            "file_size": "5",
            "is_last_chunk": "1",
            "file": SimpleUploadedFile("big.bin", b"hello"),
        },
    )

    response = index_view._upload_files(request, job_id, None)
    payload = json.loads(response.content)

    assert response.status_code == 400
    assert payload["ok"] is False
    assert "Invalid" in payload["error"]
    assert apply_upload_updates_called == []
    assert not (tmp_path / "escape.bin").exists()
    assert not (upload_root / job_id / "folder/big.bin").exists()


def test_upload_files_chunked_save_error_is_sanitized(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = "6f8b38d693784615be4d07b39841459f"
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/u1/big.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(index_view, "_load_job", lambda value: job if value == job_id else None)

    class _DummyParent:
        def mkdir(self, parents=True, exist_ok=True):
            return None

    class _DummyTarget:
        parent = _DummyParent()

        def exists(self):
            return False

        def open(self, *_args, **_kwargs):
            raise OSError("sensitive filesystem path")

    apply_calls = []

    def fake_apply_upload_updates(current_job_id, updates, upload_errors):
        apply_calls.append((current_job_id, updates, upload_errors))
        return job

    monkeypatch.setattr(
        index_view,
        "_resolve_staged_target_path",
        lambda root, staged_path: (_DummyTarget(), None),
    )
    monkeypatch.setattr(index_view, "_apply_upload_updates", fake_apply_upload_updates)

    request = RequestFactory().post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "upload_mode": "chunked",
            "relative_path": "folder/big.bin",
            "chunk_start": "0",
            "chunk_end": "5",
            "file_size": "5",
            "is_last_chunk": "1",
            "file": SimpleUploadedFile("big.bin", b"hello"),
        },
    )

    response = index_view._upload_files(request, job_id, None)
    payload = json.loads(response.content)

    assert response.status_code == 500
    assert payload["error"] == errors.unexpected_server_error_uploading_files()
    assert "sensitive filesystem path" not in payload["error"]
    assert apply_calls[0][2] == [errors.unexpected_server_error_uploading_files()]


def test_upload_files_wrapper_returns_json_when_internal_upload_raises(monkeypatch, caplog):
    request = RequestFactory().post("/omeroweb_upload/upload/test-job/")

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")

    def raise_upload_error(request, job_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(index_view, "_upload_files", raise_upload_error)

    with caplog.at_level(logging.ERROR, logger=index_view.logger.name):
        response = index_view.upload_files(request, job_id="test\njob")
    payload = json.loads(response.content)

    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error"] == errors.unexpected_server_error_uploading_files()
    assert "Unhandled error while uploading files for job test\\\\njob." in caplog.text
    assert "job test\njob" not in caplog.text


def test_upload_files_hides_oserror_details(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    job_id = "f28cb8e9da774d4688cc38b208de160f"
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/file.bin",
                "staged_path": "_staged/u1/file.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(index_view, "_load_job", lambda value: job if value == job_id else None)
    monkeypatch.setattr(index_view, "_apply_upload_updates", lambda current_job_id, updates, upload_errors: {"status": "uploading"})

    class BrokenTarget:
        def __init__(self, path: Path):
            self.parent = path.parent

        def open(self, *_args, **_kwargs):
            raise OSError("permission denied: /tmp/secret-path")

    monkeypatch.setattr(
        index_view,
        "_resolve_staged_target_path",
        lambda root, staged_path: (BrokenTarget(root / staged_path), None),
    )

    request = RequestFactory().post(
        f"/omeroweb_upload/upload/{job_id}/",
        data={
            "relative_paths": ["folder/file.bin"],
            "files": [SimpleUploadedFile("file.bin", b"hello")],
        },
    )

    response = index_view._upload_files(request, job_id, None)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error"] == errors.unexpected_server_error_uploading_files()
    assert "secret-path" not in payload["error"]
