from __future__ import annotations

import logging
import shutil
import stat
import sys
import types
from pathlib import Path

import pytest


TEST_RUNTIME_ROOT = Path(__file__).resolve().parent / "_runtime"
TEST_SERVICE_AUTH_VALUE = "job-auth-fixture"


@pytest.fixture(autouse=True)
def _clean_test_runtime_root():
    """Remove generated runtime files around each test.

    Inputs: none. Output: yields for test execution.
    """
    shutil.rmtree(TEST_RUNTIME_ROOT, ignore_errors=True)
    yield
    shutil.rmtree(TEST_RUNTIME_ROOT, ignore_errors=True)


def _install_omero_stubs() -> None:
    """Install the OMERO stubs.

    Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
    """
    omero_module = types.ModuleType("omero")
    omero_module.ClientError = type("ClientError", (Exception,), {})
    omero_module.SecurityViolation = type("SecurityViolation", (Exception,), {})
    omero_module.NoProcessorAvailable = type("NoProcessorAvailable", (Exception,), {})
    omero_module.client = lambda host, port: None
    omero_module.scripts = types.SimpleNamespace()

    omero_gateway = types.ModuleType("omero.gateway")
    omero_gateway.BlitzGateway = type("BlitzGateway", (), {})

    omero_rtypes = types.ModuleType("omero.rtypes")
    omero_rtypes.rint = lambda value: value
    omero_rtypes.rlong = lambda value: value
    omero_rtypes.robject = lambda value: value
    omero_rtypes.rstring = lambda value: value

    sys.modules["omero"] = omero_module
    sys.modules["omero.gateway"] = omero_gateway
    sys.modules["omero.rtypes"] = omero_rtypes


def _install_celery_stubs() -> None:
    """Install the celery stubs.

    Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
    """
    celery_module = types.ModuleType("celery")

    class _DummyCelery:
        """Test double for dummy celery."""

        def __init__(self, *_args, **_kwargs):
            """Create `_DummyCelery` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            self.conf = types.SimpleNamespace(update=lambda **_kwargs: None)

        @staticmethod
        def autodiscover_tasks(*_args, **_kwargs):
            """Record Celery autodiscovery calls for the surrounding test.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def task(*args, **kwargs):
            """Return the task for `_DummyCelery`.

            Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
            `_decorator`.
            """

            def _decorator(fn):
                """Return the decorator for `_DummyCelery`.

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
    """Set the required environment.

    Inputs: `monkeypatch` (pytest.MonkeyPatch) pytest monkeypatch fixture. Output: None.
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
        "OMERO_WEB_ROOT": str(TEST_RUNTIME_ROOT / "web"),
        "OMERO_WEB_VENV": "venv-3.12",
        "OMERO_JOB_SERVICE_USER": "job-service",
        "OMERO_JOB_SERVICE_PASSWORD": TEST_SERVICE_AUTH_VALUE,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _import_tasks(monkeypatch: pytest.MonkeyPatch):
    """Import the tasks.

    Inputs: `monkeypatch` (pytest.MonkeyPatch) pytest monkeypatch fixture. Output:
    `tasks`.
    """
    _set_required_env(monkeypatch)
    _install_omero_stubs()
    _install_celery_stubs()
    for module_name in [
        "omero_imaris_connector.config",
        "omero_imaris_connector.celery_app",
        "omero_imaris_connector.imaris_service",
        "omero_imaris_connector.tasks",
    ]:
        sys.modules.pop(module_name, None)
    from omero_imaris_connector import tasks

    return tasks


def test_cli_resolution_output_parsing_and_connection_session_key(
    monkeypatch, tmp_path
):
    """Verify the CLI resolution output parsing and connection session key execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in CLI resolution output parsing and connection session key.
    """
    tasks = _import_tasks(monkeypatch)
    web_root = tmp_path / "web"
    cli_path = web_root / "venv-3.12" / "bin" / "omero"
    export_path = tmp_path / f"{tmp_path.name}.ims"
    cli_path.parent.mkdir(parents=True)
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    cli_path.chmod(0o755)
    monkeypatch.setenv("OMERO_WEB_ROOT", str(web_root))
    monkeypatch.setenv("OMERO_WEB_VENV", "venv-3.12")
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)

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
    assert tasks._extract_cli_outputs(
        "\n".join(
            [
                "\t*** out parameters ***",
                "\t* Message=done",
                f"\t* Export_Path={export_path}",
                "Export_Name: demo.ims",
                "File_Annotation_Id    44",
            ]
        )
    ) == {
        "Message": "done",
        "Export_Path": str(export_path),
        "Export_Name": "demo.ims",
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


def test_cli_resolution_uses_newest_discovered_web_venv(monkeypatch, tmp_path):
    """Verify OMERO CLI resolution follows the newest env-rooted venv.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on
    regressions in dynamic virtualenv discovery.
    """
    tasks = _import_tasks(monkeypatch)
    web_root = tmp_path / "web"
    older_cli = web_root / "venv-3.9" / "bin" / "omero"
    current_cli = web_root / "venv-3.12" / "bin" / "omero"
    for cli_path in (older_cli, current_cli):
        cli_path.parent.mkdir(parents=True, exist_ok=True)
        cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
        cli_path.chmod(0o755)

    monkeypatch.setenv("OMERO_WEB_ROOT", str(web_root))
    monkeypatch.delenv("OMERO_WEB_VENV", raising=False)
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)

    assert tasks._resolve_omero_cli() == str(current_cli)


