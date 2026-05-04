from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from django.test import RequestFactory
from django.test import override_settings

from omeroweb_tools.views import index_view, utils as view_utils


def test_index_and_root_status_reflect_current_root_state(monkeypatch):
    """Verify index and root status reflect current root state.

    Inputs: `monkeypatch`. Output: None.
    """
    captured = {}
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: (
            captured.update({"template": template, "context": context}) or context
        ),
    )
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "root")

    request = RequestFactory().get("/omeroweb_tools/")
    index_response = inspect.unwrap(index_view.index)(request, conn=object())
    status_response = inspect.unwrap(index_view.root_status)(request, conn=object())

    assert captured["template"] == "omeroweb_tools/index.html"
    assert index_response["blocked_for_root"] is True
    assert json.loads(status_response.content.decode("utf-8")) == {"is_root_user": True}


def test_start_scope_sync_view_rejects_bad_method_bad_json_and_unknown_current_user(
    monkeypatch,
):
    """Verify start scope sync view rejects bad method bad JSON and unknown current user.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": True},
    )
    monkeypatch.setattr(index_view, "current_user_scope", lambda conn, username: None)

    get_request = RequestFactory().get("/omeroweb_tools/enhanced-search/sync/")
    get_response = inspect.unwrap(index_view.start_scope_sync_view)(
        get_request,
        conn=object(),
    )
    assert get_response.status_code == 405

    bad_request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data="{",
        content_type="application/json",
    )
    bad_response = inspect.unwrap(index_view.start_scope_sync_view)(
        bad_request,
        conn=object(),
    )
    assert bad_response.status_code == 400

    missing_scope_request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/sync/",
        data=json.dumps({}),
        content_type="application/json",
    )
    missing_scope_response = inspect.unwrap(index_view.start_scope_sync_view)(
        missing_scope_request,
        conn=object(),
    )
    assert missing_scope_response.status_code == 400
    assert json.loads(missing_scope_response.content.decode("utf-8")) == {
        "error": "Could not resolve the current OMERO user."
    }


def test_sync_state_view_returns_current_refresh_state(monkeypatch):
    """Verify sync state view returns current refresh state.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": True},
    )
    monkeypatch.setattr(
        index_view,
        "ensure_user_index_sync",
        lambda conn, username, settings_payload=None: (
            [{"scope_key": "user:7", "status": "running"}],
            True,
            "Indexing started.",
        ),
    )

    request = RequestFactory().get("/omeroweb_tools/enhanced-search/sync-state/")
    response = inspect.unwrap(index_view.sync_state_view)(request, conn=object())

    assert json.loads(response.content.decode("utf-8")) == {
        "sync_states": [{"scope_key": "user:7", "status": "running"}],
        "auto_sync_started": True,
        "auto_sync_message": "Indexing started.",
    }


def test_sync_state_view_returns_database_error_when_settings_unavailable(monkeypatch):
    """Verify sync state view returns database error when settings unavailable.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        index_view,
        "user_settings",
        lambda username: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )

    request = RequestFactory().get("/omeroweb_tools/enhanced-search/sync-state/")
    response = inspect.unwrap(index_view.sync_state_view)(request, conn=object())

    assert response.status_code == 503
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Could not retrieve user setting. Database is not accessible."
    }


def test_enhanced_search_view_treats_corrupt_collapsed_sections_as_empty(monkeypatch):
    """Verify enhanced search view treats corrupt collapsed sections as empty.

    Inputs: `monkeypatch`. Output: None.
    """
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
            "collapsed_sections": "metadata-index",
        },
    )
    monkeypatch.setattr(
        index_view,
        "ensure_user_index_sync",
        lambda conn, username, settings_payload=None: ([], False, "ready"),
    )
    monkeypatch.setattr(
        index_view,
        "runtime_config",
        lambda: SimpleNamespace(max_results=25),
    )
    monkeypatch.setattr(
        index_view,
        "parse_search_query",
        lambda params: (index_view.SearchQuery(query_text="lsm"), []),
    )
    monkeypatch.setattr(
        index_view,
        "search",
        lambda conn, query, acquisition_metadata_enabled: {
            "results": [],
            "page": 1,
            "page_size": 25,
            "total_count": 0,
            "has_previous": False,
            "has_next": False,
        },
    )

    request = RequestFactory().get("/omeroweb_tools/enhanced-search/?query_text=lsm")
    inspect.unwrap(index_view.enhanced_search_view)(request, conn=object())

    assert captured["metadata_index_collapsed"] is False
    assert captured["saved_queries_collapsed"] is False


def test_save_user_settings_view_rejects_non_post_and_invalid_json(monkeypatch):
    """Verify save user settings view rejects non post and invalid JSON.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")

    get_request = RequestFactory().get("/omeroweb_tools/enhanced-search/settings/")
    get_response = inspect.unwrap(index_view.save_user_settings_view)(
        get_request,
        conn=object(),
    )
    assert get_response.status_code == 405

    bad_request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/settings/",
        data="{",
        content_type="application/json",
    )
    bad_response = inspect.unwrap(index_view.save_user_settings_view)(
        bad_request,
        conn=object(),
    )
    assert bad_response.status_code == 400
    list_payload_request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/settings/",
        data=json.dumps([]),
        content_type="application/json",
    )
    list_payload_response = inspect.unwrap(index_view.save_user_settings_view)(
        list_payload_request,
        conn=object(),
    )
    assert list_payload_response.status_code == 400
    assert json.loads(list_payload_response.content.decode("utf-8")) == {
        "error": view_utils.JSON_OBJECT_REQUIRED_ERROR
    }


