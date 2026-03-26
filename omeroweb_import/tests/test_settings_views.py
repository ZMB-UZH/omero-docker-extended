from __future__ import annotations

import json

import django
from django.conf import settings
from django.test import RequestFactory

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

from omeroweb_import.views import special_method_settings_view, user_settings_view


def test_user_settings_view_hides_store_exception(monkeypatch) -> None:
    request = RequestFactory().post(
        "/omeroweb_import/settings/save/",
        data=json.dumps({"settings": {"chunk_size": 3}}),
        content_type="application/json",
    )

    monkeypatch.setattr(
        user_settings_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        user_settings_view,
        "load_request_data",
        lambda request: {"settings": {"chunk_size": 3}},
    )
    monkeypatch.setattr(
        user_settings_view,
        "save_user_settings",
        lambda username, payload: (_ for _ in ()).throw(
            user_settings_view.UserSettingsStoreError("db password leaked")
        ),
    )

    response = user_settings_view.save_settings(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 500
    assert payload["error"] == "Could not save user settings."
    assert "db password leaked" not in payload["error"]


def test_special_method_save_hides_store_exception(monkeypatch) -> None:
    request = RequestFactory().post(
        "/omeroweb_import/settings/special/save/",
        data=json.dumps({"method": "sem_edx_spectra", "settings": {"enabled": True}}),
        content_type="application/json",
    )

    monkeypatch.setattr(
        special_method_settings_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: {"method": "sem_edx_spectra", "settings": {"enabled": True}},
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "save_special_method_settings",
        lambda username, method_key, payload: (_ for _ in ()).throw(
            special_method_settings_view.UserSettingsStoreError("db password leaked")
        ),
    )

    response = special_method_settings_view.save_settings(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 500
    assert payload["error"] == "Could not save special method settings."
    assert "db password leaked" not in payload["error"]


def test_special_method_load_hides_store_exception(monkeypatch) -> None:
    request = RequestFactory().post(
        "/omeroweb_import/settings/special/load/",
        data=json.dumps({"method": "sem_edx_spectra"}),
        content_type="application/json",
    )

    monkeypatch.setattr(
        special_method_settings_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: {"method": "sem_edx_spectra"},
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_special_method_settings",
        lambda username, method_key: (_ for _ in ()).throw(
            special_method_settings_view.UserSettingsStoreError("db password leaked")
        ),
    )

    response = special_method_settings_view.load_settings(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 500
    assert payload["error"] == "Could not load special method settings."
    assert "db password leaked" not in payload["error"]
