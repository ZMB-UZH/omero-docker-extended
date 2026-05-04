from __future__ import annotations

import logging
import subprocess
from types import SimpleNamespace

import pytest

from omeroweb_import.services.omero import import_service


def test_import_service_import_file_supports_optional_import_name(
    tmp_path, monkeypatch
):
    """Verify import service import file supports optional import name.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `CompletedProcess` result.
    """
    sample_path = tmp_path / "sample.czi"
    sample_path.write_text("payload", encoding="utf-8")
    captured = {}

    def fake_run(cmd, timeout=None):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `cmd`, `timeout` timeout seconds. Output: `CompletedProcess` result.
        """
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr(import_service, "_run_omero_cli", fake_run)

    ok, stdout, stderr = import_service._import_file(
        None,
        "session-key",
        "omeroserver",
        4064,
        sample_path,
        dataset_id=17,
        import_name="Experiment 17",
    )

    assert ok is True
    assert stdout == "ok"
    assert stderr == ""
    assert captured["cmd"][-5:] == [
        "-d",
        "17",
        "-n",
        "Experiment 17",
        str(sample_path),
    ]
    assert captured["timeout"] is not None


def test_open_service_connection_reports_connect_exceptions_without_last_error(
    monkeypatch, caplog
):
    """Confirm open service connection reports connect exceptions without last error exposes the expected failure.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `caplog` pytest log capture
    fixture. Output: None after assertions pass. Raises: RuntimeError when validation or
    external operations fail.
    """

    class _Conn:
        """Test double for conn behavior in this module."""

        def __init__(self):
            """Create `_Conn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection for `_Conn`.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("connect failed")

        @staticmethod
        def getLastError():
            """Return `_Conn`'s fake last-error text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("last error unavailable")

        @staticmethod
        def close():
            """Close `_Conn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    conn = _Conn()
    monkeypatch.setattr(
        import_service,
        "_get_job_service_credentials",
        lambda: ("job-service", "test-password", "", True),
    )
    monkeypatch.setattr(import_service, "BlitzGateway", lambda *args, **kwargs: conn)

    with caplog.at_level(logging.DEBUG, logger=import_service.logger.name):
        assert import_service._open_service_connection("omeroserver", 4064) is None

    assert "has_last_error=False" in caplog.text
    assert "Suppressed non-fatal exception in import_service.py" in caplog.text


def test_open_service_connection_requires_service_password(monkeypatch, caplog):
    """Check that open service connection requires service password keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`, `caplog`. Output: fails on regressions in open service connection requires service password.
    """
    monkeypatch.setattr(
        import_service,
        "_get_job_service_credentials",
        lambda: ("job-service", "", "", True),
    )

    with caplog.at_level(logging.ERROR, logger=import_service.logger.name):
        assert import_service._open_service_connection("omeroserver", 4064) is None

    assert "job-service authentication missing" in caplog.text
    assert import_service.JOB_SERVICE_AUTH_ENV in caplog.text


def test_open_service_connection_suppresses_close_failure_after_false_connect(
    monkeypatch, caplog
):
    """Verify open service connection suppresses close failure after false connect.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `caplog` pytest log capture
    fixture. Output: `bool`. Raises: RuntimeError when validation or external operations
    fail.
    """

    class _Conn:
        """Test double for conn behavior in this module."""

        def __init__(self):
            """Create `_Conn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection for `_Conn`.

            Inputs: none. Output: bool.
            """
            return False

        @staticmethod
        def getLastError():
            """Return `_Conn`'s fake last-error text.

            Inputs: none. Output: 'gateway refused connection'.
            """
            return "gateway refused connection"

        @staticmethod
        def close():
            """Close `_Conn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    conn = _Conn()
    monkeypatch.setattr(
        import_service,
        "_get_job_service_credentials",
        lambda: ("job-service", "test-password", "", True),
    )
    monkeypatch.setattr(import_service, "BlitzGateway", lambda *args, **kwargs: conn)

    with caplog.at_level(logging.DEBUG, logger=import_service.logger.name):
        assert import_service._open_service_connection("omeroserver", 4064) is None

    assert "has_last_error=True" in caplog.text
    assert "Suppressed non-fatal exception in import_service.py" in caplog.text


def test_open_service_connection_logs_group_context_failures_but_keeps_connection(
    monkeypatch, caplog
):
    """Check that open service connection logs group context failures but keeps connection remains stable.

    Inputs: pytest provides `monkeypatch`, `caplog`. Output: fails on regressions in open service connection logs group context failures but keeps connection.
    """

    class _Conn:
        """Test double for conn behavior in this module."""

        def __init__(self):
            """Create `_Conn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(
                setOmeroGroup=lambda value: (_ for _ in ()).throw(
                    RuntimeError("group context unavailable")
                )
            )

        @staticmethod
        def connect():
            """Open the connection for `_Conn`.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def close():
            """Close `_Conn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    conn = _Conn()
    monkeypatch.setattr(
        import_service,
        "_get_job_service_credentials",
        lambda: ("job-service", "test-password", "", True),
    )
    monkeypatch.setattr(import_service, "BlitzGateway", lambda *args, **kwargs: conn)

    with caplog.at_level(logging.WARNING, logger=import_service.logger.name):
        opened = import_service._open_service_connection(
            "omeroserver", 4064, group_id=7
        )

    assert opened is conn
    assert "Failed to set job-service group context to 7" in caplog.text


def test_open_service_connection_reraises_unexpected_group_id_failures(
    monkeypatch, caplog
):
    """Verify open service connection reraises unexpected group ID failures.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `caplog` pytest log capture
    fixture. Output: `int`. Raises: RuntimeError, TypeError when validation or external
    """

    class _BadGroupId:
        """Test double for bad group identifier behavior in this module."""

        def __init__(self, *, fail=True):
            """Create `_BadGroupId` with its default state.

            Inputs: `fail`. Output: None.
            """
            self.fail = fail

        def __int__(self):
            """Return the integer representation.

            Inputs: none. Output: `int`. Raises: TypeError for the exercised failure path.
            """
            if self.fail:
                raise TypeError("bad group id")
            return 7

    class _Conn:
        """Test double for conn behavior in this module."""

        def __init__(self):
            """Create `_Conn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection for `_Conn`.

            Inputs: none. Output: bool.
            """
            return True

        @staticmethod
        def close():
            """Close `_Conn`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    conn = _Conn()
    monkeypatch.setattr(
        import_service,
        "_get_job_service_credentials",
        lambda: ("job-service", "test-password", "", False),
    )
    monkeypatch.setattr(import_service, "BlitzGateway", lambda *args, **kwargs: conn)

    with (
        caplog.at_level(logging.DEBUG, logger=import_service.logger.name),
        pytest.raises(TypeError, match="bad group id"),
    ):
        import_service._open_service_connection(
            "omeroserver", 4064, group_id=_BadGroupId(fail=True)
        )

    assert "Suppressed non-fatal exception in import_service.py" in caplog.text
