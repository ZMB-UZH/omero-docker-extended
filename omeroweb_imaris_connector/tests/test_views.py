from __future__ import annotations

import django
import json
import logging
from types import SimpleNamespace

from django.conf import settings
from django.test import RequestFactory
from iter_test_helpers import next_or_fail
import pytest

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


def _import_views():
    """Handle import views."""
    from omeroweb_imaris_connector import views

    return views


def test_imaris_export_hides_invalid_base_url_exception_text(monkeypatch) -> None:
    """Verify test imaris export hides invalid base URL exc behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1", "base_url": "://bad"},
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    response = views.imaris_export(request, conn=None)

    assert response.status_code == 400
    assert response.content.decode("utf-8") == views.INVALID_BASE_URL_MESSAGE


def test_imaris_export_hides_invalid_port_exception_text(monkeypatch) -> None:
    """Verify test imaris export hides invalid port excepti behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1", "omero_port": "bad-port"},
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)

    response = views.imaris_export(request, conn=SimpleNamespace())

    assert response.status_code == 400
    assert response.content.decode("utf-8") == views.INVALID_OMERO_PORT_MESSAGE


def test_imaris_export_capabilities_reports_omero_when_script_is_available(
    monkeypatch,
) -> None:
    """Verify test imaris export capabilities reports OMERO behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"capabilities": "1"},
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 1301)

    response = views.imaris_export(request, conn=SimpleNamespace())
    payload = json.loads(response.content.decode("utf-8"))

    assert response.status_code == 200
    assert payload == {
        "converters": {"OMERO": True, "Imaris": True},
        "omero_ims_export": True,
    }


def test_imaris_export_capabilities_hides_omero_without_script(monkeypatch) -> None:
    """Verify test imaris export capabilities hides OMERO w behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"capabilities": "1"},
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: None)

    response = views.imaris_export(request, conn=SimpleNamespace())
    payload = json.loads(response.content.decode("utf-8"))

    assert response.status_code == 200
    assert payload == {
        "converters": {"OMERO": False, "Imaris": True},
        "omero_ims_export": False,
    }


def test_imaris_export_hides_job_failure_details(monkeypatch) -> None:
    """Verify test imaris export hides job failure details."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1"},
    )
    request.session = SimpleNamespace(session_key=None)
    conn = SimpleNamespace()

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 1)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda *args, **kwargs: "celery-job-1"
    )
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "FAILED",
            None,
            "traceback secret",
            {"error": "traceback secret"},
        ),
    )
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)

    response = views.imaris_export(request, conn=conn)

    assert response.status_code == 500
    assert response.content.decode("utf-8") == views.IMS_EXPORT_JOB_FAILED_MESSAGE


def test_imaris_export_hides_internal_exception_text(monkeypatch) -> None:
    """Verify test imaris export hides internal exception text."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1"},
    )
    request.session = SimpleNamespace(session_key=None)
    conn = SimpleNamespace()

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 1)
    monkeypatch.setattr(
        views,
        "_start_celery_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("backend secret")),
    )

    response = views.imaris_export(request, conn=conn)

    assert response.status_code == 500
    assert response.content.decode("utf-8") == views.IMS_EXPORT_FAILED_MESSAGE


