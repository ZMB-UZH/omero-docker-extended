from __future__ import annotations

import runpy
from types import SimpleNamespace

from omeroweb_tools import config as tools_config
from omeroweb_tools.services import enhanced_search_service as service
from omeroweb_tools.task_names import ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME


def test_config_helpers_cover_invalid_values_and_scope_serialization():
    """Verify test config helpers cover invalid values and behavior."""
    scope = tools_config.EnhancedSearchScope("user", 7, "Your universal metadata index")

    assert scope.to_dict() == {
        "scope_type": "user",
        "scope_id": 7,
        "scope_key": "user:7",
        "label": "Your universal metadata index",
    }
    assert tools_config._bounded_int("bad", 5, 1, 10) == 5
    assert tools_config._optional_bool(None, True) is True
    assert tools_config._optional_bool("yes", False) is True
    assert tools_config._optional_bool("off", True) is False
    assert tools_config._optional_bool("unexpected", False) is False


def test_build_enhanced_search_celery_config_normalizes_invalid_inputs(monkeypatch):
    """Verify test build enhanced search celery config norm behavior."""
    monkeypatch.setattr(
        tools_config,
        "get_optional_env",
        lambda name, env_file=None: {
            tools_config.ENHANCED_SEARCH_USE_CELERY_ENV: "not-a-bool",
            tools_config.ENHANCED_SEARCH_CELERY_BROKER_ENV: " redis://broker:6379/9 ",
            tools_config.ENHANCED_SEARCH_CELERY_BACKEND_ENV: "",
            tools_config.OMERO_IMS_CELERY_BACKEND_ENV: " redis://ims-backend:6381/2 ",
            tools_config.ENHANCED_SEARCH_CELERY_QUEUE_ENV: "",
            tools_config.ENHANCED_SEARCH_CELERY_RESULT_EXPIRES_ENV: "oops",
            tools_config.ENHANCED_SEARCH_CELERY_TIME_LIMIT_ENV: "9999999",
            tools_config.ENHANCED_SEARCH_CELERY_LOGLEVEL_ENV: "   ",
            tools_config.ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY_ENV: "0",
            tools_config.ENHANCED_SEARCH_CELERY_MAX_RETRIES_ENV: "oops",
            tools_config.ENHANCED_SEARCH_CELERY_PREFETCH_ENV: "256",
        }.get(name),
    )

    celery_config = tools_config.build_enhanced_search_celery_config()

    assert celery_config.enabled is tools_config.DEFAULT_USE_CELERY
    assert celery_config.broker_url == "redis://broker:6379/9"
    assert celery_config.backend_url == "redis://ims-backend:6381/2"
    assert celery_config.queue == tools_config.DEFAULT_CELERY_QUEUE
    assert celery_config.result_expires == tools_config.DEFAULT_CELERY_RESULT_EXPIRES
    assert celery_config.time_limit == 604800
    assert celery_config.loglevel == tools_config.DEFAULT_CELERY_LOGLEVEL
    assert celery_config.worker_concurrency == 1
    assert celery_config.max_retries == tools_config.DEFAULT_CELERY_MAX_RETRIES
    assert celery_config.prefetch_multiplier == 128


def test_celery_app_builds_configured_celery_instance(monkeypatch):
    """Verify test celery app builds configured celery inst behavior."""
    created = {}

    class _FakeCelery:
        """Test double for fake celery."""

        def __init__(self, name, broker, backend):
            created["init"] = {
                "name": name,
                "broker": broker,
                "backend": backend,
            }
            self.conf = {}

        @staticmethod
        def autodiscover_tasks(packages, force=False):
            """Handle autodiscover tasks."""
            created["autodiscover"] = {"packages": packages, "force": force}

    monkeypatch.setattr(
        tools_config,
        "build_enhanced_search_celery_config",
        lambda: SimpleNamespace(
            broker_url="redis://broker.internal/queue-a",
            backend_url="redis://backend.internal/results-a",
            queue="enhanced-search",
            result_expires=123,
            time_limit=456,
            max_retries=9,
            prefetch_multiplier=3,
        ),
    )
    import celery

    monkeypatch.setattr(celery, "Celery", _FakeCelery)

    namespace = runpy.run_module(
        "omeroweb_tools.celery_app",
        run_name="omeroweb_tools.celery_app.__coverage__",
    )

    assert created["init"] == {
        "name": "omeroweb_tools",
        "broker": "redis://broker.internal/queue-a",
        "backend": "redis://backend.internal/results-a",
    }
    assert namespace["app"].conf["task_default_queue"] == "enhanced-search"
    assert namespace["app"].conf["result_expires"] == 123
    assert namespace["app"].conf["task_time_limit"] == 456
    assert namespace["app"].conf["broker_connection_max_retries"] == 9
    assert namespace["app"].conf["worker_prefetch_multiplier"] == 3
    assert created["autodiscover"] == {
        "packages": ["omeroweb_tools"],
        "force": True,
    }


def test_tasks_module_registers_and_runs_scope_sync_task(monkeypatch):
    """Verify test tasks module registers and runs scope sy behavior."""
    decorated = {}

    class _FakeApp:
        """Test double for fake app."""

        @staticmethod
        def task(**kwargs):
            """Handle task."""

            def _decorator(func):
                """Handle decorator."""
                decorated["kwargs"] = kwargs
                return func

            return _decorator

    monkeypatch.setattr("omeroweb_tools.celery_app.app", _FakeApp())
    monkeypatch.setattr(
        service,
        "run_scope_sync_task",
        lambda scope_key, run_token: {
            "scope_key": scope_key,
            "run_token": run_token,
            "status": "idle",
        },
    )

    namespace = runpy.run_module(
        "omeroweb_tools.tasks",
        run_name="omeroweb_tools.tasks.__coverage__",
    )
    run_marker = "sync-run-id"

    assert decorated["kwargs"] == {
        "bind": True,
        "name": ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME,
    }
    assert namespace["run_enhanced_search_scope_sync"](None, "user:9", run_marker) == {
        "scope_key": "user:9",
        "run_token": run_marker,
        "status": "idle",
    }
