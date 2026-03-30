from __future__ import annotations

import json
import subprocess
import urllib.error
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.views import index_view

PROMETHEUS_URL = "https://prometheus.example.test:9090"
LOKI_URL = "https://loki.example.test:3100"


class _HttpResponseStub:
    def __init__(self, status: int, payload: bytes):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class _DockerConnection:
    def __init__(self, response=None, request_error: Exception | None = None):
        self._response = response
        self._request_error = request_error
        self.requested = None
        self.closed = False

    def request(self, method, path):
        if self._request_error is not None:
            raise self._request_error
        self.requested = (method, path)

    def getresponse(self):
        return self._response

    def close(self):
        self.closed = True


def _payload(response):
    return json.loads(response.content.decode("utf-8"))


def test_env_probe_and_prometheus_helpers_cover_runtime_failures(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOOLS_SAMPLE_INT", "12")
    assert index_view._to_int_env("ADMIN_TOOLS_SAMPLE_INT", 5) == 12
    monkeypatch.setenv("ADMIN_TOOLS_SAMPLE_INT", "bad")
    assert index_view._to_int_env("ADMIN_TOOLS_SAMPLE_INT", 5) == 5

    monkeypatch.setattr(
        index_view.urllib.request,
        "urlopen",
        lambda request, timeout=2.5: _HttpResponseStub(204, b""),
    )
    assert index_view._probe_http_url("https://grafana.example.org") == {
        "ok": True,
        "status": 204,
        "error": "",
    }

    def _http_error(request, timeout=2.5):
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "backend unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(index_view.urllib.request, "urlopen", _http_error)
    assert index_view._probe_http_url("https://grafana.example.org") == {
        "ok": False,
        "status": 503,
        "error": "HTTP 503",
    }

    monkeypatch.setattr(
        index_view.urllib.request,
        "urlopen",
        lambda request, timeout=2.5: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")
        ),
    )
    assert index_view._probe_http_url("https://grafana.example.org") == {
        "ok": False,
        "status": 0,
        "error": "Connection failed",
    }

    query_payload = {
        "data": {"result": [{"value": [1711843200, "42.5"]}]},
    }
    monkeypatch.setattr(
        index_view.urllib.request,
        "urlopen",
        lambda url, timeout=5.0: _HttpResponseStub(
            200, json.dumps(query_payload).encode("utf-8")
        ),
    )
    assert index_view._prometheus_instant_query(PROMETHEUS_URL, "up") == 42.5

    seen = []

    def _query_metric(_base_url, expr):
        seen.append(expr)
        if "network_receive" in expr:
            raise RuntimeError("probe failed")
        return 7.0

    monkeypatch.setattr(index_view, "_prometheus_instant_query", _query_metric)
    metrics = index_view._collect_system_metrics(PROMETHEUS_URL)
    assert metrics["cpu_usage_percent"] == 7.0
    assert metrics["network_receive_bps"] is None
    assert metrics["network_transmit_bps"] == 7.0
    assert len(seen) == 5


def test_collect_recently_seen_services_and_parse_since_ns() -> None:
    response = _HttpResponseStub(
        200,
        json.dumps(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {
                                "container_label_com_docker_compose_service": "redis"
                            }
                        },
                        {
                            "metric": {
                                "container_label_com_docker_compose_service": "database"
                            }
                        },
                    ]
                },
            }
        ).encode("utf-8"),
    )
    original = index_view.urllib.request.urlopen
    index_view.urllib.request.urlopen = lambda url, timeout=5.0: response
    try:
        assert index_view._collect_recently_seen_services(PROMETHEUS_URL) == [
            "database",
            "redis",
        ]
    finally:
        index_view.urllib.request.urlopen = original

    assert index_view._parse_since_ns("1711843200000000000") == 1711843200000000000
    assert index_view._parse_since_ns("2026-03-30T06:56:57Z") > 0


