from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.template import Context, Engine
from django.utils import timezone as django_timezone

from omeroweb_tools.services import enhanced_search_service as service


def test_parse_search_query_validates_scope_and_date_ranges():
    """Verify parse search query validates scope and date ranges.

    Inputs: none. Output: None.
    """
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


def test_parse_search_query_accepts_display_date_formats():
    """Verify parse search query accepts display date formats.

    Inputs: none. Output: None.
    """
    query, errors = service.parse_search_query(
        {
            "acquisition_date_from": "12--04--2026",
            "acquisition_date_to": "13-04-2026",
        }
    )

    assert errors == []
    assert query.acquisition_date_from == datetime(2026, 4, 12, tzinfo=timezone.utc)
    assert query.acquisition_date_to == datetime(
        2026,
        4,
        13,
        23,
        59,
        59,
        999999,
        tzinfo=timezone.utc,
    )


def test_search_query_display_dates_do_not_localize_end_of_day_forward():
    """Verify search query display dates do not localize end of day forward.

    Inputs: none. Output: None.
    """
    assert service.SearchQuery().acquisition_date_from_display == ""
    assert service.SearchQuery().acquisition_date_to_display == ""

    query = service.SearchQuery(
        acquisition_date_from=datetime(2026, 4, 13, tzinfo=timezone.utc),
        acquisition_date_to=datetime(
            2026,
            4,
            13,
            23,
            59,
            59,
            999999,
            tzinfo=timezone.utc,
        ),
    )

    template = Engine().from_string('{{ value|date:"d-m-Y" }}')
    with django_timezone.override("Europe/Zurich"):
        assert template.render(Context({"value": query.acquisition_date_to})) == (
            "14-04-2026"
        )
        assert query.acquisition_date_from_display == "13-04-2026"
        assert query.acquisition_date_to_display == "13-04-2026"


def test_saved_query_redirect_url_urlencodes_payload():
    """Verify saved query redirect URL urlencodes payload.

    Inputs: none. Output: None.
    """
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
    """Verify search without live OMERO connection returns empty payload.

    Inputs: none. Output: None.
    """
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
    """Verify search without query text or date filters returns empty payload.

    Inputs: none. Output: None.
    """
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


def test_search_omero_builtin_scope_runs_without_acquisition_index(monkeypatch):
    """Verify search OMERO builtin scope runs without acquisition index.

    Inputs: `monkeypatch`. Output: None.
    """
    calls = []
    monkeypatch.setattr(
        service, "runtime_config", lambda: SimpleNamespace(max_results=10)
    )
    monkeypatch.setattr(
        service,
        "_search_omero_builtin_rows",
        lambda conn, query: calls.append(query.indexed_scope) or [],
    )

    payload = service.search(
        object(),
        service.SearchQuery(
            query_text="delta",
            indexed_scope=service.SEARCH_SCOPE_OMERO_BUILTIN,
        ),
        acquisition_metadata_enabled=False,
    )

    assert calls == [service.SEARCH_SCOPE_OMERO_BUILTIN]
    assert payload["results"] == []
    assert payload["total_count"] == 0


def test_search_does_not_query_user_index_without_current_user(monkeypatch):
    """Verify search does not query user index without current user.

    Inputs: `monkeypatch`. Output: None.
    """
    called = []
    monkeypatch.setattr(
        service, "runtime_config", lambda: SimpleNamespace(max_results=10)
    )
    monkeypatch.setattr(service, "_current_user_id", lambda conn: None)
    monkeypatch.setattr(service, "db_connect", lambda: called.append("db"))
    monkeypatch.setattr(service, "_search_omero_builtin_rows", lambda conn, query: [])

    payload = service.search(
        object(),
        service.SearchQuery(
            query_text="delta",
            indexed_scope=service.SEARCH_SCOPE_ACQUISITION_METADATA,
        ),
        acquisition_metadata_enabled=True,
    )

    assert called == []
    assert payload["results"] == []
    assert payload["total_count"] == 0