def test_saved_query_views_cover_validation_delete_and_fallback_redirect(
    monkeypatch,
):
    """Verify saved query views cover validation delete and fallback redirect.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")

    save_bad_method = RequestFactory().get(
        "/omeroweb_tools/enhanced-search/saved-queries/save/"
    )
    save_bad_method_response = inspect.unwrap(index_view.save_query_view)(
        save_bad_method,
        conn=object(),
    )
    assert save_bad_method_response.status_code == 405

    save_bad_json = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data="{",
        content_type="application/json",
    )
    save_bad_json_response = inspect.unwrap(index_view.save_query_view)(
        save_bad_json,
        conn=object(),
    )
    assert save_bad_json_response.status_code == 400
    save_list_payload = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps([]),
        content_type="application/json",
    )
    save_list_payload_response = inspect.unwrap(index_view.save_query_view)(
        save_list_payload,
        conn=object(),
    )
    assert save_list_payload_response.status_code == 400
    assert json.loads(save_list_payload_response.content.decode("utf-8")) == {
        "error": view_utils.JSON_OBJECT_REQUIRED_ERROR
    }

    save_bad_payload = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps({"query_name": "My query", "query_payload": []}),
        content_type="application/json",
    )
    save_bad_payload_response = inspect.unwrap(index_view.save_query_view)(
        save_bad_payload,
        conn=object(),
    )
    assert save_bad_payload_response.status_code == 400
    assert json.loads(save_bad_payload_response.content.decode("utf-8")) == {
        "error": "Query payload is required."
    }

    delete_bad_method = RequestFactory().get(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/"
    )
    delete_bad_method_response = inspect.unwrap(index_view.delete_query_view)(
        delete_bad_method,
        conn=object(),
    )
    assert delete_bad_method_response.status_code == 405

    delete_bad_json = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data="{",
        content_type="application/json",
    )
    delete_bad_json_response = inspect.unwrap(index_view.delete_query_view)(
        delete_bad_json,
        conn=object(),
    )
    assert delete_bad_json_response.status_code == 400
    delete_list_payload = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps([]),
        content_type="application/json",
    )
    delete_list_payload_response = inspect.unwrap(index_view.delete_query_view)(
        delete_list_payload,
        conn=object(),
    )
    assert delete_list_payload_response.status_code == 400
    assert json.loads(delete_list_payload_response.content.decode("utf-8")) == {
        "error": view_utils.JSON_OBJECT_REQUIRED_ERROR
    }

    delete_bad_id = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({"query_id": "bad"}),
        content_type="application/json",
    )
    delete_bad_id_response = inspect.unwrap(index_view.delete_query_view)(
        delete_bad_id,
        conn=object(),
    )
    assert delete_bad_id_response.status_code == 400

    delete_missing_id = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({}),
        content_type="application/json",
    )
    delete_missing_id_response = inspect.unwrap(index_view.delete_query_view)(
        delete_missing_id,
        conn=object(),
    )
    assert delete_missing_id_response.status_code == 400
    delete_bool_id = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({"query_id": True}),
        content_type="application/json",
    )
    delete_bool_id_response = inspect.unwrap(index_view.delete_query_view)(
        delete_bool_id,
        conn=object(),
    )
    assert delete_bool_id_response.status_code == 400

    monkeypatch.setattr(
        index_view, "remove_saved_query", lambda username, query_id: False
    )
    delete_missing = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({"query_id": 5}),
        content_type="application/json",
    )
    delete_missing_response = inspect.unwrap(index_view.delete_query_view)(
        delete_missing,
        conn=object(),
    )
    assert delete_missing_response.status_code == 404

    monkeypatch.setattr(
        index_view,
        "remove_saved_query",
        lambda username, query_id: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )
    delete_failed = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({"query_id": 5}),
        content_type="application/json",
    )
    delete_failed_response = inspect.unwrap(index_view.delete_query_view)(
        delete_failed,
        conn=object(),
    )
    assert delete_failed_response.status_code == 503
    assert json.loads(delete_failed_response.content.decode("utf-8")) == {
        "error": index_view.SAVED_QUERY_DELETE_ERROR
    }

    monkeypatch.setattr(
        index_view, "remove_saved_query", lambda username, query_id: True
    )
    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: [{"id": 9, "query_name": "Saved"}],
    )
    delete_ok = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({"query_id": 9}),
        content_type="application/json",
    )
    delete_ok_response = inspect.unwrap(index_view.delete_query_view)(
        delete_ok,
        conn=object(),
    )
    assert json.loads(delete_ok_response.content.decode("utf-8")) == {
        "ok": True,
        "saved_queries": [{"id": 9, "query_name": "Saved"}],
    }

    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )
    delete_reload_failed = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/delete/",
        data=json.dumps({"query_id": 9}),
        content_type="application/json",
    )
    delete_reload_failed_response = inspect.unwrap(index_view.delete_query_view)(
        delete_reload_failed,
        conn=object(),
    )
    assert delete_reload_failed_response.status_code == 503
    assert json.loads(delete_reload_failed_response.content.decode("utf-8")) == {
        "error": index_view.SAVED_QUERY_LOAD_ERROR
    }

    monkeypatch.setattr(index_view, "saved_queries", lambda username: [{"id": 3}])
    fallback_request = RequestFactory().get(
        "/omeroweb_tools/enhanced-search/saved-queries/999/"
    )
    with override_settings(ROOT_URLCONF="omeroweb_tools.urls"):
        fallback_response = inspect.unwrap(index_view.apply_saved_query_view)(
            fallback_request,
            conn=object(),
            query_id=999,
        )
    assert fallback_response.status_code == 302
    assert fallback_response["Location"].endswith("/enhanced-search/")

    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )
    with override_settings(ROOT_URLCONF="omeroweb_tools.urls"):
        fallback_db_response = inspect.unwrap(index_view.apply_saved_query_view)(
            fallback_request,
            conn=object(),
            query_id=999,
        )
    assert fallback_db_response.status_code == 302
    assert fallback_db_response["Location"].endswith("/enhanced-search/")


def test_save_query_view_returns_saved_queries_after_success(monkeypatch):
    """Verify save query view returns saved queries after success.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    saved = []
    monkeypatch.setattr(
        index_view,
        "save_query",
        lambda username, query_name, query_payload: saved.append(
            (username, query_name, query_payload)
        ),
    )
    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: [{"id": 1, "query_name": "My query"}],
    )

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps(
            {"query_name": "My query", "query_payload": {"query_text": "lsm"}}
        ),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.save_query_view)(request, conn=object())

    assert json.loads(response.content.decode("utf-8")) == {
        "ok": True,
        "saved_queries": [{"id": 1, "query_name": "My query"}],
    }
    assert saved == [
        (
            "alice",
            "My query",
            {
                "query_text": "lsm",
                "indexed_scope": "all_indexed_scopes",
                "page": 1,
            },
        )
    ]


