from __future__ import annotations

import pytest

from omeroweb_tools import config as tools_config


def test_build_enhanced_search_config_parses_scopes_and_bounds(monkeypatch):
    monkeypatch.setattr(
        tools_config,
        "get_optional_env",
        lambda name, env_file=None: {
            tools_config.ENHANCED_SEARCH_SCOPES_ENV: (
                '[{"type":"project","id":42,"label":"Indexed Project"},'
                '{"scope_type":"dataset","id":7}]'
            ),
            tools_config.ENHANCED_SEARCH_BATCH_SIZE_ENV: "999",
            tools_config.ENHANCED_SEARCH_MAX_RESULTS_ENV: "0",
            tools_config.ENHANCED_SEARCH_STALE_SECONDS_ENV: "30",
            tools_config.ENHANCED_SEARCH_SCHEMA_VERSION_ENV: "5",
            tools_config.ENHANCED_SEARCH_SCOPE_IMAGE_CAP_ENV: "25000",
        }.get(name),
    )

    runtime = tools_config.build_enhanced_search_config()

    assert [scope.scope_key for scope in runtime.scopes] == ["project:42", "dataset:7"]
    assert runtime.scopes[0].label == "Indexed Project"
    assert runtime.scopes[1].label == "Dataset 7"
    assert runtime.batch_size == tools_config.MAX_BATCH_SIZE
    assert runtime.max_results == 1
    assert runtime.sync_stale_seconds == 60
    assert runtime.schema_version == 5
    assert runtime.scope_image_cap == 25000


def test_build_enhanced_search_config_rejects_invalid_scope_payload(monkeypatch):
    monkeypatch.setattr(
        tools_config,
        "get_optional_env",
        lambda name, env_file=None: (
            '{"not":"a-list"}'
            if name == tools_config.ENHANCED_SEARCH_SCOPES_ENV
            else None
        ),
    )

    with pytest.raises(ValueError, match="JSON array of scope objects"):
        tools_config.build_enhanced_search_config()


def test_build_enhanced_search_celery_config_uses_defaults(monkeypatch):
    monkeypatch.setattr(
        tools_config,
        "get_optional_env",
        lambda name, env_file=None: {
            tools_config.ENHANCED_SEARCH_USE_CELERY_ENV: "false",
            tools_config.ENHANCED_SEARCH_CELERY_QUEUE_ENV: "enhanced-search-q",
        }.get(name),
    )

    celery_config = tools_config.build_enhanced_search_celery_config()

    assert celery_config.enabled is False
    assert celery_config.queue == "enhanced-search-q"
    assert celery_config.broker_url == "redis://redis:6379/3"
    assert celery_config.backend_url == "redis://redis:6379/3"
    assert celery_config.result_expires == tools_config.DEFAULT_CELERY_RESULT_EXPIRES
    assert celery_config.time_limit == tools_config.DEFAULT_CELERY_TIME_LIMIT
