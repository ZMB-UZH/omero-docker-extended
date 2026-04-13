from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import override_settings

from omeroweb_tools.services import enhanced_search_service as service


def test_parse_search_query_validates_numeric_and_date_ranges(monkeypatch):
    monkeypatch.setattr(
        service,
        "scope_map",
        lambda: {"project:7": SimpleNamespace(scope_key="project:7")},
    )

    query, errors = service.parse_search_query(
        {
            "scope_key": "project:7",
            "objective_na_min": "2.0",
            "objective_na_max": "1.0",
            "acquisition_date_from": "2026-04-12",
            "acquisition_date_to": "2026-04-11",
            "page": "bad",
        }
    )

    assert query.scope_key == "project:7"
    assert "Invalid page value." in errors
    assert "Objective NA minimum cannot be greater than maximum." in errors
    assert "Acquisition start date cannot be after the end date." in errors


def test_saved_query_redirect_url_urlencodes_payload():
    with override_settings(ROOT_URLCONF="omeroweb_tools.urls"):
        target = service.saved_query_redirect_url(
            {
                "query_text": "Zeiss LSM 980",
                "dataset_name": "Cell Cycle",
                "page": 2,
            }
        )

    assert target.startswith("/enhanced-search/")
    assert "query_text=Zeiss+LSM+980" in target
    assert "dataset_name=Cell+Cycle" in target
    assert "page=2" in target


def test_search_without_live_omero_connection_returns_empty_payload():
    payload = service.search(None, service.SearchQuery(query_text="anything"))

    assert payload == {
        "results": [],
        "page": 1,
        "page_size": service.runtime_config().max_results,
        "total_count": 0,
        "has_previous": False,
        "has_next": False,
    }


def test_request_scope_sync_dispatches_celery_task(monkeypatch):
    scope = service.EnhancedSearchScope("project", 7, "Indexed Project")
    monkeypatch.setattr(service, "scope_map", lambda: {scope.scope_key: scope})
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

    started, message = service.request_scope_sync(scope.scope_key, "alice")

    assert started is True
    assert message == "Indexing started."
    assert calls
    assert dispatched == {
        "args": (scope.scope_key, calls[0][0][6]),
        "queue": "enhanced-search",
    }


def test_request_scope_sync_uses_thread_fallback_when_celery_is_disabled(monkeypatch):
    scope = service.EnhancedSearchScope("dataset", 9, "Indexed Dataset")
    monkeypatch.setattr(service, "scope_map", lambda: {scope.scope_key: scope})
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

    started, message = service.request_scope_sync(scope.scope_key, "bob")

    assert started is True
    assert message == "Indexing started."
    assert started_with["scope_key"] == scope.scope_key
    assert started_with["run_token"]
