"""Regression tests for path handling and sensitive logging hardening."""

from __future__ import annotations

import json
import logging

from omeroweb_import.services.omero import import_service
from omeroweb_import.views import core_functions


def test_ensure_dir_rejects_unmanaged_path(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    upload_root.mkdir()
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    outside = tmp_path / "outside"
    assert core_functions._ensure_dir(outside) is False
    assert not outside.exists()


def test_ensure_dir_accepts_managed_upload_subdirectory(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    upload_root.mkdir()
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    managed_dir = upload_root / "b0aa2d2266f8466c8eea6b26477693b2"
    assert core_functions._ensure_dir(managed_dir) is True
    assert managed_dir.is_dir()


def test_job_paths_are_canonical_and_anchored_under_jobs_root(tmp_path, monkeypatch):
    jobs_root = tmp_path / "jobs-root"
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    job_id = "B0AA2D2266F8466C8EEA6B26477693B2"
    assert (
        core_functions._job_path(job_id)
        == jobs_root.resolve() / "b0aa2d2266f8466c8eea6b26477693b2.json"
    )
    assert (
        core_functions._job_lock_path(job_id)
        == jobs_root.resolve() / ".b0aa2d2266f8466c8eea6b26477693b2.lock"
    )


def test_load_job_reads_from_canonical_jobs_path(tmp_path, monkeypatch):
    jobs_root = tmp_path / "jobs-root"
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    job_id = "b0aa2d2266f8466c8eea6b26477693b2"
    job_path = jobs_root / f"{job_id}.json"
    job_path.write_text(
        json.dumps({"job_id": job_id, "status": "uploading"}), encoding="utf-8"
    )

    loaded = core_functions._load_job(job_id.upper())

    assert loaded == {"job_id": job_id, "status": "uploading"}


def test_open_service_connection_redacts_password_when_connect_raises(
    monkeypatch, caplog
):
    for module in (import_service, core_functions):
        created = []

        class FakeConn:
            def __init__(self, *_args, **_kwargs):
                self.closed = False
                self.SERVICE_OPTS = type(
                    "ServiceOpts", (), {"setOmeroGroup": lambda self, value: None}
                )()

            def connect(self):
                raise RuntimeError("authentication failed for password super-secret")

            def getLastError(self):
                return "password=super-secret"

            def close(self):
                self.closed = True

        def fake_gateway(*args, **kwargs):
            conn = FakeConn(*args, **kwargs)
            created.append(conn)
            return conn

        monkeypatch.setattr(
            module,
            "_get_job_service_credentials",
            lambda: ("svc-user", "svc-pass", "", True),
        )
        monkeypatch.setattr(module, "BlitzGateway", fake_gateway)

        with caplog.at_level(logging.ERROR, logger=module.logger.name):
            conn = module._open_service_connection("omero.example.org", 4064)

        assert conn is None
        assert created[0].closed is True
        assert "super-secret" not in caplog.text
        assert "svc-pass" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_last_error=True" in caplog.text
        caplog.clear()


def test_open_service_connection_redacts_password_when_connect_returns_false(
    monkeypatch, caplog
):
    for module in (import_service, core_functions):
        created = []

        class FakeConn:
            def __init__(self, *_args, **_kwargs):
                self.closed = False
                self.SERVICE_OPTS = type(
                    "ServiceOpts", (), {"setOmeroGroup": lambda self, value: None}
                )()

            def connect(self):
                return False

            def getLastError(self):
                return "password=super-secret"

            def close(self):
                self.closed = True

        def fake_gateway(*args, **kwargs):
            conn = FakeConn(*args, **kwargs)
            created.append(conn)
            return conn

        monkeypatch.setattr(
            module,
            "_get_job_service_credentials",
            lambda: ("svc-user", "svc-pass", "", True),
        )
        monkeypatch.setattr(module, "BlitzGateway", fake_gateway)

        with caplog.at_level(logging.ERROR, logger=module.logger.name):
            conn = module._open_service_connection("omero.example.org", 4064)

        assert conn is None
        assert created[0].closed is True
        assert "super-secret" not in caplog.text
        assert "svc-pass" not in caplog.text
        assert "has_last_error=True" in caplog.text
        caplog.clear()
