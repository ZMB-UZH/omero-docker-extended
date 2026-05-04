from __future__ import annotations

import json

import django
from django.conf import settings
from django.http import JsonResponse
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

from omeroweb_import.strings import errors as import_errors
from omeroweb_import.views import (
    special_method_settings_view,
    user_settings_view,
    utils as import_view_utils,
)


def _payload(response):
    """Return the payload.

    Inputs: `response` response object. Output: `loads` result.
    """
    return json.loads(response.content.decode("utf-8"))


def test_import_view_utils_delegate_and_reject_root_users(monkeypatch):
    """Confirm import view utils delegate and reject root users is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when import view utils delegate and reject root users stops reporting the expected error.
    """
    request = RequestFactory().post(
        "/omeroweb_import/settings/save/",
        data=json.dumps({"settings": {"enabled": True}}),
        content_type="application/json",
    )

    monkeypatch.setattr(
        import_view_utils,
        "_load_request_data",
        lambda request: {"delegated": True},
    )
    assert import_view_utils.load_request_data(request) == {"delegated": True}

    error_response = import_view_utils.json_error(
        "invalid request", status=418, extra={"detail": "more context"}
    )
    assert error_response.status_code == 418
    assert _payload(error_response) == {
        "ok": False,
        "error": "invalid request",
        "detail": "more context",
    }

    guarded = import_view_utils.require_non_root_user(
        lambda request, conn=None, url=None, **kwargs: JsonResponse({"ok": True})
    )
    monkeypatch.setattr(
        import_view_utils, "current_username", lambda request, conn: "root"
    )

    forbidden = guarded(RequestFactory().get("/guarded"), conn=object())

    assert forbidden.status_code == 403
    assert (
        _payload(forbidden)["error"]
        == "PLEASE LOGIN AS REGULAR USER\nTO USE THIS PLUGIN"
    )

    monkeypatch.setattr(import_view_utils, "current_username", lambda request, conn: "")
    unresolved = guarded(RequestFactory().get("/guarded"), conn=object())
    assert unresolved.status_code == 403
    assert _payload(unresolved)["error"] == import_errors.unable_to_determine_username()


def test_special_method_settings_cover_non_dict_payload_and_unexpected_save_failure(
    monkeypatch,
):
    """Verify special method settings cover non dict payload and unexpected save failure result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in special method settings cover non dict payload and unexpected save failure.
    """
    request = RequestFactory().post(
        "/omeroweb_import/settings/special/save/",
        data=json.dumps({"method": "sem_edx_spectra", "settings": {"enabled": True}}),
        content_type="application/json",
    )

    assert (
        special_method_settings_view._normalize_special_method_settings(["bad"]) == {}
    )

    monkeypatch.setattr(
        import_view_utils,
        "current_username",
        lambda request, conn: "alice",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "current_username",
        lambda request, conn: "alice",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "load_request_data",
        lambda request: (_ for _ in ()).throw(RuntimeError("save boom")),
    )

    response = special_method_settings_view.save_settings(request, conn=None)

    assert response.status_code == 500
    assert _payload(response)["error"] == import_errors.unexpected_error()


def test_special_method_load_settings_covers_method_username_and_unexpected_errors(
    monkeypatch,
):
    """Verify special method load settings covers method username and unexpected errors.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in special method load settings covers method username and unexpected errors.
    """
    monkeypatch.setattr(
        import_view_utils,
        "current_username",
        lambda request, conn: "alice",
    )

    get_request = RequestFactory().get("/omeroweb_import/settings/special/load/")
    response = special_method_settings_view.load_settings(get_request, conn=None)
    assert response.status_code == 405
    assert _payload(response)["error"] == import_errors.method_post_required()

    post_request = RequestFactory().post(
        "/omeroweb_import/settings/special/load/",
        data=json.dumps({"method": "sem_edx_spectra"}),
        content_type="application/json",
    )
    monkeypatch.setattr(
        special_method_settings_view,
        "current_username",
        lambda request, conn: "",
    )
    response = special_method_settings_view.load_settings(post_request, conn=None)
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
        lambda request: (_ for _ in ()).throw(RuntimeError("load boom")),
    )
    response = special_method_settings_view.load_settings(post_request, conn=None)
    assert response.status_code == 500
    assert _payload(response)["error"] == import_errors.unexpected_error()


def test_user_settings_view_returns_generic_error_on_unexpected_failure(monkeypatch):
    """Confirm user settings view returns generic error on unexpected failure exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when user settings view returns generic error on unexpected failure stops reporting the expected error.
    """
    request = RequestFactory().post(
        "/omeroweb_import/settings/save/",
        data=json.dumps({"settings": {"chunk_size": 3}}),
        content_type="application/json",
    )

    monkeypatch.setattr(
        import_view_utils,
        "current_username",
        lambda request, conn: "alice",
    )
    monkeypatch.setattr(
        user_settings_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        user_settings_view,
        "load_request_data",
        lambda request: (_ for _ in ()).throw(RuntimeError("unexpected failure")),
    )

    response = user_settings_view.save_settings(request, conn=None)

    assert response.status_code == 500
    assert _payload(response)["error"] == import_errors.unexpected_error()
