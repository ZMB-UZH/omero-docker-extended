from __future__ import annotations

import json
import requests

import pytest

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.services import log_query as log_query_module
from omeroweb_admin_tools.services.log_query import (
    LogEntry,
    _apply_global_cap,
    _build_logs_cache_key,
    _execute_loki_query,
    _fetch_loki_logs_uncached,
    _parse_entries_from_payload,
)


class _DummyResponse:
    """Test double for dummy response."""

    def __init__(self, payload, status=200):
        """Create `_DummyResponse` with `payload` and `status`.

        Inputs: `payload`, `status`. Output: None.
        """
        self._payload = payload
        self.status = status
        self.status_code = status
        self.headers = {}
        self.content = payload
        self.text = payload.decode("utf-8", errors="replace")

    def read(self):
        """Read data from the resource.

        Inputs: none. Output: `self._payload`.
        """
        return self._payload


def _config():
    """Return the config.

    Inputs: none. Output: `LogConfig` result.
    """
    return LogConfig(
        loki_url="https://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=5.0,
        cache_max_bytes=64 * 1024 * 1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
    )


def test_execute_loki_query_returns_json_payload(monkeypatch) -> None:
    """Verify execute loki query returns JSON payload result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in execute loki query returns JSON payload.
    """
    payload = {"status": "success", "data": {"result": []}}
    monkeypatch.setattr(
        log_query_module.requests,
        "get",
        lambda url, timeout: _DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    result = _execute_loki_query(_config(), '{compose_service="omeroserver"}', 60, 20)

    assert result == payload


def test_execute_loki_query_wraps_non_json_http_and_timeout_errors(
    monkeypatch,
) -> None:
    """Verify execute loki query wraps non JSON HTTP and timeout errors.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in execute loki query wraps non JSON HTTP and timeout errors.
    """
    config = _config()

    monkeypatch.setattr(
        log_query_module.requests,
        "get",
        lambda url, timeout: _DummyResponse(b"not-json", status=200),
    )
    with pytest.raises(RuntimeError, match="non-JSON response"):
        _execute_loki_query(config, '{compose_service="omeroserver"}', 60, 20)

    monkeypatch.setattr(
        log_query_module.requests,
        "get",
        lambda url, timeout: _DummyResponse(b"upstream failed", status=502),
    )
    with pytest.raises(RuntimeError, match="Loki HTTP error 502"):
        _execute_loki_query(config, '{compose_service="omeroserver"}', 60, 20)

    monkeypatch.setattr(
        log_query_module.requests,
        "get",
        lambda url, timeout: (_ for _ in ()).throw(requests.Timeout("late")),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        _execute_loki_query(config, '{compose_service="omeroserver"}', 60, 20)


def test_parse_entries_from_payload_handles_internal_streams_and_detected_levels():
    """Verify parse entries from payload handles internal streams and detected levels result shape.

    Inputs: admin-tool fixtures. Output: fails on regressions in parse entries from payload handles internal streams and detected levels.
    """
    payload = {
        "data": {
            "result": [
                {
                    "stream": {
                        "compose_service": "omeroserver",
                        "log_type": "internal",
                        "filename": "Blitz-0.log",
                        "detected_level": "warning",
                    },
                    "values": [
                        [
                            "1710000000000000000",
                            "2026-03-09 12:00:00,000 INFO [omero] started",
                        ]
                    ],
                },
                {
                    "stream": {
                        "compose_service": "omeroweb",
                        "container": "omeroweb-1",
                        "level": "error",
                    },
                    "values": [
                        ["1710000001000000000", "Traceback (most recent call last):"]
                    ],
                },
            ]
        }
    }

    entries = _parse_entries_from_payload(payload)

    assert entries[0].container == "omeroserver_internal/Blitz-0.log"
    assert entries[0].level == "warn"
    assert entries[0].message == "[omero] started"
    assert entries[1].container == "omeroweb"
    assert entries[1].level == "error"


def test_build_logs_cache_key_varies_by_internal_files_and_text_query() -> None:
    """Verify build logs cache key varies by internal files and text query.

    Inputs: admin-tool fixtures. Output: fails on regressions in build logs cache key varies by internal files and text query.
    """
    config = _config()
    base = _build_logs_cache_key(config, ["omeroserver"], 60, 20)
    text = _build_logs_cache_key(
        config,
        ["omeroserver"],
        60,
        20,
        text_query="error",
    )
    internal = _build_logs_cache_key(
        config,
        ["omeroserver_internal"],
        60,
        20,
        internal_files={"omeroserver_internal": {"Blitz-0.log"}},
    )

    assert len({base, text, internal}) == 3


def test_apply_global_cap_keeps_most_recent_entries() -> None:
    """Check that apply global cap keeps most recent entries remains stable.

    Inputs: admin-tool fixtures. Output: fails on regressions in apply global cap keeps most recent entries.
    """
    entries = [
        LogEntry(
            timestamp="2026-03-09T00:00:01+00:00",
            container="a",
            level="info",
            message="older",
        ),
        LogEntry(
            timestamp="2026-03-09T00:00:03+00:00",
            container="b",
            level="info",
            message="newest",
        ),
        LogEntry(
            timestamp="2026-03-09T00:00:02+00:00",
            container="a",
            level="info",
            message="middle",
        ),
    ]

    capped = _apply_global_cap(entries, 2)

    assert [entry.message for entry in capped] == ["newest", "middle"]


def test_fetch_loki_logs_uncached_aggregates_jobs_and_filters_internal_batches(
    monkeypatch,
) -> None:
    """Verify fetch loki logs uncached aggregates jobs and filters internal batches.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in fetch loki logs uncached aggregates jobs and filters internal batches.
    """
    config = _config()
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
    monkeypatch.setattr(
        log_query_module,
        "_prepare_query_jobs",
        lambda *args, **kwargs: [docker_job, internal_job],
    )

    def fake_execute_query_job(config, job, lookback_seconds, max_entries, since_ns):
        """Simulate execute query job so the surrounding test controls that dependency.

        Inputs: `config` configuration, `job`, `lookback_seconds`, `max_entries`,
        `since_ns`. Output: `tuple`.
        """
        if job.source_type == "docker":
            return job, [
                LogEntry(
                    timestamp="2026-03-09T00:00:02+00:00",
                    container="omeroserver",
                    level="info",
                    message="docker",
                )
            ]
        return job, [
            LogEntry(
                timestamp="2026-03-09T00:00:03+00:00",
                container="omeroserver_internal/Blitz-0.log",
                level="warn",
                message="internal-kept",
            ),
            LogEntry(
                timestamp="2026-03-09T00:00:04+00:00",
                container="omeroserver_internal/DropBox.err",
                level="warn",
                message="internal-dropped",
            ),
        ]

    monkeypatch.setattr(log_query_module, "_execute_query_job", fake_execute_query_job)

    entries = _fetch_loki_logs_uncached(
        config,
        ["omeroserver", "omeroserver_internal"],
        60,
        10,
        internal_files={"omeroserver_internal": {"Blitz-0.log"}},
    )

    assert [(entry.container, entry.message) for entry in entries] == [
        ("omeroserver", "docker"),
        ("omeroserver_internal/Blitz-0.log", "internal-kept"),
    ]


def test_internal_batch_query_splits_after_failure(monkeypatch) -> None:
    """Verify internal batch query splits after failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in internal batch query splits after failure.
    when validation or the called operation fails.
    """
    config = _config()
    job = log_query_module._QueryJob(
        query='{compose_service="omeroweb", log_type="internal"}',
        source_type="internal_batch",
        source_name="omeroweb_internal",
        selected_files=("OMEROweb.log", "omero-web.stderr.log"),
    )
    calls = []

    def fake_execute_query_job(config, job, lookback_seconds, max_entries, since_ns):
        """Simulate execute query job so the surrounding test controls that dependency.

        Inputs: `config` configuration, `job`, `lookback_seconds`, `max_entries`,
        `since_ns`. Output: `tuple`. Raises: RuntimeError for the exercised failure path.
        """
        calls.append(job.selected_files)
        if len(job.selected_files) > 1:
            raise RuntimeError("batch too slow")
        filename = job.selected_files[0]
        return job, [
            LogEntry(
                timestamp="2026-03-09T00:00:03+00:00",
                container=f"omeroweb_internal/{filename}",
                level="info",
                message=filename,
            )
        ]

    monkeypatch.setattr(log_query_module, "_execute_query_job", fake_execute_query_job)

    resolved_job, entries = log_query_module._execute_internal_batch_with_split(
        config,
        job,
        lookback_seconds=60,
        max_entries=10,
        since_ns=None,
    )

    assert resolved_job == job
    assert calls == [
        ("OMEROweb.log", "omero-web.stderr.log"),
        ("OMEROweb.log",),
        ("omero-web.stderr.log",),
    ]
    assert [entry.message for entry in entries] == [
        "OMEROweb.log",
        "omero-web.stderr.log",
    ]


def test_internal_batch_query_preserves_unsplittable_failure(monkeypatch) -> None:
    """Check that internal batch query preserves unsplittable failure remains stable.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in internal batch query preserves unsplittable failure.
    """
    job = log_query_module._QueryJob(
        query='{compose_service="omeroweb", log_type="internal"}',
        source_type="internal_batch",
        source_name="omeroweb_internal",
        selected_files=("OMEROweb.log",),
    )
    monkeypatch.setattr(
        log_query_module,
        "_execute_query_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("single file slow")),
    )

    with pytest.raises(RuntimeError, match="single file slow"):
        log_query_module._execute_internal_batch_with_split(
            _config(),
            job,
            lookback_seconds=60,
            max_entries=10,
            since_ns=None,
        )


def test_query_failure_formatter_reports_overflow_count() -> None:
    """Verify query failure formatter reports overflow count.

    Inputs: admin-tool fixtures. Output: fails on regressions in query failure formatter reports overflow count.
    """
    failures = [
        log_query_module._QueryFailure(
            job=log_query_module._QueryJob(
                query="{}",
                source_type="docker",
                source_name=f"svc-{idx}",
            ),
            reason="offline",
        )
        for idx in range(5)
    ]

    assert log_query_module._format_query_failures(failures).endswith("; 2 more")


def test_internal_entries_are_capped_per_service_after_batch_aggregation(
    monkeypatch,
) -> None:
    """Verify internal entries are capped per service after batch aggregation.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in internal entries are capped per service after batch aggregation.
    """
    job = log_query_module._QueryJob(
        query='{compose_service="omeroweb", log_type="internal"}',
        source_type="internal_batch",
        source_name="omeroweb_internal",
        selected_files=("OMEROweb.log",),
    )
    monkeypatch.setattr(
        log_query_module,
        "_prepare_query_jobs",
        lambda *args, **kwargs: [job],
    )
    monkeypatch.setattr(
        log_query_module,
        "_execute_query_job",
        lambda *args, **kwargs: (
            job,
            [
                LogEntry(
                    timestamp="2026-03-09T00:00:01+00:00",
                    container="omeroweb_internal/OMEROweb.log",
                    level="info",
                    message="old",
                ),
                LogEntry(
                    timestamp="2026-03-09T00:00:03+00:00",
                    container="omeroweb_internal/OMEROweb.log",
                    level="info",
                    message="new",
                ),
                LogEntry(
                    timestamp="2026-03-09T00:00:02+00:00",
                    container="omeroweb_internal/OMEROweb.log",
                    level="info",
                    message="middle",
                ),
            ],
        ),
    )

    entries = _fetch_loki_logs_uncached(_config(), ["omeroweb_internal"], 60, 2)

    assert [entry.message for entry in entries] == ["new", "middle"]