def test_cli_resolution_covers_explicit_path_and_invalid_env_edges(
    monkeypatch, tmp_path, caplog
):
    """Verify OMERO CLI resolution handles explicit and invalid env edges.

    Inputs: pytest provides `monkeypatch`, `tmp_path`, `caplog`. Output: fails
    on regressions in CLI candidate handling.
    """
    tasks = _import_tasks(monkeypatch)
    explicit_cli = tmp_path / "explicit" / "omero"
    explicit_cli.parent.mkdir(parents=True)
    explicit_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    explicit_cli.chmod(0o755)
    monkeypatch.setenv("OMERO_WEB_OMERO_BIN", str(explicit_cli))
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)
    assert tasks._resolve_omero_cli() == str(explicit_cli)

    path_cli = tmp_path / "path" / "omero"
    path_cli.parent.mkdir(parents=True)
    path_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    path_cli.chmod(0o755)
    monkeypatch.delenv("OMERO_WEB_OMERO_BIN", raising=False)
    monkeypatch.delenv("OMERO_BIN", raising=False)
    monkeypatch.delenv("OMERO_WEB_ROOT", raising=False)
    monkeypatch.delenv("OMERO_WEB_VENV", raising=False)
    monkeypatch.setattr(tasks.shutil, "which", lambda name: str(path_cli))
    assert tasks._resolve_omero_cli() == str(path_cli)

    real_path = tasks.Path

    def path_rejecting_bad_env(value):
        """Return a path object unless the test requests an invalid value.

        Inputs: `value`. Output: `Path`. Raises: ValueError for bad sentinels.
        """
        if value in {"bad-root", "bad-venv"}:
            raise ValueError("bad path")
        return real_path(value)

    monkeypatch.setattr(tasks, "Path", path_rejecting_bad_env)
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)
    monkeypatch.setenv("OMERO_WEB_ROOT", "bad-root")
    monkeypatch.delenv("OMERO_WEB_VENV", raising=False)
    assert tasks._iter_omero_cli_candidates() == []

    monkeypatch.setenv("OMERO_WEB_ROOT", str(tmp_path / "web"))
    monkeypatch.setenv("OMERO_WEB_VENV", "bad-venv")
    assert tasks._iter_omero_cli_candidates() == []

    class _BadWebRoot:
        """Path test double whose glob operation fails."""

        @staticmethod
        def glob(_pattern):
            """Raise while listing candidates.

            Inputs: `_pattern`. Output: raises OSError.
            """
            raise OSError("cannot list")

    monkeypatch.setattr(
        tasks,
        "Path",
        lambda value: _BadWebRoot() if value == "bad-glob-root" else real_path(value),
    )
    monkeypatch.setenv("OMERO_WEB_ROOT", "bad-glob-root")
    monkeypatch.delenv("OMERO_WEB_VENV", raising=False)
    with caplog.at_level(logging.DEBUG):
        assert tasks._iter_omero_cli_candidates() == []
    assert "Unable to inspect OMERO_WEB_ROOT" in caplog.text


def test_resolve_executable_candidate_covers_command_and_rejection_paths(
    monkeypatch, tmp_path
):
    """Verify executable candidate resolution handles command and failure paths.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on
    regressions in executable candidate resolution.
    """
    tasks = _import_tasks(monkeypatch)
    cli_path = tmp_path / "bin" / "omero"
    cli_path.parent.mkdir(parents=True)
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    cli_path.chmod(0o755)

    monkeypatch.setattr(tasks.shutil, "which", lambda name: str(cli_path))
    assert tasks._resolve_executable_candidate("omero") == str(cli_path)
    assert tasks._resolve_executable_candidate("") is None
    assert tasks._resolve_executable_candidate(str(tmp_path / "missing")) is None

    monkeypatch.setattr(
        tasks.os.path,
        "isfile",
        lambda candidate: (_ for _ in ()).throw(OSError("bad stat")),
    )
    assert tasks._resolve_executable_candidate(str(cli_path)) is None


