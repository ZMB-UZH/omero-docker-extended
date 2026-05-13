from __future__ import annotations

import django
import json
import logging
import sys
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
    """Import the views.

    Inputs: none. Output: `views`.
    """
    from omero_imaris_connector import views

    return views


def test_imaris_export_hides_invalid_base_url_exception_text(monkeypatch) -> None:
    """Confirm imaris export hides invalid base URL exception text exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when imaris export hides invalid base URL exception text stops reporting the expected error.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "1", "base_url": "://bad"},
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    response = views.imaris_export(request, conn=None)

    assert response.status_code == 400
    assert response.content.decode("utf-8") == views.INVALID_BASE_URL_MESSAGE


def test_imaris_export_hides_invalid_port_exception_text(monkeypatch) -> None:
    """Confirm imaris export hides invalid port exception text exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when imaris export hides invalid port exception text stops reporting the expected error.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
    """Verify the imaris export capabilities reports OMERO when script is available execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export capabilities reports OMERO when script is available integration.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
        "omero_ims_export_capability": views.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
        "converters": {"OMERO": True, "Imaris": True},
        "omero_ims_export": True,
        "ome_tiff_async_export": True,
    }


def test_imaris_export_capabilities_hides_omero_without_script(monkeypatch) -> None:
    """Verify the imaris export capabilities hides OMERO without script execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export capabilities hides OMERO without script integration.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
        "omero_ims_export_capability": views.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
        "converters": {"OMERO": False, "Imaris": True},
        "omero_ims_export": False,
        "ome_tiff_async_export": True,
    }


def test_imaris_export_capabilities_hides_probe_exceptions(monkeypatch, caplog) -> None:
    """Verify imaris export capabilities hides probe exceptions.

    Inputs: pytest provides `monkeypatch`, `caplog`. Output: fails on regressions in imaris export capabilities hides probe exceptions.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"capabilities": "1"},
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(
        views,
        "_find_script_id",
        lambda conn: (_ for _ in ()).throw(RuntimeError("backend secret")),
    )

    with caplog.at_level(logging.WARNING, logger=views.logger.name):
        response = views.imaris_export(request, conn=SimpleNamespace())
    payload = json.loads(response.content.decode("utf-8"))

    assert response.status_code == 200
    assert payload == {
        "omero_ims_export_capability": views.OMERO_IMS_EXPORT_CAPABILITY_FLAG,
        "converters": {"OMERO": False, "Imaris": True},
        "omero_ims_export": False,
        "ome_tiff_async_export": True,
    }
    assert "backend secret" in caplog.text


def test_imaris_export_hides_job_failure_details(monkeypatch) -> None:
    """Verify imaris export hides job failure details.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export hides job failure details.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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


def test_imaris_export_returns_public_task_failure_messages(monkeypatch) -> None:
    """Verify imaris export returns public task failure messages result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export returns public task failure messages.
    """
    views = _import_views()
    public_error = "Could not prepare source image for IMS conversion"

    status_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"job": "celery-job-public"},
    )
    status_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "FAILED",
            None,
            "internal traceback",
            {"error": public_error, "public_error": True},
        ),
    )
    status_response = views.imaris_export(status_request, conn=None)
    assert status_response.status_code == 200
    status_payload = json.loads(status_response.content.decode("utf-8"))
    assert status_payload["failed"] is True
    assert status_payload["error"] == public_error
    assert "internal traceback" not in status_response.content.decode("utf-8")

    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "FAILED",
            None,
            public_error,
            {"error": public_error, "public_error": True},
        ),
    )
    status_response = views.imaris_export(status_request, conn=None)
    status_payload = json.loads(status_response.content.decode("utf-8"))
    assert status_payload["failed"] is True
    assert status_payload["error"] == public_error

    start_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "1"},
    )
    start_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 1)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda *args, **kwargs: "celery-job-public"
    )
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)
    start_response = views.imaris_export(start_request, conn=SimpleNamespace())
    assert start_response.status_code == 500
    assert start_response.content.decode("utf-8") == public_error


