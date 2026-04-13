from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.test import override_settings

from omeroweb_tools.views import index_view


def test_enhanced_search_view_blocks_root_without_running_search(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: (
            captured.update({"template": template, "context": context}) or context
        ),
    )
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "root")
    monkeypatch.setattr(
        index_view,
        "parse_search_query",
        lambda params: (index_view.SearchQuery(query_text="lsm"), []),
    )
    monkeypatch.setattr(
        index_view,
        "search",
        lambda conn, query, acquisition_metadata_enabled: pytest.fail(
            "search must not run for root"
        ),
    )
    monkeypatch.setattr(index_view, "saved_queries", lambda username: ["unexpected"])
    monkeypatch.setattr(
        index_view,
        "ensure_user_index_sync",
        lambda conn, username, settings_payload=None: pytest.fail(
            "auto sync must not run for root"
        ),
    )
    monkeypatch.setattr(
        index_view,
        "runtime_config",
        lambda: SimpleNamespace(max_results=50),
    )

    request = RequestFactory().get("/omeroweb_tools/enhanced-search/?query_text=lsm")
    response = inspect.unwrap(index_view.enhanced_search_view)(request, conn=object())

    assert response["blocked_for_root"] is True
    assert response["saved_queries"] == []
    assert response["user_settings"] == {"acquisition_metadata_enabled": False}
    assert captured["template"] == "omeroweb_tools/enhanced_search.html"


def test_enhanced_search_view_builds_pagination_querystrings(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: captured.update(context) or context,
    )
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(index_view, "saved_queries", lambda username: [])
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": True},
    )
    monkeypatch.setattr(
        index_view,
        "ensure_user_index_sync",
        lambda conn, username, settings_payload=None: (
            [{"scope_key": "user:3", "status": "running"}],
            True,
            "Indexing started.",
        ),
    )
    monkeypatch.setattr(
        index_view,
        "runtime_config",
        lambda: SimpleNamespace(max_results=25),
    )

    query = index_view.SearchQuery(
        query_text="lsm",
        indexed_scope="omero_builtin",
        page=2,
    )
    monkeypatch.setattr(index_view, "parse_search_query", lambda params: (query, []))
    monkeypatch.setattr(
        index_view,
        "search",
        lambda conn, query, acquisition_metadata_enabled: {
            "results": [{"image_id": 1}],
            "page": 2,
            "page_size": 25,
            "total_count": 80,
            "has_previous": True,
            "has_next": True,
        },
    )

    request = RequestFactory().get(
        "/omeroweb_tools/enhanced-search/?query_text=lsm&indexed_scope=omero_builtin&page=2"
    )
    inspect.unwrap(index_view.enhanced_search_view)(request, conn=object())

    assert (
        captured["previous_page_querystring"]
        == "query_text=lsm&indexed_scope=omero_builtin&page=1"
    )
    assert (
        captured["next_page_querystring"]
        == "query_text=lsm&indexed_scope=omero_builtin&page=3"
    )
    assert captured["blocked_for_root"] is False
    assert captured["sync_states"] == [{"scope_key": "user:3", "status": "running"}]
    assert captured["auto_sync_started"] is True
    assert captured["auto_sync_message"] == "Indexing started."


def test_start_scope_sync_view_rejects_root_user(monkeypatch):
    monkeypatch.setattr(
        "omeroweb_tools.views.utils.current_username",
        lambda request, conn: "root",
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data=json.dumps({"scope_key": "project:7"}),
        content_type="application/json",
    )
    response = index_view.start_scope_sync_view(request, conn=object())

    assert response.status_code == 403
    assert b"PLEASE LOGIN AS REGULAR USER" in response.content


def test_start_scope_sync_view_requires_acquisition_indexing(monkeypatch):
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": False},
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data=json.dumps({"scope_key": "project:7"}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.start_scope_sync_view)(request, conn=object())

    assert response.status_code == 409
    assert json.loads(response.content.decode("utf-8")) == {
        "error": (
            "Enable acquisition metadata indexing in Tools settings before "
            "refreshing the acquisition index."
        )
    }


