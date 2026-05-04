from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

import pytest


TEST_RUNTIME_ROOT = Path(__file__).resolve().parent / "_runtime"
TEST_SERVICE_AUTH_VALUE = "job-auth-fixture"


def _install_omero_stubs() -> None:
    """Install OMERO stubs.

    Inputs: none. Output: None.
    """
    omero_module = types.ModuleType("omero")
    omero_module.ClientError = type("ClientError", (Exception,), {})
    omero_module.SecurityViolation = type("SecurityViolation", (Exception,), {})
    omero_module.NoProcessorAvailable = type("NoProcessorAvailable", (Exception,), {})
    omero_module.client = lambda host, port: None

    omero_gateway = types.ModuleType("omero.gateway")
    omero_gateway.BlitzGateway = type("BlitzGateway", (), {})

    omero_rtypes = types.ModuleType("omero.rtypes")
    omero_rtypes.rint = lambda value: value

    sys.modules["omero"] = omero_module
    sys.modules["omero.gateway"] = omero_gateway
    sys.modules["omero.rtypes"] = omero_rtypes


def _install_celery_stubs() -> None:
    """Install celery stubs.

    Inputs: none. Output: None.
    """
    celery_module = types.ModuleType("celery")

    class _DummyCelery:
        """Test double for dummy celery."""

        def __init__(self, *_args, **_kwargs):
            """Initialize the instance.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            self.conf = types.SimpleNamespace(update=lambda **_kwargs: None)

        @staticmethod
        def autodiscover_tasks(*_args, **_kwargs):
            """Autodiscover tasks.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def task(*args, **kwargs):
            """Task.

            Inputs: `*args`, `**kwargs`. Output: computed value.
            """

            def _decorator(fn):
                """Decorator.

                Inputs: `fn`. Output: `fn`.
                """
                return fn

            return _decorator

    celery_module.Celery = _DummyCelery
    celery_module.states = types.SimpleNamespace(
        FAILURE="FAILURE",
        PENDING="PENDING",
        RECEIVED="RECEIVED",
        STARTED="STARTED",
        SUCCESS="SUCCESS",
        REVOKED="REVOKED",
        IGNORED="IGNORED",
    )
    sys.modules["celery"] = celery_module


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required environment.

    Inputs: `monkeypatch`. Output: None.
    """
    values = {
        "OMERO_IMS_USE_CELERY": "true",
        "OMERO_IMS_USE_JOB_SERVICE_SESSION": "true",
        "OMERO_IMS_CELERY_BROKER_URL": "redis://example/0",
        "OMERO_IMS_CELERY_BACKEND_URL": "redis://example/1",
        "OMERO_IMS_CELERY_QUEUE": "imaris",
        "OMERO_IMS_CELERY_RESULT_EXPIRES": "3600",
        "OMERO_IMS_CELERY_TIME_LIMIT": "3600",
        "OMERO_IMS_CELERY_MAX_RETRIES": "3",
        "OMERO_IMS_CELERY_PREFETCH": "1",
        "OMERO_IMS_EXPORT_TIMEOUT": "10",
        "OMERO_IMS_EXPORT_POLL_INTERVAL": "0.1",
        "OMERO_IMS_SCRIPT_NAME": "IMS_Export.py",
        "OMERO_IMS_EXPORT_DIR": str(TEST_RUNTIME_ROOT / "export"),
        "OMERO_IMS_SCRIPT_START_TIMEOUT": "1",
        "OMERO_IMS_SCRIPT_START_RETRY_INTERVAL": "0.1",
        "OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL": "10",
        "OMERO_TMP_PATH": str(TEST_RUNTIME_ROOT / "tmp"),
        "OMERO_JOB_SERVICE_USER": "job-service",
        "OMERO_JOB_SERVICE_PASSWORD": TEST_SERVICE_AUTH_VALUE,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _import_tasks(monkeypatch: pytest.MonkeyPatch):
    """Import tasks.

    Inputs: `monkeypatch`. Output: `tasks`.
    """
    _set_required_env(monkeypatch)
    _install_omero_stubs()
    _install_celery_stubs()
    for module_name in [
        "omeroweb_imaris_connector.config",
        "omeroweb_imaris_connector.celery_app",
        "omeroweb_imaris_connector.imaris_service",
        "omeroweb_imaris_connector.tasks",
    ]:
        sys.modules.pop(module_name, None)
    from omeroweb_imaris_connector import tasks

    return tasks


def test_cli_resolution_output_parsing_and_connection_session_key(
    monkeypatch, tmp_path
):
    """Verify cli resolution output parsing and connection session key.

    Inputs: `monkeypatch`, `tmp_path`. Output: None.
    """
    tasks = _import_tasks(monkeypatch)
    cli_path = tmp_path / "omero"
    export_path = tmp_path / f"{tmp_path.name}.ims"
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        tasks.os.path, "exists", lambda path: str(path) == str(cli_path)
    )
    monkeypatch.setattr(tasks.shutil, "which", lambda name: str(cli_path))

    assert tasks._resolve_omero_cli() == str(cli_path)
    assert tasks._extract_cli_outputs(
        "\n".join(
            [
                "* Message = done",
                f"* Export_Path = {export_path}",
                "* Ignored = nope",
                "* File_Annotation_Id = 44",
            ]
        )
    ) == {
        "Message": "done",
        "Export_Path": str(export_path),
        "File_Annotation_Id": "44",
    }
    assert (
        tasks._get_connection_session_key(
            types.SimpleNamespace(getSessionId=lambda: "session-1")
        )
        == "session-1"
    )
    assert (
        tasks._get_connection_session_key(
            types.SimpleNamespace(
                getSessionId=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                c=types.SimpleNamespace(getSessionId=lambda: "session-2"),
            )
        )
        == "session-2"
    )


def test_run_script_via_omero_cli_covers_success_and_failure_paths(
    monkeypatch, tmp_path, caplog
):
    """Verify run script via OMERO cli covers success and failure paths.

    Inputs: `monkeypatch`, `tmp_path`, `caplog`. Output: `types.SimpleNamespace` result.
    """
    tasks = _import_tasks(monkeypatch)
    cli_path = tmp_path / "omero"
    export_path = tmp_path / f"{tmp_path.name}.ims"
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(tasks, "_resolve_omero_cli", lambda: str(cli_path))

    captured = {}

    def successful_run(cmd, *, timeout, check, env, **_kwargs):
        """Successful run.

        Inputs: `cmd`, `timeout`, `check`, `env`, `**_kwargs`. Output:
        `types.SimpleNamespace` result.
        """
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        captured["env"] = {
            "HOME": env["HOME"],
            "OMERO_USERDIR": env["OMERO_USERDIR"],
            "OMERO_SESSIONDIR": env["OMERO_SESSIONDIR"],
            "OMERO_TMPDIR": env["OMERO_TMPDIR"],
        }
        return types.SimpleNamespace(
            returncode=0,
            stdout=f"* Export_Path = {export_path}\n* Export_Name = demo.ims",
            stderr="",
        )

    monkeypatch.setattr(tasks.subprocess, "run", successful_run)
    outputs = tasks._run_script_via_omero_cli(
        script_id=7,
        image_id=11,
        host="omeroserver",
        port=4064,
        session_key="session-key",
    )
    assert outputs["Export_Path"] == str(export_path)
    assert captured["cmd"][:5] == [str(cli_path), "-q", "script", "launch", "7"]
    assert captured["timeout"] == tasks.EXPORT_TIMEOUT + 120
    assert captured["env"]["HOME"] == captured["env"]["OMERO_USERDIR"]
    assert Path(captured["env"]["OMERO_USERDIR"]).is_relative_to(
        TEST_RUNTIME_ROOT / "tmp"
    )

    with pytest.raises(RuntimeError, match="live OMERO session key"):
        tasks._run_script_via_omero_cli(7, 11, "omeroserver", 4064, session_key=None)

    monkeypatch.setattr(
        tasks.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="backend failed",
        ),
    )
    with (
        caplog.at_level(logging.ERROR, logger=tasks.logger.name),
        pytest.raises(RuntimeError, match="CLI launch failed"),
    ):
        tasks._run_script_via_omero_cli(7, 11, "omeroserver", 4064, "session-key")
    assert "backend failed" not in caplog.text
    assert "stderr_lines=1" in caplog.text

    monkeypatch.setattr(
        tasks.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout="* Message = Could not get original file path",
            stderr="",
        ),
    )
    with pytest.raises(tasks.IMSExportTaskError, match="no export path") as exc_info:
        tasks._run_script_via_omero_cli(7, 11, "omeroserver", 4064, "session-key")
    assert exc_info.value.public_message == "Could not get original file path"

    monkeypatch.setattr(
        tasks.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout="* Message = done",
            stderr="",
        ),
    )
    with pytest.raises(tasks.IMSExportTaskError, match="no export path") as exc_info:
        tasks._run_script_via_omero_cli(7, 11, "omeroserver", 4064, "session-key")
    assert exc_info.value.public_message is None


def test_session_and_job_service_connections_cover_success_and_validation(monkeypatch):
    """Verify session and job service connections cover success and validation.

    Inputs: `monkeypatch`. Output: computed value.
    """
    tasks = _import_tasks(monkeypatch)
    detach_calls = []
    join_calls = []

    class DummyClient:
        """Test double for dummy client."""

        @staticmethod
        def joinSession(session_key):
            """Join session.

            Inputs: `session_key`. Output: `types.SimpleNamespace` result.
            """
            join_calls.append(session_key)
            return types.SimpleNamespace(
                detachOnDestroy=lambda: detach_calls.append(True)
            )

    class DummyGateway:
        """Test double for dummy gateway."""

        def __init__(self, *args, **kwargs):
            """Initialize the instance.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.kwargs = kwargs
            self.connected = kwargs.get("host") == "omeroserver"
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=lambda value: setattr(self, "group", value)
            )

        def connect(self):
            """Open the connection.

            Inputs: none. Output: `self.connected`.
            """
            return self.connected

    monkeypatch.setattr(
        tasks.omero,
        "client",
        lambda host, port: DummyClient(),
        raising=False,
    )
    monkeypatch.setattr(tasks, "BlitzGateway", DummyGateway)

    conn = tasks._open_session_connection("session-1", "omeroserver", 4064)
    assert join_calls == ["session-1"]
    assert detach_calls == [True]
    assert conn.group == "-1"

    with pytest.raises(RuntimeError, match="Invalid port value"):
        tasks._open_session_connection("session-1", "omeroserver", "bad-port")

    monkeypatch.setattr(
        tasks,
        "get_job_service_credentials",
        lambda: ("job-service", TEST_SERVICE_AUTH_VALUE),
    )
    conn = tasks._open_job_service_connection("omeroserver", 4064, secure=True)
    assert conn.group == "-1"

    monkeypatch.setattr(
        tasks,
        "get_job_service_credentials",
        lambda: ("job-service", ""),
    )
    with pytest.raises(RuntimeError, match="password is required"):
        tasks._open_job_service_connection("omeroserver", 4064)


