from __future__ import annotations

import pytest

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.services import log_query as log_query_module
from omeroweb_admin_tools.services.log_query import (
    LogEntry,
    _build_internal_file_query,
    _build_internal_files_query,
    _build_docker_query,
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
    """Verify build loki query requires containers.

    Inputs: admin-tool fixtures. Output: fails on regressions in build loki query requires containers.
    """
    with pytest.raises(ValueError):
        build_loki_query([])


def test_build_loki_query_builds_regex() -> None:
    """Verify build loki query builds regex.

    Inputs: admin-tool fixtures. Output: fails on regressions in build loki query builds regex.
    """
    query = build_loki_query(["omeroserver", "omeroweb"])
    assert query == '{compose_service=~"^(omeroserver|omeroweb)$"}'


def test_log_query_rejects_unsafe_service_and_filename_values() -> None:
    """Confirm log query rejects unsafe service and filename values is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in log query rejects unsafe service and filename values.
    """
    with pytest.raises(ValueError):
        build_loki_query(['omeroserver"} |~ ".+'])
    with pytest.raises(ValueError):
        _build_docker_query('redis"} |~ ".+')
    with pytest.raises(ValueError):
        _build_internal_file_query("omeroserver_internal", "../Blitz-0.log")


def test_strip_message_prefix_removes_timestamp_and_level() -> None:
    """Check strip message prefix removes timestamp and level cleanup behavior.

    Inputs: admin-tool fixtures. Output: fails on regressions in strip message prefix removes timestamp and level.
    """
    message = "2026-02-02 14:52:58,266 INFO [omero.util] Started server"
    assert _strip_message_prefix(message) == "[omero.util] Started server"


def test_cap_entries_per_container_keeps_most_recent() -> None:
    """Check that cap entries per container keeps most recent remains stable.

    Inputs: admin-tool fixtures. Output: fails on regressions in cap entries per container keeps most recent.
    """
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
    """Verify build internal file query uses filepath label.

    Inputs: admin-tool fixtures. Output: fails on regressions in build internal file query uses filepath label.
    """
    query = _build_internal_file_query("omeroserver_internal", "Blitz-0.log")
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filepath=~"(^|.*/)Blitz\\\\-0\\\\.log$"}'
    )


def test_build_internal_file_query_handles_filename_label() -> None:
    """Verify build internal file query handles filename label.

    Inputs: admin-tool fixtures. Output: fails on regressions in build internal file query handles filename label.
    """
    query = _build_internal_file_query(
        "omeroserver_internal", "Blitz-0.log", "filename"
    )
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filename=~"(^|.*/)Blitz\\\\-0\\\\.log$"}'
    )


def test_build_internal_files_query_combines_multiple_files() -> None:
    """Verify build internal files query combines multiple files.

    Inputs: admin-tool fixtures. Output: fails on regressions in build internal files query combines multiple files.
    """
    query = _build_internal_files_query(
        "omeroserver_internal",
        ["Blitz-0.log", "DropBox.err"],
    )
    assert (
        query
        == '{compose_service="omeroserver", log_type="internal", filepath=~"(^|.*/)(Blitz\\\\-0\\\\.log|DropBox\\\\.err)$"}'
    )


def test_cap_entries_per_container_does_not_apply_global_cap() -> None:
    """Verify cap entries per container does not apply global cap.

    Inputs: admin-tool fixtures. Output: fails on regressions in cap entries per container does not apply global cap.
    """
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
    """Check normalize level maps unknown to info parsing against the documented contract.

    Inputs: admin-tool fixtures. Output: fails on regressions in normalize level maps unknown to info.
    """
    assert _normalize_level("unknown", "job-service sync loop starting") == "info"


def test_normalize_level_uses_error_keywords() -> None:
    """Confirm normalize level uses error keywords exposes the expected failure.

    Inputs: admin-tool fixtures. Output: fails on regressions when normalize level uses error keywords stops reporting the expected error.
    """
    assert _normalize_level("unknown", "Failed to ensure job-service exists") == "error"


def test_normalize_level_uses_error_traceback_detection() -> None:
    """Confirm normalize level uses error traceback detection exposes the expected failure.

    Inputs: admin-tool fixtures. Output: fails on regressions when normalize level uses error traceback detection stops reporting the expected error.
    """
    assert _normalize_level("", "Traceback (most recent call last):") == "error"


def test_normalize_level_traceback_continuation_line_is_debug() -> None:
    """Check normalize level traceback continuation line is debug parsing against the documented contract.

    Inputs: admin-tool fixtures. Output: fails on regressions in normalize level traceback continuation line is debug.
    """
    assert (
        _normalize_level(
            "", "During handling of the above exception, another exception occurred:"
        )
        == "debug"
    )


