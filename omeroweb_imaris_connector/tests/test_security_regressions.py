from __future__ import annotations

import json
import sys
import types
import urllib.parse
from pathlib import Path

import pytest


TEST_RUNTIME_ROOT = Path(__file__).resolve().parent / "_runtime"


class _BaseResponse:
    """Represent base response."""

    def __init__(self, content="", status=200, content_type=None):
        self.status_code = status
        self.content_type = content_type
        self.headers = {}
        if isinstance(content, bytes):
            self.content = content
        else:
            self.content = str(content).encode("utf-8")

    def __setitem__(self, key, value):
        self.headers[key] = value

    def __getitem__(self, key):
        return self.headers[key]


class _JsonResponse(_BaseResponse):
    """Represent JSON response."""

    def __init__(self, payload=None, status=200, **_kwargs):
        self.payload = payload
        super().__init__(
            json.dumps(payload or {}).encode("utf-8"),
            status=status,
            content_type="application/json",
        )


class _HttpResponse(_BaseResponse):
    """Represent HTTP response."""

    pass


class _HttpResponseBadRequest(_HttpResponse):
    """Represent HTTP response bad request."""

    def __init__(self, content="Bad Request", **kwargs):
        super().__init__(content, status=400, **kwargs)


class _DummyQueryDict(dict):
    """Test double for dummy query dict."""

    def urlencode(self):
        """Handle urlencode."""
        return urllib.parse.urlencode(self)


class _DummyRequest:
    """Test double for dummy request."""

    def __init__(self, query: dict[str, str], path: str = "/imaris/export/"):
        self.GET = _DummyQueryDict(query)
        self.path = path
        self.META = {}
        self.session = types.SimpleNamespace(session_key=None)

    @staticmethod
    def build_absolute_uri(path: str) -> str:
        """Build build absolute uri."""
        return f"https://omero.example.org{path}"


def _install_django_stubs() -> None:
    """Handle install django stubs."""
    django_module = types.ModuleType("django")
    django_http = types.ModuleType("django.http")
    django_http.JsonResponse = _JsonResponse
    django_http.HttpResponse = _HttpResponse
    django_http.HttpResponseBadRequest = _HttpResponseBadRequest
    sys.modules["django"] = django_module
    sys.modules["django.http"] = django_http


def _install_omero_stubs() -> None:
    """Handle install OMERO stubs."""
    omero_module = types.ModuleType("omero")
    omero_module.ClientError = type("ClientError", (Exception,), {})
    omero_module.SecurityViolation = type("SecurityViolation", (Exception,), {})
    omero_module.NoProcessorAvailable = type("NoProcessorAvailable", (Exception,), {})
    omero_module.client = lambda host, port: types.SimpleNamespace(
        joinSession=lambda session_key: types.SimpleNamespace(
            detachOnDestroy=lambda: None
        )
    )

    omero_gateway = types.ModuleType("omero.gateway")
    omero_gateway.BlitzGateway = type("BlitzGateway", (), {})

    omero_rtypes = types.ModuleType("omero.rtypes")
    omero_rtypes.rint = lambda value: value

    sys.modules["omero"] = omero_module
    sys.modules["omero.gateway"] = omero_gateway
    sys.modules["omero.rtypes"] = omero_rtypes


def _install_celery_stubs() -> None:
    """Handle install celery stubs."""
    celery_module = types.ModuleType("celery")

    class _DummyCelery:
        """Test double for dummy celery."""

        def __init__(self, *_args, **_kwargs):
            self.conf = types.SimpleNamespace(update=lambda **_kwargs: None)

        @staticmethod
        def autodiscover_tasks(*_args, **_kwargs):
            """Handle autodiscover tasks."""
            return None

        @staticmethod
        def task(*args, **kwargs):
            """Handle task."""

            def _decorator(fn):
                """Handle decorator."""
                return fn

            return _decorator

    celery_module.Celery = _DummyCelery
    celery_module.states = types.SimpleNamespace(
        PENDING="PENDING",
        RECEIVED="RECEIVED",
        STARTED="STARTED",
        FAILURE="FAILURE",
        IGNORED="IGNORED",
        SUCCESS="SUCCESS",
        REVOKED="REVOKED",
    )
    sys.modules["celery"] = celery_module