@pytest.mark.parametrize(
    ("query", "expected_filter_key"),
    [
        (
            service.SearchQuery(
                indexed_scope=service.SEARCH_SCOPE_ACQUISITION_METADATA,
                acquisition_date_from=datetime(2026, 4, 12, tzinfo=timezone.utc),
            ),
            "acquisition_date_from",
        ),
        (
            service.SearchQuery(
                indexed_scope=service.SEARCH_SCOPE_ACQUISITION_METADATA,
                acquisition_date_to=datetime(2026, 4, 12, 23, 59, tzinfo=timezone.utc),
            ),
            "acquisition_date_to",
        ),
    ],
)
def test_search_runs_with_one_sided_date_filters(
    monkeypatch,
    query,
    expected_filter_key,
):
    """Verify search runs with one sided date filters.

    Inputs: `monkeypatch`, `query`, `expected_filter_key`. Output: computed value.
    """

    class _DbConn:
        """Represent database conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    captured_calls = []
    monkeypatch.setattr(
        service, "runtime_config", lambda: SimpleNamespace(max_results=10)
    )
    monkeypatch.setattr(service, "db_connect", _DbConn)
    monkeypatch.setattr(service, "_visible_group_ids", lambda conn: [5])
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 21)
    monkeypatch.setattr(
        service,
        "search_index_rows",
        lambda conn, **kwargs: (
            captured_calls.append(kwargs)
            or (
                [
                    {
                        "image_id": 17,
                        "group_id": 5,
                        "group_name": "Research",
                        "owner_id": 21,
                        "owner_name": "alice",
                        "image_name": "img-17",
                        "dataset_id": 101,
                        "dataset_name": "Dataset A",
                        "project_id": 201,
                        "project_name": "Project A",
                        "acquisition_date": datetime(
                            2026, 4, 12, 8, 15, tzinfo=timezone.utc
                        ),
                        "channel_summary": "GFP",
                        "pixel_size_x_um": 0.1,
                        "pixel_size_y_um": 0.1,
                        "z_step_um": 0.4,
                        "indexed_sources": ["Universal metadata index"],
                    }
                ],
                1,
            )
        ),
    )
    monkeypatch.setattr(service, "_search_omero_builtin_rows", lambda conn, query: [])
    monkeypatch.setattr(
        service,
        "_accessible_images_by_id",
        lambda conn, image_ids: {17: SimpleNamespace(getName=lambda: "img-17")},
    )
    monkeypatch.setattr(
        service,
        "reverse",
        lambda name, args=None: (
            "/webclient/"
            if name == "webindex"
            else f"/webgateway/render_thumbnail/{args[0]}/"
        ),
    )
    monkeypatch.setattr(service, "get_text", lambda value: value)

    payload = service.search(
        object(),
        query,
        acquisition_metadata_enabled=True,
    )

    assert payload["total_count"] == 1
    assert payload["results"][0]["image_id"] == 17
    assert captured_calls[0]["scope_type"] == service.USER_SCOPE_TYPE
    assert captured_calls[0]["scope_id"] == 21
    assert captured_calls[0]["filters"][expected_filter_key] is not None
    assert captured_calls[0]["limit"] == 10
    assert captured_calls[0]["offset"] == 0


def test_sync_state_needs_refresh_for_stale_running_state(monkeypatch):
    """Verify sync state needs refresh for stale running state.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(sync_stale_seconds=600),
    )

    state = {
        "status": "running",
        "updated_at": datetime.now(timezone.utc) - timedelta(seconds=601),
    }

    assert service._sync_state_needs_refresh(state) is True


