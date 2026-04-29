from __future__ import annotations

import json

import django
import pytest
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

from omeroweb_import.views import (
    special_method_settings_view,
    user_settings_view,
    utils as import_view_utils,
)
from omeroweb_import.strings import errors as import_errors
from omeroweb_import.strings import messages as import_messages


def _payload(response):
    """Handle payload."""
    return json.loads(response.content.decode("utf-8"))


@pytest.fixture(autouse=True)
def _regular_wrapper_user(monkeypatch):
    """Handle regular wrapper user."""
    monkeypatch.setattr(
        import_view_utils,
        "current_username",
        lambda request, conn: "alice",
    )


def test_user_settings_view_saves_payload_and_returns_normalized_response(
    monkeypatch,
) -> None:
    """Verify test user settings view saves payload and ret behavior."""
    request = RequestFactory().post(
        "/omeroweb_import/settings/save/",
        data=json.dumps({"settings": {"chunk_size": 3, "preserve_paths": True}}),
        content_type="application/json",
    )
    saved = {}

    monkeypatch.setattr(
        user_settings_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        user_settings_view,
        "load_request_data",
        lambda request: {"settings": {"chunk_size": 3, "preserve_paths": True}},
    )
    monkeypatch.setattr(
        user_settings_view,
        "save_user_settings",
        lambda username, payload: saved.update(
            {"username": username, "payload": payload.copy()}
        ),
    )

    response = user_settings_view.save_settings(request, conn=None)

    assert response.status_code == 200
    assert _payload(response) == {
        "success": True,
        "message": import_messages.user_settings_saved(),
        "settings": {"chunk_size": 3, "preserve_paths": True},
    }
    assert saved == {
        "username": "alice",
        "payload": {"chunk_size": 3, "preserve_paths": True},
    }


def test_user_settings_view_rejects_invalid_method_username_and_payload(
    monkeypatch,
) -> None:
    """Verify test user settings view rejects invalid metho behavior."""
    request = RequestFactory().get("/omeroweb_import/settings/save/")

    response = user_settings_view.save_settings(request, conn=None)
    assert response.status_code == 405
    assert _payload(response)["error"] == import_errors.method_post_required()

    request = RequestFactory().post(
        "/omeroweb_import/settings/save/",
        data=json.dumps({"settings": {}}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        user_settings_view, "current_username", lambda request, conn: ""
    )
    response = user_settings_view.save_settings(request, conn=None)
    assert response.status_code == 400
    assert _payload(response)["error"] == import_errors.unable_to_determine_username()

    monkeypatch.setattr(
        user_settings_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        user_settings_view,
        "load_request_data",
        lambda request: {"settings": ["not-a-dict"]},
    )
    response = user_settings_view.save_settings(request, conn=None)
    assert response.status_code == 400
    assert _payload(response)["error"] == import_errors.invalid_user_settings_payload()


def test_user_settings_view_hides_store_exception(monkeypatch) -> None:
    """Verify test user settings view hides store exception."""
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
    payload = _payload(response)

    assert response.status_code == 500
    assert payload["error"] == "Could not save user settings."
    assert "db password leaked" not in payload["error"]


def test_special_method_save_hides_store_exception(monkeypatch) -> None:
    """Verify test special method save hides store exception."""
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
    payload = _payload(response)

    assert response.status_code == 500
    assert payload["error"] == "Could not save special method settings."
    assert "db password leaked" not in payload["error"]


def test_special_method_load_hides_store_exception(monkeypatch) -> None:
    """Verify test special method load hides store exception."""
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
    payload = _payload(response)

    assert response.status_code == 500
    assert payload["error"] == "Could not load special method settings."
    assert "db password leaked" not in payload["error"]


def test_special_method_settings_views_normalize_and_load_payloads(
    monkeypatch,
) -> None:
    """Verify test special method settings views normalize behavior."""
    save_request = RequestFactory().post(
        "/omeroweb_import/settings/special/save/",
        data=json.dumps(
            {
                "method": "sem_edx_spectra",
                "settings": {"enabled": 1, "create_tables": "", "notes": "yes"},
            }
        ),
        content_type="application/json",
    )
    load_request = RequestFactory().post(
        "/omeroweb_import/settings/special/load/",
        data=json.dumps({"method": "sem_edx_spectra"}),
        content_type="application/json",
    )
    saved = {}

    monkeypatch.setattr(
        special_method_settings_view,
        "current_username",
        lambda request, conn: "alice",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: (
            {
                "method": "sem_edx_spectra",
                "settings": {"enabled": 1, "create_tables": "", "notes": "yes"},
            }
            if request is save_request
            else {"method": "sem_edx_spectra"}
        ),
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "save_special_method_settings",
        lambda username, method_key, payload: saved.update(
            {
                "username": username,
                "method_key": method_key,
                "payload": payload.copy(),
            }
        ),
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_special_method_settings",
        lambda username, method_key: {"enabled": True, "create_tables": False},
    )

    save_response = special_method_settings_view.save_settings(save_request, conn=None)
    load_response = special_method_settings_view.load_settings(load_request, conn=None)

    assert save_response.status_code == 200
    assert _payload(save_response) == {
        "success": True,
        "message": import_messages.special_method_settings_saved_db(),
        "settings": {
            "enabled": 1,
            "create_tables": "",
            "notes": "yes",
        },
    }
    assert saved == {
        "username": "alice",
        "method_key": "sem_edx_spectra",
        "payload": {
            "enabled": 1,
            "create_tables": "",
            "notes": "yes",
        },
    }

    assert load_response.status_code == 200
    assert _payload(load_response) == {
        "success": True,
        "settings": {"enabled": True, "create_tables": False},
    }


def test_special_method_settings_views_reject_invalid_requests(monkeypatch) -> None:
    """Verify test special method settings views reject inv behavior."""
    get_request = RequestFactory().get("/omeroweb_import/settings/special/save/")
    response = special_method_settings_view.save_settings(get_request, conn=None)
    assert response.status_code == 405
    assert _payload(response)["error"] == import_errors.method_post_required()

    request = RequestFactory().post(
        "/omeroweb_import/settings/special/save/",
        data=json.dumps({"method": "", "settings": []}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "current_username",
        lambda request, conn: "",
    )
    response = special_method_settings_view.save_settings(request, conn=None)
    assert response.status_code == 400
    assert _payload(response)["error"] == import_errors.unable_to_determine_username()

    monkeypatch.setattr(
        special_method_settings_view,
        "current_username",
        lambda request, conn: "alice",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: {"method": "", "settings": []},
    )
    response = special_method_settings_view.save_settings(request, conn=None)
    assert response.status_code == 400
    assert _payload(response)["error"] == import_errors.invalid_special_method_key()

    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: {"method": "sem_edx_spectra", "settings": []},
    )
    response = special_method_settings_view.save_settings(request, conn=None)
    assert response.status_code == 400
    assert _payload(response)["error"] == (
        import_errors.invalid_special_method_settings_payload()
    )

    load_request = RequestFactory().post(
        "/omeroweb_import/settings/special/load/",
        data=json.dumps({"method": ""}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: {"method": ""},
    )
    response = special_method_settings_view.load_settings(load_request, conn=None)
    assert response.status_code == 400
    assert _payload(response)["error"] == import_errors.invalid_special_method_key()