def test_run_script_via_omero_cli_covers_success_and_failure_paths(
    monkeypatch, tmp_path, caplog
):
    """Verify the run script via OMERO CLI covers success and failure paths execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`, `caplog`. Output: fails on regressions in run script via OMERO CLI covers success and failure paths integration.
    """
    tasks = _import_tasks(monkeypatch)
    cli_path = tmp_path / "omero"
    export_path = tmp_path / f"{tmp_path.name}.ims"
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(tasks, "_resolve_omero_cli", lambda: str(cli_path))

    captured = {}

    def successful_run(
        cmd,
        *,
        timeout,
        check,
        env,
        on_tick,
        start_new_session,
        **_kwargs,
    ):
        """Return the successful run.

        Inputs: `cmd`, `timeout` timeout seconds, `check`, `env` environment mapping,
        `**_kwargs`. Output: `SimpleNamespace` result.
        """
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        captured["start_new_session"] = start_new_session
        captured["env"] = {
            "HOME": env["HOME"],
            "OMERO_USERDIR": env["OMERO_USERDIR"],
            "OMERO_SESSIONDIR": env["OMERO_SESSIONDIR"],
            "OMERO_TMPDIR": env["OMERO_TMPDIR"],
        }
        on_tick(12345, 0.0)
        return types.SimpleNamespace(
            returncode=0,
            stdout=f"* Export_Path = {export_path}\n* Export_Name = demo.ims",
            stderr="",
        )

    monkeypatch.setattr(tasks.subprocess, "run_streaming", successful_run)
    status_updates = []
    outputs = tasks._run_script_via_omero_cli(
        script_id=7,
        image_id=11,
        host="omeroserver",
        port=4064,
        session_key="session-key",
        status_callback=lambda status, meta: status_updates.append((status, meta)),
    )
    assert outputs["Export_Path"] == str(export_path)
    assert captured["cmd"][:5] == [str(cli_path), "-q", "script", "launch", "7"]
    assert captured["timeout"] == tasks.EXPORT_TIMEOUT + 120
    assert status_updates == [
        (
            "running_script",
            {
                "script_id": 7,
                "cli_pid": 12345,
                "cli_pgid": 12345,
                "elapsed": 0.0,
            },
        )
    ]
    assert captured["start_new_session"] is True
    assert captured["env"]["HOME"] == captured["env"]["OMERO_USERDIR"]
    assert Path(captured["env"]["OMERO_USERDIR"]).is_relative_to(
        TEST_RUNTIME_ROOT / "tmp"
    )

    with pytest.raises(RuntimeError, match="live OMERO session key"):
        tasks._run_script_via_omero_cli(7, 11, "omeroserver", 4064, session_key=None)

    monkeypatch.setattr(
        tasks.subprocess,
        "run_streaming",
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
        "run_streaming",
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
        "run_streaming",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0,
            stdout="* Message = done",
            stderr="",
        ),
    )
    with pytest.raises(tasks.IMSExportTaskError, match="no export path") as exc_info:
        tasks._run_script_via_omero_cli(7, 11, "omeroserver", 4064, "session-key")
    assert exc_info.value.public_message is None


def test_run_ome_tiff_export_task_materializes_outputs_and_closes_connection(
    monkeypatch,
):
    """Verify OME-TIFF export task returns serialized outputs and closes the connection.

    Inputs: pytest provides `monkeypatch`. Output: fails on OME-TIFF task regressions.
    """
    tasks = _import_tasks(monkeypatch)
    closed = []
    state_updates = []
    conn = types.SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(
        tasks,
        "_open_export_connection",
        lambda session_key, host, port, secure=None: conn,
    )
    monkeypatch.setattr(
        tasks,
        "_run_ome_tiff_export",
        lambda conn_arg, image_id, status_callback=None: (
            status_callback("running_export", {"export_name": "demo.ome.tif"})
            or {
                "Export_Path": "/exports/image_12/demo.ome.tif",
                "Export_Name": "demo.ome.tif",
            }
        ),
    )

    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-ome"),
        update_state=lambda state, meta: state_updates.append((state, meta)),
    )

    result = tasks.run_ome_tiff_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        secure=True,
    )

    assert result == {
        "state": "FINISHED",
        "outputs": {
            "Export_Path": "/exports/image_12/demo.ome.tif",
            "Export_Name": "demo.ome.tif",
        },
        "error": None,
    }
    assert state_updates[0][0] == "STARTED"
    assert state_updates[0][1]["image_id"] == 12
    assert state_updates[0][1]["status"] == "connecting"
    assert "started_at" in state_updates[0][1]
    assert state_updates[-1][1]["status"] == "running_export"
    assert closed == [True]


