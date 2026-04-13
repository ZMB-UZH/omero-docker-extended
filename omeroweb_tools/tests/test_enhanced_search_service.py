from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import override_settings

from omeroweb_tools.services import enhanced_search_service as service


def test_parse_search_query_validates_scope_and_date_ranges():
    query, errors = service.parse_search_query(
        {
            "indexed_scope": "invalid-scope",
            "acquisition_date_from": "2026-04-12",
            "acquisition_date_to": "2026-04-11",
            "page": "bad",
        }
    )

    assert query.indexed_scope == service.SEARCH_SCOPE_ALL_INDEXED
    assert "Invalid page value." in errors
    assert "Selected indexed scope is not supported." in errors
    assert "Acquisition start date cannot be after the end date." in errors


def test_saved_query_redirect_url_urlencodes_payload():
    with override_settings(ROOT_URLCONF="omeroweb_tools.urls"):
        target = service.saved_query_redirect_url(
            {
                "query_text": "Zeiss LSM 980",
                "indexed_scope": service.SEARCH_SCOPE_OMERO_BUILTIN,
                "page": 2,
            }
        )

    assert target.startswith("/enhanced-search/")
    assert "query_text=Zeiss+LSM+980" in target
    assert f"indexed_scope={service.SEARCH_SCOPE_OMERO_BUILTIN}" in target
    assert "page=2" in target


def test_search_without_live_omero_connection_returns_empty_payload():
    payload = service.search(
        None,
        service.SearchQuery(query_text="anything"),
        acquisition_metadata_enabled=False,
    )

    assert payload == {
        "results": [],
        "page": 1,
        "page_size": service.runtime_config().max_results,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }


def test_search_without_query_text_or_date_filters_returns_empty_payload():
    payload = service.search(
        object(),
        service.SearchQuery(query_text=""),
        acquisition_metadata_enabled=True,
    )

    assert payload == {
        "results": [],
        "page": 1,
        "page_size": service.runtime_config().max_results,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }


def test_save_user_settings_clears_current_user_scope_when_disabled(monkeypatch):
    class _DbConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    cleared = []
    monkeypatch.setattr(service, "db_connect", lambda: _DbConn())
    monkeypatch.setattr(
        service,
        "save_user_settings_row",
        lambda conn, username, payload: payload,
    )
    monkeypatch.setattr(
        service,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": True},
    )
    monkeypatch.setattr(
        service,
        "_current_user_id",
        lambda conn: 21,
    )
    monkeypatch.setattr(
        service,
        "clear_scope_index",
        lambda conn, scope_type, scope_id, current_message: cleared.append(
            (scope_type, scope_id, current_message)
        ),
    )
    monkeypatch.setattr(
        service,
        "sync_states_for_user",
        lambda conn, username: [],
    )

    saved = service.save_user_settings(
        object(),
        "alice",
        {"acquisition_metadata_enabled": False},
    )

    assert saved["user_settings"] == {"acquisition_metadata_enabled": False}
    assert cleared == [
        (
            service.USER_SCOPE_TYPE,
            21,
            "Acquisition metadata indexing is disabled for your account.",
        )
    ]


def test_save_user_settings_auto_starts_indexing_for_enabled_user(monkeypatch):
    class _DbConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(service, "db_connect", lambda: _DbConn())
    monkeypatch.setattr(
        service,
        "save_user_settings_row",
        lambda conn, username, payload: payload,
    )
    monkeypatch.setattr(
        service,
        "user_settings",
        lambda username: {"acquisition_metadata_enabled": False},
    )
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 21)
    monkeypatch.setattr(
        service,
        "current_sync_states",
        lambda scopes: [
            {"indexed_image_count": 0, "last_successful_at": None, "status": "idle"}
        ],
    )
    started = []
    monkeypatch.setattr(
        service,
        "request_scope_sync",
        lambda scope_key, requested_by, scope_label=None: (
            started.append((scope_key, requested_by, scope_label)) or True,
            "Indexing started.",
        ),
    )
    monkeypatch.setattr(
        service,
        "sync_states_for_user",
        lambda conn, username: [{"scope_key": "user:21", "status": "running"}],
    )

    saved = service.save_user_settings(
        object(),
        "alice",
        {"acquisition_metadata_enabled": True},
    )

    assert started == [("user:21", "alice", service.USER_SCOPE_LABEL)]
    assert saved["user_settings"] == {"acquisition_metadata_enabled": True}
    assert saved["sync_started"] is True
    assert saved["sync_message"] == "Indexing started."


def test_scope_from_key_rejects_non_user_scopes():
    assert service.scope_from_key("dataset:7") is None
    assert service.scope_from_key("group:9") is None


