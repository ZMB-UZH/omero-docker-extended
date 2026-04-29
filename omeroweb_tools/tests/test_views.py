from __future__ import annotations

import hashlib
import inspect
import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.test import override_settings

from omeroweb_tools.views import index_view, utils as view_utils


def test_enhanced_search_view_blocks_root_without_running_search(monkeypatch):
    """Verify test enhanced search view blocks root without behavior."""
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
    assert response["user_settings"] == {
        "acquisition_metadata_enabled": False,
        "collapsed_sections": [],
    }
    assert response["metadata_index_collapsed"] is False
    assert response["saved_queries_collapsed"] is False
    assert response["user_settings_available"] is True
    assert response["indexed_scope_storage_key"] == (
        "omeroweb_tools:enhanced_search:indexed_scope:"
        f"{hashlib.sha256(b'root').hexdigest()}"
    )
    assert (
        response["acquisition_index_status"]
        == "Universal metadata indexing is disabled for your user account."
    )
    assert captured["template"] == "omeroweb_tools/enhanced_search.html"


def test_enhanced_search_view_blocks_unresolved_user_without_store_access(monkeypatch):
    """Verify test enhanced search view blocks unresolved u behavior."""
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: context,
    )
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "")
    monkeypatch.setattr(
        index_view,
        "parse_search_query",
        lambda params: (index_view.SearchQuery(query_text="lsm"), []),
    )
    monkeypatch.setattr(
        index_view,
        "search",
        lambda conn, query, acquisition_metadata_enabled: pytest.fail(
            "search must not run without a resolved user"
        ),
    )
    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: pytest.fail("saved queries must not load without a user"),
    )
    monkeypatch.setattr(
        index_view,
        "ensure_user_index_sync",
        lambda conn, username, settings_payload=None: pytest.fail(
            "auto sync must not run without a resolved user"
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
    assert response["indexed_scope_storage_key"] == (
        "omeroweb_tools:enhanced_search:indexed_scope:"
        f"{hashlib.sha256(b'').hexdigest()}"
    )


def test_enhanced_search_view_builds_pagination_querystrings(monkeypatch):
    """Verify test enhanced search view builds pagination q behavior."""
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
        lambda username: {
            "acquisition_metadata_enabled": True,
            "collapsed_sections": ["metadata-index", "saved-queries"],
        },
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
    assert captured["user_settings_available"] is True
    assert captured["metadata_index_collapsed"] is True
    assert captured["saved_queries_collapsed"] is True
    assert captured["sync_states"] == [{"scope_key": "user:3", "status": "running"}]
    assert captured["auto_sync_started"] is True
    assert captured["auto_sync_message"] == "Indexing started."
    assert captured["indexed_scope_storage_key"] == (
        "omeroweb_tools:enhanced_search:indexed_scope:"
        f"{hashlib.sha256(b'alice').hexdigest()}"
    )


def test_enhanced_search_view_handles_settings_store_failure(monkeypatch):
    """Verify test enhanced search view handles settings st behavior."""
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
        lambda username: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )
    monkeypatch.setattr(
        index_view,
        "ensure_user_index_sync",
        lambda conn, username, settings_payload=None: pytest.fail(
            "auto sync must not run when settings are unavailable"
        ),
    )
    monkeypatch.setattr(
        index_view, "parse_search_query", lambda params: (index_view.SearchQuery(), [])
    )
    monkeypatch.setattr(
        index_view,
        "runtime_config",
        lambda: SimpleNamespace(max_results=25),
    )

    request = RequestFactory().get("/omeroweb_tools/enhanced-search/")
    response = inspect.unwrap(index_view.enhanced_search_view)(request, conn=object())

    assert response["user_settings"] == {
        "acquisition_metadata_enabled": False,
        "collapsed_sections": [],
    }
    assert response["metadata_index_collapsed"] is False
    assert response["saved_queries_collapsed"] is False
    assert response["user_settings_available"] is False
    assert response["acquisition_index_status_state"] == "error"
    assert (
        response["acquisition_index_status"]
        == "Could not retrieve user setting. Database is not accessible."
    )


def test_start_scope_sync_view_rejects_root_user(monkeypatch):
    """Verify test start scope sync view rejects root user."""
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
    """Verify test start scope sync view requires acquisiti behavior."""
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
            "Enable universal metadata indexing in Tools settings before "
            "refreshing the metadata index."
        )
    }


def test_start_scope_sync_view_returns_database_error_when_settings_unavailable(
    monkeypatch,
):
    """Verify test start scope sync view returns database e behavior."""
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data=json.dumps({}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.start_scope_sync_view)(request, conn=object())

    assert response.status_code == 503
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Could not retrieve user setting. Database is not accessible."
    }