def test_save_query_view_normalizes_name_and_handles_store_failure(monkeypatch):
    """Verify save query view normalizes name and handles store failure.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    saved = []
    monkeypatch.setattr(
        index_view,
        "save_query",
        lambda username, query_name, query_payload: saved.append(
            (username, query_name, query_payload)
        ),
    )
    monkeypatch.setattr(index_view, "saved_queries", lambda username: [{"id": 1}])

    request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps(
            {
                "query_name": "  My\tquery\nname  ",
                "query_payload": {"query_text": "lsm"},
            }
        ),
        content_type="application/json",
    )
    response = inspect.unwrap(index_view.save_query_view)(request, conn=object())

    assert response.status_code == 200
    assert saved == [
        (
            "alice",
            "My query name",
            {
                "query_text": "lsm",
                "indexed_scope": "all_indexed_scopes",
                "page": 1,
            },
        )
    ]

    invalid_payload_request = RequestFactory().post(
        "/omeroweb_tools/enhanced-search/saved-queries/save/",
        data=json.dumps(
            {
                "query_name": "Invalid query",
                "query_payload": {"indexed_scope": "deleted_scope"},
            }
        ),
        content_type="application/json",
    )
    invalid_payload_response = inspect.unwrap(index_view.save_query_view)(
        invalid_payload_request,
        conn=object(),
    )
    assert invalid_payload_response.status_code == 400
    assert json.loads(invalid_payload_response.content.decode("utf-8")) == {
        "error": index_view.SAVED_QUERY_PAYLOAD_INVALID_ERROR
    }

    monkeypatch.setattr(
        index_view,
        "save_query",
        lambda username, query_name, query_payload: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )
    failed_response = inspect.unwrap(index_view.save_query_view)(request, conn=object())
    assert failed_response.status_code == 503
    assert json.loads(failed_response.content.decode("utf-8")) == {
        "error": index_view.SAVED_QUERY_SAVE_ERROR
    }

    monkeypatch.setattr(index_view, "save_query", lambda *args: None)
    monkeypatch.setattr(
        index_view,
        "saved_queries",
        lambda username: (_ for _ in ()).throw(
            index_view.EnhancedSearchStoreError("db offline")
        ),
    )
    reload_failed_response = inspect.unwrap(index_view.save_query_view)(
        request,
        conn=object(),
    )
    assert reload_failed_response.status_code == 503
    assert json.loads(reload_failed_response.content.decode("utf-8")) == {
        "error": index_view.SAVED_QUERY_LOAD_ERROR
    }


def test_view_utils_cover_json_root_guard_host_resolution_and_validation(monkeypatch):
    """Verify view utils cover JSON root guard host resolution and validation.

    Inputs: `monkeypatch`. Output: dict.
    """
    monkeypatch.setattr(
        view_utils,
        "_current_username",
        lambda request, conn: "alice",
    )
    assert view_utils.current_username(object(), object()) == "alice"

    monkeypatch.setattr(
        view_utils, "parse_json_body", lambda request: ({"ok": True}, None)
    )
    assert view_utils.load_json_body(object()) == ({"ok": True}, None)
    assert view_utils.load_json_object(object()) == ({"ok": True}, None)

    monkeypatch.setattr(
        view_utils,
        "parse_json_body",
        lambda request: (None, "Invalid JSON payload."),
    )
    assert view_utils.load_json_body(object()) == (None, "Invalid JSON payload.")
    assert view_utils.load_json_object(object()) == (None, "Invalid JSON payload.")

    monkeypatch.setattr(view_utils, "parse_json_body", lambda request: ([], None))
    assert view_utils.load_json_object(object()) == (
        None,
        view_utils.JSON_OBJECT_REQUIRED_ERROR,
    )

    guarded_calls = []

    @view_utils.require_non_root_user
    def _guarded_view(request, conn=None, url=None, **kwargs):
        """Guarded view.

        Inputs: `request`, `conn`, `url`, `**kwargs`. Output: dict.
        """
        guarded_calls.append((conn, url))
        return {"ok": True}

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "root")
    root_response = _guarded_view(SimpleNamespace(), conn=object())
    assert root_response.status_code == 403

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "")
    missing_user_response = _guarded_view(SimpleNamespace(), conn=object())
    assert missing_user_response.status_code == 403
    assert json.loads(missing_user_response.content.decode("utf-8")) == {
        "error": view_utils.CURRENT_USER_REQUIRED_ERROR
    }

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")
    assert _guarded_view(SimpleNamespace(), conn="conn", url="url") == {"ok": True}
    assert guarded_calls == [("conn", "url")]

    monkeypatch.setattr(view_utils, "get_env", lambda name, env_file=None: "4080")
    with override_settings(OMERO_HOST="", OMERO_PORT="bad"):
        host, port = view_utils.resolve_omero_host_port(SimpleNamespace())
    assert host == "4080"
    assert port is None

    monkeypatch.setattr(
        view_utils,
        "get_env",
        lambda name, env_file=None: {
            "OMEROHOST": "omero-host",
            "OMERO_PORT": "4064",
        }[name],
    )
    with override_settings(OMERO_HOST=None, OMERO_PORT=None):
        host, port = view_utils.resolve_omero_host_port(SimpleNamespace())
    assert (host, port) == ("omero-host", 4064)

    assert view_utils.validate_user_password(object(), "") == (
        False,
        "Password is required.",
    )
    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "")
    monkeypatch.setattr(
        view_utils,
        "resolve_omero_host_port",
        lambda conn: ("omero-host", 4064),
    )
    assert view_utils.validate_user_password(object(), "secret") == (
        False,
        "Could not validate the provided password.",
    )