def test_run_ome_tiff_export_keeps_staged_file_private(monkeypatch):
    """Verify OME-TIFF exports are readable by the service user only.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on permissive
    file-mode regressions.
    """
    tasks = _import_tasks(monkeypatch)
    observed_export_roots = []

    def materialize_ome_tiff_source(conn, image, image_id, export_root):
        """Create a permissive file for the task helper to harden.

        Inputs: fake export arguments. Output: string path to the staged file.
        """
        observed_export_roots.append(Path(export_root))
        export_path = Path(export_root) / f"image_{int(image_id)}" / "source"
        export_path.mkdir(parents=True, exist_ok=True)
        export_path = export_path / "demo.ome.tif"
        export_path.write_bytes(b"II*\x00")
        export_path.chmod(0o666)
        return str(export_path)

    def safe_filename(_name, fallback="image"):
        """Return a deterministic safe export name for the fake script module.

        Inputs: ignored, plus fallback matching the public helper signature. Output: filename stem.
        """
        _ = fallback
        return "demo"

    fake_script = types.SimpleNamespace(
        _get_export_root=lambda conn: pytest.fail(
            "OME-TIFF staging must not use OMERO_IMS_EXPORT_DIR"
        ),
        safe_filename=safe_filename,
        materialize_ome_tiff_source=materialize_ome_tiff_source,
    )
    image = types.SimpleNamespace(getName=lambda: "demo")
    conn = types.SimpleNamespace(getObject=lambda kind, image_id: image)
    monkeypatch.setattr(tasks, "_ims_export_script_module", lambda: fake_script)

    outputs = tasks._run_ome_tiff_export(conn, 12)

    expected_root = (
        TEST_RUNTIME_ROOT / "tmp" / "omero-imaris-connector" / "ome-tiff-source"
    )
    expected_path = expected_root / "image_12" / "source" / "demo.ome.tif"
    assert observed_export_roots == [expected_root]
    assert outputs["Export_Path"] == str(expected_path)
    assert stat.S_IMODE(expected_path.stat().st_mode) == 0o600


def test_session_and_job_service_connections_cover_success_and_validation(monkeypatch):
    """Verify session and job service connections cover success and validation.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in session and job service connections cover success and validation.
    """
    tasks = _import_tasks(monkeypatch)
    detach_calls = []
    join_calls = []

    class DummyClient:
        """Test double for dummy client."""

        @staticmethod
        def joinSession(session_key):
            """Join the session for `DummyClient`.

            Inputs: `session_key`. Output: `SimpleNamespace` result.
            """
            join_calls.append(session_key)
            return types.SimpleNamespace(
                detachOnDestroy=lambda: detach_calls.append(True)
            )

    class DummyGateway:
        """Test double for dummy gateway."""

        def __init__(self, *args, **kwargs):
            """Create `DummyGateway` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.kwargs = kwargs
            self.connected = kwargs.get("host") == "omeroserver"
            self.SERVICE_OPTS = types.SimpleNamespace(
                setOmeroGroup=lambda value: setattr(self, "group", value)
            )

        def connect(self):
            """Open the connection for `DummyGateway`.

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
    assert getattr(conn, tasks._PRESERVE_JOINED_SESSION_ATTR) is True

    with pytest.raises(RuntimeError, match="Invalid port value"):
        tasks._open_session_connection("session-1", "omeroserver", "bad-port")

    monkeypatch.setattr(
        tasks,
        "get_job_service_credentials",
        lambda: ("job-service", TEST_SERVICE_AUTH_VALUE),
    )
    conn = tasks._open_job_service_connection("omeroserver", 4064, secure=True)
    assert conn.group == "-1"
    assert getattr(conn, tasks._PRESERVE_JOINED_SESSION_ATTR) is False

    monkeypatch.setattr(
        tasks,
        "get_job_service_credentials",
        lambda: ("job-service", ""),
    )
    with pytest.raises(RuntimeError, match="password is required"):
        tasks._open_job_service_connection("omeroserver", 4064)


def test_open_export_connection_prefers_requesting_session_when_job_service_enabled(
    monkeypatch,
) -> None:
    """Verify requester sessions stay authoritative in job-service mode.

    Inputs: pytest provides `monkeypatch`. Output: validates connection
    selection for requester-session and job-service fallback paths.
    """
    tasks = _import_tasks(monkeypatch)
    calls = []
    monkeypatch.setattr(tasks, "use_job_service_session", lambda: True)
    monkeypatch.setattr(
        tasks,
        "_open_session_connection",
        lambda session_key, host, port, secure=None: (
            calls.append(("session", session_key, host, port, secure)) or "session-conn"
        ),
    )
    monkeypatch.setattr(
        tasks,
        "_open_job_service_connection",
        lambda host, port, secure=None: (
            calls.append(("job-service", host, port, secure)) or "job-service-conn"
        ),
    )

    configured_host = "configured-omero.example"
    configured_port = 16555

    assert (
        tasks._open_export_connection(
            "request-session", configured_host, configured_port, secure=True
        )
        == "session-conn"
    )
    assert calls == [
        ("session", "request-session", configured_host, configured_port, True)
    ]

    calls.clear()
    assert (
        tasks._open_export_connection(
            None, configured_host, configured_port, secure=True
        )
        == "job-service-conn"
    )
    assert calls == [("job-service", configured_host, configured_port, True)]

    calls.clear()
    monkeypatch.setattr(tasks, "use_job_service_session", lambda: False)
    assert (
        tasks._open_export_connection(
            None, configured_host, configured_port, secure=True
        )
        == "session-conn"
    )
    assert calls == [("session", None, configured_host, configured_port, True)]