def test_sync_state_needs_refresh_for_recent_running_state(monkeypatch):
    """Verify sync state needs refresh for recent running state.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(sync_stale_seconds=600),
    )

    state = {
        "status": "running",
        "updated_at": datetime.now(timezone.utc) - timedelta(seconds=60),
    }

    assert service._sync_state_needs_refresh(state) is False


def test_save_user_settings_clears_current_user_scope_when_disabled(monkeypatch):
    """Verify save user settings clears current user scope when disabled.

    Inputs: `monkeypatch`. Output: computed value.
    """

    class _DbConn:
        """Represent database conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    cleared = []
    monkeypatch.setattr(service, "db_connect", _DbConn)
    monkeypatch.setattr(
        service,
        "save_user_settings_row",
        lambda conn, username, payload: payload,
    )
    monkeypatch.setattr(
        service,
        "user_settings",
        lambda username: {
            "acquisition_metadata_enabled": True,
            "collapsed_sections": ["saved-queries"],
        },
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

    assert saved["user_settings"] == {
        "acquisition_metadata_enabled": False,
        "collapsed_sections": ["saved-queries"],
    }
    assert cleared == [
        (
            service.USER_SCOPE_TYPE,
            21,
            service.acquisition_index_disabled_detail_message(),
        )
    ]


def test_save_user_settings_auto_starts_indexing_for_enabled_user(monkeypatch):
    """Verify save user settings auto starts indexing for enabled user.

    Inputs: `monkeypatch`. Output: computed value.
    """

    class _DbConn:
        """Represent database conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _DbConn)
    monkeypatch.setattr(
        service,
        "save_user_settings_row",
        lambda conn, username, payload: payload,
    )
    monkeypatch.setattr(
        service,
        "user_settings",
        lambda username: {
            "acquisition_metadata_enabled": False,
            "collapsed_sections": ["metadata-index"],
        },
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
    assert saved["user_settings"] == {
        "acquisition_metadata_enabled": True,
        "collapsed_sections": ["metadata-index"],
    }
    assert saved["sync_started"] is True
    assert saved["sync_message"] == "Indexing started."


def test_scope_from_key_rejects_non_user_scopes():
    """Verify scope from key rejects non user scopes.

    Inputs: none. Output: None.
    """
    assert service.scope_from_key("dataset:7") is None
    assert service.scope_from_key("group:9") is None


def test_ensure_user_index_sync_autostarts_enabled_user_when_state_is_missing(
    monkeypatch,
):
    """Verify ensure user index sync autostarts enabled user when state is missing.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify ensure user index sync skips recent success.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify search merges OMERO and acquisition results.

    Inputs: `monkeypatch`. Output: computed value.
    """
    monkeypatch.setattr(
        service, "runtime_config", lambda: SimpleNamespace(max_results=10)
    )
    monkeypatch.setattr(service, "_visible_group_ids", lambda conn: [5])
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 11)

    class _DbConn:
        """Represent database conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _DbConn)
    captured_index_calls = []
    monkeypatch.setattr(
        service,
        "search_index_rows",
        lambda *args, **kwargs: (
            captured_index_calls.append(kwargs)
            or (
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
            )
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
        """Image.

        Inputs: `name`. Output: `SimpleNamespace` result.
        """
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
        "Universal metadata index",
    ]
    assert results_by_id[18]["indexed_sources"] == ["OMERO index"]
    assert results_by_id[17]["image_name"] == "Current 17"
    assert results_by_id[17]["thumbnail_url"] == "/render-thumbnail/17/"
    assert captured_index_calls[0]["scope_type"] == service.USER_SCOPE_TYPE
    assert captured_index_calls[0]["scope_id"] == 11


def test_all_indexed_search_dispatches_independent_sources_concurrently(monkeypatch):
    """Verify all indexed search dispatches independent sources concurrently.

    Inputs: `monkeypatch`. Output: computed value.
    """
    events = []
    executor_inits = []

    class _Future:
        """Represent future."""

        def __init__(self, func, kwargs):
            """Initialize the instance.

            Inputs: `func`, `kwargs`. Output: None.
            """
            self._func = func
            self._kwargs = kwargs

        def result(self):
            """Return the asynchronous result.

            Inputs: none. Output: `self._func` result.
            """
            events.append("future-result")
            return self._func(**self._kwargs)

    class _Executor:
        """Represent executor."""

        def __init__(self, max_workers, thread_name_prefix):
            """Initialize the instance.

            Inputs: `max_workers`, `thread_name_prefix`. Output: None.
            """
            executor_inits.append(
                {
                    "max_workers": max_workers,
                    "thread_name_prefix": thread_name_prefix,
                }
            )

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

        @staticmethod
        def submit(func, **kwargs):
            """Submit.

            Inputs: `func`, `**kwargs`. Output: `_Future` result.
            """
            events.append("submit-acquisition")
            return _Future(func, kwargs)

    monkeypatch.setattr(service, "ThreadPoolExecutor", _Executor)
    monkeypatch.setattr(
        service, "runtime_config", lambda: SimpleNamespace(max_results=10)
    )
    monkeypatch.setattr(service, "_current_user_id", lambda conn: 11)
    monkeypatch.setattr(service, "_visible_group_ids", lambda conn: [5])
    monkeypatch.setattr(
        service,
        "_search_acquisition_index_rows",
        lambda **kwargs: events.append(("acquisition", kwargs)) or ([], 0),
    )
    monkeypatch.setattr(
        service,
        "_search_omero_builtin_rows",
        lambda conn, query: events.append("omero") or [],
    )

    payload = service.search(
        object(),
        service.SearchQuery(
            query_text="delta",
            indexed_scope=service.SEARCH_SCOPE_ALL_INDEXED,
        ),
        acquisition_metadata_enabled=True,
    )

    assert payload["results"] == []
    assert executor_inits == [
        {
            "max_workers": 2,
            "thread_name_prefix": "enhanced-search-source",
        }
    ]
    assert events[0:3] == ["submit-acquisition", "omero", "future-result"]
    assert events[3][0] == "acquisition"
    assert events[3][1]["scope_type"] == service.USER_SCOPE_TYPE
    assert events[3][1]["scope_id"] == 11


def test_search_omero_builtin_rows_uses_prefix_query_for_partial_matching(monkeypatch):
    """Verify search OMERO builtin rows uses prefix query for partial matching.

    Inputs: `monkeypatch`. Output: list.
    """
    captured = {}

    class _Conn:
        """Represent conn."""

        @staticmethod
        def searchObjects(obj_types, text, **kwargs):
            """Search objects.

            Inputs: `obj_types`, `text`, `**kwargs`. Output: list.
            """
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


def test_search_omero_builtin_rows_drops_single_letter_noise_terms(monkeypatch):
    """Verify search OMERO builtin rows drops single letter noise terms.

    Inputs: `monkeypatch`. Output: list.
    """
    captured = {}

    class _Conn:
        """Represent conn."""

        @staticmethod
        def searchObjects(obj_types, text, **kwargs):
            """Search objects.

            Inputs: `obj_types`, `text`, `**kwargs`. Output: list.
            """
            captured["obj_types"] = obj_types
            captured["text"] = text
            captured["kwargs"] = kwargs
            return []

    rows = service._search_omero_builtin_rows(
        _Conn(),
        service.SearchQuery(query_text="definitely-not-a-real-hit-xyz"),
    )

    assert rows == []
    assert captured["obj_types"] == ["Project", "Dataset", "Image"]
    assert captured["text"] == "definitely* OR not* OR real* OR hit* OR xyz*"
    assert captured["kwargs"]["rawQuery"] is True


def test_request_scope_sync_dispatches_celery_task(monkeypatch):
    """Verify request scope sync dispatches celery task.

    Inputs: `monkeypatch`. Output: computed value.
    """
    scope = service.EnhancedSearchScope("user", 7, "Your universal metadata index")
    monkeypatch.setattr(service, "scope_from_key", lambda scope_key, label=None: scope)
    celery_config = SimpleNamespace(
        enabled=True,
        broker_url="redis://redis:6379/3",
        queue="enhanced-search",
    )
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(schema_version=3, sync_stale_seconds=600),
    )
    monkeypatch.setattr(
        service,
        "runtime_celery_config",
        lambda: celery_config,
    )

    class _Conn:
        """Represent conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _Conn)
    calls = []
    monkeypatch.setattr(
        service,
        "try_start_scope_sync",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    dispatched = {}
    monkeypatch.setattr(
        service,
        "_dispatch_scope_sync_task",
        lambda scope_key, run_token, config: dispatched.update(
            {
                "name": service.ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME,
                "args": (scope_key, run_token),
                "config": config,
            }
        ),
    )

    started, message = service.request_scope_sync(
        scope.scope_key,
        "alice",
        scope_label=scope.label,
    )

    assert started is True
    assert message == "Indexing started."
    assert calls
    assert dispatched == {
        "name": service.ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME,
        "args": (scope.scope_key, calls[0][0][6]),
        "config": celery_config,
    }


def test_request_scope_sync_marks_error_when_celery_dispatch_fails(monkeypatch):
    """Verify request scope sync marks error when celery dispatch fails.

    Inputs: `monkeypatch`. Output: computed value.
    """
    scope = service.EnhancedSearchScope("user", 9, "Your universal metadata index")
    monkeypatch.setattr(service, "scope_from_key", lambda scope_key, label=None: scope)
    celery_config = SimpleNamespace(
        enabled=True,
        broker_url="redis://redis:6379/3",
        queue="enhanced-search",
    )
    monkeypatch.setattr(
        service,
        "runtime_config",
        lambda: SimpleNamespace(schema_version=3, sync_stale_seconds=600),
    )
    monkeypatch.setattr(
        service,
        "runtime_celery_config",
        lambda: celery_config,
    )

    class _Conn:
        """Represent conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _Conn)
    calls = []
    monkeypatch.setattr(
        service,
        "try_start_scope_sync",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )
    monkeypatch.setattr(
        service,
        "_dispatch_scope_sync_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("queue offline")),
    )
    mark_calls = []
    monkeypatch.setattr(
        service,
        "mark_sync_error",
        lambda conn, scope_type, scope_id, **kwargs: mark_calls.append(
            {
                "scope_type": scope_type,
                "scope_id": scope_id,
                **kwargs,
            }
        ),
    )

    started, message = service.request_scope_sync(
        scope.scope_key,
        "alice",
        scope_label=scope.label,
    )

    assert started is False
    assert message == "Could not dispatch enhanced-search indexing."
    assert calls
    assert mark_calls == [
        {
            "scope_type": scope.scope_type,
            "scope_id": scope.scope_id,
            "run_token": calls[0][0][6],
            "error_text": "Enhanced-search worker dispatch failed.",
            "indexed_image_count": 0,
        }
    ]