def test_imaris_export_status_logs_escape_user_controlled_values(
    monkeypatch, caplog
) -> None:
    """Verify test imaris export status logs escape user co behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"job": "celery-job\nforged"},
        HTTP_X_FORWARDED_FOR="203.0.113.5\nspoofed",
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("RUNNING", None, None, None),
    )

    with caplog.at_level(logging.DEBUG, logger=views.logger.name):
        response = views.imaris_export(request, conn=None)

    assert response.status_code == 200
    assert (
        "IMS export status request job_id=celery-job\\\\nforged from 203.0.113.5\\\\nspoofed"
        in caplog.text
    )
    assert "job_id=celery-job\nforged" not in caplog.text


def test_imaris_export_start_logs_escape_wait_and_ip_values(
    monkeypatch, caplog
) -> None:
    """Verify test imaris export start logs escape wait and behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1", "async": "1", "wait": "0\nline"},
        HTTP_X_FORWARDED_FOR="198.51.100.8\nspoofed",
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 7)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda *_args, **_kwargs: "celery-job-1"
    )

    with caplog.at_level(logging.INFO, logger=views.logger.name):
        response = views.imaris_export(request, conn=SimpleNamespace())

    assert response.status_code == 200
    assert (
        "IMS export request image_id=1 async=True wait_param=0\\\\nline from 198.51.100.8\\\\nspoofed"
        in caplog.text
    )
    assert "wait_param=0\nline" not in caplog.text


def test_imaris_view_helpers_cover_url_ip_port_and_session_resolution() -> None:
    """Verify test imaris view helpers cover URL ip port an behavior."""
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        HTTP_X_FORWARDED_FOR="203.0.113.5, 198.51.100.1",
    )
    request.session = SimpleNamespace(session_key=None)
    views = _import_views()

    assert views._parse_base_url("https://omero.example.org:4080") == (
        "https://omero.example.org:4080"
    )
    assert (
        views._build_absolute_url(
            request,
            "/omeroweb_imaris_connector/export/?job=1",
            base_url_override="https://omero.example.org:4080",
        )
        == "https://omero.example.org:4080/omeroweb_imaris_connector/export/?job=1"
    )
    assert views._get_client_ip(request) == "203.0.113.5"
    assert views._parse_port_param(" 4064 ") == 4064
    assert views._parse_port_param("") is None
    assert (
        views._get_session_key(
            SimpleNamespace(
                getSessionId=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                c=SimpleNamespace(getSessionId=lambda: "session-2"),
            )
        )
        == "session-2"
    )


def test_imaris_view_helpers_cover_invalid_base_urls_and_status_edge_cases(
    monkeypatch,
):
    """Verify test imaris view helpers cover invalid base U behavior."""
    views = _import_views()

    class _BrokenStr:
        """Represent broken str."""

        def __str__(self):
            raise RuntimeError("bad string")

    with pytest.raises(ValueError, match="Invalid base_url value"):
        views._parse_base_url(_BrokenStr())

    with pytest.raises(ValueError, match="must not include a path"):
        views._parse_base_url("https://omero.example.org/app")

    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"job": "job-7"},
    )
    request.session = SimpleNamespace(session_key=None)
    assert views.imaris_export(request, conn=None).status_code == 400

    running_download_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"job": "celery-job-7", "download": "1"},
    )
    running_download_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("RUNNING", None, None, {"job_state": "queued"}),
    )
    running_download = views.imaris_export(running_download_request, conn=None)
    assert running_download.status_code == 409

    timeout_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"job": "celery-job-8"},
    )
    timeout_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("TIMEOUT", None, None, {"job_state": "timed out"}),
    )
    timeout_response = views.imaris_export(timeout_request, conn=None)
    timeout_payload = json.loads(timeout_response.content)
    assert timeout_payload == {
        "job_id": "celery-job-8",
        "state": "TIMEOUT",
        "finished": False,
        "failed": True,
        "status": "timed out",
        "error": views.IMS_EXPORT_JOB_FAILED_MESSAGE,
    }