def test_close_export_connection_preserves_joined_requester_session(monkeypatch):
    """Verify requester-session task cleanup does not kill the OMERO.web session.

    Inputs: pytest provides `monkeypatch`. Output: fails on hard-close regressions.
    """
    tasks = _import_tasks(monkeypatch)
    calls = []
    requester_conn = types.SimpleNamespace(close=lambda **kwargs: calls.append(kwargs))
    setattr(requester_conn, tasks._PRESERVE_JOINED_SESSION_ATTR, True)

    tasks._close_export_connection(requester_conn)

    assert calls == [{"hard": False}]


def test_close_export_connection_hard_closes_job_service_session(monkeypatch):
    """Verify job-service task cleanup owns and closes its own session.

    Inputs: pytest provides `monkeypatch`. Output: fails on session cleanup regressions.
    """
    tasks = _import_tasks(monkeypatch)
    calls = []
    job_conn = types.SimpleNamespace(close=lambda **kwargs: calls.append(kwargs))
    setattr(job_conn, tasks._PRESERVE_JOINED_SESSION_ATTR, False)

    tasks._close_export_connection(job_conn)

    assert calls == [{"hard": True}]


def test_run_ims_export_task_updates_failure_meta_and_closes_connections(
    monkeypatch, tmp_path
):
    """Verify run IMS export task updates failure meta and closes connections.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in run IMS export task updates failure meta and closes connections.
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
    """Verify the task helpers cover CLI resolution connection errors and success execution contract.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in task helpers cover CLI resolution connection errors and success.
    """
    tasks = _import_tasks(monkeypatch)

    monkeypatch.setenv("OMERO_WEB_ROOT", str(tmp_path / "empty-web-root"))
    monkeypatch.delenv("OMERO_WEB_VENV", raising=False)
    monkeypatch.delenv("OMERO_WEB_OMERO_BIN", raising=False)
    monkeypatch.delenv("OMERO_BIN", raising=False)
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
        """Test double for client error behavior in this module."""

    class _SecurityViolation(Exception):
        """Test double for security violation behavior in this module."""

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
        """Test double for failing gateway behavior in this module."""

        def __init__(self, *args, **kwargs):
            """Create `_FailingGateway` with its default state.

            Inputs: `*args`, `**kwargs`. Output: None.
            """
            self.SERVICE_OPTS = types.SimpleNamespace(setOmeroGroup=lambda value: None)

        @staticmethod
        def connect():
            """Open the connection for `_FailingGateway`.

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

    updates.clear()
    closed.clear()
    monkeypatch.setattr(tasks, "export_task_cancel_requested", lambda task_id: True)
    result = tasks.run_ims_export_task(
        task_self,
        image_id=7,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        secure=True,
    )
    assert result == {
        "state": "CANCELLED",
        "outputs": None,
        "error": "IMS export stopped by user.",
    }
    assert closed == [True]