def test_normalize_level_redis_bloom_error_rate_is_info() -> None:
    """Confirm normalize level redis bloom error rate is info exposes the expected failure.

    Inputs: admin-tool fixtures. Output: fails on regressions when normalize level redis bloom error rate is info stops reporting the expected error.
    """
    message = (
        "1:M 04 Mar 2026 12:16:02.311 * <bf> \t{ bf-error-rate       :      0.01 }"
    )
    assert _normalize_level("unknown", message) == "info"


def test_normalize_level_traceback_file_line_is_debug() -> None:
    """Check normalize level traceback file line is debug parsing against the documented contract.

    Inputs: admin-tool fixtures. Output: fails on regressions in normalize level traceback file line is debug.
    """
    message = (
        '  File "/opt/omero/web/site-packages/django/core/handlers/exception.py", '
        "line 55, in inner"
    )
    assert _normalize_level("", message) == "debug"


def test_normalize_level_exception_line_is_error() -> None:
    """Confirm normalize level exception line is error exposes the expected failure.

    Inputs: admin-tool fixtures. Output: fails on regressions when normalize level exception line is error stops reporting the expected error.
    """
    assert _normalize_level("", "KeyError: 'public_enabled'") == "error"
    assert (
        _normalize_level(
            "", "AttributeError: type object 'RequestContext' has no attribute 'html'"
        )
        == "error"
    )
    assert _normalize_level("", "ValueError: invalid literal for int()") == "error"


def test_normalize_level_django_template_lookup_is_debug() -> None:
    """Check normalize level django template lookup is debug parsing against the documented contract.

    Inputs: admin-tool fixtures. Output: fails on regressions in normalize level django template lookup is debug.
    """
    message = (
        "django.template.base.VariableDoesNotExist: Failed lookup for key [name] "
        "in <URLResolver <module 'omeroweb.webclient.urls'> (None:None) '^webclient/'>"
    )
    assert _normalize_level("unknown", message) == "debug"


def test_prepare_query_jobs_batches_internal_files() -> None:
    """Verify prepare query jobs batches internal files.

    Inputs: admin-tool fixtures. Output: fails on regressions in prepare query jobs batches internal files.
    """
    jobs = _prepare_query_jobs(
        ["omeroserver_internal"],
        internal_files={
            "omeroserver_internal": {f"Blitz-{idx}.log" for idx in range(13)}
        },
        internal_file_batch_size=12,
    )

    assert len(jobs) == 2
    assert all(job.source_type == "internal_batch" for job in jobs)
    assert sum(len(job.selected_files) for job in jobs) == 13


def test_prepare_query_jobs_rejects_non_positive_internal_batch_size() -> None:
    """Confirm prepare query jobs rejects non positive internal batch size is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in prepare query jobs rejects non positive internal batch size.
    """
    with pytest.raises(ValueError, match="internal_file_batch_size"):
        _prepare_query_jobs(["omeroserver_internal"], internal_file_batch_size=0)


def test_prepare_query_jobs_applies_text_filter_to_docker_and_internal_queries() -> (
    None
):
    """Verify prepare query jobs applies text filter to docker and internal queries.

    Inputs: admin-tool fixtures. Output: fails on regressions in prepare query jobs applies text filter to docker and internal queries.
    """
    jobs = _prepare_query_jobs(
        ["omeroserver", "omeroweb_internal"],
        text_query='imaris "warning"',
        internal_file_batch_size=12,
    )

    assert len(jobs) == 2
    assert all("|~" in job.query for job in jobs)
    assert any('\\"warning\\"' in job.query for job in jobs)


def test_fetch_loki_logs_uses_process_local_cache(monkeypatch) -> None:
    """Verify fetch loki logs uses process local cache.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in fetch loki logs uses process local cache.
    """
    config = LogConfig(
        loki_url="https://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=30.0,
        cache_max_bytes=64 * 1024 * 1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
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
        """Simulate fetch so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `list`.
        """
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
    """Verify fetch loki logs cache key varies by text query.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in fetch loki logs cache key varies by text query.
    """
    config = LogConfig(
        loki_url="https://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=30.0,
        cache_max_bytes=64 * 1024 * 1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
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
        """Simulate fetch so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `list`.
        """
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
    """Verify fetch internal log labels reads filesystem and caches.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in fetch internal log labels reads filesystem and caches.
    """
    config = LogConfig(
        loki_url="https://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=30.0,
        cache_max_bytes=64 * 1024 * 1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
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
        """Simulate glob so the surrounding test controls that dependency.

        Inputs: `pattern`. Output: `list`.
        """
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
    second_labels, second_key = fetch_internal_log_labels(
        config, "omeroserver_internal"
    )

    assert first_labels == ["Blitz-0.log", "DropBox.log"]
    assert second_labels == ["Blitz-0.log", "DropBox.log"]
    assert first_key == "filepath"
    assert second_key == "filepath"
    assert len(seen_patterns) == len(
        log_query_module._INTERNAL_LOG_GLOB_PATTERNS["omeroserver"]
    )