def test_imaris_export_sync_paths_cover_missing_script_wait_override_and_unknown_state(
    monkeypatch,
) -> None:
    """Verify test imaris export sync paths cover missing s behavior."""
    views = _import_views()

    missing_script_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "7"},
    )
    missing_script_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: None)
    missing_script = views.imaris_export(missing_script_request, conn=SimpleNamespace())
    assert missing_script.status_code == 500
    assert b"script not found" in missing_script.content

    wait_override_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "7", "async": "1", "wait": "1"},
    )
    wait_override_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 9)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id: "celery-job-10"
    )
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("FINISHED", {}, None, None),
    )
    monkeypatch.setattr(
        views,
        "_build_download_response",
        lambda conn, outputs, export_name=None: views.HttpResponse(
            export_name or "missing"
        ),
    )
    wait_override = views.imaris_export(wait_override_request, conn=SimpleNamespace())
    assert wait_override.content.decode("utf-8") == "missing"

    unknown_state_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "7"},
    )
    unknown_state_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id: "celery-job-11"
    )
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("RUNNING", None, None, None),
    )
    time_values = iter([0.0, 0.0, views.EXPORT_TIMEOUT + 1.0])
    monkeypatch.setattr(views.time, "time", lambda: next_or_fail(time_values))
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)
    unknown_state = views.imaris_export(unknown_state_request, conn=SimpleNamespace())
    assert unknown_state.status_code == 504


def test_poll_celery_job_covers_pending_failure_success_revoked_and_unknown(
    monkeypatch,
):
    """Verify test poll celery job covers pending failure s behavior."""
    views = _import_views()

    def _set_result(state, result=None, info=None):
        """Handle set result."""
        monkeypatch.setattr(
            views.celery_app,
            "AsyncResult",
            lambda task_id: SimpleNamespace(state=state, result=result, info=info),
            raising=False,
        )

    _set_result(views.celery_states.PENDING)
    assert views._poll_celery_job("celery-job-1") == ("RUNNING", None, None, None)

    _set_result(views.celery_states.FAILURE, result=RuntimeError("boom"), info={})
    state, outputs, error, meta = views._poll_celery_job("celery-job-2")
    assert (state, outputs, meta) == ("FAILED", None, {})
    assert "boom" in error

    _set_result(
        views.celery_states.SUCCESS,
        result={"state": "FINISHED", "outputs": {"Export_Name": "demo.ims"}},
        info={"status": "finished"},
    )
    assert views._poll_celery_job("celery-job-3") == (
        "FINISHED",
        {"Export_Name": "demo.ims"},
        None,
        {"status": "finished"},
    )

    _set_result(views.celery_states.REVOKED, info={"status": "cancelled"})
    assert views._poll_celery_job("celery-job-4") == (
        "CANCELLED",
        None,
        "Job was cancelled",
        {"status": "cancelled"},
    )

    _set_result("CUSTOM", info={"status": "custom"})
    assert views._poll_celery_job("celery-job-5") == (
        "CUSTOM",
        None,
        None,
        {"status": "custom"},
    )


