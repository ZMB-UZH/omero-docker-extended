"""Regression tests for path handling and sensitive logging hardening."""

from __future__ import annotations

import json
import logging

from omeroweb_import.services.omero import import_service
from omeroweb_import.views import core_functions


def _test_job_id(suffix: str) -> str:
    """Verify job ID.

    Inputs: `suffix`. Output: `str`.
    """
    return "a" * (32 - len(suffix)) + suffix


def test_ensure_dir_rejects_unmanaged_path(tmp_path, monkeypatch):
    """Verify ensure directory rejects unmanaged path.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
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
    """Verify ensure directory accepts managed upload subdirectory.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    upload_root.mkdir()
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    managed_dir = upload_root / _test_job_id("b2")
    assert core_functions._ensure_dir(managed_dir) is True
    assert managed_dir.is_dir()


def test_job_paths_are_canonical_and_anchored_under_jobs_root(tmp_path, monkeypatch):
    """Verify job paths are canonical and anchored under jobs root.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    jobs_root = tmp_path / "jobs-root"
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    job_id = _test_job_id("b2").upper()
    assert (
        core_functions._job_path(job_id)
        == jobs_root.resolve() / f"{_test_job_id('b2')}.json"
    )
    assert (
        core_functions._job_lock_path(job_id)
        == jobs_root.resolve() / f".{_test_job_id('b2')}.lock"
    )


def test_load_job_reads_from_canonical_jobs_path(tmp_path, monkeypatch):
    """Verify load job reads from canonical jobs path.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    jobs_root = tmp_path / "jobs-root"
    jobs_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    job_id = _test_job_id("b2")
    job_path = jobs_root / f"{job_id}.json"
    job_path.write_text(
        json.dumps({"job_id": job_id, "status": "uploading"}), encoding="utf-8"
    )

    loaded = core_functions._load_job(job_id.upper())

    assert loaded == {"job_id": job_id, "status": "uploading"}


def test_open_service_connection_redacts_password_when_connect_raises(
    monkeypatch, caplog
):
    """Verify open service connection redacts password when connect raises.

    Inputs: `monkeypatch`, `caplog`. Output: computed value. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    for module in (import_service, core_functions):
        created = []

        class FakeConn:
            """Test double for fake conn."""

            def __init__(self, *_args, **_kwargs):
                """Initialize the instance.

                Inputs: `*_args`, `**_kwargs`. Output: None.
                """
                self.closed = False
                self.SERVICE_OPTS = type(
                    "ServiceOpts", (), {"setOmeroGroup": lambda self, value: None}
                )()

            @staticmethod
            def connect():
                """Open the connection.

                Inputs: none. Output: None. Raises on invalid or unavailable state.
                """
                raise RuntimeError("authentication failed for password super-secret")

            @staticmethod
            def getLastError():
                """Return Last Error.

                Inputs: none. Output: 'password=super-secret'.
                """
                return "password=super-secret"

            def close(self):
                """Close the resource.

                Inputs: none. Output: None.
                """
                self.closed = True

        def fake_gateway(*args, _created=created, _conn_factory=FakeConn, **kwargs):
            """Fake gateway.

            Inputs: `_created`, `_conn_factory`, `*args`, `**kwargs`. Output: `conn`.
            """
            conn = _conn_factory(*args, **kwargs)
            _created.append(conn)
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
    """Verify open service connection redacts password when connect returns false.

    Inputs: `monkeypatch`, `caplog`. Output: computed value.
    """
    for module in (import_service, core_functions):
        created = []

        class FakeConn:
            """Test double for fake conn."""

            def __init__(self, *_args, **_kwargs):
                """Initialize the instance.

                Inputs: `*_args`, `**_kwargs`. Output: None.
                """
                self.closed = False
                self.SERVICE_OPTS = type(
                    "ServiceOpts", (), {"setOmeroGroup": lambda self, value: None}
                )()

            @staticmethod
            def connect():
                """Open the connection.

                Inputs: none. Output: bool.
                """
                return False

            @staticmethod
            def getLastError():
                """Return Last Error.

                Inputs: none. Output: 'password=super-secret'.
                """
                return "password=super-secret"

            def close(self):
                """Close the resource.

                Inputs: none. Output: None.
                """
                self.closed = True

        def fake_gateway(*args, _created=created, _conn_factory=FakeConn, **kwargs):
            """Fake gateway.

            Inputs: `_created`, `_conn_factory`, `*args`, `**kwargs`. Output: `conn`.
            """
            conn = _conn_factory(*args, **kwargs)
            _created.append(conn)
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


def _assert_service_connection_falls_back_to_job_group(module, monkeypatch):
    """Assert service connection falls back to job group.

    Inputs: `module`, `monkeypatch`. Output: bool or None.
    """
    group_calls = []

    class ServiceOpts:
        """Represent service opts."""

        @staticmethod
        def setOmeroGroup(value):
            """Set OMERO Group.

            Inputs: `value`. Output: None.
            """
            group_calls.append(value)

    class FakeConn:
        """Test double for fake conn."""

        def __init__(self, *_args, **_kwargs):
            """Initialize the instance.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            self.SERVICE_OPTS = ServiceOpts()

        @staticmethod
        def connect():
            """Open the connection.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None.
            """
            return None

    monkeypatch.setattr(
        module,
        "_get_job_service_credentials",
        lambda: ("svc-user", "svc-pass", "not-a-number", True),
    )
    monkeypatch.setattr(module, "BlitzGateway", FakeConn)

    conn = module._open_service_connection("omero.example.org", 4064, group_id=7)

    assert conn is not None
    assert group_calls == ["7"]


def test_open_service_connection_falls_back_to_job_group_when_override_is_invalid(
    monkeypatch,
):
    """Verify open service connection falls back to job group when override is invalid.

    Inputs: `monkeypatch`. Output: None.
    """
    for module in (import_service, core_functions):
        _assert_service_connection_falls_back_to_job_group(module, monkeypatch)
