from __future__ import annotations

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