def test_save_user_settings_view_persists_payload(monkeypatch):
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "save_user_settings",
        lambda conn, username, payload: {
            "user_settings": {"acquisition_metadata_enabled": True},
            "sync_started": True,
            "sync_message": "Indexing started.",
            "sync_states": [{"scope_key": "user:3"}],
        },
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/settings/",
        data=json.dumps({"acquisition_metadata_enabled": True}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.save_user_settings_view)(
        request, conn=object()
    )

    assert response.status_code == 200
    assert json.loads(response.content.decode("utf-8")) == {
        "ok": True,
        "user_settings": {"acquisition_metadata_enabled": True},
        "sync_started": True,
        "sync_message": "Indexing started.",
        "sync_states": [{"scope_key": "user:3"}],
    }


def test_start_scope_sync_view_targets_current_user_scope(monkeypatch):
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": True},
    )
    monkeypatch.setattr(
        index_view,
        "current_user_scope",
        lambda conn, username: SimpleNamespace(
            scope_key="user:3", label="Your acquisition metadata"
        ),
    )
    monkeypatch.setattr(
        index_view,
        "request_scope_sync",
        lambda scope_key, requested_by, scope_label=None: (
            scope_key == "user:3"
            and requested_by == "alice"
            and scope_label == "Your acquisition metadata",
            "Indexing started.",
        ),
    )
    monkeypatch.setattr(
        index_view,
        "sync_states_for_user",
        lambda conn, username: [{"scope_key": "user:3", "status": "running"}],
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data=json.dumps({}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.start_scope_sync_view)(
        request,
        conn=object(),
    )

    assert response.status_code == 200
    assert json.loads(response.content.decode("utf-8")) == {
        "ok": True,
        "message": "Indexing started.",
        "sync_states": [{"scope_key": "user:3", "status": "running"}],
    }


def test_start_scope_sync_view_ignores_requested_scope_key(monkeypatch):
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": True},
    )
    monkeypatch.setattr(
        index_view,
        "current_user_scope",
        lambda conn, username: SimpleNamespace(
            scope_key="user:3", label="Your acquisition metadata"
        ),
    )
    requested = {}
    monkeypatch.setattr(
        index_view,
        "request_scope_sync",
        lambda scope_key, requested_by, scope_label=None: (
            requested.update(
                {
                    "scope_key": scope_key,
                    "requested_by": requested_by,
                    "scope_label": scope_label,
                }
            )
            or True,
            "Indexing started.",
        ),
    )
    monkeypatch.setattr(
        index_view,
        "sync_states_for_user",
        lambda conn, username: [{"scope_key": "user:3", "status": "running"}],
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data=json.dumps({"scope_key": "user:999"}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.start_scope_sync_view)(request, conn=object())

    assert response.status_code == 200
    assert requested == {
        "scope_key": "user:3",
        "requested_by": "alice",
        "scope_label": "Your acquisition metadata",
    }


def test_save_query_view_validates_required_payload(monkeypatch):
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps({"query_name": "", "query_payload": []}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.save_query_view)(request, conn=object())

    assert response.status_code == 400
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Query name is required."
    }


def test_apply_saved_query_view_redirects_with_safe_query_string(monkeypatch):
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: [
            {
                "id": 3,
                "query_payload": {
                    "query_text": "Zeiss LSM 980",
                    "indexed_scope": "all_indexed_scopes",
                    "page": 2,
                },
            }
        ],
    )

    request = RequestFactory().get("/omeroweb_tools/enhanced-search/saved-queries/3/")
    with override_settings(ROOT_URLCONF="omeroweb_tools.urls"):
        response = inspect.unwrap(index_view.apply_saved_query_view)(
            request,
            conn=object(),
            query_id=3,
        )

    assert response.status_code == 302
    assert response["Location"].endswith(
        "/enhanced-search/?query_text=Zeiss+LSM+980&indexed_scope=all_indexed_scopes&page=2"
    )