def test_dispatch_scope_sync_task_uses_explicit_broker_connection(monkeypatch):
    """Verify dispatch scope sync task uses explicit broker connection.

    Inputs: `monkeypatch`. Output: computed value.
    """
    send_calls = {}

    class _FakeConnection:
        """Test double for fake connection."""

        def __init__(self, url):
            """Initialize the instance.

            Inputs: `url`. Output: None.
            """
            self.url = url
            self.closed = False

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            send_calls["connection_url"] = self.url
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            self.closed = True
            send_calls["connection_closed"] = True
            return False

    class _FakeApp:
        """Test double for fake app."""

        @staticmethod
        def send_task(name, *, args, queue, connection):
            """Send task.

            Inputs: `name`, `args`, `queue`, `connection`. Output: None.
            """
            send_calls.update(
                {
                    "name": name,
                    "args": args,
                    "queue": queue,
                    "connection_object": connection,
                }
            )

    fake_celery_module = SimpleNamespace(app=_FakeApp())
    monkeypatch.setitem(
        __import__("sys").modules,
        "omeroweb_tools.celery_app",
        fake_celery_module,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "kombu",
        SimpleNamespace(Connection=_FakeConnection),
    )

    celery_config = SimpleNamespace(
        broker_url="redis://redis:6379/3",
        queue="enhanced-search",
    )
    service._dispatch_scope_sync_task("user:7", "token-123", celery_config)

    assert send_calls == {
        "connection_url": "redis://redis:6379/3",
        "connection_closed": True,
        "name": service.ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME,
        "args": ("user:7", "token-123"),
        "queue": "enhanced-search",
        "connection_object": send_calls["connection_object"],
    }
    assert send_calls["connection_object"].url == "redis://redis:6379/3"


