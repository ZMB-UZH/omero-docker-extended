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
    """Verify test ttl cache handles loader failures inflig behavior."""
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

    cache._values["b"] = log_query_module._CacheRecord(
        value="1111",
        expires_at=99.0,
        size_bytes=4,
    )
    cache._total_size_bytes = 4
    current_time[0] = 102.0
    assert cache.get_or_load("b", lambda: "3333") == "3333"
    assert cache._total_size_bytes == 4

    class _StalePopDict(dict):
        """Represent stale pop dict."""

        def pop(self, key, default=None):
            """Handle pop."""
            if key == "stale":
                super().pop(key, None)
                return None
            return super().pop(key, default)

    cache._values = _StalePopDict(
        stale=log_query_module._CacheRecord(
            value="gone",
            expires_at=500.0,
            size_bytes=4,
        )
    )
    cache._total_size_bytes = 4
    cache._max_items = 0
    cache._prune_locked(100.0)

    current_time[0] = 200.0
    assert cache.get_or_load("b", lambda: "9") == "9"
    cache.reconfigure(max_bytes=1)
    assert cache._max_bytes == 1
    assert len(cache._values) <= 1


def test_log_query_helpers_cover_internal_containers_caps_and_serialization() -> None:
    """Verify test log query helpers cover internal contain behavior."""
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
    """Verify test log query level and filesystem helpers c behavior."""
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
    assert _fetch_internal_log_labels_uncached("unknown_internal") == ((), "filepath")

    assert _format_timestamp("1710000000000000000").endswith("+00:00")
    assert _parse_level_from_message("") is None
    assert _parse_level_from_message("2026-03-30 07:00:00 LOG database started") == (
        "info"
    )
    assert _is_traceback_continuation("") is False
    assert _is_traceback_continuation('  File "server.py", line 7, in main') is True
    assert _is_traceback_continuation("Traceback (most recent call last):") is False
    assert _is_django_template_lookup_noise("") is False
    assert _is_django_template_lookup_noise("plain log line") is False
    assert (
        _is_django_template_lookup_noise(
            "django.template.base.VariableDoesNotExist: plain missing variable"
        )
        is False
    )
    assert _is_redis_bloom_info("") is False
    assert _is_redis_bloom_info("redis healthy") is False

    with pytest.raises(ValueError, match="At least one filename is required"):
        _build_internal_files_query("omeroserver_internal", [])


def test_log_query_remaining_runtime_paths_cover_loki_failures_job_errors_and_empty_labels(
    monkeypatch,
) -> None:
    """Verify test log query remaining runtime paths cover behavior."""
    config = log_query_module.LogConfig(
        loki_url="https://loki.example.test:3100",
        lookback_seconds=60,
        max_entries=10,
        timeout_seconds=2.5,
        cache_max_bytes=1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
    )
    monkeypatch.setattr(
        log_query_module.requests,
        "get",
        lambda url, timeout=2.5: (_ for _ in ()).throw(
            log_query_module.requests.Timeout("late")
        ),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        log_query_module._execute_loki_query(
            config,
            '{compose_service="omeroserver"}',
            60,
            10,
            since_ns=1710000000000000000,
        )

    with pytest.raises(RuntimeError, match="Invalid Loki URL"):
        log_query_module._execute_loki_query(
            log_query_module.LogConfig(
                loki_url="file:///etc/passwd",
                lookback_seconds=60,
                max_entries=10,
                timeout_seconds=1.0,
                cache_max_bytes=1024,
                internal_file_batch_size=12,
                max_parallel_queries=4,
            ),
            '{compose_service="omeroserver"}',
            60,
            10,
        )

    docker_job = log_query_module._QueryJob(
        query='{compose_service="omeroserver"}',
        source_type="docker",
        source_name="omeroserver",
    )
    internal_job = log_query_module._QueryJob(
        query='{compose_service="omeroserver", log_type="internal"}',
        source_type="internal_batch",
        source_name="omeroserver_internal",
        selected_files=("Blitz-0.log",),
    )
    aggregate_job = log_query_module._QueryJob(
        query='{compose_service="omeroweb", log_type="internal"}',
        source_type="internal_all",
        source_name="omeroweb_internal",
    )
    monkeypatch.setattr(
        log_query_module,
        "_prepare_query_jobs",
        lambda *args, **kwargs: [docker_job, internal_job, aggregate_job],
    )

    aggregate_entries = [
        LogEntry(
            timestamp="2026-03-30T07:00:00+00:00",
            container="omeroweb_internal/a.log",
            level="info",
            message="old",
        ),
        LogEntry(
            timestamp="2026-03-30T07:01:00+00:00",
            container="omeroweb_internal/a.log",
            level="warn",
            message="new",
        ),
    ]

    class _FakeExecutor:
        """Test double for fake executor."""

        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def submit(fn, config, job, lookback_seconds, max_entries, since_ns):
            """Handle submit."""
            future = concurrent.futures.Future()
            if job is docker_job:
                future.set_exception(RuntimeError("docker failed"))
            elif job is internal_job:
                future.set_exception(RuntimeError("internal failed"))
            else:
                future.set_result((job, aggregate_entries))
            return future

    monkeypatch.setattr(
        log_query_module.concurrent.futures,
        "ThreadPoolExecutor",
        _FakeExecutor,
    )

    def _as_completed(futures):
        """Handle as completed."""
        return list(futures)

    monkeypatch.setattr(
        log_query_module.concurrent.futures,
        "as_completed",
        _as_completed,
    )

    with pytest.raises(RuntimeError, match="Loki log query failed for 2 source"):
        log_query_module.fetch_loki_logs(
            config,
            ["omeroserver", "omeroweb_internal"],
            lookback_seconds=60,
            max_entries=1,
            internal_files={"omeroserver_internal": {"Blitz-0.log"}},
        )

    monkeypatch.setattr(
        log_query_module,
        "_discover_internal_log_labels_from_filesystem",
        lambda compose_service: ([], "filepath"),
    )
    assert _fetch_internal_log_labels_uncached("omeroserver_internal") == (
        (),
        "filepath",
    )

    entry = LogEntry(
        timestamp="2026-03-30T07:00:00+00:00",
        container="omeroserver",
        level="info",
        message="only",
    )
    assert _apply_global_cap([entry], 5) == [entry]
