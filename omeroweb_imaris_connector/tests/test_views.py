from __future__ import annotations

import logging
from types import SimpleNamespace

from django.test import RequestFactory


def _import_views():
    from omeroweb_imaris_connector import views

    return views


def test_imaris_export_hides_invalid_base_url_exception_text(monkeypatch) -> None:
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


def test_imaris_export_hides_job_failure_details(monkeypatch) -> None:
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1"},
    )
    request.session = SimpleNamespace(session_key=None)
    conn = SimpleNamespace()

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 1)
    monkeypatch.setattr(views, "_start_celery_job", lambda *args, **kwargs: "celery-job-1")
    monkeypatch.setattr(
        views,
        "_poll_celery_job",
        lambda job_id: ("FAILED", None, "traceback secret", {"error": "traceback secret"}),
    )
    monkeypatch.setattr(views.time, "sleep", lambda *_args: None)

    response = views.imaris_export(request, conn=conn)

    assert response.status_code == 500
    assert response.content.decode("utf-8") == views.IMS_EXPORT_JOB_FAILED_MESSAGE


def test_imaris_export_hides_internal_exception_text(monkeypatch) -> None:
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


def test_imaris_export_status_logs_escape_user_controlled_values(monkeypatch, caplog) -> None:
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
    assert "IMS export status request job_id=celery-job\\\\nforged from 203.0.113.5\\\\nspoofed" in caplog.text
    assert "job_id=celery-job\nforged" not in caplog.text


def test_imaris_export_start_logs_escape_wait_and_ip_values(monkeypatch, caplog) -> None:
    request = RequestFactory().get(
        "/omeroweb_imaris_connector/export/",
        data={"image": "1", "async": "1", "wait": "0\nline"},
        HTTP_X_FORWARDED_FOR="198.51.100.8\nspoofed",
    )
    request.session = SimpleNamespace(session_key=None)

    views = _import_views()
    monkeypatch.setattr(views, "use_celery", lambda: True)
    monkeypatch.setattr(views, "_find_script_id", lambda conn: 7)
    monkeypatch.setattr(views, "_start_celery_job", lambda *_args, **_kwargs: "celery-job-1")

    with caplog.at_level(logging.INFO, logger=views.logger.name):
        response = views.imaris_export(request, conn=SimpleNamespace())

    assert response.status_code == 200
    assert "IMS export request image_id=1 async=True wait_param=0\\\\nline from 198.51.100.8\\\\nspoofed" in caplog.text
    assert "wait_param=0\nline" not in caplog.text
