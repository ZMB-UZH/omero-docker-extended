from __future__ import annotations

import io
import json
import socket
import urllib.error

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
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
        self.headers = {}

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _config():
    return LogConfig(
        loki_url="https://loki:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=5.0,
        cache_max_bytes=64 * 1024 * 1024,
    )


def test_execute_loki_query_returns_json_payload(monkeypatch) -> None:
    payload = {"status": "success", "data": {"result": []}}
    monkeypatch.setattr(
        log_query_module.urllib.request,
        "urlopen",
        lambda request, timeout: _DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    result = _execute_loki_query(_config(), '{compose_service="omeroserver"}', 60, 20)

    assert result == payload


def test_execute_loki_query_wraps_non_json_http_and_timeout_errors(
    monkeypatch,
) -> None:
    config = _config()

    monkeypatch.setattr(
        log_query_module.urllib.request,
        "urlopen",
        lambda request, timeout: _DummyResponse(b"not-json", status=200),
    )
    with pytest.raises(RuntimeError, match="non-JSON response"):
        _execute_loki_query(config, '{compose_service="omeroserver"}', 60, 20)

    http_error = urllib.error.HTTPError(
        url="https://loki:3100",
        code=502,
        msg="Bad Gateway",
        hdrs={},
        fp=io.BytesIO(b"upstream failed"),
    )
    monkeypatch.setattr(
        log_query_module.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(http_error),
    )
    with pytest.raises(RuntimeError, match="Loki HTTP error 502: upstream failed"):
        _execute_loki_query(config, '{compose_service="omeroserver"}', 60, 20)

    monkeypatch.setattr(
        log_query_module.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(socket.timeout("late")),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        _execute_loki_query(config, '{compose_service="omeroserver"}', 60, 20)


def test_parse_entries_from_payload_handles_internal_streams_and_detected_levels():
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