def test_save_user_settings_view_persists_payload(monkeypatch):
    """Verify test save user settings view persists payload."""
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "save_user_settings",
        lambda conn, username, payload: {
            "user_settings": {
                "acquisition_metadata_enabled": True,
                "collapsed_sections": ["metadata-index"],
            },
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
        "user_settings": {
            "acquisition_metadata_enabled": True,
            "collapsed_sections": ["metadata-index"],
        },
        "sync_started": True,
        "sync_message": "Indexing started.",
        "sync_states": [{"scope_key": "user:3"}],
    }


def test_save_user_settings_view_returns_database_error_message(monkeypatch):
    """Verify test save user settings view returns database behavior."""
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "save_user_settings",
        lambda conn, username, payload: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/settings/",
        data=json.dumps({"acquisition_metadata_enabled": True}),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.save_user_settings_view)(
        request, conn=object()
    )

    assert response.status_code == 503
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Could not save user setting. Database is not accessible."
    }


def test_start_scope_sync_view_targets_current_user_scope(monkeypatch):
    """Verify test start scope sync view targets current us behavior."""
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
            scope_key="user:3", label="Your universal metadata index"
        ),
    )
    monkeypatch.setattr(
        index_view,
        "request_scope_sync",
        lambda scope_key, requested_by, scope_label=None: (
            scope_key == "user:3"
            and requested_by == "alice"
            and scope_label == "Your universal metadata index",
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
    """Verify test start scope sync view ignores requested behavior."""
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
            scope_key="user:3", label="Your universal metadata index"
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
        "scope_label": "Your universal metadata index",
    }


def test_save_query_view_validates_required_payload(monkeypatch):
    """Verify test save query view validates required payload."""
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


def test_save_query_view_rejects_overlong_query_names(monkeypatch):
    """Verify test save query view rejects overlong query n behavior."""
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps(
            {
                "query_name": "x" * (index_view.SAVED_QUERY_NAME_MAX_LENGTH + 1),
                "query_payload": {"query_text": "lsm"},
            }
        ),
        content_type="application/json",
    )

    response = inspect.unwrap(index_view.save_query_view)(request, conn=object())

    assert response.status_code == 400
    assert json.loads(response.content.decode("utf-8")) == {
        "error": index_view.SAVED_QUERY_NAME_TOO_LONG_ERROR
    }


def test_apply_saved_query_view_redirects_with_safe_query_string(monkeypatch):
    """Verify test apply saved query view redirects with sa behavior."""
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


def test_validate_user_password_closes_session_after_success(monkeypatch):
    """Verify test validate user password closes session af behavior."""
    closed = []
    credential_value = "opaque-value"

    class _Client:
        """Represent client."""

        @staticmethod
        def createSession(username, provided_value):
            """Build create session."""
            assert username == "alice"
            assert provided_value == credential_value

        @staticmethod
        def closeSession():
            """Handle close session."""
            closed.append(True)

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        view_utils,
        "resolve_omero_host_port",
        lambda conn: ("omeroserver", 4064),
    )
    monkeypatch.setattr(view_utils.omero, "client", lambda host, port: _Client())

    valid, error = view_utils.validate_user_password(object(), credential_value)

    assert valid is True
    assert error is None
    assert closed == [True]


def test_validate_user_password_does_not_close_session_when_login_fails(monkeypatch):
    """Verify test validate user password does not close se behavior."""
    closed = []
    credential_value = "opaque-value"

    class _Client:
        """Represent client."""

        @staticmethod
        def createSession(username, provided_value):
            """Build create session."""
            assert provided_value == credential_value
            raise RuntimeError("nope")

        @staticmethod
        def closeSession():
            """Handle close session."""
            closed.append(True)

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        view_utils,
        "resolve_omero_host_port",
        lambda conn: ("omeroserver", 4064),
    )
    monkeypatch.setattr(view_utils.omero, "client", lambda host, port: _Client())

    valid, error = view_utils.validate_user_password(object(), credential_value)

    assert valid is False
    assert error == view_utils.AUTH_VALIDATION_FAILED_ERROR
    assert closed == []


def test_validate_user_password_suppresses_close_failure_after_success(monkeypatch):
    """Verify test validate user password suppresses close behavior."""
    credential_value = "opaque-value"

    class _Client:
        """Represent client."""

        @staticmethod
        def createSession(username, provided_value):
            """Build create session."""
            assert username == "alice"
            assert provided_value == credential_value

        @staticmethod
        def closeSession():
            """Handle close session."""
            raise RuntimeError("close failed")

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        view_utils,
        "resolve_omero_host_port",
        lambda conn: ("omeroserver", 4064),
    )
    monkeypatch.setattr(view_utils.omero, "client", lambda host, port: _Client())

    valid, error = view_utils.validate_user_password(object(), credential_value)

    assert valid is True
    assert error is None