def test_request_scope_sync_uses_thread_fallback_when_celery_is_disabled(monkeypatch):
    """Verify request scope sync uses thread fallback when celery is disabled.

    Inputs: `monkeypatch`. Output: computed value.
    """
    scope = service.EnhancedSearchScope("user", 9, "Your universal metadata index")
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
        """Represent conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _Conn)
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
    """Verify process sync batch stops when sync lease is not active.

    Inputs: `monkeypatch`. Output: computed value. Raises on invalid or unavailable
    state.

    state.
    """
    scope = service.EnhancedSearchScope("user", 9, "Your universal metadata index")

    class _Conn:
        """Represent conn."""

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _Conn)
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


def test_process_sync_batch_commits_after_progress_update(monkeypatch):
    """Verify process sync batch commits after progress update.

    Inputs: `monkeypatch`. Output: computed value.
    """
    scope = service.EnhancedSearchScope("user", 9, "Your universal metadata index")
    lease_id = f"{scope.scope_key}:lease"

    class _Conn:
        """Represent conn."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.commits = 0

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

        def commit(self):
            """Commit the transaction.

            Inputs: none. Output: None.
            """
            self.commits += 1

    conn = _Conn()
    upserts = []
    progress_updates = []
    monkeypatch.setattr(service, "db_connect", lambda: conn)
    monkeypatch.setattr(
        service,
        "sync_run_is_active",
        lambda conn, scope_type, scope_id, run_token: True,
    )
    monkeypatch.setattr(
        service,
        "_document_for_image",
        lambda image, schema_version: (
            {"image_id": image.image_id, "schema_version": schema_version},
            (),
            (),
        ),
    )
    monkeypatch.setattr(
        service,
        "upsert_search_document",
        lambda *args, **kwargs: upserts.append(kwargs),
    )
    monkeypatch.setattr(
        service,
        "update_sync_progress",
        lambda *args, **kwargs: progress_updates.append(kwargs),
    )

    processed = service._process_sync_batch(
        scope,
        lease_id,
        [SimpleNamespace(image_id=17)],
        2,
        3,
    )

    assert processed == 3
    assert upserts[0]["commit"] is False
    assert upserts[0]["run_token"] == lease_id
    assert progress_updates == [
        {
            "commit": False,
            "run_token": lease_id,
            "indexed_image_count": 3,
            "current_message": "Indexed 3 image(s).",
            "last_cursor_image_id": 17,
        }
    ]
    assert conn.commits == 1


def test_process_sync_batch_skips_non_callable_commit_attribute(monkeypatch):
    """Verify process sync batch skips non callable commit attribute.

    Inputs: `monkeypatch`. Output: computed value.
    """
    scope = service.EnhancedSearchScope("user", 9, "Your universal metadata index")

    class _Conn:
        """Represent conn."""

        commit = "not-callable"

        def __enter__(self):
            """Enter the context manager.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit the context manager.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(service, "db_connect", _Conn)
    monkeypatch.setattr(
        service,
        "sync_run_is_active",
        lambda conn, scope_type, scope_id, run_token: True,
    )
    monkeypatch.setattr(
        service,
        "_document_for_image",
        lambda image, schema_version: (
            {"image_id": image.image_id, "schema_version": schema_version},
            (),
            (),
        ),
    )
    monkeypatch.setattr(service, "upsert_search_document", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "update_sync_progress", lambda *args, **kwargs: None)

    assert (
        service._process_sync_batch(
            scope,
            "token",
            [SimpleNamespace(image_id=17)],
            2,
            3,
        )
        == 3
    )