def test_run_ims_export_task_updates_failure_meta_and_closes_connections(
    monkeypatch, tmp_path
):
    """Verify run IMS export task updates failure meta and closes connections.

    Inputs: `monkeypatch`, `tmp_path`. Output: None.
    """
    tasks = _import_tasks(monkeypatch)
    updates = []
    closed = []

    conn = types.SimpleNamespace(
        close=lambda: closed.append(True),
        SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
    )

    monkeypatch.setattr(tasks, "use_job_service_session", lambda: True)
    monkeypatch.setattr(
        tasks, "_open_job_service_connection", lambda *args, **kwargs: conn
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda current_conn: 99)
    monkeypatch.setattr(tasks, "_get_connection_session_key", lambda current_conn: None)

    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-1"),
        update_state=lambda state, meta: updates.append((state, meta)),
    )

    with pytest.raises(RuntimeError, match="session key unavailable"):
        tasks.run_ims_export_task(
            task_self,
            image_id=7,
            session_key=None,
            host="omeroserver",
            port=4064,
        )

    assert [meta["status"] for state, meta in updates[:-1] if state == "STARTED"] == [
        "connecting",
        "finding_script",
        "running_script",
    ]
    assert updates[2][1]["script_id"] == 99
    assert updates[-1][0] == tasks.states.FAILURE
    assert updates[-1][1]["error"] == "IMS export job failed."
    assert closed == [True]