def test_logs_view_and_internal_log_labels_cover_configuration_paths(
    monkeypatch,
) -> None:
    request = RequestFactory().get("/admin_tools/logs/")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )

    monkeypatch.setattr(
        index_view,
        "optional_log_config",
        lambda: LogConfig(
            loki_url=LOKI_URL,
            lookback_seconds=60,
            max_entries=100,
            timeout_seconds=5.0,
            cache_max_bytes=1024,
        ),
    )
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: HttpResponse(
            json.dumps(context, sort_keys=True),
            content_type="application/json",
        ),
    )

    response = index_view.logs_view(request, conn=None)
    assert response.status_code == 200
    payload = _payload(response)
    assert json.loads(payload["log_config"])["loki_url"] == LOKI_URL
    assert payload["table_row_cap"] == index_view.LOG_TABLE_ROW_CAP
    assert payload["log_sources"][0]["container"] == "omeroserver"

    monkeypatch.setattr(index_view, "_require_root_user", lambda request, conn: None)
    monkeypatch.setattr(index_view, "optional_log_config", lambda: None)
    invalid_response = index_view.internal_log_labels(
        RequestFactory().get(
            "/admin_tools/internal-log-labels/",
            data={"service": "bad-service"},
        ),
        conn=None,
    )
    assert invalid_response.status_code == 503

    monkeypatch.setattr(
        index_view,
        "optional_log_config",
        lambda: LogConfig(
            loki_url=LOKI_URL,
            lookback_seconds=60,
            max_entries=100,
            timeout_seconds=5.0,
            cache_max_bytes=1024,
        ),
    )
    monkeypatch.setattr(
        index_view,
        "fetch_internal_log_labels",
        lambda config, service: (_ for _ in ()).throw(RuntimeError("backend exploded")),
    )
    valid_response = index_view.internal_log_labels(
        RequestFactory().get(
            "/admin_tools/internal-log-labels/",
            data={"service": "omeroweb_internal"},
        ),
        conn=None,
    )
    assert valid_response.status_code == 200
    assert _payload(valid_response) == {"service": "omeroweb_internal", "labels": []}


def test_docker_compose_and_api_helpers_cover_json_and_socket_errors(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        index_view.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, ["docker"])
        ),
    )
    assert index_view._docker_compose_json(["docker", "compose", "ps"]) is None

    monkeypatch.setattr(
        index_view.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="{broken"),
    )
    assert index_view._docker_compose_json(["docker", "compose", "ps"]) is None

    socket_path = tmp_path / "docker.sock"
    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", str(socket_path))
    monkeypatch.setattr(index_view.os.path, "exists", lambda path: True)

    ok_connection = _DockerConnection(
        _HttpResponseStub(200, b'{"containers": ["omeroserver"]}')
    )
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: ok_connection,
    )
    assert index_view._docker_api_json("/containers/json") == {
        "containers": ["omeroserver"]
    }
    assert ok_connection.requested == ("GET", "/containers/json")
    assert ok_connection.closed is True

    denied_connection = _DockerConnection(request_error=PermissionError("denied"))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: denied_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None

    bad_status_connection = _DockerConnection(_HttpResponseStub(503, b"{}"))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: bad_status_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None

    invalid_json_connection = _DockerConnection(_HttpResponseStub(200, b"{broken"))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: invalid_json_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None


def test_docker_diagnostics_and_compose_health_helpers_cover_inspection_paths(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    monkeypatch.setattr(index_view.os.path, "exists", lambda path: True)
    monkeypatch.setattr(index_view.os, "access", lambda path, mode: True)
    monkeypatch.setattr(index_view.os, "getuid", lambda: 1001)
    monkeypatch.setattr(index_view.os, "getgroups", lambda: [998, 999])
    monkeypatch.setattr(
        index_view.os,
        "stat",
        lambda path: SimpleNamespace(st_uid=0, st_gid=999, st_mode=0o140660),
    )

    def _docker_api(path, timeout_seconds=3.0):
        if path == "/containers/json?all=1":
            return [
                {
                    "Id": "db1",
                    "Labels": {"com.docker.compose.service": "database"},
                    "State": "running",
                    "Status": "Up 5 minutes (healthy)",
                },
                {
                    "Id": "cache1",
                    "Labels": {"com.docker.compose.service": "redis"},
                    "State": "running",
                    "Status": "Up 1 minute",
                },
            ]
        if path == "/containers/cache1/json":
            return {
                "Config": {"Healthcheck": {"Test": ["CMD", "redis-cli", "ping"]}},
                "State": {"Health": {"Status": "starting"}},
            }
        raise AssertionError(f"unexpected docker api path: {path}")

    monkeypatch.setattr(index_view, "_docker_api_json", _docker_api)

    diagnostics = index_view._diagnose_docker_health()
    health_config, runtime = index_view._load_compose_health_data()

    assert diagnostics["api_reachable"] is True
    assert diagnostics["containers_with_health"] == 1
    assert diagnostics["process_in_socket_group"] is True
    assert diagnostics["sample_statuses"][0]["parsed_health"] == "healthy"

    assert health_config == {"database": True, "redis": True}
    assert runtime == {
        "database": {"state": "running", "health": "healthy"},
        "redis": {"state": "running", "health": "starting"},
    }

    monkeypatch.setattr(index_view, "_docker_api_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        index_view, "_load_compose_healthcheck_config", lambda: {"grafana": True}
    )
    monkeypatch.setattr(
        index_view,
        "_load_compose_runtime_health",
        lambda: {"grafana": {"state": "running", "health": "healthy"}},
    )
    assert index_view._load_compose_health_data() == (
        {"grafana": True},
        {"grafana": {"state": "running", "health": "healthy"}},
    )
