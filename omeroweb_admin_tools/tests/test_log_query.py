from __future__ import annotations

import pytest

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.services import log_query as log_query_module
from omeroweb_admin_tools.services.log_query import (
    LogEntry,
    _build_internal_file_query,
    _build_internal_files_query,
    _cap_entries_per_container,
    _estimate_label_cache_size,
    _estimate_log_entries_size,
    _normalize_level,
    _prepare_query_jobs,
    _strip_message_prefix,
    build_loki_query,
    fetch_internal_log_labels,
    fetch_loki_logs,
)


def test_build_loki_query_requires_containers() -> None:
    with pytest.raises(ValueError):
        build_loki_query([])


def test_build_loki_query_builds_regex() -> None:
    query = build_loki_query(["omeroserver", "omeroweb"])
    assert query == '{compose_service=~"^(omeroserver|omeroweb)$"}'


def test_strip_message_prefix_removes_timestamp_and_level() -> None:
    message = "2026-02-02 14:52:58,266 INFO [omero.util] Started server"
    assert _strip_message_prefix(message) == "[omero.util] Started server"


def test_cap_entries_per_container_keeps_most_recent() -> None:
    entries = [
        LogEntry(
            timestamp="2026-02-02T14:52:58+00:00",
            container="omeroserver",
            level="info",
            message="one",
        ),
        LogEntry(
            timestamp="2026-02-02T14:52:59+00:00",
            container="omeroserver",
            level="info",
            message="two",
        ),
        LogEntry(
            timestamp="2026-02-02T14:52:00+00:00",
            container="omeroweb",
            level="info",
            message="other",
        ),
    ]

    capped = _cap_entries_per_container(entries, 1)
    assert {entry.message for entry in capped} == {"two", "other"}


def test_build_internal_file_query_uses_filepath_label() -> None:
    query = _build_internal_file_query("omeroserver_internal", "Blitz-0.log")
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filepath=~"(^|.*/)Blitz\\\\-0\\\\.log$"}'
    )


def test_build_internal_file_query_handles_filename_label() -> None:
    query = _build_internal_file_query(
        "omeroserver_internal", "Blitz-0.log", "filename"
    )
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filename=~"(^|.*/)Blitz\\\\-0\\\\.log$"}'
    )


def test_build_internal_files_query_combines_multiple_files() -> None:
    query = _build_internal_files_query(
        "omeroserver_internal",
        ["Blitz-0.log", "DropBox.err"],
    )
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filepath=~"(^|.*/)(Blitz\\\\-0\\\\.log|DropBox\\\\.err)$"}'
    )


def test_cap_entries_per_container_does_not_apply_global_cap() -> None:
    entries = [
        LogEntry(
            timestamp="2026-02-02T14:52:58+00:00",
            container="a",
            level="info",
            message="1",
        ),
        LogEntry(
            timestamp="2026-02-02T14:52:59+00:00",
            container="a",
            level="info",
            message="2",
        ),
        LogEntry(
            timestamp="2026-02-02T14:53:00+00:00",
            container="b",
            level="info",
            message="3",
        ),
    ]
    capped = _cap_entries_per_container(entries, 2)
    assert len(capped) == 3


def test_normalize_level_maps_unknown_to_info() -> None:
    assert _normalize_level("unknown", "job-service sync loop starting") == "info"


def test_normalize_level_uses_error_keywords() -> None:
    assert _normalize_level("unknown", "Failed to ensure job-service exists") == "error"


def test_normalize_level_uses_error_traceback_detection() -> None:
    assert _normalize_level("", "Traceback (most recent call last):") == "error"


def test_normalize_level_traceback_continuation_line_is_debug() -> None:
    assert (
        _normalize_level("", "During handling of the above exception, another exception occurred:")
        == "debug"
    )


def test_normalize_level_redis_bloom_error_rate_is_info() -> None:
    message = "1:M 04 Mar 2026 12:16:02.311 * <bf> \t{ bf-error-rate       :      0.01 }"
    assert _normalize_level("unknown", message) == "info"


def test_normalize_level_traceback_file_line_is_debug() -> None:
    message = (
        '  File "/opt/omero/web/site-packages/django/core/handlers/exception.py", '
        "line 55, in inner"
    )
    assert _normalize_level("", message) == "debug"


def test_normalize_level_exception_line_is_error() -> None:
    assert _normalize_level("", "KeyError: 'public_enabled'") == "error"
    assert _normalize_level("", "AttributeError: type object 'RequestContext' has no attribute 'html'") == "error"
    assert _normalize_level("", "ValueError: invalid literal for int()") == "error"


def test_normalize_level_django_template_lookup_is_debug() -> None:
    message = (
        "django.template.base.VariableDoesNotExist: Failed lookup for key [name] "
        "in <URLResolver <module 'omeroweb.webclient.urls'> (None:None) '^webclient/'>"
    )
    assert _normalize_level("unknown", message) == "debug"