def test_imaris_export_hides_internal_exception_text(monkeypatch) -> None:
    """Confirm imaris export hides internal exception text exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when imaris export hides internal exception text stops reporting the expected error.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
    """Verify imaris export status logs escape user controlled values.

    Inputs: pytest provides `monkeypatch`, `caplog`. Output: fails on regressions in imaris export status logs escape user controlled values.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
    """Verify imaris export start logs escape wait and ip values.

    Inputs: pytest provides `monkeypatch`, `caplog`. Output: fails on regressions in imaris export start logs escape wait and ip values.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
    """Verify imaris view helpers cover URL ip port and session resolution.

    Inputs: Imaris and OMERO fakes. Output: fails on regressions in imaris view helpers cover URL ip port and session resolution.
    """
    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
            "/omero_imaris_connector/export/?job=1",
            base_url_override="https://omero.example.org:4080",
        )
        == "https://omero.example.org:4080/omero_imaris_connector/export/?job=1"
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
    """Verify imaris view helpers cover invalid base URLs and status edge cases.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris view helpers cover invalid base URLs and status edge cases.
    when validation or the called operation fails.
    """
    views = _import_views()

    class _BrokenStr:
        """Test double for broken str behavior in this module."""

        def __str__(self):
            """Return `_BrokenStr` as test-readable text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("bad string")

    with pytest.raises(ValueError, match="Invalid base_url value"):
        views._parse_base_url(_BrokenStr())

    with pytest.raises(ValueError, match="must not include a path"):
        views._parse_base_url("https://omero.example.org/app")

    request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"job": "job-7"},
    )
    request.session = SimpleNamespace(session_key=None)
    assert views.imaris_export(request, conn=None).status_code == 400

    running_download_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
        "/omero_imaris_connector/export/",
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
    """Verify the imaris export sync paths cover missing script wait override and unknown state execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export sync paths cover missing script wait override and unknown state integration.
    """
    views = _import_views()

    missing_script_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "7"},
    )
    missing_script_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: None)
    missing_script = views.imaris_export(missing_script_request, conn=SimpleNamespace())
    assert missing_script.status_code == 500
    assert b"script not found" in missing_script.content

    wait_override_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "7", "async": "1", "wait": "1"},
    )
    wait_override_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 9)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id, **_kwargs: "celery-job-10"
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
        "/omero_imaris_connector/export/",
        data={"image": "7"},
    )
    unknown_state_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id, **_kwargs: "celery-job-11"
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
    """Verify poll celery job covers pending failure success revoked and unknown.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in poll celery job covers pending failure success revoked and unknown.
    """
    views = _import_views()

    def _set_result(state, result=None, info=None):
        """Set the result.

        Inputs: `state`, `result`, `info`. Output: None.
        """
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

    _set_result(
        views.EXPORT_STATE_CANCELLED,
        info={"error": views.IMS_EXPORT_CANCELLED_MESSAGE},
    )
    assert views._poll_celery_job("celery-job-4b") == (
        "CANCELLED",
        None,
        views.IMS_EXPORT_CANCELLED_MESSAGE,
        {"error": views.IMS_EXPORT_CANCELLED_MESSAGE},
    )

    _set_result("CUSTOM", info={"status": "custom"})
    assert views._poll_celery_job("celery-job-5") == (
        "CUSTOM",
        None,
        None,
        {"status": "custom"},
    )


def test_poll_celery_job_handles_malformed_stale_backend_result(monkeypatch):
    """Verify malformed stale Celery results do not break status/cancel flows.

    Inputs: pytest provides `monkeypatch`. Output: fails on stale-result regressions.
    """
    views = _import_views()

    class _BrokenResult:
        """AsyncResult double whose backend properties raise on decode."""

        @property
        def state(self):
            """Raise like Celery does for malformed exception-state results.

            Inputs: none. Output: raises ValueError.
            """
            raise ValueError("Exception information must include the exception type")

    monkeypatch.setattr(
        views.celery_app,
        "AsyncResult",
        lambda task_id: _BrokenResult(),
        raising=False,
    )

    assert views._poll_celery_job("celery-job-6") == (
        "FAILED",
        None,
        views.IMS_EXPORT_JOB_FAILED_MESSAGE,
        None,
    )


