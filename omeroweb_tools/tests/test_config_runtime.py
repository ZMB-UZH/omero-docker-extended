from __future__ import annotations

from omeroweb_tools import config as tools_config


def test_build_enhanced_search_config_bounds_runtime_values(monkeypatch):
    """Verify test build enhanced search config bounds runt behavior."""
    monkeypatch.setattr(
        tools_config,
        "get_optional_env",
        lambda name, env_file=None: {
            tools_config.ENHANCED_SEARCH_BATCH_SIZE_ENV: "999",
            tools_config.ENHANCED_SEARCH_MAX_RESULTS_ENV: "0",
            tools_config.ENHANCED_SEARCH_STALE_SECONDS_ENV: "30",
            tools_config.ENHANCED_SEARCH_SCHEMA_VERSION_ENV: "5",
        }.get(name),
    )

    runtime = tools_config.build_enhanced_search_config()

    assert runtime.batch_size == tools_config.MAX_BATCH_SIZE
    assert runtime.max_results == 1
    assert runtime.sync_stale_seconds == 60
    assert runtime.schema_version == 5


def test_build_enhanced_search_celery_config_uses_defaults(monkeypatch):
    """Verify test build enhanced search celery config uses behavior."""
    monkeypatch.setattr(
        tools_config,
        "get_optional_env",
        lambda name, env_file=None: {
            tools_config.ENHANCED_SEARCH_USE_CELERY_ENV: "false",
            tools_config.OMERO_IMS_CELERY_BROKER_ENV: "redis://redis-host:6390/2",
            tools_config.OMERO_IMS_CELERY_BACKEND_ENV: "redis://redis-host:6390/2",
            tools_config.ENHANCED_SEARCH_CELERY_QUEUE_ENV: "enhanced-search-q",
        }.get(name),
    )

    celery_config = tools_config.build_enhanced_search_celery_config()

    assert celery_config.enabled is False
    assert celery_config.queue == "enhanced-search-q"
    assert celery_config.broker_url == "redis://redis-host:6390/2"
    assert celery_config.backend_url == "redis://redis-host:6390/2"
    assert celery_config.result_expires == tools_config.DEFAULT_CELERY_RESULT_EXPIRES
    assert celery_config.time_limit == tools_config.DEFAULT_CELERY_TIME_LIMIT