def test_prepare_query_jobs_batches_internal_files() -> None:
    jobs = _prepare_query_jobs(
        ["omeroserver_internal"],
        internal_files={
            "omeroserver_internal": {f"Blitz-{idx}.log" for idx in range(13)}
        },
    )

    assert len(jobs) == 2
    assert all(job.source_type == "internal_batch" for job in jobs)
    assert sum(len(job.selected_files) for job in jobs) == 13


def test_prepare_query_jobs_applies_text_filter_to_docker_and_internal_queries() -> None:
    jobs = _prepare_query_jobs(
        ["omeroserver", "omeroweb_internal"],
        text_query='imaris "warning"',
    )

    assert len(jobs) == 2
    assert all("|~" in job.query for job in jobs)
    assert any('\\"warning\\"' in job.query for job in jobs)


def test_fetch_loki_logs_uses_process_local_cache(monkeypatch) -> None:
    config = LogConfig(
        loki_url="http://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=30.0,
        cache_max_bytes=64 * 1024 * 1024,
    )
    calls = {"count": 0}
    monkeypatch.setattr(
        log_query_module,
        "_LOG_RESULT_CACHE",
        log_query_module._InMemoryTTLCache(
            ttl_seconds=60.0,
            max_items=8,
            max_bytes=64 * 1024 * 1024,
            size_estimator=_estimate_log_entries_size,
        ),
    )

    def fake_fetch(*args, **kwargs):
        calls["count"] += 1
        return [
            LogEntry(
                timestamp="2026-03-09T00:00:00+00:00",
                container="omeroserver",
                level="info",
                message="cached",
            )
        ]

    monkeypatch.setattr(log_query_module, "_fetch_loki_logs_uncached", fake_fetch)

    first = fetch_loki_logs(config, ["omeroserver"], 900, 100)
    second = fetch_loki_logs(config, ["omeroserver"], 900, 100)

    assert calls["count"] == 1
    assert [entry.message for entry in first] == ["cached"]
    assert [entry.message for entry in second] == ["cached"]


def test_fetch_loki_logs_cache_key_varies_by_text_query(monkeypatch) -> None:
    config = LogConfig(
        loki_url="http://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=30.0,
        cache_max_bytes=64 * 1024 * 1024,
    )
    calls = {"count": 0}
    monkeypatch.setattr(
        log_query_module,
        "_LOG_RESULT_CACHE",
        log_query_module._InMemoryTTLCache(
            ttl_seconds=60.0,
            max_items=8,
            max_bytes=64 * 1024 * 1024,
            size_estimator=_estimate_log_entries_size,
        ),
    )

    def fake_fetch(*args, **kwargs):
        calls["count"] += 1
        return [
            LogEntry(
                timestamp="2026-03-09T00:00:00+00:00",
                container="omeroserver",
                level="info",
                message=str(kwargs.get("text_query")),
            )
        ]

    monkeypatch.setattr(log_query_module, "_fetch_loki_logs_uncached", fake_fetch)

    first = fetch_loki_logs(config, ["omeroserver"], 900, 100, text_query="imaris")
    second = fetch_loki_logs(config, ["omeroserver"], 900, 100, text_query="imaris")
    third = fetch_loki_logs(config, ["omeroserver"], 900, 100, text_query="bioformats")

    assert calls["count"] == 2
    assert [entry.message for entry in first] == ["imaris"]
    assert [entry.message for entry in second] == ["imaris"]
    assert [entry.message for entry in third] == ["bioformats"]


def test_fetch_internal_log_labels_reads_filesystem_and_caches(monkeypatch) -> None:
    config = LogConfig(
        loki_url="http://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=30.0,
        cache_max_bytes=64 * 1024 * 1024,
    )
    seen_patterns = []
    monkeypatch.setattr(
        log_query_module,
        "_INTERNAL_LABELS_CACHE",
        log_query_module._InMemoryTTLCache(
            ttl_seconds=60.0,
            max_items=8,
            max_bytes=8 * 1024 * 1024,
            size_estimator=_estimate_label_cache_size,
        ),
    )

    def fake_glob(pattern):
        seen_patterns.append(pattern)
        if pattern.endswith("*.log"):
            return [
                "/opt/omero/server/OMERO.server/var/log/Blitz-0.log",
                "/opt/omero/server/OMERO.server/var/log/DropBox.log",
            ]
        return []

    monkeypatch.setattr(log_query_module.glob, "glob", fake_glob)
    monkeypatch.setattr(log_query_module.os.path, "isfile", lambda path: True)

    first_labels, first_key = fetch_internal_log_labels(config, "omeroserver_internal")
    second_labels, second_key = fetch_internal_log_labels(config, "omeroserver_internal")

    assert first_labels == ["Blitz-0.log", "DropBox.log"]
    assert second_labels == ["Blitz-0.log", "DropBox.log"]
    assert first_key == "filepath"
    assert second_key == "filepath"
    assert len(seen_patterns) == len(log_query_module._INTERNAL_LOG_GLOB_PATTERNS["omeroserver"])