def test_start_celery_job_validates_connection_metadata_and_dispatches(monkeypatch):
    """Verify test start celery job validates connection me behavior."""
    views = _import_views()
    dispatched = {}
    monkeypatch.setattr(views, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(
        views, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064)
    )
    monkeypatch.setattr(views, "_resolve_omero_secure", lambda conn: True)
    monkeypatch.setattr(
        views.run_ims_export_task,
        "apply_async",
        lambda kwargs, queue: dispatched.setdefault(
            "result",
            SimpleNamespace(id="task-123", kwargs=kwargs, queue=queue),
        ),
        raising=False,
    )

    assert views._start_celery_job(SimpleNamespace(), 17) == "celery-task-123"
    assert dispatched["result"].kwargs == {
        "image_id": 17,
        "session_key": "session-key",
        "host": "omeroserver",
        "port": 4064,
        "secure": True,
    }

    monkeypatch.setattr(views, "_get_session_key", lambda conn: None)
    with pytest.raises(RuntimeError, match="session key unavailable"):
        views._start_celery_job(SimpleNamespace(), 17)

    monkeypatch.setattr(views, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(
        views, "_resolve_omero_host_port", lambda conn: ("omeroserver", 70000)
    )
    with pytest.raises(RuntimeError, match="out of range"):
        views._start_celery_job(SimpleNamespace(), 17)


def test_imaris_view_helpers_cover_env_fallbacks_and_unknown_status_paths(
    monkeypatch,
) -> None:
    """Verify test imaris view helpers cover env fallbacks behavior."""
    views = _import_views()
    original_poll_celery_job = views._poll_celery_job

    class _BrokenStr:
        """Represent broken str."""

        def __str__(self):
            raise RuntimeError("bad string")

    assert views._parse_base_url(None) is None
    assert views._parse_base_url("   ") is None
    assert views._parse_port_param(_BrokenStr()) is None

    assert views._get_session_key(None) is None
    assert (
        views._get_session_key(SimpleNamespace(getSessionId=lambda: "session-1"))
        == "session-1"
    )
    assert views._get_session_key(SimpleNamespace(_sessionUuid="session-2")) == (
        "session-2"
    )
    assert (
        views._get_session_key(
            SimpleNamespace(
                getSessionId=lambda: "",
                c=SimpleNamespace(
                    getSessionId=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
                ),
            )
        )
        is None
    )

    monkeypatch.setattr(
        views,
        "get_env",
        lambda key, env_file=None: {
            "OMEROHOST": "env-host",
            "OMERO_PORT": "4064",
            "CONFIG_omero_security_ssl": "yes",
        }.get(key),
    )
    assert views._resolve_omero_host_port(SimpleNamespace(host=None, port=None)) == (
        "env-host",
        4064,
    )
    assert views._resolve_omero_host_port(
        SimpleNamespace(host="direct", port="   ")
    ) == (
        "direct",
        None,
    )
    assert views._resolve_omero_host_port(SimpleNamespace(host=None, port="bad")) == (
        "env-host",
        None,
    )
    assert views._resolve_omero_secure(SimpleNamespace(secure=False)) is False
    assert views._resolve_omero_secure(SimpleNamespace(secure=None)) is True

    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "7"},
    )
    request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 9)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id: "celery-job-12"
    )
    time_values = iter([0.0, views.EXPORT_TIMEOUT + 1.0])
    monkeypatch.setattr(views.time, "time", lambda: next(time_values, 0.0))
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)
    unknown_status = views.imaris_export(request, conn=SimpleNamespace())
    assert unknown_status.status_code == 500
    assert b"Could not determine IMS export job status" in unknown_status.content

    failing_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "8"},
    )
    failing_request.session = SimpleNamespace(session_key=None)
    time_values = iter([0.0, 0.0, 0.2])
    monkeypatch.setattr(views.time, "time", lambda: next(time_values, 0.2))
    poll_results = iter(
        [
            ("RUNNING", None, None, {"error": "meta-error"}),
            ("FAILED", None, None, None),
        ]
    )
    monkeypatch.setattr(
        views, "_poll_celery_job", lambda job_id: next_or_fail(poll_results)
    )
    failed = views.imaris_export(failing_request, conn=SimpleNamespace())
    assert failed.status_code == 500
    assert failed.content.decode("utf-8") == views.IMS_EXPORT_JOB_FAILED_MESSAGE

    class _BrokenResult:
        """Represent broken result."""

        def __str__(self):
            raise RuntimeError("cannot stringify")

    monkeypatch.setattr(
        views.celery_app,
        "AsyncResult",
        lambda task_id: SimpleNamespace(
            state=views.celery_states.FAILURE,
            result=_BrokenResult(),
            info={},
        ),
        raising=False,
    )
    monkeypatch.setattr(views, "_poll_celery_job", original_poll_celery_job)
    assert views._poll_celery_job("celery-job-13") == (
        "FAILED",
        None,
        "Unknown error",
        {},
    )