def test_ensure_user_index_sync_autostarts_enabled_user_when_state_is_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "current_user_scope",
        lambda conn, username: service.EnhancedSearchScope(
            service.USER_SCOPE_TYPE,
            21,
            service.USER_SCOPE_LABEL,
        ),
    )
    monkeypatch.setattr(
        service,
        "current_sync_states",
        lambda scopes: [
            {"scope_key": "user:21", "status": "idle", "last_successful_at": None}
        ],
    )
    started = []
    monkeypatch.setattr(
        service,
        "request_scope_sync",
        lambda scope_key, requested_by, scope_label=None: (
            started.append((scope_key, requested_by, scope_label)) or True,
            "Indexing started.",
        ),
    )
    monkeypatch.setattr(
        service,
        "sync_states_for_user",
        lambda conn, username: [{"scope_key": "user:21", "status": "running"}],
    )

    states, auto_started, message = service.ensure_user_index_sync(
        object(),
        "alice",
        settings_payload={"acquisition_metadata_enabled": True},
    )

    assert states == [{"scope_key": "user:21", "status": "running"}]
    assert auto_started is True
    assert message == "Indexing started."
    assert started == [("user:21", "alice", service.USER_SCOPE_LABEL)]


def test_ensure_user_index_sync_skips_recent_success(monkeypatch):
    recent_success = datetime.now(timezone.utc) - timedelta(seconds=30)
    monkeypatch.setattr(
        service,
        "current_user_scope",
        lambda conn, username: service.EnhancedSearchScope(
            service.USER_SCOPE_TYPE,
            21,
            service.USER_SCOPE_LABEL,
        ),
    )
    monkeypatch.setattr(
        service,
        "current_sync_states",
        lambda scopes: [
            {
                "scope_key": "user:21",
                "status": "idle",
                "last_successful_at": recent_success,
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(sync_stale_seconds=600),
    )
    monkeypatch.setattr(
        service,
        "request_scope_sync",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("auto sync should not run for fresh index state")
        ),
    )

    states, auto_started, message = service.ensure_user_index_sync(
        object(),
        "alice",
        settings_payload={"acquisition_metadata_enabled": True},
    )

    assert states == [
        {
            "scope_key": "user:21",
            "status": "idle",
            "last_successful_at": recent_success,
        }
    ]
    assert auto_started is False
    assert message == ""


def test_search_merges_omero_and_acquisition_results(monkeypatch):
    monkeypatch.setattr(
        service, "runtime_config", lambda: SimpleNamespace(max_results=10)
    )
    monkeypatch.setattr(service, "_visible_group_ids", lambda conn: [5])
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 11)

    class _DbConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(service, "db_connect", lambda: _DbConn())
    monkeypatch.setattr(
        service,
        "search_index_rows",
        lambda *args, **kwargs: (
            [
                {
                    "image_id": 17,
                    "image_name": "Indexed image",
                    "dataset_id": 101,
                    "dataset_name": "Dataset A",
                    "project_id": 201,
                    "project_name": "Project A",
                    "owner_id": 11,
                    "owner_name": "alice",
                    "group_id": 5,
                    "group_name": "Group A",
                    "acquisition_date": None,
                    "instrument_manufacturer": "",
                    "instrument_model": "",
                    "objective_model": "",
                    "objective_magnification": None,
                    "objective_na": None,
                    "detector_model": "",
                    "detector_binning": "",
                    "detector_gain": None,
                    "pixel_size_x_um": None,
                    "pixel_size_y_um": None,
                    "z_step_um": None,
                    "channel_summary": "",
                    "indexed_at": None,
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(
        service,
        "_search_omero_builtin_rows",
        lambda conn, query: [
            {
                "image_id": 17,
                "image_name": "Live image",
                "dataset_id": 101,
                "dataset_name": "Dataset A",
                "project_id": 201,
                "project_name": "Project A",
                "owner_id": 11,
                "owner_name": "alice",
                "group_id": 5,
                "group_name": "Group A",
                "acquisition_date": None,
                "instrument_manufacturer": "",
                "instrument_model": "",
                "objective_model": "",
                "objective_magnification": None,
                "objective_na": None,
                "detector_model": "",
                "detector_binning": "",
                "detector_gain": None,
                "pixel_size_x_um": None,
                "pixel_size_y_um": None,
                "z_step_um": None,
                "channel_summary": "",
                "indexed_at": None,
                "indexed_sources": ["OMERO index"],
            },
            {
                "image_id": 18,
                "image_name": "Built-in only",
                "dataset_id": None,
                "dataset_name": "",
                "project_id": None,
                "project_name": "",
                "owner_id": 11,
                "owner_name": "alice",
                "group_id": 5,
                "group_name": "Group A",
                "acquisition_date": None,
                "instrument_manufacturer": "",
                "instrument_model": "",
                "objective_model": "",
                "objective_magnification": None,
                "objective_na": None,
                "detector_model": "",
                "detector_binning": "",
                "detector_gain": None,
                "pixel_size_x_um": None,
                "pixel_size_y_um": None,
                "z_step_um": None,
                "channel_summary": "",
                "indexed_at": None,
                "indexed_sources": ["OMERO index"],
            },
        ],
    )

    def _image(name):
        return SimpleNamespace(getName=lambda: name)

    monkeypatch.setattr(
        service,
        "_accessible_images_by_id",
        lambda conn, image_ids: {17: _image("Current 17"), 18: _image("Current 18")},
    )
    monkeypatch.setattr(
        service,
        "reverse",
        lambda name, args=None, kwargs=None: (
            f"/render-thumbnail/{args[0]}/"
            if name == "render_thumbnail"
            else "/webclient/"
        ),
    )
    monkeypatch.setattr(service, "get_text", lambda value: value)

    payload = service.search(
        object(),
        service.SearchQuery(query_text="lsm"),
        acquisition_metadata_enabled=True,
    )

    assert payload["total_count"] == 2
    results_by_id = {row["image_id"]: row for row in payload["results"]}
    assert results_by_id[17]["indexed_sources"] == [
        "OMERO index",
        "Acquisition metadata",
    ]
    assert results_by_id[18]["indexed_sources"] == ["OMERO index"]
    assert results_by_id[17]["image_name"] == "Current 17"
    assert results_by_id[17]["thumbnail_url"] == "/render-thumbnail/17/"


def test_search_omero_builtin_rows_uses_prefix_query_for_partial_matching(monkeypatch):
    captured = {}

    class _Conn:
        def searchObjects(self, obj_types, text, **kwargs):
            captured["obj_types"] = obj_types
            captured["text"] = text
            captured["kwargs"] = kwargs
            return []

    rows = service._search_omero_builtin_rows(
        _Conn(),
        service.SearchQuery(query_text="104 204"),
    )

    assert rows == []
    assert captured["obj_types"] == ["Project", "Dataset", "Image"]
    assert captured["text"] == "104* OR 204*"
    assert captured["kwargs"]["rawQuery"] is True


def test_request_scope_sync_dispatches_celery_task(monkeypatch):
    scope = service.EnhancedSearchScope("user", 7, "Your acquisition metadata")
    monkeypatch.setattr(service, "scope_from_key", lambda scope_key, label=None: scope)
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(schema_version=3, sync_stale_seconds=600),
    )
    monkeypatch.setattr(
        service,
        "runtime_celery_config",
        lambda: SimpleNamespace(enabled=True, queue="enhanced-search"),
    )

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(service, "db_connect", lambda: _Conn())
    calls = []
    monkeypatch.setattr(
        service,
        "try_start_scope_sync",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    dispatched = {}

    class _Task:
        @staticmethod
        def apply_async(*, args, queue):
            dispatched["args"] = args
            dispatched["queue"] = queue

    import sys

    fake_tasks_module = SimpleNamespace(run_enhanced_search_scope_sync=_Task())
    monkeypatch.setitem(sys.modules, "omeroweb_tools.tasks", fake_tasks_module)

    started, message = service.request_scope_sync(
        scope.scope_key,
        "alice",
        scope_label=scope.label,
    )

    assert started is True
    assert message == "Indexing started."
    assert calls
    assert dispatched == {
        "args": (scope.scope_key, calls[0][0][6]),
        "queue": "enhanced-search",
    }


def test_request_scope_sync_uses_thread_fallback_when_celery_is_disabled(monkeypatch):
    scope = service.EnhancedSearchScope("user", 9, "Your acquisition metadata")
    monkeypatch.setattr(service, "scope_from_key", lambda scope_key, label=None: scope)
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(schema_version=2, sync_stale_seconds=120),
    )
    monkeypatch.setattr(
        service,
        "runtime_celery_config",
        lambda: SimpleNamespace(enabled=False),
    )

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(service, "db_connect", lambda: _Conn())
    monkeypatch.setattr(service, "try_start_scope_sync", lambda *args, **kwargs: True)

    started_with = {}
    monkeypatch.setattr(
        service,
        "_start_threaded_sync",
        lambda dispatched_scope, run_token: started_with.update(
            {"scope_key": dispatched_scope.scope_key, "run_token": run_token}
        ),
    )

    started, message = service.request_scope_sync(
        scope.scope_key,
        "bob",
        scope_label=scope.label,
    )

    assert started is True
    assert message == "Indexing started."
    assert started_with["scope_key"] == scope.scope_key
    assert started_with["run_token"]


def test_process_sync_batch_stops_when_sync_lease_is_not_active(monkeypatch):
    scope = service.EnhancedSearchScope("user", 9, "Your acquisition metadata")

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(service, "db_connect", lambda: _Conn())
    monkeypatch.setattr(
        service,
        "sync_run_is_active",
        lambda conn, scope_type, scope_id, run_token: False,
    )
    monkeypatch.setattr(
        service,
        "upsert_search_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("upsert should not run after sync lease cancellation")
        ),
    )

    try:
        service._process_sync_batch(scope, "token", [object()], 0, 3)
    except service.ScopeSyncCancelledError as exc:
        assert "user:9" in str(exc)
    else:
        raise AssertionError("expected ScopeSyncCancelledError")