def test_task_helpers_cover_cli_resolution_connection_errors_and_success(
    monkeypatch, tmp_path
):
    """Verify task helpers cover cli resolution connection errors and success.

    Inputs: `monkeypatch`, `tmp_path`. Output: bool.
    """
    tasks = _import_tasks(monkeypatch)

    monkeypatch.setattr(tasks.os.path, "exists", lambda path: False)
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="OMERO CLI binary not found"):
        tasks._resolve_omero_cli()

    assert tasks._build_failure_meta(RuntimeError("boom")) == {
        "exc_type": "RuntimeError",
        "exc_module": "builtins",
        "exc_message": "IMS export job failed.",
        "error": "IMS export job failed.",
        "public_error": False,
    }
    assert tasks._public_script_message(None) is None
    assert tasks._public_script_message("   ") is None
    assert tasks._public_script_message("Image 7 not found") == "Image 7 not found"
    assert (
        tasks._public_script_message("Original file not found: /private/source.tif")
        == "Original file not found."
    )
    public_payload = tasks._build_failure_meta(
        tasks.IMSExportTaskError(
            "internal detail",
            public_message="Could not prepare source image for IMS conversion",
        )
    )
    assert (
        public_payload["error"] == "Could not prepare source image for IMS conversion"
    )
    assert public_payload["public_error"] is True

    with pytest.raises(RuntimeError, match="Session key is required"):
        tasks._open_session_connection("", "omeroserver", 4064)
    with pytest.raises(RuntimeError, match="OMERO host is required"):
        tasks._open_session_connection("session", "", 4064)
    with pytest.raises(RuntimeError, match="OMERO port is required"):
        tasks._open_session_connection("session", "omeroserver", None)

    class _ClientError(Exception):
        """Represent client error."""

    class _SecurityViolation(Exception):
        """Represent security violation."""

    omero_stub = types.SimpleNamespace(
        ClientError=_ClientError,
        SecurityViolation=_SecurityViolation,
    )
    monkeypatch.setattr(tasks, "omero", omero_stub)

    monkeypatch.setattr(
        omero_stub,
        "client",
        lambda host, port: types.SimpleNamespace(
            joinSession=lambda session_key: (_ for _ in ()).throw(
                _ClientError("bad client")
            )
        ),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="Failed to connect to OMERO"):
        tasks._open_session_connection("session", "omeroserver", 4064)

    monkeypatch.setattr(
        tasks,
        "get_job_service_credentials",
        lambda: ("job-service", TEST_SERVICE_AUTH_VALUE),
    )

    class _FailingGateway:
        """Represent failing gateway."""

        def __init__(self, *args, **kwargs):
            """Initialize the instance.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.SERVICE_OPTS = types.SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection.

            Inputs: none. Output: bool.
            """
            return False

    monkeypatch.setattr(tasks, "BlitzGateway", _FailingGateway)
    with pytest.raises(RuntimeError, match="job-service session"):
        tasks._open_job_service_connection("omeroserver", 4064)

    updates = []
    closed = []
    conn = types.SimpleNamespace(
        close=lambda: closed.append(True),
        SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
    )

    monkeypatch.setattr(tasks, "use_job_service_session", lambda: False)
    monkeypatch.setattr(
        tasks,
        "_open_session_connection",
        lambda session_key, host, port, secure=None: conn,
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda current_conn: 88)
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **kwargs: {
            "Export_Path": str(tmp_path / "demo.ims"),
            "Export_Name": "demo.ims",
        },
    )
    monkeypatch.setattr(
        tasks,
        "_serialize_outputs",
        lambda outputs: {"Export_Name": outputs["Export_Name"]},
    )

    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-2"),
        update_state=lambda state, meta: updates.append((state, meta)),
    )

    result = tasks.run_ims_export_task(
        task_self,
        image_id=7,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        secure=True,
    )

    assert [meta["status"] for state, meta in updates] == [
        "connecting",
        "finding_script",
        "running_script",
    ]
    assert updates[2][1]["script_id"] == 88
    assert result == {
        "state": "FINISHED",
        "outputs": {"Export_Name": "demo.ims"},
        "error": None,
    }
    assert closed == [True]

    updates.clear()
    closed.clear()
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **kwargs: (_ for _ in ()).throw(
            tasks.IMSExportTaskError(
                "script did not return export path",
                public_message="Image 7 not found",
            )
        ),
    )
    result = tasks.run_ims_export_task(
        task_self,
        image_id=7,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        secure=True,
    )
    assert result == {
        "state": "FAILED",
        "outputs": None,
        "error": "Image 7 not found",
        "public_error": True,
    }
    assert closed == [True]


