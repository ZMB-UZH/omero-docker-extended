from __future__ import annotations

from iter_test_helpers import next_or_fail

import builtins

import pytest
import requests

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.services import log_query as log_query_module
from omeroweb_admin_tools.services import system_diagnostics


class _FakeDockerResponse:
    """Test double for fake docker response."""

    def __init__(self, status: int, payload: bytes):
        """Create `_FakeDockerResponse` with `status` and `payload`.

        Inputs: `status`, `payload`. Output: None.
        """
        self.status = status
        self.status_code = status
        self._payload = payload
        self.content = payload
        self.text = payload.decode("utf-8", errors="replace")

    def read(self):
        """Read data from the resource.

        Inputs: none. Output: `self._payload`.
        """
        return self._payload


class _FakeDockerConnection:
    """Test double for fake docker connection."""

    def __init__(self, response=None, *, request_error=None):
        """Create `_FakeDockerConnection` with `response`.

        Inputs: `response`, `request_error`. Output: None.
        """
        self._response = response
        self._request_error = request_error
        self.closed = False

    def request(self, method, path):
        """Request the request for `_FakeDockerConnection`.

        Inputs: `method`, `path` path. Output: None. Raises: _request_error when validation or the called operation fails.
        """
        if self._request_error is not None:
            raise self._request_error

    def getresponse(self):
        """Return the HTTP response.

        Inputs: none. Output: `self._response`.
        """
        return self._response

    def close(self):
        """Close `_FakeDockerConnection`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


def _log_config(url: str = "https://loki:3100") -> LogConfig:
    """Log the config.

    Inputs: `url` (str) URL. Output: `LogConfig`.
    """
    return LogConfig(
        loki_url=url,
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=5.0,
        cache_max_bytes=64 * 1024 * 1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
    )


def test_system_diagnostics_helpers_cover_cached_runtime_and_socket_edges(
    monkeypatch, tmp_path
):
    """Verify system diagnostics helpers cover cached runtime and socket edges.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` temporary path fixture.
    Output: `real_import` result. Raises: ImportError for the exercised failure path.
    """
    monkeypatch.setenv("FLOAT_ENV", "not-a-number")
    assert system_diagnostics._to_float_env("FLOAT_ENV", 2.5) == 2.5

    monkeypatch.setenv("SECONDARY_ENV", "")
    assert (
        system_diagnostics._first_present_env(
            ("MISSING_ENV", "SECONDARY_ENV"),
            "fallback",
        )
        == "fallback"
    )

    cached_module = object()
    previous_cached = system_diagnostics._get_cached_psycopg2_module()
    try:
        system_diagnostics._set_cached_psycopg2_module(cached_module)
        assert system_diagnostics._load_psycopg2() is cached_module

        system_diagnostics._set_cached_psycopg2_module(
            system_diagnostics._PSYCOPG2_UNSET
        )
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            """Return the fake import.

            Inputs: `name` name, `*args` positional arguments, `**kwargs` keyword
            arguments. Output: `real_import` result. Raises: ImportError when validation or the called operation fails.
            """
            if name == "psycopg2":
                raise ImportError("missing psycopg2")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        with pytest.raises(RuntimeError, match="psycopg2-binary"):
            system_diagnostics._load_psycopg2()
    finally:
        system_diagnostics._set_cached_psycopg2_module(previous_cached)

    monkeypatch.setenv("ADMIN_TOOLS_OMERO_DB_HOST", "database")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_DB_PORT", "5544")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_DB_USER", "omero")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_DB_PASSWORD", "secret")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_DB_NAME", "omero-db")
    assert system_diagnostics._omero_database_profile() == (
        system_diagnostics.DatabaseRuntimeProfile(
            host="database",
            port=5544,
            user="omero",
            password="secret",
            dbname="omero-db",
        )
    )

    class _FakeSocket:
        """Test double for fake socket."""

        def __init__(self):
            """Create `_FakeSocket` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.timeout = None
            self.connected_path = None

        def settimeout(self, timeout):
            """Set the socket timeout.

            Inputs: `timeout`. Output: None.
            """
            self.timeout = timeout

        def connect(self, path):
            """Open the connection for `_FakeSocket`.

            Inputs: `path`. Output: None.
            """
            self.connected_path = path

    fake_socket = _FakeSocket()
    monkeypatch.setattr(
        system_diagnostics.socket,
        "socket",
        lambda *args, **kwargs: fake_socket,
    )
    docker_socket_path = tmp_path / "docker.sock"
    connection = system_diagnostics._UnixSocketHTTPConnection(
        str(docker_socket_path),
        timeout=2.0,
    )
    connection.connect()
    assert fake_socket.timeout == 2.0
    assert fake_socket.connected_path == str(docker_socket_path)

    monkeypatch.setattr(system_diagnostics.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        system_diagnostics,
        "_UnixSocketHTTPConnection",
        lambda *args, **kwargs: _FakeDockerConnection(
            request_error=OSError("socket down")
        ),
    )
    ok, payload, error = system_diagnostics._docker_api_json("/containers/json")
    assert ok is False
    assert payload is None
    assert "Docker API request failed" in error

    monkeypatch.setattr(
        system_diagnostics,
        "_UnixSocketHTTPConnection",
        lambda *args, **kwargs: _FakeDockerConnection(_FakeDockerResponse(200, b"   ")),
    )
    ok, payload, error = system_diagnostics._docker_api_json("/containers/json")
    assert ok is False
    assert payload is None
    assert "empty response" in error

    monkeypatch.setattr(
        system_diagnostics,
        "_docker_api_json",
        lambda path: (False, None, "socket unavailable"),
    )
    assert system_diagnostics._inspect_docker_service_runtime("omeroserver") == (
        None,
        "socket unavailable",
    )

    responses = iter(
        [
            (
                True,
                [{"Id": "abcdef1234567890", "Created": 1, "Names": [""]}],
                "",
            ),
            (False, None, "inspect failed"),
        ]
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_docker_api_json",
        lambda path: next_or_fail(responses),
    )
    assert system_diagnostics._inspect_docker_service_runtime("omeroserver") == (
        None,
        "inspect failed",
    )

    responses = iter(
        [
            (
                True,
                [{"Id": "abcdef1234567890", "Created": 1, "Names": [""]}],
                "",
            ),
            (
                True,
                {"Name": "/inspect-name", "State": {"Status": "running"}},
                "",
            ),
        ]
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_docker_api_json",
        lambda path: next_or_fail(responses),
    )
    runtime, error = system_diagnostics._inspect_docker_service_runtime("omeroserver")
    assert error == ""
    assert runtime == {
        "container_id": "abcdef123456",
        "container_name": "inspect-name",
        "state": "running",
        "health": "none",
    }

    invalid_http = system_diagnostics._http_probe(
        "http",
        "Probe HTTP",
        "https://user:pass@example.test/path#fragment",
        1.0,
    )
    assert invalid_http.status == "fail"
    assert invalid_http.details == "HTTP probe URL is invalid."


def test_log_query_helpers_cover_validation_inference_and_job_execution(monkeypatch):
    """Verify log query helpers cover validation inference and job execution.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in log query helpers cover validation inference and job execution.
    """
    assert log_query_module._estimate_log_entries_size("invalid") == 0
    assert log_query_module._estimate_log_entries_size((object(),)) == 0
    assert log_query_module._estimate_label_cache_size(("only-one-item",)) == 0
    assert (
        log_query_module._estimate_label_cache_size((["not-a-tuple"], "filepath")) == 0
    )

    assert log_query_module._infer_level_from_message("") == "info"
    assert log_query_module._infer_level_from_message("panic in worker") == "fatal"
    assert log_query_module._infer_level_from_message("timeout waiting for redis") == (
        "warn"
    )
    assert log_query_module._infer_level_from_message("trace details enabled") == (
        "debug"
    )
    assert log_query_module._normalize_level("info", "DEBUG boot complete") == "debug"
    assert log_query_module._normalize_level("info", "plain startup line") == "info"

    with pytest.raises(RuntimeError, match="SSRF protection"):
        log_query_module._execute_loki_query(
            _log_config("https://user:pass@loki:3100#fragment"),
            '{compose_service="omeroserver"}',
            60,
            20,
        )

    monkeypatch.setattr(
        log_query_module.requests,
        "get",
        lambda url, timeout: (_ for _ in ()).throw(
            requests.RequestException("offline")
        ),
    )
    with pytest.raises(RuntimeError, match="request failed"):
        log_query_module._execute_loki_query(
            _log_config(),
            '{compose_service="omeroserver"}',
            60,
            20,
        )

    payload = {
        "data": {
            "result": [
                {
                    "stream": {
                        "log_type": "internal",
                        "filename": "server.log",
                        "detected_level": "info",
                    },
                    "values": [["1710000000000000000", ""]],
                }
            ]
        }
    }
    entries = log_query_module._parse_entries_from_payload(payload)
    assert entries[0].container == "unknown_internal/server.log"
    assert entries[0].level == "info"
    assert entries[0].message == ""

    jobs = log_query_module._prepare_query_jobs(
        ["omeroserver", "omeroweb_internal"],
        internal_files={"omeroweb_internal": {"server.log", "worker.log"}},
        text_query="boom",
        internal_file_batch_size=12,
    )
    assert {job.source_type for job in jobs} == {"docker", "internal_batch"}
    assert any(job.source_name == "omeroserver" for job in jobs)
    assert all("|~" in job.query for job in jobs)

    monkeypatch.setattr(
        log_query_module, "_execute_loki_query", lambda *args, **kwargs: payload
    )
    docker_job = log_query_module._QueryJob(
        query='{compose_service="omeroserver"}',
        source_type="docker",
        source_name="omeroserver",
    )
    resolved_job, resolved_entries = log_query_module._execute_query_job(
        _log_config(),
        docker_job,
        60,
        20,
        since_ns=7,
    )
    assert resolved_job == docker_job
    assert [entry.container for entry in resolved_entries] == [
        "unknown_internal/server.log"
    ]

    filtered = log_query_module._filter_internal_batch_entries(
        "omeroweb_internal",
        ("server.log",),
        [
            log_query_module.LogEntry(
                timestamp="2026-03-30T00:00:00+00:00",
                container="omeroweb",
                level="info",
                message="docker",
            ),
            log_query_module.LogEntry(
                timestamp="2026-03-30T00:00:01+00:00",
                container="omeroweb_internal/server.log",
                level="info",
                message="internal",
            ),
        ],
    )
    assert [entry.message for entry in filtered] == ["internal"]

    assert (
        log_query_module._fetch_loki_logs_uncached(
            _log_config(),
            [],
            60,
            20,
        )
        == []
    )
    assert log_query_module._strip_message_prefix("") == ""
