"""Regression tests for chunked upload handling."""

from __future__ import annotations

import json
import hashlib
import logging
from pathlib import Path

import django
import pytest
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

from omeroweb_import.strings import errors
from omeroweb_import.views import index_view
from omeroweb_import.views import utils as view_utils


def _test_job_id(suffix: str) -> str:
    """Build a fake job ID at runtime so static scanners do not flag it as a token."""
    return "a" * (32 - len(suffix)) + suffix


def _ensure_dir(path):
    """Handle ensure dir."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return True


def _mark_job_owned(monkeypatch, job):
    """Handle mark job owned."""
    job["username"] = "alice"
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")


def test_upload_files_accepts_chunked_upload_and_marks_file_uploaded(
    tmp_path: Path, monkeypatch
):
    """Verify test upload files accepts chunked upload and behavior."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("b2")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 10,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/folder/big.bin",
                "size": 10,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )

    import_started = []
    prepare_calls = []
    fake_conn = object()

    def fake_apply_upload_updates(current_job_id, updates, upload_errors):
        """Handle fake apply upload updates."""
        assert current_job_id == job_id
        assert upload_errors == []
        assert updates == [{"upload_id": "u1", "status": "uploaded"}]
        job["files"][0]["status"] = "uploaded"
        job["uploaded_bytes"] = 10
        job["status"] = "ready"
        return job

    monkeypatch.setattr(index_view, "_apply_upload_updates", fake_apply_upload_updates)
    monkeypatch.setattr(
        index_view,
        "_start_import_thread",
        import_started.append,
    )
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_for_request_path_import",
        lambda current_job_id, current_job, conn: (
            prepare_calls.append((current_job_id, conn)),
            (current_job, None),
        )[1],
    )

    factory = RequestFactory()

    first_request = factory.post(
        f"/omeroweb_import/upload/{job_id}/",
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
    first_response = index_view._upload_files(first_request, job_id, fake_conn)
    first_payload = json.loads(first_response.content)

    assert first_response.status_code == 200
    assert first_payload["ok"] is True
    assert first_payload["complete"] is False

    staged_target = upload_root / job_id / "_staged/folder/big.bin"
    assert staged_target.read_bytes() == b"hello"
    assert import_started == []

    second_request = factory.post(
        f"/omeroweb_import/upload/{job_id}/",
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
    second_response = index_view._upload_files(second_request, job_id, fake_conn)
    second_payload = json.loads(second_response.content)

    assert second_response.status_code == 200
    assert second_payload["ok"] is True
    assert second_payload["complete"] is True
    assert second_payload["saved"] == ["folder/big.bin"]
    assert second_payload["ready"] is True
    assert staged_target.read_bytes() == b"helloworld"
    assert job["files"][0]["status"] == "uploaded"
    assert import_started == [job_id]
    assert prepare_calls == [(job_id, fake_conn)]


def test_upload_files_accepts_idempotent_final_chunk_retry_with_checksum(
    tmp_path: Path,
    monkeypatch,
):
    """Verify final chunk retry is accepted without mutating completed jobs."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("c3")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 5,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/retry.bin",
                "staged_path": "_staged/folder/retry.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)
    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )
    apply_calls = []
    import_started = []

    def fake_apply_upload_updates(current_job_id, updates, upload_errors):
        """Mark the job as uploaded once."""
        apply_calls.append((current_job_id, updates, upload_errors))
        job["files"][0]["status"] = "uploaded"
        job["uploaded_bytes"] = 5
        job["status"] = "ready"
        return job

    monkeypatch.setattr(index_view, "_apply_upload_updates", fake_apply_upload_updates)
    monkeypatch.setattr(index_view, "_start_import_thread", import_started.append)
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_for_request_path_import",
        lambda current_job_id, current_job, conn: (current_job, None),
    )

    factory = RequestFactory()
    body = b"retry"
    checksum = hashlib.sha256(body).hexdigest()
    request_payload = {
        "upload_mode": "chunked",
        "relative_path": "folder/retry.bin",
        "chunk_start": "0",
        "chunk_end": "5",
        "file_size": "5",
        "is_last_chunk": "1",
        "chunk_sha256": checksum,
    }

    first_response = index_view._upload_files(
        factory.post(
            f"/omeroweb_import/upload/{job_id}/",
            data={**request_payload, "file": SimpleUploadedFile("retry.bin", body)},
        ),
        job_id,
        object(),
    )
    duplicate_response = index_view._upload_files(
        factory.post(
            f"/omeroweb_import/upload/{job_id}/",
            data={**request_payload, "file": SimpleUploadedFile("retry.bin", body)},
        ),
        job_id,
        object(),
    )

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 200
    assert json.loads(duplicate_response.content)["complete"] is True
    assert (upload_root / job_id / "_staged/folder/retry.bin").read_bytes() == body
    assert len(apply_calls) == 1
    assert import_started == [job_id]


def test_upload_files_rejects_chunk_checksum_mismatch(tmp_path: Path, monkeypatch):
    """Verify chunk checksum mismatch is rejected before staging bytes."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("c4")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 5,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/bad.bin",
                "staged_path": "_staged/folder/bad.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)
    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda *_args: pytest.fail("checksum failures must not update the job"),
    )

    response = index_view._upload_files(
        RequestFactory().post(
            f"/omeroweb_import/upload/{job_id}/",
            data={
                "upload_mode": "chunked",
                "relative_path": "folder/bad.bin",
                "chunk_start": "0",
                "chunk_end": "5",
                "file_size": "5",
                "is_last_chunk": "1",
                "chunk_sha256": "0" * 64,
                "file": SimpleUploadedFile("bad.bin", b"fresh"),
            },
        ),
        job_id,
        object(),
    )

    assert response.status_code == 400
    assert json.loads(response.content)["error"] == (
        errors.upload_chunk_metadata_invalid(
            "chunk_sha256 does not match uploaded bytes"
        )
    )
    assert not (upload_root / job_id / "_staged/folder/bad.bin").exists()


def test_upload_files_defers_noncompat_import_until_background_plan_exists(
    tmp_path: Path, monkeypatch
):
    """Verify test upload files defers noncompat import unt behavior."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("ff")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 5,
        "compatibility_enabled": False,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/file.bin",
                "staged_path": "_staged/folder/file.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )

    import_started = []
    helper_calls = []
    fake_conn = object()

    def fake_apply_upload_updates(current_job_id, updates, upload_errors):
        """Handle fake apply upload updates."""
        assert current_job_id == job_id
        assert upload_errors == []
        assert updates == [{"upload_id": "u1", "status": "uploaded"}]
        job["files"][0]["status"] = "uploaded"
        job["uploaded_bytes"] = 5
        job["status"] = "ready"
        return job

    monkeypatch.setattr(index_view, "_apply_upload_updates", fake_apply_upload_updates)
    monkeypatch.setattr(
        index_view,
        "_start_import_thread",
        import_started.append,
    )
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_for_request_path_import",
        lambda current_job_id, current_job, conn: (
            helper_calls.append((current_job_id, conn)),
            ({**current_job, "status": "checking"}, None),
        )[1],
    )

    request = RequestFactory().post(
        f"/omeroweb_import/upload/{job_id}/",
        data={
            "relative_paths": ["folder/file.bin"],
            "files": [SimpleUploadedFile("file.bin", b"hello")],
        },
    )

    response = index_view._upload_files(request, job_id, conn=fake_conn)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert import_started == []
    assert helper_calls == [(job_id, fake_conn)]


def test_upload_files_resets_existing_staged_file_when_chunk_restarts(
    tmp_path: Path, monkeypatch
):
    """Verify test upload files resets existing staged file behavior."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("ba")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "uploaded_bytes": 0,
        "total_bytes": 5,
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/folder/big.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )
    prepare_calls = []
    fake_conn = object()
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: {
            **job,
            "status": "ready",
            "uploaded_bytes": 5,
        },
    )
    monkeypatch.setattr(index_view, "_start_import_thread", lambda current_job_id: None)
    monkeypatch.setattr(
        index_view,
        "_prepare_uploaded_job_for_request_path_import",
        lambda current_job_id, current_job, conn: (
            prepare_calls.append((current_job_id, conn)),
            (current_job, None),
        )[1],
    )

    staged_target = upload_root / job_id / "_staged/folder/big.bin"
    staged_target.parent.mkdir(parents=True, exist_ok=True)
    staged_target.write_bytes(b"stale-data")

    request = RequestFactory().post(
        f"/omeroweb_import/upload/{job_id}/",
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

    response = index_view._upload_files(request, job_id, fake_conn)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert staged_target.read_bytes() == b"fresh"
    assert prepare_calls == [(job_id, fake_conn)]


def test_upload_files_rejects_chunk_offset_mismatch(tmp_path: Path, monkeypatch):
    """Verify test upload files rejects chunk offset mismatch."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("dd")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/folder/big.bin",
                "size": 10,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )

    staged_target = upload_root / job_id / "_staged/folder/big.bin"
    staged_target.parent.mkdir(parents=True, exist_ok=True)
    staged_target.write_bytes(b"abc")

    factory = RequestFactory()
    request = factory.post(
        f"/omeroweb_import/upload/{job_id}/",
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
    assert payload["error"] == errors.upload_chunk_offset_mismatch(
        "folder/big.bin", 3, 5
    )
    assert staged_target.read_bytes() == b"abc"


def test_upload_files_rejects_unsafe_staged_path(tmp_path: Path, monkeypatch):
    """Verify test upload files rejects unsafe staged path."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("f4")
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
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )

    apply_upload_updates_called = []
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda *args, **kwargs: apply_upload_updates_called.append((args, kwargs)),
    )

    factory = RequestFactory()
    request = factory.post(
        f"/omeroweb_import/upload/{job_id}/",
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
    """Verify test upload files chunked save error is sanit behavior."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("9f")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/big.bin",
                "staged_path": "_staged/folder/big.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )

    apply_calls = []

    def fake_apply_upload_updates(current_job_id, updates, upload_errors):
        """Handle fake apply upload updates."""
        apply_calls.append((current_job_id, updates, upload_errors))
        return job

    monkeypatch.setattr(
        index_view,
        "_reset_staged_upload_file",
        lambda root, staged_path: None,
    )
    monkeypatch.setattr(
        index_view,
        "_staged_upload_size",
        lambda root, staged_path: (0, None),
    )
    monkeypatch.setattr(
        index_view,
        "_append_upload_chunks_to_staged_path",
        lambda root, staged_path, upload: (
            None,
            None,
            OSError("sensitive filesystem path"),
        ),
    )
    monkeypatch.setattr(index_view, "_apply_upload_updates", fake_apply_upload_updates)

    request = RequestFactory().post(
        f"/omeroweb_import/upload/{job_id}/",
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


def test_upload_files_wrapper_returns_json_when_internal_upload_raises(
    monkeypatch, caplog
):
    """Verify test upload files wrapper returns JSON when i behavior."""
    request = RequestFactory().post("/omeroweb_import/upload/test-job/")

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")

    def raise_upload_error(request, job_id):
        """Handle raise upload error."""
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
    """Verify test upload files hides oserror details."""
    upload_root = tmp_path / "upload-root"
    job_id = _test_job_id("0f")
    job = {
        "job_id": job_id,
        "status": "uploading",
        "files": [
            {
                "upload_id": "u1",
                "relative_path": "folder/file.bin",
                "staged_path": "_staged/folder/file.bin",
                "size": 5,
                "status": "pending",
                "errors": [],
            }
        ],
    }
    _mark_job_owned(monkeypatch, job)

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_ensure_dir", _ensure_dir)
    monkeypatch.setattr(
        index_view, "_load_job", lambda value: job if value == job_id else None
    )
    monkeypatch.setattr(
        index_view,
        "_apply_upload_updates",
        lambda current_job_id, updates, upload_errors: {"status": "uploading"},
    )

    monkeypatch.setattr(
        index_view,
        "_replace_staged_upload_file",
        lambda root, staged_path, upload: (
            None,
            OSError("permission denied: /tmp/secret-path"),
        ),
    )

    request = RequestFactory().post(
        f"/omeroweb_import/upload/{job_id}/",
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