def _install_omeroweb_stub() -> None:
    """Handle install omeroweb stub."""
    omeroweb_module = types.ModuleType("omeroweb")
    decorators_module = types.ModuleType("omeroweb.decorators")
    decorators_module.login_required = lambda *args, **kwargs: lambda view: view
    sys.modules["omeroweb"] = omeroweb_module
    sys.modules["omeroweb.decorators"] = decorators_module


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handle set required env."""
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
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _import_modules(monkeypatch: pytest.MonkeyPatch):
    """Handle import modules."""
    _set_required_env(monkeypatch)
    _install_django_stubs()
    _install_omero_stubs()
    _install_celery_stubs()
    _install_omeroweb_stub()

    for module_name in [
        "omeroweb_imaris_connector.config",
        "omeroweb_imaris_connector.celery_app",
        "omeroweb_imaris_connector.imaris_service",
        "omeroweb_imaris_connector.tasks",
        "omeroweb_imaris_connector.views",
    ]:
        sys.modules.pop(module_name, None)

    from omeroweb_imaris_connector import tasks, views

    return tasks, views


def test_imaris_export_ignores_request_backend_override_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test imaris export ignores request backend ov behavior."""
    _tasks, views = _import_modules(monkeypatch)
    request = _DummyRequest(
        {
            "image": "42",
            "async": "1",
            "omero_host": "169.254.169.254",
            "omero_port": "4444",
            "omero_secure": "0",
        }
    )
    conn = object()
    captured = {}

    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 7)
    monkeypatch.setattr(
        views,
        "_start_celery_job",
        lambda actual_conn, image_id: (
            captured.update({"conn": actual_conn, "image_id": image_id})
            or "celery-job-1"
        ),
    )
    monkeypatch.setattr(
        views,
        "_build_absolute_url",
        lambda request, path, base_url_override=None: (
            f"https://omero.example.org{path}"
        ),
    )

    response = views.imaris_export(request, conn=conn)

    assert response.status_code == 200
    assert captured == {"conn": conn, "image_id": 42}
    assert json.loads(response.content.decode("utf-8")) == {
        "job_id": "celery-job-1",
        "status_url": "https://omero.example.org/imaris/export/?job=celery-job-1",
    }


def test_imaris_export_status_hides_backend_failure_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test imaris export status hides backend failu behavior."""
    _tasks, views = _import_modules(monkeypatch)
    request = _DummyRequest({"job": "celery-123"})

    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "FAILED",
            None,
            "super-secret backend error",
            {"status": "FAILED"},
        ),
    )

    response = views.imaris_export(request, conn=None)

    assert response.status_code == 200
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["failed"] is True
    assert payload["error"] == "IMS export job failed."
    assert "super-secret" not in response.content.decode("utf-8")


def test_build_failure_meta_uses_generic_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test build failure meta uses generic error me behavior."""
    tasks, _views = _import_modules(monkeypatch)

    payload = tasks._build_failure_meta(RuntimeError("database password leaked"))

    assert payload["error"] == "IMS export job failed."
    assert payload["exc_message"] == "IMS export job failed."
    assert "password leaked" not in json.dumps(payload)


def test_run_ims_export_task_prefers_user_session_key_for_cli_even_in_job_service_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test run IMS export task prefers user session behavior."""
    tasks, _views = _import_modules(monkeypatch)
    captured = {}
    dummy_conn = types.SimpleNamespace(
        getSessionId=lambda: "job-service-session",
        close=lambda: None,
    )
    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-1"),
        update_state=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(tasks, "use_job_service_session", lambda: True)
    monkeypatch.setattr(
        tasks, "_open_job_service_connection", lambda *args, **kwargs: dummy_conn
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda conn: 99)
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **kwargs: (
            captured.update(kwargs)
            or {"Export_Path": str(TEST_RUNTIME_ROOT / "export.ims")}
        ),
    )

    result = tasks.run_ims_export_task(
        task_self,
        image_id=5,
        session_key="user-session",
        host="omero.internal",
        port=4064,
        secure=True,
    )

    assert result["state"] == "FINISHED"
    assert captured["session_key"] == "user-session"
    assert "username" not in captured
    assert "password" not in captured


def test_run_ims_export_task_uses_cli_with_user_session_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test run IMS export task uses cli with user s behavior."""
    tasks, _views = _import_modules(monkeypatch)
    captured = {}
    dummy_conn = types.SimpleNamespace(close=lambda: None)
    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-2"),
        update_state=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(tasks, "use_job_service_session", lambda: False)
    monkeypatch.setattr(
        tasks, "_open_session_connection", lambda *args, **kwargs: dummy_conn
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda conn: 101)
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **kwargs: (
            captured.update(kwargs)
            or {"Export_Path": str(TEST_RUNTIME_ROOT / "export.ims")}
        ),
    )

    result = tasks.run_ims_export_task(
        task_self,
        image_id=6,
        session_key="user-session",
        host="omero.internal",
        port=4064,
        secure=True,
    )

    assert result["state"] == "FINISHED"
    assert captured["session_key"] == "user-session"
    assert captured["script_id"] == 101
    assert captured["image_id"] == 6


def test_run_ims_export_task_uses_job_service_session_key_when_user_session_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test run IMS export task uses job service ses behavior."""
    tasks, _views = _import_modules(monkeypatch)
    captured = {}
    dummy_conn = types.SimpleNamespace(
        getSessionId=lambda: "job-service-session",
        close=lambda: None,
    )
    task_self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="task-3"),
        update_state=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(tasks, "use_job_service_session", lambda: True)
    monkeypatch.setattr(
        tasks, "_open_job_service_connection", lambda *args, **kwargs: dummy_conn
    )
    monkeypatch.setattr(tasks, "_find_script_id", lambda conn: 202)
    monkeypatch.setattr(
        tasks,
        "_run_script_via_omero_cli",
        lambda **kwargs: (
            captured.update(kwargs)
            or {"Export_Path": str(TEST_RUNTIME_ROOT / "export.ims")}
        ),
    )

    result = tasks.run_ims_export_task(
        task_self,
        image_id=7,
        session_key=None,
        host="omero.internal",
        port=4064,
        secure=True,
    )

    assert result["state"] == "FINISHED"
    assert captured["session_key"] == "job-service-session"
    assert captured["script_id"] == 202
    assert captured["image_id"] == 7