def test_task_helpers_cover_security_validation_and_close_warning_paths(
    monkeypatch,
):
    """Verify task helpers cover security validation and close warning paths.

    Inputs: `monkeypatch`. Output: None.
    """
    tasks = _import_tasks(monkeypatch)

    assert tasks._get_connection_session_key(None) is None
    assert (
        tasks._get_connection_session_key(
            types.SimpleNamespace(
                c=types.SimpleNamespace(
                    getSessionId=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
                )
            )
        )
        is None
    )

    class _ClientError(Exception):
        """Represent client error."""

    class _SecurityViolation(Exception):
        """Represent security violation."""

    omero_stub = types.SimpleNamespace(
        ClientError=_ClientError,
        SecurityViolation=_SecurityViolation,
    )
    monkeypatch.setattr(tasks, "omero", omero_stub)

    monkeypatch.setattr(
        omero_stub,
        "client",
        lambda host, port: types.SimpleNamespace(joinSession=lambda session_key: None),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="Failed to open OMERO session"):
        tasks._open_session_connection("session", "omeroserver", 4064)

    monkeypatch.setattr(
        omero_stub,
        "client",
        lambda host, port: types.SimpleNamespace(
            joinSession=lambda session_key: (_ for _ in ()).throw(
                _SecurityViolation("denied")
            )
        ),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="Access denied"):
        tasks._open_session_connection("session", "omeroserver", 4064)

    monkeypatch.setattr(
        tasks, "get_job_service_credentials", lambda: ("job-service", "secret")
    )
    with pytest.raises(RuntimeError, match="OMERO host is required"):
        tasks._open_job_service_connection("", 4064)
    with pytest.raises(RuntimeError, match="OMERO port is required"):
        tasks._open_job_service_connection("omeroserver", None)
    with pytest.raises(RuntimeError, match="Invalid port value"):
        tasks._open_job_service_connection("omeroserver", "bad-port")
    monkeypatch.setattr(tasks, "get_job_service_credentials", lambda: ("", "secret"))
    with pytest.raises(RuntimeError, match="username is required"):
        tasks._open_job_service_connection("omeroserver", 4064)

    monkeypatch.setattr(tasks, "use_job_service_session", lambda: False)
    conn = types.SimpleNamespace(
        close=lambda: (_ for _ in ()).throw(RuntimeError("close failed")),
        SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
    )
    updates = []
    warnings = []
    monkeypatch.setattr(
        tasks,
        "_open_session_connection",
        lambda session_key, host, port, secure=None: conn,
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda current_conn: None)
    monkeypatch.setattr(
        tasks.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message % args),
    )

    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-3"),
        update_state=lambda state, meta: updates.append((state, meta)),
    )

    with pytest.raises(RuntimeError, match="script not found"):
        tasks.run_ims_export_task(
            task_self,
            image_id=8,
            session_key="session-key",
            host="omeroserver",
            port=4064,
        )

    assert updates[-1][0] == tasks.states.FAILURE
    assert warnings == ["Error closing OMERO connection: close failed"]