def test_imaris_export_covers_async_status_download_and_sync_success_paths(monkeypatch):
    """Verify test imaris export covers async status downlo behavior."""
    views = _import_views()

    async_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "7", "async": "1", "base_url": "https://omero.example.org"},
    )
    async_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 9)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id: "celery-job-7"
    )
    async_response = views.imaris_export(async_request, conn=SimpleNamespace())
    async_payload = json.loads(async_response.content)
    assert async_payload == {
        "job_id": "celery-job-7",
        "status_url": "https://omero.example.org/omeroweb_imaris_connector/export/?job=celery-job-7&base_url=https%3A%2F%2Fomero.example.org",
    }

    status_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"job": "celery-job-7", "base_url": "https://omero.example.org"},
    )
    status_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "FINISHED",
            {"Export_Name": "demo.ims"},
            None,
            {"status": "complete"},
        ),
    )
    status_response = views.imaris_export(status_request, conn=None)
    status_payload = json.loads(status_response.content)
    assert status_payload["finished"] is True
    assert status_payload["status"] == "complete"
    assert status_payload["download_url"] == (
        "https://omero.example.org/omeroweb_imaris_connector/export/?job=celery-job-7&download=1"
    )

    download_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"job": "celery-job-7", "download": "1"},
    )
    download_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views,
        "_build_download_response",
        lambda conn, outputs: views.HttpResponse("downloaded"),
    )
    download_response = views.imaris_export(download_request, conn=SimpleNamespace())
    assert download_response.content.decode("utf-8") == "downloaded"

    sync_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "7"},
    )
    sync_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id: "celery-job-8"
    )
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "FINISHED",
            {"Export_Name": "demo.ims"},
            None,
            {"status": "done"},
        ),
    )
    monkeypatch.setattr(
        views,
        "_build_download_response",
        lambda conn, outputs, export_name=None: views.HttpResponse(
            export_name or "missing"
        ),
    )
    sync_response = views.imaris_export(sync_request, conn=SimpleNamespace())
    assert sync_response.content.decode("utf-8") == "demo.ims"


def test_imaris_export_rejects_missing_image_invalid_image_no_celery_and_timeout(
    monkeypatch,
) -> None:
    """Verify test imaris export rejects missing image inva behavior."""
    views = _import_views()

    missing_request = RequestFactory().get("/omeroweb_imaris_connector/export/")
    missing_request.session = SimpleNamespace(session_key=None)
    assert views.imaris_export(missing_request, conn=None).status_code == 400

    invalid_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "bad"},
    )
    invalid_request.session = SimpleNamespace(session_key=None)
    assert views.imaris_export(invalid_request, conn=None).status_code == 400

    no_celery_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1"},
    )
    no_celery_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: False)
    assert (
        views.imaris_export(no_celery_request, conn=SimpleNamespace()).status_code
        == 500
    )

    timeout_request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1"},
    )
    timeout_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 7)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id: "celery-job-9"
    )
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("RUNNING", None, None, {"status": "running"}),
    )
    time_values = iter([0.0, 0.0, views.EXPORT_TIMEOUT + 1.0])
    monkeypatch.setattr(views.time, "time", lambda: next_or_fail(time_values))
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)
    assert (
        views.imaris_export(timeout_request, conn=SimpleNamespace()).status_code == 504
    )


def test_imaris_view_failure_paths_cover_meta_errors_missing_host_port_and_port_validation(
    monkeypatch,
) -> None:
    """Verify test imaris view failure paths cover meta err behavior."""
    views = _import_views()

    monkeypatch.setattr(
        views.celery_app,
        "AsyncResult",
        lambda task_id: SimpleNamespace(
            state=views.celery_states.FAILURE,
            result=RuntimeError("ignored"),
            info={"error": "meta boom"},
        ),
        raising=False,
    )
    assert views._poll_celery_job("celery-job-14") == (
        "FAILED",
        None,
        "meta boom",
        {"error": "meta boom"},
    )

    with pytest.raises(ValueError, match="out of range"):
        views._parse_port_param("70000")

    monkeypatch.setattr(views, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(views, "_resolve_omero_host_port", lambda conn: (None, None))
    monkeypatch.setattr(views, "_resolve_omero_secure", lambda conn: True)
    with pytest.raises(RuntimeError, match="host/port unavailable"):
        views._start_celery_job(SimpleNamespace(), 19)