def test_start_celery_job_validates_connection_metadata_and_dispatches(monkeypatch):
    """Verify start celery job validates connection metadata and dispatches.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in start celery job validates connection metadata and dispatches.
    """
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
            "ims",
            SimpleNamespace(id="task-123", kwargs=kwargs, queue=queue),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        views.run_ome_tiff_export_task,
        "apply_async",
        lambda kwargs, queue: dispatched.setdefault(
            "ome",
            SimpleNamespace(id="task-456", kwargs=kwargs, queue=queue),
        ),
        raising=False,
    )

    assert views._start_celery_job(SimpleNamespace(), 17) == "celery-task-123"
    assert dispatched["ims"].kwargs == {
        "image_id": 17,
        "session_key": "session-key",
        "host": "omeroserver",
        "port": 4064,
        "secure": True,
        "owner_token": views._hash_job_owner_token("session-key"),
    }
    assert (
        views._start_celery_job(
            SimpleNamespace(),
            18,
            export_format=views.EXPORT_FORMAT_OME_TIFF,
        )
        == "celery-task-456"
    )
    assert dispatched["ome"].kwargs["image_id"] == 18
    assert dispatched["ome"].kwargs["owner_token"] == views._hash_job_owner_token(
        "session-key"
    )

    monkeypatch.setattr(views, "_get_session_key", lambda conn: None)
    with pytest.raises(RuntimeError, match="session key unavailable"):
        views._start_celery_job(SimpleNamespace(), 17)

    monkeypatch.setattr(views, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(
        views, "_resolve_omero_host_port", lambda conn: ("omeroserver", 70000)
    )
    with pytest.raises(RuntimeError, match="out of range"):
        views._start_celery_job(SimpleNamespace(), 17)


def test_export_job_owner_registry_rejects_other_sessions(monkeypatch):
    """Verify export job ownership is session-scoped before task metadata exists.

    Inputs: pytest provides `monkeypatch`. Output: fails on multi-user isolation
    regressions.
    """
    views = _import_views()
    records = {}
    monkeypatch.setattr(
        views.cache,
        "set",
        lambda key, value, timeout=None: records.setdefault(key, value),
    )
    monkeypatch.setattr(views.cache, "get", lambda key: records.get(key))
    monkeypatch.setattr(views, "_get_session_key", lambda conn: conn.session_key)

    job_id = "celery-task-123"
    views._record_export_job_owner(
        job_id,
        views._hash_job_owner_token("session-a"),
    )

    assert views._export_job_belongs_to_current_session(
        job_id,
        SimpleNamespace(session_key="session-a"),
    )
    assert not views._export_job_belongs_to_current_session(
        job_id,
        SimpleNamespace(session_key="session-b"),
    )


def test_remove_queued_redis_task_removes_only_matching_message(monkeypatch):
    """Verify stop removes matching queued Celery messages from the Redis broker.

    Inputs: pytest provides `monkeypatch`. Output: fails on stale queued work
    cancellation regressions.
    """
    views = _import_views()
    removed = []

    class _FakeRedis:
        """Redis list double for queued Celery messages."""

        @staticmethod
        def lrange(queue_key, start, end):
            """Return queued messages.

            Inputs: queue key and range. Output: list of messages.
            """
            assert queue_key == views.CELERY_QUEUE
            assert (start, end) == (0, -1)
            return [b'{"headers":{"id":"other"}}', b'{"headers":{"id":"task-123"}}']

        @staticmethod
        def lrem(queue_key, count, message):
            """Record removed messages.

            Inputs: queue key, count, message. Output: number removed.
            """
            removed.append((queue_key, count, message))
            return 1

    monkeypatch.setattr(
        views.celery_app.conf,
        "broker_url",
        "redis://redis:6379/2",
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "redis",
        SimpleNamespace(Redis=SimpleNamespace(from_url=lambda url: _FakeRedis())),
    )

    result = views._remove_queued_redis_task("task-123")

    assert result["broker_queue_removal_attempted"] is True
    assert result["broker_queue_messages_removed"] == 1
    assert removed == [(views.CELERY_QUEUE, 1, b'{"headers":{"id":"task-123"}}')]


def test_cancel_celery_job_revokes_cli_and_cleans_server_artifacts(
    monkeypatch,
    tmp_path,
):
    """Verify IMS export cancellation revokes work, kills CLI, and cleans safely.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in
    cancellation cleanup and response sanitization.
    """
    views = _import_views()
    export_root = tmp_path / "exports"
    image_dir = export_root / "image_12"
    image_dir.mkdir(parents=True)
    export_path = image_dir / "finished.ims"
    partial_path = image_dir / "partial.ims"
    export_path.write_bytes(b"finished")
    partial_path.write_bytes(b"partial")

    deleted = []
    revoked = []
    stored = []
    forgotten = []
    events = []
    alive = {"345": True}

    class _FakeBackend:
        """Test double for Celery backend result storage."""

        @staticmethod
        def store_result(task_id, payload, state):
            """Record the stored Celery result.

            Inputs: `task_id`, `payload`, `state`. Output: None.
            """
            stored.append((task_id, payload, state))

    monkeypatch.setattr(views, "EXPORT_ROOT", export_root)
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: (
            "RUNNING",
            {"Export_Path": str(export_path), "File_Annotation_Id": "9"},
            None,
            {
                "status": "running_script",
                "image_id": 12,
                "started_at": 0.0,
                "cli_pid": 345,
            },
        ),
    )
    monkeypatch.setattr(
        views.celery_app,
        "AsyncResult",
        lambda task_id: SimpleNamespace(
            backend=_FakeBackend(),
            forget=lambda: forgotten.append(task_id),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        views.celery_app,
        "control",
        SimpleNamespace(
            revoke=lambda task_id, terminate, signal: (
                events.append("revoke"),
                revoked.append((task_id, terminate, signal)),
            )
        ),
        raising=False,
    )
    monkeypatch.setattr(
        views,
        "_is_expected_ims_export_cli_process",
        lambda pid: pid == 345,
    )
    monkeypatch.setattr(
        views,
        "_remove_queued_redis_task",
        lambda task_id: {
            "broker_queue_removal_attempted": True,
            "broker_queue_messages_removed": 1,
        },
    )
    monkeypatch.setattr(
        views,
        "mark_export_task_cancel_requested",
        lambda task_id: events.append("mark_cancel"),
    )

    def _fake_kill(pid, sig):
        """Record expected process termination calls.

        Inputs: `pid`, `sig`. Output: None or raises ProcessLookupError.
        """
        if sig == 0:
            if alive.get(str(pid)):
                return None
            raise ProcessLookupError
        if sig == views.signal.SIGTERM:
            events.append("terminate_cli")
            alive[str(pid)] = False
            return None
        raise AssertionError(f"unexpected signal: {sig}")

    monkeypatch.setattr(views.os, "kill", _fake_kill)

    conn = SimpleNamespace(
        deleteObjects=lambda obj_type, ids, wait: deleted.append((obj_type, ids, wait))
    )

    payload = views._cancel_celery_job("celery-task-123", conn)
    serialized = json.dumps(payload)

    assert payload["cancelled"] is True
    assert payload["cleanup"]["export_file_removed"] is True
    assert payload["cleanup"]["recent_artifacts_removed"] == 1
    assert payload["cleanup"]["file_annotation_removed"] is True
    assert payload["cleanup"]["local_cli_termination_attempted"] is True
    assert payload["cleanup"]["local_cli_process_stopped"] is True
    assert payload["cleanup"]["broker_queue_messages_removed"] == 1
    assert events[:3] == ["mark_cancel", "terminate_cli", "revoke"]
    assert revoked == [("task-123", True, "SIGTERM")]
    assert stored == [
        (
            "task-123",
            {
                "state": views.EXPORT_STATE_CANCELLED,
                "error": views.IMS_EXPORT_CANCELLED_MESSAGE,
            },
            views.EXPORT_STATE_CANCELLED,
        )
    ]
    assert forgotten == ["task-123"]
    assert deleted == [("Annotation", [9], True)]
    assert not export_path.exists()
    assert not partial_path.exists()
    assert str(export_root) not in serialized


def test_terminate_export_cli_process_prefers_process_group(monkeypatch):
    """Verify IMS cancellation terminates the recorded OMERO CLI process group.

    Inputs: pytest provides `monkeypatch`. Output: fails on process-group cancellation
    regressions.
    """
    views = _import_views()
    signals = []
    members = [[345, 346], []]
    monkeypatch.setattr(
        views,
        "_process_group_has_expected_ims_export_cli",
        lambda pgid: pgid == 345,
    )
    monkeypatch.setattr(
        views,
        "_process_group_members",
        lambda pgid: members.pop(0) if members else [],
    )
    monkeypatch.setattr(
        views.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )

    result = views._terminate_export_cli_process(
        {"status": "running_script", "cli_pid": 345, "cli_pgid": 345}
    )

    assert result["local_cli_termination_attempted"] is True
    assert result["local_cli_process_stopped"] is True
    assert signals == [(345, views.signal.SIGTERM)]


def test_expected_ims_export_cli_detection_accepts_python_shebang(monkeypatch):
    """Verify live OMERO CLI shebang processes are recognized for cancellation.

    Inputs: pytest provides `monkeypatch`. Output: fails on process validation
    regressions.
    """
    views = _import_views()
    cmdlines = {
        101: (
            "/opt/omero/web/venv-3.12/bin/python3.12",
            "/opt/omero/web/venv-3.12/bin/omero",
            "script",
            "launch",
            "1002",
            "Image_ID=338",
        ),
        102: ("omero", "script", "launch", "1002"),
        103: ("python3", "/opt/not-omero", "script", "launch"),
        104: ("/opt/omero/web/venv-3.12/bin/omero", "sessions", "list"),
    }
    monkeypatch.setattr(views, "_read_proc_cmdline", lambda pid: cmdlines[int(pid)])

    assert views._is_expected_ims_export_cli_process(101)
    assert views._is_expected_ims_export_cli_process(102)
    assert not views._is_expected_ims_export_cli_process(103)
    assert not views._is_expected_ims_export_cli_process(104)


def test_terminate_process_group_treats_zombie_only_group_as_stopped(monkeypatch):
    """Verify cancelled export groups do not report active work for zombies only.

    Inputs: pytest provides `monkeypatch`. Output: fails on cancellation cleanup
    reporting regressions.
    """
    views = _import_views()
    signals = []
    monkeypatch.setattr(
        views,
        "_process_group_has_expected_ims_export_cli",
        lambda pgid: pgid == 345,
    )
    monkeypatch.setattr(
        views,
        "_process_group_members",
        lambda pgid: [345] if pgid == 345 else [],
    )
    monkeypatch.setattr(views, "_process_is_zombie", lambda pid: True)
    monkeypatch.setattr(
        views.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert views._terminate_process_group(345) is True
    assert signals == [(345, views.signal.SIGTERM)]


def test_imaris_view_helpers_cover_env_fallbacks_and_unknown_status_paths(
    monkeypatch,
) -> None:
    """Verify imaris view helpers cover env fallbacks and unknown status paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris view helpers cover env fallbacks and unknown status paths.
    when validation or the called operation fails.
    """
    views = _import_views()
    original_poll_celery_job = views._poll_celery_job

    class _BrokenStr:
        """Test double for broken str behavior in this module."""

        def __str__(self):
            """Return `_BrokenStr` as test-readable text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
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
        "/omero_imaris_connector/export/",
        data={"image": "7"},
    )
    request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 9)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id, **_kwargs: "celery-job-12"
    )
    time_values = iter([0.0, views.EXPORT_TIMEOUT + 1.0])
    monkeypatch.setattr(views.time, "time", lambda: next(time_values, 0.0))
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)
    unknown_status = views.imaris_export(request, conn=SimpleNamespace())
    assert unknown_status.status_code == 500
    assert b"Could not determine IMS export job status" in unknown_status.content

    failing_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
        """Test double for broken result behavior in this module."""

        def __str__(self):
            """Return `_BrokenResult` as test-readable text.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
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
    """Verify imaris export covers async status download and sync success paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export covers async status download and sync success paths.
    """
    views = _import_views()

    async_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "7", "async": "1", "base_url": "https://omero.example.org"},
    )
    async_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 9)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id, **_kwargs: "celery-job-7"
    )
    async_response = views.imaris_export(async_request, conn=SimpleNamespace())
    async_payload = json.loads(async_response.content)
    assert async_payload == {
        "job_id": "celery-job-7",
        "status_url": "https://omero.example.org/omero_imaris_connector/export/?job=celery-job-7&base_url=https%3A%2F%2Fomero.example.org",
    }

    status_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
        "https://omero.example.org/omero_imaris_connector/export/?job=celery-job-7&download=1"
    )

    download_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
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
        "/omero_imaris_connector/export/",
        data={"image": "7"},
    )
    sync_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id, **_kwargs: "celery-job-8"
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
    """Confirm imaris export rejects missing image invalid image no celery and timeout is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris export rejects missing image invalid image no celery and timeout.
    """
    views = _import_views()

    missing_request = RequestFactory().get("/omero_imaris_connector/export/")
    missing_request.session = SimpleNamespace(session_key=None)
    assert views.imaris_export(missing_request, conn=None).status_code == 400

    invalid_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "bad"},
    )
    invalid_request.session = SimpleNamespace(session_key=None)
    assert views.imaris_export(invalid_request, conn=None).status_code == 400

    no_celery_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "1"},
    )
    no_celery_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: False)
    assert (
        views.imaris_export(no_celery_request, conn=SimpleNamespace()).status_code
        == 500
    )

    timeout_request = RequestFactory().get(
        "/omero_imaris_connector/export/",
        data={"image": "1"},
    )
    timeout_request.session = SimpleNamespace(session_key=None)
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 7)
    monkeypatch.setattr(
        views, "_start_celery_job", lambda conn, image_id, **_kwargs: "celery-job-9"
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
    """Verify imaris view failure paths cover meta errors missing host port and port validation.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris view failure paths cover meta errors missing host port and port validation.
    """
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

    monkeypatch.setattr(
        views.celery_app,
        "AsyncResult",
        lambda task_id: SimpleNamespace(
            state=views.celery_states.SUCCESS,
            result={
                "state": "FAILED",
                "outputs": None,
                "error": "Image 7 not found",
                "public_error": True,
            },
            info={
                "state": "FAILED",
                "outputs": None,
                "error": "Image 7 not found",
                "public_error": True,
            },
        ),
        raising=False,
    )
    assert views._poll_celery_job("celery-job-15") == (
        "FAILED",
        None,
        "Image 7 not found",
        {
            "state": "FAILED",
            "outputs": None,
            "error": "Image 7 not found",
            "public_error": True,
        },
    )

    with pytest.raises(ValueError, match="out of range"):
        views._parse_port_param("70000")

    monkeypatch.setattr(views, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(views, "_resolve_omero_host_port", lambda conn: (None, None))
    monkeypatch.setattr(views, "_resolve_omero_secure", lambda conn: True)
    with pytest.raises(RuntimeError, match="host/port unavailable"):
        views._start_celery_job(SimpleNamespace(), 19)