def test_task_helpers_cover_security_validation_and_close_warning_paths(
    monkeypatch,
):
    """Verify the task helpers cover security validation and close warning paths safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when task helpers cover security validation and close warning paths accepts unsafe input.
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
        """Test double for client error behavior in this module."""

    class _SecurityViolation(Exception):
        """Test double for security violation behavior in this module."""

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
    expected_failure_warning = (
        "IMS export task failed image_id=8 task_id=task-3: "
        + "IMS export script not found on OMERO.server."
    )
    assert warnings == [
        expected_failure_warning,
        "Error closing OMERO connection: close failed",
    ]


def test_export_cancel_markers_use_redis_as_best_effort_state(monkeypatch):
    """Verify cancellation markers are bounded, session-safe, and fail closed.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions that would
    make user stop requests depend on a brittle Redis connection or unbounded TTL.
    """
    tasks = _import_tasks(monkeypatch)

    assert tasks._export_cancel_marker_key("") is None
    assert tasks._export_cancel_marker_key("task-1").endswith(":task-1")
    monkeypatch.setattr(tasks, "get_celery_result_expires", lambda: 1)
    assert (
        tasks._export_cancel_marker_ttl() == tasks._EXPORT_CANCEL_MARKER_MIN_TTL_SECONDS
    )
    monkeypatch.setattr(
        tasks,
        "get_celery_result_expires",
        lambda: (_ for _ in ()).throw(RuntimeError("bad config")),
    )
    assert (
        tasks._export_cancel_marker_ttl() == tasks._EXPORT_CANCEL_MARKER_MIN_TTL_SECONDS
    )

    monkeypatch.setattr(
        tasks,
        "get_celery_broker_url",
        lambda: (_ for _ in ()).throw(RuntimeError("bad broker")),
    )
    assert tasks._export_cancel_redis_client() is None
    monkeypatch.setattr(tasks, "get_celery_broker_url", lambda: "amqp://broker")
    assert tasks._export_cancel_redis_client() is None
    monkeypatch.setattr(tasks, "get_celery_broker_url", lambda: "redis://redis/0")
    monkeypatch.setitem(sys.modules, "redis", None)
    assert tasks._export_cancel_redis_client() is None

    redis_state = {"client": None, "raise": True}
    redis_module = types.ModuleType("redis")

    class _RedisFactory:
        """Factory double for Redis connection setup."""

        @staticmethod
        def from_url(url):
            """Return the configured fake client or raise a connection error.

            Inputs: Redis URL. Output: fake Redis client.
            """
            assert url == "redis://redis/0"
            if redis_state["raise"]:
                raise RuntimeError("connect failed")
            return redis_state["client"]

    redis_module.Redis = _RedisFactory
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    assert tasks._export_cancel_redis_client() is None

    class _MarkerRedis:
        """Redis double for cancellation marker set/read semantics."""

        def __init__(self):
            """Initialize marker storage state.

            Inputs: none. Output: None.
            """
            self.fail_set = False
            self.fail_get = False
            self.setex_calls = []

        def setex(self, key, ttl, value):
            """Record marker writes.

            Inputs: Redis key, TTL, value. Output: None.
            """
            if self.fail_set:
                raise RuntimeError("write failed")
            self.setex_calls.append((key, ttl, value))

        def get(self, key):
            """Return a stored marker.

            Inputs: Redis key. Output: marker bytes.
            """
            if self.fail_get:
                raise RuntimeError("read failed")
            assert key == tasks._export_cancel_marker_key("task-1")
            return b"1"

    client = _MarkerRedis()
    redis_state.update({"client": client, "raise": False})
    monkeypatch.setattr(tasks, "get_celery_result_expires", lambda: 1)

    assert tasks._export_cancel_redis_client() is client
    assert not tasks.mark_export_task_cancel_requested("")
    assert tasks.mark_export_task_cancel_requested("task-1")
    assert client.setex_calls == [
        (
            tasks._export_cancel_marker_key("task-1"),
            tasks._EXPORT_CANCEL_MARKER_MIN_TTL_SECONDS,
            b"1",
        )
    ]
    assert tasks.export_task_cancel_requested("task-1")

    client.fail_set = True
    assert not tasks.mark_export_task_cancel_requested("task-2")
    client.fail_get = True
    assert not tasks.export_task_cancel_requested("task-1")


def test_run_script_via_omero_cli_tick_reporting_is_best_effort(
    monkeypatch,
    tmp_path,
    caplog,
):
    """Verify CLI process telemetry cannot fail an otherwise valid export.

    Inputs: pytest provides `monkeypatch`, `tmp_path`, `caplog`. Output: fails on
    regressions that would abort a conversion because progress reporting failed.
    """
    tasks = _import_tasks(monkeypatch)
    cli_path = tmp_path / "omero"
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
    export_path = tmp_path / "telemetry.ims"
    monkeypatch.setattr(tasks, "_resolve_omero_cli", lambda: str(cli_path))

    def streaming_run(*_args, on_tick, **_kwargs):
        """Simulate a streaming OMERO CLI process.

        Inputs: ignored process arguments plus tick callback. Output: completed process.
        """
        on_tick(4242, 1.5)
        return types.SimpleNamespace(
            returncode=0,
            stdout=f"Export_Path = {export_path}\nExport_Name = telemetry.ims",
            stderr="",
        )

    monkeypatch.setattr(tasks.subprocess, "run_streaming", streaming_run)

    assert tasks._run_script_via_omero_cli(
        9,
        12,
        "omeroserver",
        4064,
        "session-key",
    ) == {
        "Export_Path": str(export_path),
        "Export_Name": "telemetry.ims",
    }

    with caplog.at_level(logging.ERROR, logger=tasks.logger.name):
        assert tasks._run_script_via_omero_cli(
            9,
            12,
            "omeroserver",
            4064,
            "session-key",
            status_callback=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("callback failed")
            ),
        )["Export_Path"] == str(export_path)
    assert "Failed to update IMS export CLI process metadata" in caplog.text


def test_ims_task_owner_token_survives_success_public_failure_and_cancel(
    monkeypatch,
    tmp_path,
):
    """Verify IMS task ownership metadata survives every public terminal state.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions
    that would make status or cancellation ownership checks lose their token.
    """
    tasks = _import_tasks(monkeypatch)
    closed = []
    updates = []
    conn = types.SimpleNamespace(
        close=lambda **_kwargs: closed.append(True),
        SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda value: None),
    )
    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-owner"),
        update_state=lambda state, meta: updates.append((state, meta)),
    )
    owner_marker = "owner-marker"
    monkeypatch.setattr(tasks, "use_job_service_session", lambda: False)
    monkeypatch.setattr(
        tasks,
        "_open_export_connection",
        lambda session_key, host, port, secure=None: conn,
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda current_conn: 91)
    monkeypatch.setattr(tasks, "_serialize_outputs", dict)
    monkeypatch.setattr(tasks, "export_task_cancel_requested", lambda task_id: False)
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **_kwargs: {
            "Export_Path": str(tmp_path / "owner.ims"),
            "Export_Name": "owner.ims",
        },
    )

    result = tasks.run_ims_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        owner_token=owner_marker,
    )
    assert result["owner_token"] == owner_marker
    assert all(meta["owner_token"] == owner_marker for _state, meta in updates)

    updates.clear()
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **_kwargs: (_ for _ in ()).throw(
            tasks.IMSExportTaskError(
                "private detail", public_message="Image 12 not found"
            )
        ),
    )
    result = tasks.run_ims_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        owner_token=owner_marker,
    )
    assert result == {
        "state": "FAILED",
        "outputs": None,
        "error": "Image 12 not found",
        "public_error": True,
        "owner_token": owner_marker,
    }

    monkeypatch.setattr(tasks, "export_task_cancel_requested", lambda task_id: True)
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("worker stopped")),
    )
    result = tasks.run_ims_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        owner_token=owner_marker,
    )
    assert result == {
        "state": "CANCELLED",
        "outputs": None,
        "error": "IMS export stopped by user.",
        "owner_token": owner_marker,
    }
    assert len(closed) == 3


def test_close_export_connection_accepts_gateway_close_signature_variants(
    monkeypatch,
):
    """Verify gateway cleanup handles supported OMERO.py close signatures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions that would
    leak or hard-close the wrong session when gateway versions differ.
    """
    tasks = _import_tasks(monkeypatch)

    tasks._close_export_connection(types.SimpleNamespace())

    positional_calls = []

    class _PositionalClose:
        """Gateway double whose close method only accepts a positional hard flag."""

        @staticmethod
        def close(*args, **kwargs):
            """Record close calls or reject keyword usage.

            Inputs: close args and kwargs. Output: None.
            """
            if kwargs:
                raise TypeError("no keyword close")
            positional_calls.append(args)

    tasks._close_export_connection(_PositionalClose())
    assert positional_calls == [(True,)]

    no_arg_calls = []

    class _NoArgClose:
        """Gateway double whose close method accepts no arguments."""

        @staticmethod
        def close(*args, **kwargs):
            """Record no-argument close calls.

            Inputs: close args and kwargs. Output: None.
            """
            if args or kwargs:
                raise TypeError("no close arguments")
            no_arg_calls.append(True)

    tasks._close_export_connection(_NoArgClose())
    assert no_arg_calls == [True]


def test_ome_tiff_task_uses_format_specific_public_failure_contract(monkeypatch):
    """Verify OME-TIFF task failures never fall back to IMS-specific messages.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in missing
    image handling, materialization failure reporting, and task failure metadata.
    """
    tasks = _import_tasks(monkeypatch)

    with pytest.raises(tasks.OMEExportTaskError) as missing_image:
        tasks._run_ome_tiff_export(
            types.SimpleNamespace(getObject=lambda kind, image_id: None),
            12,
        )
    assert missing_image.value.public_message == "Image 12 not found"
    assert tasks._ims_export_script_module().safe_filename("sample") == "sample"

    status_updates = []
    fake_script = types.SimpleNamespace(
        safe_filename=lambda name, fallback: "sample",
        materialize_ome_tiff_source=lambda conn, image, image_id, root: "",
    )
    monkeypatch.setattr(tasks, "_ims_export_script_module", lambda: fake_script)
    image = types.SimpleNamespace(getName=lambda: "sample")
    with pytest.raises(tasks.OMEExportTaskError) as missing_file:
        tasks._run_ome_tiff_export(
            types.SimpleNamespace(getObject=lambda kind, image_id: image),
            12,
            status_callback=lambda status, meta: status_updates.append((status, meta)),
        )
    assert missing_file.value.public_message == (
        "Could not export selected Image as OME-TIFF"
    )
    assert status_updates == [("running_export", {"export_name": "sample.ome.tif"})]

    image_id = 42
    size_x = 1024
    size_y = 2048
    large_image_message = (
        "Selected Image OME-TIFF export is unsupported for large/pyramidal "
        f"Image {image_id} (sizeX={size_x}, sizeY={size_y}) "
        "by OMERO's standard OME-TIFF exporter."
    )
    fake_script = types.SimpleNamespace(
        safe_filename=lambda name, fallback: "sample",
        materialize_ome_tiff_source=lambda conn, image, image_id, root: (
            _ for _ in ()
        ).throw(
            RuntimeError(
                f"Image:{image_id} is too large for export "
                f"(sizeX={size_x}, sizeY={size_y})"
            )
        ),
        public_ome_tiff_export_failure_message=lambda exc: large_image_message,
    )
    monkeypatch.setattr(tasks, "_ims_export_script_module", lambda: fake_script)
    with pytest.raises(tasks.OMEExportTaskError) as large_image:
        tasks._run_ome_tiff_export(
            types.SimpleNamespace(getObject=lambda kind, image_id: image),
            image_id,
        )
    assert large_image.value.public_message == large_image_message

    closed = []
    updates = []
    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-ome"),
        update_state=lambda state, meta: updates.append((state, meta)),
    )
    owner_marker = "owner-marker"
    monkeypatch.setattr(
        tasks,
        "_open_export_connection",
        lambda session_key, host, port, secure=None: types.SimpleNamespace(
            close=lambda **_kwargs: closed.append(True)
        ),
    )
    monkeypatch.setattr(tasks, "export_task_cancel_requested", lambda task_id: False)
    export_path = str(TEST_RUNTIME_ROOT / "exports" / "image_12" / "sample.ome.tif")
    monkeypatch.setattr(
        tasks,
        "_run_ome_tiff_export",
        lambda *_args, **_kwargs: {
            "Export_Path": export_path,
            "Export_Name": "sample.ome.tif",
        },
    )
    monkeypatch.setattr(tasks, "_serialize_outputs", dict)
    result = tasks.run_ome_tiff_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        owner_token=owner_marker,
    )
    assert result == {
        "state": "FINISHED",
        "outputs": {
            "Export_Path": export_path,
            "Export_Name": "sample.ome.tif",
        },
        "error": None,
        "owner_token": owner_marker,
    }

    monkeypatch.setattr(
        tasks,
        "_run_ome_tiff_export",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            tasks.OMEExportTaskError(
                "private path", public_message="Image 12 not found"
            )
        ),
    )
    result = tasks.run_ome_tiff_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        owner_token=owner_marker,
    )
    assert result == {
        "state": "FAILED",
        "outputs": None,
        "error": "Image 12 not found",
        "public_error": True,
        "owner_token": owner_marker,
    }

    monkeypatch.setattr(
        tasks,
        "_run_ome_tiff_export",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("backend detail")),
    )
    with pytest.raises(RuntimeError, match="backend detail"):
        tasks.run_ome_tiff_export_task(
            task_self,
            image_id=12,
            session_key="session-key",
            host="omeroserver",
            port=4064,
            owner_token=owner_marker,
        )
    assert updates[-1][0] == tasks.states.FAILURE
    assert updates[-1][1]["error"] == "OME-TIFF export job failed."
    assert updates[-1][1]["owner_token"] == owner_marker

    monkeypatch.setattr(tasks, "export_task_cancel_requested", lambda task_id: True)
    result = tasks.run_ome_tiff_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
        owner_token=owner_marker,
    )
    assert result == {
        "state": "CANCELLED",
        "outputs": None,
        "error": "IMS export stopped by user.",
        "owner_token": owner_marker,
    }
    assert len(closed) == 4


def test_ome_tiff_task_logs_close_failures_without_hiding_public_result(
    monkeypatch,
):
    """Verify OME-TIFF task cleanup errors do not replace the public task result.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions that would
    hide a completed task behind a connection-close compatibility failure.
    """
    tasks = _import_tasks(monkeypatch)
    warnings = []
    export_path = str(TEST_RUNTIME_ROOT / "exports" / "image_12" / "close.ome.tif")
    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-ome-close"),
        update_state=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tasks,
        "_open_export_connection",
        lambda session_key, host, port, secure=None: types.SimpleNamespace(
            close=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("close failed"))
        ),
    )
    monkeypatch.setattr(
        tasks,
        "_run_ome_tiff_export",
        lambda *_args, **_kwargs: {
            "Export_Path": export_path,
            "Export_Name": "close.ome.tif",
        },
    )
    monkeypatch.setattr(tasks, "_serialize_outputs", dict)
    monkeypatch.setattr(
        tasks.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message % args),
    )

    result = tasks.run_ome_tiff_export_task(
        task_self,
        image_id=12,
        session_key="session-key",
        host="omeroserver",
        port=4064,
    )

    assert result["state"] == "FINISHED"
    assert warnings == ["Error closing OMERO connection: close failed"]
