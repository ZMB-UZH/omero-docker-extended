from __future__ import annotations

import concurrent.futures

import pytest

from omeroweb_admin_tools.services import log_query as log_query_module
from omeroweb_admin_tools.services.log_query import (
    LogEntry,
    _apply_global_cap,
    _build_docker_query,
    _build_internal_files_query,
    _chunks,
    _discover_internal_log_labels_from_filesystem,
    _entry_sort_key,
    _escape_logql_string,
    _fetch_internal_log_labels_uncached,
    _filter_internal_batch_entries,
    _format_timestamp,
    _is_django_template_lookup_noise,
    _is_redis_bloom_info,
    _is_traceback_continuation,
    _parse_level_from_message,
    _split_internal_container,
    _append_text_filter,
    serialize_entries,
)


def test_ttl_cache_handles_loader_failures_inflight_results_and_pruning(
    monkeypatch,
) -> None:
    current_time = [100.0]
    monkeypatch.setattr(log_query_module.time, "monotonic", lambda: current_time[0])
    cache = log_query_module._InMemoryTTLCache(
        ttl_seconds=10.0,
        max_items=1,
        max_bytes=4,
        size_estimator=lambda value: len(str(value)),
    )

    with pytest.raises(RuntimeError, match="boom"):
        cache.get_or_load(
            "broken",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    assert cache._inflight == {}

    future = concurrent.futures.Future()
    future.set_result("shared")
    cache._inflight["shared"] = future
    assert cache.get_or_load("shared", lambda: "other") == "shared"

    assert cache.get_or_load("a", lambda: "1111") == "1111"
    current_time[0] = 101.0
    assert cache.get_or_load("b", lambda: "2222") == "2222"
    assert set(cache._values) == {"b"}

    current_time[0] = 200.0
    assert cache.get_or_load("b", lambda: "9") == "9"
    cache.reconfigure(max_bytes=1)
    assert cache._max_bytes == 1
    assert len(cache._values) <= 1


def test_log_query_helpers_cover_internal_containers_caps_and_serialization() -> None:
    entries = [
        LogEntry(
            timestamp="2026-03-30T07:00:00+00:00",
            container="omeroserver_internal/Blitz-0.log",
            level="info",
            message="kept",
        ),
        LogEntry(
            timestamp="2026-03-30T07:01:00+00:00",
            container="omeroserver_internal/DropBox.err",
            level="warn",
            message="dropped",
        ),
    ]

    assert _split_internal_container("plain-container") is None
    assert _split_internal_container("_internal/") is None
    assert _chunks(["a", "b", "c"], 2) == [("a", "b"), ("c",)]
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        _chunks(["a"], 0)

    assert (
        _escape_logql_string('warn "quoted" \\ path') == 'warn \\"quoted\\" \\\\ path'
    )
    assert _append_text_filter('{compose_service="omeroserver"}', None) == (
        '{compose_service="omeroserver"}'
    )
    assert (
        _append_text_filter(
            '{compose_service="omeroserver"}',
            'warn "quoted"',
        )
        == '{compose_service="omeroserver"} |~ "(?i)warn\\\\ \\"quoted\\""'
    )

    assert _build_docker_query("omeroserver") == (
        '{compose_service="omeroserver", container_id=~".+"}'
    )
    assert _build_docker_query("redis") == '{compose_service="redis"}'

    assert _filter_internal_batch_entries(
        "omeroserver_internal",
        ("Blitz-0.log",),
        entries,
    ) == [entries[0]]
    assert _apply_global_cap(entries, 0) == []
    assert log_query_module._cap_entries_per_container(entries, 0) == []
    assert _entry_sort_key(
        LogEntry(
            timestamp="not-a-timestamp",
            container="omeroserver",
            level="info",
            message="raw",
        )
    ) == (0, "not-a-timestamp")
    assert (
        serialize_entries(entries)[0]["container"] == "omeroserver_internal/Blitz-0.log"
    )


def test_log_query_level_and_filesystem_helpers_cover_remaining_edges(
    tmp_path,
    monkeypatch,
) -> None:
    log_file = tmp_path / "master.err"
    log_file.write_text("payload", encoding="utf-8")
    non_file = tmp_path / "logs"
    non_file.mkdir()

    monkeypatch.setattr(
        log_query_module,
        "_INTERNAL_LOG_GLOB_PATTERNS",
        {"omeroweb": (str(tmp_path / "*"),)},
    )

    discovered = _discover_internal_log_labels_from_filesystem("omeroweb_internal")
    assert discovered == (["master.err"], "filepath")
    assert _discover_internal_log_labels_from_filesystem("unknown_internal") is None
    assert _fetch_internal_log_labels_uncached("unknown_internal") == (
        tuple(),
        "filepath",
    )

    assert _format_timestamp("1710000000000000000").endswith("+00:00")
    assert _parse_level_from_message("") is None
    assert _parse_level_from_message("2026-03-30 07:00:00 LOG database started") == (
        "info"
    )
    assert _is_traceback_continuation('  File "server.py", line 7, in main') is True
    assert _is_traceback_continuation("Traceback (most recent call last):") is False
    assert _is_django_template_lookup_noise("plain log line") is False
    assert _is_redis_bloom_info("redis healthy") is False

    with pytest.raises(ValueError, match="At least one filename is required"):
        _build_internal_files_query("omeroserver_internal", [])
